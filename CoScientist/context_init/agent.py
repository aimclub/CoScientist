"""The pre-stage context-initialization agent.

``ContextInitSessionAgent`` is a ``SessionAgent`` that:

  1. runs its LLM to draft a ``ResearchFrame`` from the raw research question
     (``output_schema = research_frame``, stored under ``output_key``);
  2. shows the operator a STRUCTURED WEB FORM (one field per framing entity)
     through the HITL bridge, and folds the operator's answers back onto the
     frame — untouched fields keep the agent's drafted values (soft gate);
  3. seeds the confirmed frame into the Research Context Graph (the privileged
     init path) BEFORE the orchestrator runs, then publishes a short summary.

In headless mode (no HITL handler) the base loop skips the review and step 3
still runs — the agent's drafted frame is seeded as-is.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from CoScientist.context_init.commit import seed_frame
from CoScientist.context_init.models import FrameOperation, ResearchFrame
from CoScientist.context_init.operations import (
    OPS_FORM_BLOCK,
    fill_operations_if_missing,
)
from CoScientist.graph.research.store import get_research_graph
from CoScientist.graph.session_scope import session_key
from CoScientist.hitl.field_status import OPERATOR_STATUS, is_open
from CoScientist.hitl.models import HITLAction, HITLRequest, HITLResponse
from CoScientist.hitl.session_agent import SessionAgent

logger = logging.getLogger(__name__)

FRAME_STATE_KEY = "research_frame"
_FORM_INTRO = ("Заполните рамку исследования. Пустые поля агент заполнит "
               "рабочими значениями. Рамка задаёт стратегию: литературный "
               "поиск, дорогой или дешёвый эксперимент.")


def coerce_frame(value: Any) -> ResearchFrame:
    """Best-effort ResearchFrame from a model output / state value."""
    if isinstance(value, ResearchFrame):
        frame = value.normalized()
    else:
        if isinstance(value, str):
            value = json.loads(value)
        frame = ResearchFrame.model_validate(value).normalized()
    return fill_operations_if_missing(frame)


def frame_to_form(frame: ResearchFrame) -> Dict[str, Any]:
    """Build the HITLRequest.form payload the web UI renders as a form."""
    frame = frame.normalized()
    blocks: List[Dict[str, Any]] = []
    for b in frame.blocks:
        fields = [
            {"name": f.name, "value": f.value, "status": f.status,
             "open": is_open(f.status)}
            for f in b.fields
        ]
        blocks.append({"title": b.title, "usage": b.usage, "fields": fields})
    ops_fields = [
        {"name": op.operation_id, "value": op.statement,
         "status": "задано заказчиком", "open": False}
        for op in frame.operations
    ]
    if not ops_fields:
        ops_fields = [{
            "name": "OP-1", "value": "", "status": "не задано", "open": True,
        }]
    blocks.append({
        "title": OPS_FORM_BLOCK,
        "usage": "слоты плана: одна обязательная задача на операцию; отчёт не входит",
        "fields": ops_fields,
    })
    return {"title": "Рамка исследования", "intro": _FORM_INTRO, "blocks": blocks}


def apply_form_values(frame: ResearchFrame,
                      form_values: Optional[Dict[str, Any]]) -> ResearchFrame:
    """Fold operator answers ({block: {field: value}}) onto the frame; the
    touched fields become «уточнено оператором», the rest keep their status."""
    if not form_values:
        return frame
    frame = frame.normalized()
    for b in frame.blocks:
        answers = form_values.get(b.title) or {}
        if not isinstance(answers, dict):
            continue
        for f in b.fields:
            val = answers.get(f.name)
            if val is None or not str(val).strip():
                continue
            f.value = str(val).strip()
            f.status = OPERATOR_STATUS
    answers = form_values.get(OPS_FORM_BLOCK) or {}
    if isinstance(answers, dict) and any(str(v).strip() for v in answers.values()):
        def _op_sort(name: str) -> int:
            match = re.match(r"OP-(\d+)$", str(name).strip(), re.I)
            return int(match.group(1)) if match else 10**6
        rows: List[FrameOperation] = []
        for name in sorted(answers, key=_op_sort):
            val = str(answers.get(name) or "").strip()
            if not val:
                continue
            rows.append(FrameOperation(operation_id=f"OP-{len(rows) + 1}", statement=val))
        if rows:
            frame.operations = rows
    return frame


def render_frame_summary(frame: ResearchFrame) -> str:
    """Compact readable summary (console review / chat publication)."""
    lines: List[str] = ["## Рамка исследования", ""]
    for b in frame.blocks:
        set_fields = b.set_fields()
        mark = "✓" if set_fields else "—"
        lines.append(f"{mark} **{b.title}**"
                     + (f": {len(set_fields)} поле(й)" if set_fields else " (пусто)"))
        for f in set_fields:
            lines.append(f"    - {f.name}: {f.value}")
    if frame.operations:
        lines.append(f"✓ **{OPS_FORM_BLOCK}**: {len(frame.operations)} слот(ов)")
        for op in frame.operations:
            lines.append(f"    - {op.operation_id}: {op.statement}")
    return "\n".join(lines)


class ContextInitSessionAgent(SessionAgent):
    """SessionAgent that confirms the frame via a web form and seeds the graph."""

    def _review_output(self, output_text) -> str:
        try:
            return render_frame_summary(coerce_frame(output_text))
        except Exception:  # noqa: BLE001 — review must never crash the run
            return super()._review_output(output_text)

    async def _review_decision(self, ctx: InvocationContext, output_text) -> HITLResponse:
        try:
            frame = coerce_frame(ctx.session.state.get(self.output_key) or output_text)
        except Exception as exc:  # noqa: BLE001 — fall back to plain approval
            logger.warning("frame form skipped (parse failed): %s", exc)
            return HITLResponse(action=HITLAction.APPROVE, approved=True)

        user_id, session_id = session_key(ctx)
        request = HITLRequest(
            agent_name=self.name,
            action_type=HITLAction.APPROVE,
            message="Подтвердите рамку исследования перед запуском.",
            form=frame_to_form(frame),
            context={"_session": {"user_id": user_id, "session_id": session_id}},
            invoked_via="internal_loop",
        )
        response = await self.hitl_handler.handle_request(request)

        # Fold the operator's answers in and store the merged frame back, so the
        # base loop finishes (approved, no instructions) with the updated frame.
        merged = apply_form_values(frame, response.form_values)
        if self.output_key:
            ctx.session.state[self.output_key] = merged.model_dump()
        return HITLResponse(action=HITLAction.APPROVE, approved=True)

    def _post_final_events(self, ctx: InvocationContext, output_text):
        try:
            frame = coerce_frame(ctx.session.state.get(self.output_key) or output_text)
        except Exception as exc:  # noqa: BLE001 — seeding must not kill the run
            logger.warning("frame not seeded (parse failed): %s", exc)
            return
        try:
            store = get_research_graph(ctx)
            result = seed_frame(store, frame)
        except Exception as exc:  # noqa: BLE001
            logger.warning("frame graph seeding failed: %s", exc)
            return

        ok = bool(result.get("ok"))
        stats = result.get("graph_stats") or {}
        header = ("🧭 Рамка исследования зафиксирована в графе"
                  if ok else "⚠️ Рамку не удалось зафиксировать в графе")
        if ok and stats:
            header += (f" ({stats.get('nodes', 0)} узлов, "
                       f"{stats.get('edges', 0)} рёбер).")
        text = f"{header}\n\n{render_frame_summary(frame)}"
        delta = {FRAME_STATE_KEY: frame.model_dump()}
        if ask := (frame.original_request or "").strip():
            delta["orchestrator_root_goal"] = ask
        if frame.operations:
            delta["experiment_operations"] = [op.model_dump() for op in frame.operations]
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=text)]),
            actions=EventActions(state_delta=delta),
        )


__all__ = [
    "ContextInitSessionAgent",
    "FRAME_STATE_KEY",
    "apply_form_values",
    "coerce_frame",
    "frame_to_form",
    "render_frame_summary",
]
