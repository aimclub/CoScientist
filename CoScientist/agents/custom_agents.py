"""Custom (non-LLM) agent classes referenced from system.yaml via custom:<name>."""
import logging
from typing import AsyncGenerator, List, Dict, Any
from typing_extensions import override

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.adk.utils.context_utils import Aclosing

logger = logging.getLogger(__name__)

class WebToolsDeployerAgent(BaseAgent):
    """
    Custom agent for deploying found web mcp servers.
    """

    # --- Field Declarations for Pydantic ---
    # model_config allows setting Pydantic configurations if needed, e.g., arbitrary_types_allowed
    model_config = {"arbitrary_types_allowed": True}


    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """
        Implements the custom orchestration logic for the story workflow.
        Uses the instance attributes assigned by Pydantic.
        """

        current_state = ctx.session.state

        filtered_mcps: List[Dict[str, Any]] = current_state.get('filtered_mcps', [])

        #TODO: Implement full deploying strategy after side tools are ready
        deployed_mcps = []
        ctx.session.state['deployed_mcps'] = deployed_mcps
        yield Event(author=self.name, invocation_id=ctx.invocation_id)

        # if not filtered_mcps:
        #     return


class ExecutorSwitchAgent(BaseAgent):
    """Runs exactly ONE of its children: the primary executor, or the fallback.

    Declared as ``children: [<primary>, <fallback>]``. The fallback is chosen
    only when the tool-prep pipeline's reranker never actually JUDGED the
    retrieved candidates — an unreadable answer, or one carrying no usable
    ``{index, score}`` pair — and the local cross-encoder could not stand in for
    it either. In that state ``filtered_tools`` is empty for a reason that says
    nothing about relevance, and abstaining on it throws away tools retrieval
    found correctly; FEDOT.MAS instead takes the whole unfiltered candidate set
    and does its own selection over it.

    Why a switch rather than two siblings in the sequence: ``AgentTool`` returns
    the LAST content-bearing event of the agent it wraps, and a ``before_agent``
    callback that short-circuits its own agent still emits one. A sibling that
    stood down after the real executor ran would therefore overwrite the
    pipeline's answer with its own "skipped" note (measured, both with and
    without text). Running one child and only one child removes that hazard.
    """

    model_config = {"arbitrary_types_allowed": True}

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        from CoScientist.agents.callbacks.tool_callbacks import rerank_fallback_active

        children: List[BaseAgent] = list(self.sub_agents or [])
        if not children:
            logger.warning("%s: no children declared — nothing to run", self.name)
            return

        chosen = children[0]
        if len(children) > 1 and rerank_fallback_active(ctx.session.state):
            chosen = children[1]
            verdict = (ctx.session.state.get("executor_tool_match") or {})
            logger.info(
                "%s: reranker verdict=%s over %s candidate(s) — routing to %s",
                self.name, verdict.get("reason"), verdict.get("candidates"), chosen.name,
            )

        async with Aclosing(chosen.run_async(ctx)) as agen:
            async for event in agen:
                yield event


#: The stable identity of a dataset: its link without the query string, so a
#: re-signed URL of the same S3 object is still "the dataset already analysed".
def dataset_identity(url: str) -> str:
    return str(url or "").split("?", 1)[0].strip()


class DatasetIntakeAgent(BaseAgent):
    """Pre-stage: has the CoderAgent look at the session's dataset before planning.

    Declared as ``subordinates: [CoderAgent]``. When the session has a dataset
    archive attached (``state['dataset_url']``) that has not been analysed yet,
    the coder is asked — through the same AgentTool the executor uses — to
    fetch it where it works (the OpenHands sandbox unpacks it into
    ``/workspace``), inspect it without changing it and write a short report.
    The report lands in ``state['dataset_report']`` and reaches the planner,
    the orchestrator and the context-init stage through ``inject_dataset_context``.

    Without a dataset, or for one already analysed, it does nothing at all: no
    model call, no event. Running the coder as a tool, not as a child, keeps the
    coder's own request separate from the user's — it describes the data, it
    does not start on the task — and returns its sandbox binding to the
    session, so later coder work continues in the sandbox the data is already in.
    """

    model_config = {"arbitrary_types_allowed": True}

    subordinates: List[BaseAgent] = []
    #: Characters of the report kept for prompts; the coder is asked for less.
    max_report_chars: int = 6000

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        from google.adk.events import EventActions
        from google.adk.tools.agent_tool import AgentTool
        from google.adk.tools.tool_context import ToolContext
        from google.genai import types

        from CoScientist.agents.callbacks.tool_callbacks import (
            DATASET_REPORT_FOR_STATE_KEY,
            DATASET_REPORT_STATE_KEY,
            DATASET_URL_STATE_KEY,
        )

        state = ctx.session.state
        url = str(state.get(DATASET_URL_STATE_KEY) or "").strip()
        identity = dataset_identity(url)
        if not url or state.get(DATASET_REPORT_FOR_STATE_KEY) == identity:
            return
        if not self.subordinates:
            logger.warning("%s: no coder declared — dataset left unanalysed", self.name)
            return

        coder = self.subordinates[0]
        tool_context = ToolContext(ctx)
        request = _dataset_request(_user_text(ctx))
        try:
            report = await AgentTool(agent=coder).run_async(
                args={"request": request}, tool_context=tool_context)
        except Exception as exc:  # noqa: BLE001 — planning must go on without it
            logger.warning("%s: dataset analysis failed: %s", self.name, exc)
            yield Event(
                author=self.name, invocation_id=ctx.invocation_id,
                content=types.Content(role="model", parts=[types.Part(text=(
                    f"Dataset analysis failed ({type(exc).__name__}); planning "
                    "continues without a dataset report."))]),
                actions=tool_context.actions,
            )
            return

        text = str(report or "").strip()
        if len(text) > self.max_report_chars:
            text = text[: self.max_report_chars].rstrip() + "\n…[report truncated]"
        actions: EventActions = tool_context.actions
        actions.state_delta[DATASET_REPORT_STATE_KEY] = text
        actions.state_delta[DATASET_REPORT_FOR_STATE_KEY] = identity
        yield Event(
            author=self.name, invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part(
                text=f"## Dataset report\n\n{text or '(the coder returned no report)'}")]),
            actions=actions,
        )


def _user_text(ctx: InvocationContext) -> str:
    content = getattr(ctx, "user_content", None)
    parts = getattr(content, "parts", None) or []
    return "\n".join(p.text for p in parts if getattr(p, "text", None)).strip()


def _dataset_request(user_request: str) -> str:
    context = (
        "\n\nFor context only — the user's request, which you must NOT work on "
        f"now:\n<<<\n{user_request[:4000]}\n>>>" if user_request else ""
    )
    return (
        "Analyse the dataset archive attached to this session BEFORE any planning "
        "happens. Get it where you work — in the OpenHands sandbox pass the "
        "session's dataset link as `dataset_url` to `run_sandbox_task` (it is "
        "unpacked into /workspace); otherwise download and unzip it in your "
        "workspace. Inspect it WITHOUT modifying, moving or deleting anything, "
        "and do not start on the user's task.\n\n"
        "Reply with a brief report (at most ~300 words), plain markdown:\n"
        "- layout: top-level tree, number of files, total size, file formats;\n"
        "- per data file (or group of similar files): what it holds — columns or "
        "fields with types and units when evident, row/record counts, missing "
        "values; for chemistry formats (SMILES, mol/sdf, cif, pdb, xyz, spectra, "
        "xls/csv tables) the entities and properties present;\n"
        "- problems: unreadable or empty files, encodings, inconsistencies;\n"
        "- exact paths of the files as they lie where you unpacked them."
        f"{context}"
    )
