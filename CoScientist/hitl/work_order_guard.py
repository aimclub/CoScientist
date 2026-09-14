"""Keep an agent inside its approved Work Order.

A deterministic before_tool check, so a contract binds the agent instead of
being a promise the model may forget after the first surprising search result:

  * before a contract is declared only orientation reads go through;
  * after a rejection nothing does;
  * afterwards a call must use a declared tool, stay within its budget, and
    not produce a side effect the contract did not declare.

A blocked call is not a dead end: the message tells the agent to amend the
contract (update_work_order), which puts the change in front of the human.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from CoScientist.hitl.work_order import load_order, order_key, save_order, usage_key
from CoScientist.hitl.work_order_risk import EXEMPT_TOOLS, ORIENTATION_TOOLS, classify_call

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


def make_work_order_guard(agent_name: str, handler: Any = None):
    """before_tool callback enforcing ``agent_name``'s Work Order."""

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

        if tool_name in EXEMPT_TOOLS:
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

        block = None
        _, side_effect = classify_call(tool_name, actual_args)
        usage = dict(state.get(usage_key(agent_name)) or {})
        if tool_name not in order.planned_tools and tool_name not in ORIENTATION_TOOLS:
            block = _blocked(
                "undeclared_tool", tool_name,
                f"BLOCKED: `{tool_name}` is not in your approved work order. If you "
                f"really need it, call update_work_order(reason=..., "
                f"add_tools=[\"{tool_name}\"]) — or continue with the planned tools.",
            )
        elif tool_name in order.budget and usage.get(tool_name, 0) >= order.budget[tool_name]:
            block = _blocked(
                "budget_exceeded", tool_name,
                f"BLOCKED: the budget for `{tool_name}` ({order.budget[tool_name]} calls) "
                f"is used up. Work with what you have, or call update_work_order("
                f"reason=..., budget={{\"{tool_name}\": <new limit>}}).",
                budget=order.budget[tool_name],
            )
        elif side_effect is not None and side_effect not in order.side_effect_kinds():
            block = _blocked(
                "undeclared_side_effect", tool_name,
                f"BLOCKED: this call has a side effect ({side_effect.value}) your work "
                f"order does not declare. Call update_work_order(reason=..., "
                f"add_side_effects=[{{\"kind\": \"{side_effect.value}\", \"detail\": ...}}]) "
                f"first, or do it without that side effect.",
                side_effect=side_effect.value,
            )

        if block is not None:
            logger.info("[%s] work order guard: %s %s", agent_name, block["reason"], tool_name)
            await _record_deviation(context, order, block, actual_args)
            return block

        usage[tool_name] = usage.get(tool_name, 0) + 1
        state[usage_key(agent_name)] = usage
        return None

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
        if state.get(usage_key(agent_name)):
            state[usage_key(agent_name)] = {}
        return None

    return reset_work_order
