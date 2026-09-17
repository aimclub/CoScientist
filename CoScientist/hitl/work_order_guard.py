"""Keep an agent inside its approved Work Order.

A deterministic before_tool check, so a contract binds the agent instead of
being a promise the model may forget after the first surprising search result:

  * before a contract is declared only orientation reads go through;
  * after a rejection nothing does;
  * afterwards a call must use a declared tool.

A blocked call is not a dead end: the message tells the agent to amend the
contract (update_work_order), which puts the change in front of the human.

The guard also keeps the journal the Work Report shows next to the agent's
claims (calls per tool), and ``make_work_report_fallback`` puts a report before
the human when the agent finished without submitting one.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from google.genai import types as genai_types

from CoScientist.hitl.work_order import WorkReport, load_order, order_key, save_order
from CoScientist.hitl.work_order_risk import ORIENTATION_TOOLS, exempt_tools

logger = logging.getLogger("CoScientist.hitl.work_order")


def _blocked(reason: str, tool_name: str, message: str, **extra) -> Dict[str, Any]:
    return {
        "status": "blocked",
        "blocked_by": "work_order_guard",
        "reason": reason,
        "tool": tool_name,
        "message": message,
        **extra,
    }


def make_work_order_guard(
    agent_name: str, handler: Any = None, internal_tools: Iterable[str] = ()
):
    """before_tool callback enforcing ``agent_name``'s Work Order."""
    exempt = exempt_tools(internal_tools)

    def _handler():
        if handler is not None:
            return handler
        from CoScientist.agents.common import hitl_handler
        return hitl_handler

    async def _record_deviation(tool_context, order, block: Dict[str, Any], args: Any) -> None:
        from CoScientist.hitl.callbacks import format_tool_args
        from CoScientist.hitl.work_order_tools import session_context, work_order_active

        deviation = {
            "reason": block["reason"],
            "tool": block["tool"],
            "args": format_tool_args(args)[:500],
            "revision": order.revision,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        order.deviations.append(deviation)
        save_order(tool_context.state, order)
        if not work_order_active():
            return
        try:
            await _handler().notify({
                "kind": "deviation",
                "agent_name": agent_name,
                "revision": order.revision,
                "deviation": deviation,
                "_session": session_context(tool_context),
            })
        except Exception:  # noqa: BLE001 - a notice must never fail the run
            logger.exception("%s: work order deviation notice failed", agent_name)

    async def work_order_guard(
        tool=None,
        args=None,
        tool_context=None,
        *,
        tool_args=None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        actual_tool = tool if tool is not None else kwargs.get("tool")
        actual_args = args if args is not None else tool_args if tool_args is not None else {}
        context = tool_context if tool_context is not None else kwargs.get("tool_context")
        if context is None:
            return None
        tool_name = str(getattr(actual_tool, "name", "") or actual_tool or "")

        if tool_name in exempt:
            return None

        state = context.state
        order = load_order(state, agent_name)
        if order is None:
            if tool_name in ORIENTATION_TOOLS:
                return None
            return _blocked(
                "no_work_order", tool_name,
                f"BLOCKED: declare your work order with declare_work_order before "
                f"calling `{tool_name}`. You may read your own context first "
                f"({', '.join(sorted(ORIENTATION_TOOLS))}).",
            )

        if order.status != "approved":
            return _blocked(
                "rejected", tool_name,
                "BLOCKED: the human rejected your work order. Do not act; finish "
                "and report why the task was not carried out.",
            )

        if tool_name in order.planned_tools or tool_name in ORIENTATION_TOOLS:
            order.tool_calls[tool_name] = order.tool_calls.get(tool_name, 0) + 1
            save_order(state, order)
            return None
        block = _blocked(
            "undeclared_tool", tool_name,
            f"BLOCKED: `{tool_name}` is not in your approved work order. If you "
            f"really need it, call update_work_order(reason=..., "
            f"add_tools=[\"{tool_name}\"]) — or continue with the planned tools.",
        )
        logger.info("[%s] work order guard: %s %s", agent_name, block["reason"], tool_name)
        await _record_deviation(context, order, block, actual_args)
        return block

    return work_order_guard


def make_reset_work_order(agent_name: str):
    """before_agent callback: every delegation starts without a contract.

    AgentTool copies the parent's state into the sub-run, so the order from the
    previous delegation of this agent would otherwise still be "approved".
    """

    def reset_work_order(callback_context=None, **kwargs) -> None:
        context = callback_context if callback_context is not None else kwargs.get("callback_context")
        if context is None:
            return None
        state = context.state
        if state.get(order_key(agent_name)) is not None:
            state[order_key(agent_name)] = None
        return None

    return reset_work_order


def _final_text(callback_context: Any, agent_name: str) -> str:
    """The agent's last text answer in this session, if the session is reachable."""
    invocation = getattr(callback_context, "_invocation_context", None)
    session = getattr(invocation, "session", None)
    for event in reversed(list(getattr(session, "events", None) or [])):
        if getattr(event, "author", None) != agent_name:
            continue
        parts = getattr(getattr(event, "content", None), "parts", None) or []
        text = "".join(getattr(p, "text", None) or "" for p in parts).strip()
        if text:
            return text
    return ""


def make_work_report_fallback(agent_name: str, handler: Any = None):
    """after_agent callback: the agent finished without an accepted Work Report.

    The run is over, so the human cannot send the agent back to work from here.
    The card is built from what the system recorded plus the agent's final text;
    anything but acceptance replaces the answer with the human's verdict, so the
    parent sees it and can delegate again.
    """

    def _handler():
        if handler is not None:
            return handler
        from CoScientist.agents.common import hitl_handler
        return hitl_handler

    async def work_report_fallback(callback_context=None, **kwargs) -> Optional[genai_types.Content]:
        from CoScientist.hitl.work_order_tools import WorkOrderToolset, work_order_active

        context = callback_context if callback_context is not None else kwargs.get("callback_context")
        if context is None or not work_order_active():
            return None
        order = load_order(context.state, agent_name)
        if order is None or order.status != "approved":
            return None
        if order.report is not None and order.report.status in ("accepted", "rejected"):
            return None

        final_text = _final_text(context, agent_name)
        previous_round = order.report.round if order.report is not None else 0
        order.report = WorkReport(
            summary=final_text, round=previous_round + 1, fallback=True,
        )
        toolset = WorkOrderToolset(agent_name, handler=_handler())
        try:
            response = await toolset.review_report(order, context)
        except Exception:  # noqa: BLE001 - a failed card must not swallow the answer
            logger.exception("%s: work report fallback failed", agent_name)
            return None

        feedback = (response.instructions or response.free_input or "").strip() if response else ""
        accepted = response is None or response.approved
        order.report.status = "accepted" if accepted else "rejected"
        order.report.operator_notes = feedback
        save_order(context.state, order)
        if accepted:
            return None
        return genai_types.Content(role="model", parts=[genai_types.Part(text=(
            f"The human did not accept the result of {agent_name}"
            f" (the agent finished without a work report). "
            f"Feedback: {feedback or 'none given'}. "
            f"Agent's answer was:\n{final_text or '(empty)'}\n\n"
            "Delegate the task again with this feedback, or report to the human "
            "why it could not be done."
        ))])

    return work_report_fallback
