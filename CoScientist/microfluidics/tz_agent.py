"""ТЗ session agent + document publication for the microfluidics profile.

``TZSessionAgent`` is the SessionAgent used for TZSpecAgent:

  * the ТЗ is assembled SECTION BY SECTION through ``fill_tz_section``
    (``tz_builder.py``), which keeps it in ``state["structured_tz"]`` — the
    model's final answer is only a short "done" line, so every reviewer reads
    the ТЗ from state. An agent that stops before the last section is sent
    back to continue from the section it stopped at;
  * the operator reviews the ТЗ as a FORM in the web ТЗ panel (``tz_review.py``):
    sections with empty fields first, filled ones below. Values typed by the
    operator go straight into the ТЗ; fields left EMPTY are filled by the
    agent (``fill_agent_fields``, «заполнено агентом») and the ТЗ comes back
    for another round with those fields highlighted — until the operator
    submits a form with nothing left empty;
  * every change is pushed to the panel live (``tz_live.py``): the agent runs
    in a nested AgentTool session the web session cannot see;
  * once the ТЗ is accepted (approved by the human, or produced directly in
    headless mode) the agent PUBLISHES the document: saves it to
    ``tz_documents/TZ_<timestamp>.md``, stores it in session state under
    ``structured_tz_document`` and emits a chat message with the file path,
    the web link (/api/tz-document) and the full document text — right before
    the pipeline moves on to planning / literature search.

``save_tz_document`` remains available as an after_agent callback for
profiles that want persistence without the chat message.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional, Tuple

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.utils.context_utils import Aclosing
from google.genai import types

from CoScientist.graph.session_scope import session_key
from CoScientist.hitl.models import HITLAction, HITLRequest, HITLResponse
from CoScientist.hitl.session_agent import SessionAgent
from CoScientist.microfluidics.render import render_tz_document
from CoScientist.microfluidics.tz_builder import (
    AGENT_FILL_STATE_KEY,
    AGENT_FILL_TOOL_NAME,
    FILL_TOOL_NAME,
    TOTAL_SECTIONS,
    TZ_BUILD_STATE_KEY,
    TZ_STATE_KEY,
    agent_fill_feedback,
    agent_fill_instruction,
    agent_fill_pending,
    agent_fill_request,
    load_tz,
    unfinished_feedback,
)
from CoScientist.microfluidics.tz_live import publish_tz
from CoScientist.microfluidics.tz_review import (
    agent_fill_message,
    apply_operator_values,
    tz_form,
    tz_view,
)

logger = logging.getLogger(__name__)

TZ_DOCUMENT_STATE_KEY = "structured_tz_document"
TZ_DOCUMENTS_DIR = Path("tz_documents")

_TZ_TOOLS = {FILL_TOOL_NAME, AGENT_FILL_TOOL_NAME}
_REWRITE_PROMPT = (
    "Оператор прислал правки к ТЗ:\n\n{feedback}\n\n"
    "ТЗ собирается заново: заполни все разделы через fill_tz_section, начиная "
    "с раздела 1, перенося прежние значения и применяя правки."
)


def persist_tz_document(tz, out_dir: Optional[Path] = None) -> Tuple[str, Optional[Path]]:
    """Render the ТЗ document and write it to disk.

    Returns ``(document_markdown, saved_path)``; ``saved_path`` is None when
    the file could not be written (the document itself is still returned).
    Raises only if the ТЗ cannot be rendered at all.
    """
    document = render_tz_document(tz)
    out_dir = out_dir or TZ_DOCUMENTS_DIR
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"TZ_{stamp}.md"
        path.write_text(document, encoding="utf-8")
        logger.info("ТЗ document saved to %s", path)
        return document, path
    except OSError as exc:
        logger.warning("Could not write the ТЗ document file: %s", exc)
        return document, None


def _touches_tz(event: Event) -> bool:
    """Did this event carry the answer of a tool that changes the ТЗ?"""
    parts = event.content.parts if event.content and event.content.parts else []
    return any(
        p.function_response is not None and p.function_response.name in _TZ_TOOLS
        for p in parts
    )


class TZSessionAgent(SessionAgent):
    """SessionAgent that reviews the ТЗ through the web ТЗ panel, round by round.

    Each round the operator gets the whole ТЗ as a form. Typed values are
    applied at once; if fields were left empty the agent fills them and the
    next round shows the result, agent values highlighted. A round with nothing
    left empty accepts the ТЗ. No answer (timeout, a handler without forms)
    accepts it as it is; a free-text correction (console "Edit") refills the
    whole ТЗ from section 1. At most ``max_form_rounds`` forms per invocation,
    so the pipeline can never get stuck."""

    # The agent composes complete instructions itself (fill what was left /
    # rewrite with these corrections); the base wrapper would contradict them.
    correction_prompt: str = "{feedback}"
    max_form_rounds: int = 5
    # Filling a 16-section form takes longer than a yes/no: the web handler's
    # auto-approve waits at least this long for it.
    form_timeout_seconds: float = 1800

    def _current_tz(self, ctx: InvocationContext, fallback):
        """The ТЗ assembled by fill_tz_section; ``fallback`` when there is none."""
        return ctx.session.state.get(TZ_STATE_KEY) or fallback

    def _proposed_output(self, ctx: InvocationContext, output_text):
        return self._current_tz(ctx, output_text)

    def _unfinished_feedback(self, ctx: InvocationContext):
        state = ctx.session.state
        return (
            agent_fill_feedback(state, ctx.invocation_id)
            or unfinished_feedback(state, ctx.invocation_id)
        )

    def _rewrite_state_delta(self, ctx: InvocationContext) -> dict:
        state = ctx.session.state
        request = agent_fill_pending(state, ctx.invocation_id)
        if request is not None:
            # The operator's answers and what is left to the agent ride on the
            # feedback event, so they are persisted (and reach the parent
            # session through the AgentTool) even before the agent's first call.
            return {TZ_STATE_KEY: state.get(TZ_STATE_KEY), AGENT_FILL_STATE_KEY: request}
        # Clearing the edition marker makes fill_tz_section start over at
        # section 1; the previous ТЗ stays in state until then.
        return {TZ_BUILD_STATE_KEY: None}

    def _review_output(self, output_text) -> str:
        try:
            return render_tz_document(output_text)
        except Exception as exc:  # noqa: BLE001 — review must never crash the run
            logger.warning("TZ review render failed (%s); showing raw output", exc)
            return str(output_text)

    # ── live panel ───────────────────────────────────────────────────────────
    async def _publish(self, ctx: InvocationContext, phase: str, tz=None) -> None:
        state = ctx.session.state
        tz = tz if tz is not None else load_tz(state.get(TZ_STATE_KEY))
        if tz is None:
            return
        request = agent_fill_pending(state, ctx.invocation_id)
        agent_fill = None
        if request is not None:
            total = int(request.get("total") or 0)
            agent_fill = {"done": total - len(request["pending"]), "total": total}
        await publish_tz(ctx, {
            "phase": phase,
            "agent": self.name,
            "progress": {"filled": len(tz.blocks), "total": TOTAL_SECTIONS},
            "agent_fill": agent_fill,
            "round": state.get(self._round_key(ctx)),
            **tz_view(tz, request),
        })

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        async with Aclosing(super()._run_async_impl(ctx)) as agen:
            async for event in agen:
                yield event
                # The consumer has appended the event by now: state is current.
                if _touches_tz(event):
                    phase = (
                        "agent_filling"
                        if agent_fill_pending(ctx.session.state, ctx.invocation_id)
                        else "filling"
                    )
                    await self._publish(ctx, phase)
        await self._publish(ctx, "final")

    # ── operator review ──────────────────────────────────────────────────────
    @staticmethod
    def _round_key(ctx: InvocationContext) -> str:
        return f"_tz_form_round_{ctx.invocation_id}"

    async def _review_decision(self, ctx: InvocationContext, output_text) -> HITLResponse:
        state = ctx.session.state
        tz = load_tz(self._current_tz(ctx, output_text))
        if tz is None or not tz.blocks:
            # Nothing assembled to put in a form — plain review of what there is.
            return await super()._review_decision(ctx, output_text)

        round_no = int(state.get(self._round_key(ctx)) or 0) + 1
        if round_no > self.max_form_rounds:
            logger.warning(
                "%s: %d review rounds done — ТЗ accepted as it is", self.name,
                self.max_form_rounds,
            )
            return HITLResponse(action=HITLAction.APPROVE, approved=True)
        state[self._round_key(ctx)] = round_no
        # Whatever the agent did not manage to fill shows up as empty again.
        state[AGENT_FILL_STATE_KEY] = None
        await self._publish(ctx, "review", tz)

        user_id, session_id = session_key(ctx)
        form = tz_form(tz, round_no)
        request = HITLRequest(
            agent_name=self.name,
            action_type=HITLAction.APPROVE,
            message=f"Проверка ТЗ оператором (раунд {round_no}). {form['intro']}",
            form=form,
            context={
                "output": self._review_output(tz),
                "_session": {"user_id": user_id, "session_id": session_id},
            },
            invoked_via="internal_loop",
            timeout_seconds=self.form_timeout_seconds,
        )
        response = await self.hitl_handler.handle_request(request)

        if response.form_values is None:
            feedback = (response.instructions or response.free_input or "").strip()
            if response.action == HITLAction.EDIT and feedback:
                # A handler without forms (console) sent free-text corrections.
                return HITLResponse(
                    action=HITLAction.EDIT, approved=False,
                    instructions=_REWRITE_PROMPT.format(feedback=feedback),
                )
            # Timeout / skip: the operator is not there — keep the ТЗ as it is.
            return HITLResponse(action=HITLAction.APPROVE, approved=True)

        answers = apply_operator_values(tz, response.form_values)
        # In-run for the tools; persisted by the next event's state delta.
        state[TZ_STATE_KEY] = answers.tz.model_dump()
        fill = agent_fill_request(ctx.invocation_id, answers.left_to_agent)
        logger.info(
            "%s: round %d — %d value(s) from the operator, %d left to the agent",
            self.name, round_no, answers.set_by_operator, answers.left_count,
        )
        if fill is None:
            await self._publish(ctx, "review", answers.tz)
            return HITLResponse(action=HITLAction.APPROVE, approved=True)

        state[AGENT_FILL_STATE_KEY] = fill
        await self._publish(ctx, "agent_filling", answers.tz)
        return HITLResponse(
            action=HITLAction.EDIT, approved=False,
            instructions=agent_fill_message(answers, agent_fill_instruction(fill)),
        )

    def _post_final_events(self, ctx: InvocationContext, output_text):
        """Publish the accepted ТЗ document into the chat (file + state + text)."""
        tz = self._current_tz(ctx, output_text)
        try:
            document, path = persist_tz_document(tz)
        except Exception as exc:  # noqa: BLE001 — publishing must not kill the run
            logger.warning("TZ document publication failed: %s", exc)
            return

        header = "📄 Структурированное ТЗ сформировано."
        if path is not None:
            header += f"\nФайл: {path.resolve()}"
        header += "\nОткрыть в браузере: /api/tz-document"
        text = f"{header}\n\n{document}"

        delta = {TZ_DOCUMENT_STATE_KEY: document, AGENT_FILL_STATE_KEY: None}
        model = load_tz(tz)
        if model is not None:
            # Operator answers may not have been followed by any tool call.
            delta[TZ_STATE_KEY] = model.model_dump()
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=text)]),
            actions=EventActions(state_delta=delta),
        )


def save_tz_document(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """after_agent callback: persist the approved ТЗ as a Markdown document
    (state + file) WITHOUT emitting a chat message."""
    tz = callback_context.state.get("structured_tz")
    if not tz:
        return None
    try:
        document, _path = persist_tz_document(tz)
    except Exception as exc:  # noqa: BLE001 — a render bug must not kill the run
        logger.warning("TZ document render failed: %s", exc)
        return None
    callback_context.state[TZ_DOCUMENT_STATE_KEY] = document
    return None


__all__ = [
    "TZSessionAgent",
    "TZ_DOCUMENT_STATE_KEY",
    "persist_tz_document",
    "save_tz_document",
]
