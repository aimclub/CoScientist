"""Orchestrator helpers for ExperimentModuleAgent call shaping.

Two structural (never keyword-based) safety nets live here:

1. ``coalesce_experiment_module_calls`` — if the orchestrator accidentally fans
   out several ExperimentModuleAgent calls in one turn, merge them into a single
   self-contained brief so the module builds ONE ExperimentPlan.

2. ``suppress_experiment_module_after_completed`` — prevent re-entering the module
   after result HITL accepted the stage or if planning budget is exhausted.
"""

from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)

_EM_NAME = "ExperimentModuleAgent"
#: Why the last plan or result review did not end in an approval. Owned by
#: CoScientist/experiments/review.py (imported lazily, like everything else
#: this module reaches for: importing review at module scope would pull the
#: whole experiment package into the orchestrator's callback chain).
_PAUSE_REASON_STATE_KEY = "experiment_review_pause_reason"
_TIMED_OUT_REASONS = {"plan_review_timeout", "result_review_timeout"}
# Set by research_init, or by ContextInit from the user's original_request.
_ROOT_GOAL_STATE_KEY = "orchestrator_root_goal"
_FRAME_STATE_KEY = "research_frame"


def _spend(state: object, current_runs: int) -> None:
    """Let this dispatch through, one unit lighter.

    Always returns None, so it can be returned straight from the decision:
    an after_model callback that returns None leaves the response alone.
    """
    if hasattr(state, "__setitem__"):
        state["experiment_module_runs"] = current_runs + 1
    return None


def _text_parts(content: object) -> str:
    parts = getattr(content, "parts", None) if content is not None else None
    return "\n".join(
        t.strip() for p in (parts or [])
        if (t := getattr(p, "text", "") or "").strip()
    ).strip()


def _canonical_ask(callback_context: CallbackContext, fallback: str) -> str:
    """User's original ask — never a reworded Research/McpBuilder brief.

    Order: research_init goal, ContextInit frame.original_request, user_content, brief.
    """
    state = getattr(callback_context, "state", None)
    getter = getattr(state, "get", None) if state is not None else None
    if callable(getter):
        root = getter(_ROOT_GOAL_STATE_KEY)
        if isinstance(root, str) and root.strip():
            return root.strip()
        raw = getter(_FRAME_STATE_KEY)
        if isinstance(raw, dict):
            text = raw.get("original_request")
            if isinstance(text, str) and text.strip():
                return text.strip()
        text = getattr(raw, "original_request", None) if raw is not None else None
        if isinstance(text, str) and text.strip():
            return text.strip()
    user = _text_parts(getattr(callback_context, "user_content", None))
    return user or fallback


def coalesce_experiment_module_calls(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """If the orchestrator fans out N ExperimentModuleAgent calls, keep one.

    Merges every ``request`` into a single self-contained brief so the module
    builds one ExperimentPlan instead of N interleaved runtimes.
    """
    state = getattr(callback_context, "state", None)
    content = getattr(llm_response, "content", None)
    parts = list(getattr(content, "parts", None) or [])
    if not parts:
        return None

    em_idxs: list[int] = []
    requests: list[str] = []
    for i, part in enumerate(parts):
        fc = getattr(part, "function_call", None)
        if fc is None or getattr(fc, "name", None) != _EM_NAME:
            continue
        em_idxs.append(i)
        args = dict(getattr(fc, "args", None) or {})
        req = args.get("request")
        if isinstance(req, str) and req.strip():
            requests.append(req.strip())

    # Marks that the module was asked for at all; the BUDGET is spent in
    # suppress_experiment_module_after_completed, which is where it is
    # checked. Counting here meant a dispatch paid for itself before being
    # judged, and the judge then refused it for being over budget.
    if em_idxs and hasattr(state, "__setitem__"):
        state["experiment_module_dispatched"] = True

    if len(em_idxs) <= 1:
        return None

    canonical = _canonical_ask(callback_context, "")
    merged = canonical or (
        "Complete the following computational experiment as ONE stage. "
        "Build a single ExperimentPlan covering all items below in order "
        "(with depends_on / artifact handoff as needed):\n\n"
        + "\n\n".join(r for r in requests)
    )
    keep_i = em_idxs[0]
    keep_fc = getattr(parts[keep_i], "function_call", None)
    if keep_fc is not None:
        keep_fc.args = dict(getattr(keep_fc, "args", None) or {})
        keep_fc.args["request"] = merged

    drop = set(em_idxs[1:])
    content.parts = [p for i, p in enumerate(parts) if i not in drop]
    agent = getattr(callback_context, "agent_name", None) or "orchestrator"
    logger.warning(
        "[%s] coalesced %d ExperimentModuleAgent calls into 1",
        agent,
        len(em_idxs),
    )
    return None  # in-place mutation is enough


def suppress_experiment_module_after_completed(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """after_model: do not re-enter the module after result HITL accepted the
    stage, or if planning is paused, or if the dispatch budget is spent — and
    spend a unit of that budget for a dispatch this lets through."""
    state = getattr(callback_context, "state", None)
    getter = getattr(state, "get", None) if state is not None else None
    if not callable(getter):
        return None

    # Find the dispatch first: with nothing to judge there is nothing to spend
    # either, and this callback runs after every model turn.
    content = getattr(llm_response, "content", None)
    parts = list(getattr(content, "parts", None) or [])
    em_idxs = [
        i for i, part in enumerate(parts)
        if getattr(getattr(part, "function_call", None), "name", None) == _EM_NAME
    ]
    if not em_idxs:
        return None

    runtime = getter("experiment_runtime")
    plan_paused = bool(getter("experiment_plan_review_paused"))
    is_completed = isinstance(runtime, dict) and runtime.get("phase") == "completed"
    from CoScientist.config import get_settings
    try:
        current_runs = int(getter("experiment_module_runs") or 0)
    except (TypeError, ValueError):
        current_runs = 0
    max_em_runs = get_settings().experiments.max_replans
    budget_exhausted = current_runs >= max_em_runs

    if plan_paused:
        pass
    elif budget_exhausted:
        pass
    elif is_completed:
        from CoScientist.experiments.review import result_tasks_ok
        if not result_tasks_ok(runtime):
            return _spend(state, current_runs)
    else:
        return _spend(state, current_runs)

    # Refused: strip the calls, and say why in their place.
    kept = [p for i, p in enumerate(parts) if i not in set(em_idxs)]
    if not kept:
        summary = getter("experiment_summary") if callable(getter) else None
        if not isinstance(summary, str) or not summary.strip():
            if plan_paused:
                summary = (
                    "Experiment plan review is paused for this session; "
                    "not starting a second plan."
                )
            elif budget_exhausted:
                # A budget spent because nobody answered the review is not a
                # budget spent on bad plans, and the orchestrator writes this
                # sentence into the final report.
                reason = str(getter(_PAUSE_REASON_STATE_KEY) or "")
                if reason in _TIMED_OUT_REASONS:
                    what = "plan" if reason == "plan_review_timeout" else "result"
                    summary = (
                        f"The experiment {what} was waiting for a human "
                        f"approval and the review window ran out "
                        f"({current_runs}/{max_em_runs} attempts used); "
                        "synthesizing final report with available results."
                    )
                else:
                    summary = (
                        f"Experiment module reached maximum attempt budget "
                        f"({current_runs}/{max_em_runs}); synthesizing final "
                        "report with available results."
                    )
            else:
                summary = (
                    "Experiment stage already completed for this session; "
                    "not starting a second plan."
                )
        kept = [types.Part(text=summary)]
    content.parts = kept
    logger.warning(
        "[%s] suppressed ExperimentModuleAgent: runs=%d/%d plan_paused=%s pause_reason=%s",
        getattr(callback_context, "agent_name", None) or "orchestrator",
        current_runs,
        max_em_runs,
        plan_paused,
        getter(_PAUSE_REASON_STATE_KEY) or "-",
    )
    return None


__all__ = [
    "coalesce_experiment_module_calls",
    "suppress_experiment_module_after_completed",
]
