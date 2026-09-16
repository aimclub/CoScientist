"""Work Order tools: declare the contract, amend it, report step progress.

One toolset instance per agent (the assembler builds it with the agent's real
tool names, so a contract can only name tools the agent actually has).

How a contract is confirmed depends on its risk tier (work_order_risk.py):

  read         a declaration is reviewed like compute; an amendment that only
               adds read tools is a notice card and returns at once;
  compute      a HITL request with a veto window — auto-approved when it runs out
               (a window of -1 disables auto-approval: it waits for the human);
  side_effect  a HITL request under the operator's global HITL timeout.

With HITL or Work Orders switched off, the contract is still recorded (the guard
keeps working as a budget/scope check) and approved without asking anyone.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from CoScientist.config import get_settings
from CoScientist.graph.session_scope import session_key
from CoScientist.hitl.models import HITLAction, HITLRequest, HITLResponse
from CoScientist.hitl.work_order import (
    Assumption,
    SideEffect,
    WorkOrder,
    WorkStep,
    diff_work_orders,
    load_order,
    render_work_order,
    save_order,
    usage_key,
)
from CoScientist.hitl.work_order_risk import (
    EXEMPT_TOOLS,
    TOOL_SIDE_EFFECTS,
    SideEffectKind,
    Tier,
    exempt_tools,
    max_tier,
    tool_tier,
)

logger = logging.getLogger("CoScientist.hitl.work_order")

_STEP_STATUSES = ("pending", "in_progress", "done", "skipped")


def work_order_active() -> bool:
    web = get_settings().web
    return bool(web.hitl_enabled and web.work_order_enabled)


def _error(message: str) -> Dict[str, Any]:
    return {"status": "error", "message": message}


def session_context(tool_context: Any) -> Dict[str, str]:
    user_id, session_id = session_key(tool_context)
    return {"user_id": user_id, "session_id": session_id}


class WorkOrderToolset:
    """declare_work_order / update_work_order / update_work_step for one agent."""

    def __init__(
        self,
        agent_name: str,
        valid_tool_names: Optional[Iterable[str]] = None,
        handler: Any = None,
        internal_tools: Iterable[str] = (),
    ) -> None:
        self.agent_name = agent_name
        # Allowed without declaring and kept apart from the contract's tools, so
        # they neither raise its tier nor show on the card unless the viewer
        # asks. The agent may still name them — that is no error.
        self.exempt = exempt_tools(internal_tools)
        # None: the agent's tool surface is resolved at runtime — names can't be checked.
        self.valid_tool_names = (
            None if valid_tool_names is None
            else set(valid_tool_names) - self.exempt
        )
        self._handler_override = handler

    # ── plumbing ────────────────────────────────────────────────────────────
    @property
    def handler(self):
        if self._handler_override is not None:
            return self._handler_override
        from CoScientist.agents.common import hitl_handler
        return hitl_handler

    def tools(self) -> List[FunctionTool]:
        return [
            FunctionTool(self.declare_work_order),
            FunctionTool(self.update_work_order),
            FunctionTool(self.update_work_step),
        ]

    def _unknown_tools(self, names: Iterable[str]) -> List[str]:
        if self.valid_tool_names is None:
            return []
        return [n for n in names if n not in self.valid_tool_names]


    def _parse_steps(self, raw: Optional[List[Any]], start: int = 1) -> List[WorkStep] | str:
        steps: List[WorkStep] = []
        for offset, item in enumerate(raw or []):
            if isinstance(item, str):
                item = {"title": item}
            if not isinstance(item, dict) or not str(item.get("title") or "").strip():
                return f"Step at index {offset} needs a non-empty 'title'."
            tools = item.get("tools") or []
            if isinstance(tools, str):
                tools = [tools]
            tools = [str(t) for t in tools]
            steps.append(WorkStep(
                id=f"S{start + offset}",
                title=str(item["title"]).strip(),
                tools=[t for t in tools if t not in self.exempt],
                internal_tools=self._internal_named(tools),
                expected_outcome=str(item.get("expected_outcome") or ""),
            ))
        return steps

    def _internal_named(self, names: Iterable[str], into: Optional[List[str]] = None) -> List[str]:
        """The internal tools among ``names``, appended to ``into`` without
        repeats. Protocol tools are not listed: nobody needs to see those."""
        found = list(into or [])
        for name in names:
            if name in self.exempt and name not in EXEMPT_TOOLS and name not in found:
                found.append(name)
        return found

    @staticmethod
    def _parse_assumptions(raw: Optional[List[Any]]) -> List[Assumption] | str:
        assumptions: List[Assumption] = []
        for offset, item in enumerate(raw or []):
            # A {"text": ...} dict is the older shape; models still send it now and then.
            if isinstance(item, dict):
                item = item.get("text")
            text = str(item or "").strip()
            if not text:
                return f"Assumption at index {offset} must be a non-empty string."
            assumptions.append(Assumption(id=f"A{offset + 1}", text=text))
        return assumptions


    @staticmethod
    def _implied_side_effects(tools: Iterable[str], effects: List[SideEffect]) -> None:
        """A tool whose very nature is a side effect declares it implicitly."""
        declared = {e.kind for e in effects}
        for tool in tools:
            kind = TOOL_SIDE_EFFECTS.get(tool)
            if kind is not None and kind not in declared:
                effects.append(SideEffect(kind=kind, detail=f"implied by {tool}"))
                declared.add(kind)

    async def _review(
        self,
        order: WorkOrder,
        tier: Tier,
        tool_context: Any,
        *,
        trigger: str,
        extra_context: Optional[Dict[str, Any]] = None,
        force_blocking: bool = False,
    ) -> Optional[HITLResponse]:
        """Put the contract (or amendment) in front of the human by tier.

        Returns None when nobody is asked (off, or a read-tier amendment
        notice): the caller treats that as approved.
        """
        session = session_context(tool_context)
        if not work_order_active():
            return None
        # A read-only amendment is just a notice; the contract itself always goes
        # to the human (under the veto window) — otherwise the agent starts first.
        if tier == Tier.READ and trigger != "work_order" and not force_blocking:
            try:
                await self.handler.notify({
                    "kind": "amended",
                    "agent_name": self.agent_name,
                    "tier": tier.value,
                    "work_order": order.model_dump(mode="json"),
                    "text": render_work_order(order),
                    **(extra_context or {}),
                    "_session": session,
                })
            except Exception:  # noqa: BLE001 - a notice must never fail the run
                logger.exception("%s: work order notice failed", self.agent_name)
            return None

        veto = tier in (Tier.READ, Tier.COMPUTE) and not force_blocking
        # A non-positive window reaches the handler as-is: no deadline, wait for the human.
        veto_seconds = get_settings().web.work_order_veto_seconds
        veto_timeout = float(veto_seconds) if veto_seconds > 0 else -1.0
        request = HITLRequest(
            agent_name=self.agent_name,
            action_type=HITLAction.APPROVE,
            message=(
                f"Agent '{self.agent_name}' declares a work order "
                f"(rev {order.revision}, tier {tier.value}). Please review."
            ),
            context={
                "work_order": order.model_dump(mode="json"),
                "tier": tier.value,
                "output": render_work_order(order),
                **(extra_context or {}),
                "_session": session,
            },
            invoked_via="tool",
            trigger=trigger,
            timeout_seconds=veto_timeout if veto else None,
        )
        return await self.handler.handle_request(request)

    # ── tools ───────────────────────────────────────────────────────────────
    async def declare_work_order(
        self,
        goal: str,
        done_criteria: str,
        assumptions: List[str],
        steps: List[Dict[str, Any]],
        planned_tools: List[str],
        tool_context: ToolContext,
        expected_outcome: str = "",
        fallback: str = "",
    ) -> Dict[str, Any]:
        """Declare your work order BEFORE your first external action.

        The human sees it and may approve, adjust or reject it. After approval
        you may only call the tools you declared; to need more, call
        update_work_order with a reason.

        Args:
            goal: What this run must achieve, in one or two sentences.
            done_criteria: How you will know you are done.
            assumptions: Every assumption your plan relies on, one string per
                item. Keep assumptions atomic (one condition per item) and non-trivial.
            steps: Ordered steps, each {"title", "tools": [tool names],
                "expected_outcome"}.
            planned_tools: All tool names you intend to call.
            expected_outcome: What result you expect (be concrete: counts,
                ranges, metrics).
            fallback: What you will do if the plan does not work.

        Returns:
            {"status": "approved" | "revise" | "rejected" | "error", ...}.
        """
        state = tool_context.state
        current = load_order(state, self.agent_name)
        if current is not None and current.status == "approved":
            return _error(
                "A work order is already approved for this run. To change it, "
                "call update_work_order with a reason."
            )
        if current is not None and current.status == "rejected":
            return {
                "status": "rejected",
                "message": "The human rejected your work order. Do not act; "
                           "finish and report why the task was not carried out.",
            }
        if not str(goal or "").strip():
            return _error("'goal' must not be empty.")

        parsed_assumptions = self._parse_assumptions(assumptions)
        if isinstance(parsed_assumptions, str):
            return _error(parsed_assumptions)
        parsed_steps = self._parse_steps(steps)
        if isinstance(parsed_steps, str):
            return _error(parsed_steps)
        named = [str(t) for t in planned_tools or []]
        tools: List[str] = []
        for name in named + [t for s in parsed_steps for t in s.tools]:
            if name not in tools and name not in self.exempt:
                tools.append(name)
        internal = self._internal_named(
            named + [t for s in parsed_steps for t in s.internal_tools]
        )
        unknown = self._unknown_tools(tools)
        if unknown:
            return _error(
                f"Unknown tools {unknown}. You can only plan tools you have: "
                f"{sorted(self.valid_tool_names or [])}."
            )
        effects: List[SideEffect] = []
        self._implied_side_effects(tools, effects)

        order = WorkOrder(
            agent=self.agent_name,
            goal=str(goal).strip(),
            done_criteria=str(done_criteria or ""),
            assumptions=parsed_assumptions,
            steps=parsed_steps,
            planned_tools=tools,
            internal_tools=internal,
            side_effects=effects,
            expected_outcome=str(expected_outcome or ""),
            fallback=str(fallback or ""),
        )
        tier = order.recompute_tier()

        response = await self._review(order, tier, tool_context, trigger="work_order")
        return self._settle_declaration(state, order, response)

    def _settle_declaration(
        self, state: Any, order: WorkOrder, response: Optional[HITLResponse]
    ) -> Dict[str, Any]:
        feedback = (response.instructions or response.free_input or "").strip() if response else ""

        if response is not None and response.action == HITLAction.EDIT:
            return {
                "status": "revise",
                "feedback": feedback or "No feedback provided.",
                "message": "The human asked for changes. Declare a revised work "
                           "order with declare_work_order before acting.",
            }
        if response is not None and not response.approved:
            order.status = "rejected"
            order.operator_notes = feedback
            save_order(state, order)
            return {
                "status": "rejected",
                "reason": feedback or "No reason given.",
                "message": "The human rejected your work order. Do not act; "
                           "finish and report why the task was not carried out.",
            }

        rejected_ids = set()
        if response is not None and isinstance(response.form_values, dict):
            rejected_ids = {str(i) for i in response.form_values.get("rejected_assumption_ids") or []}
        for assumption in order.assumptions:
            assumption.rejected = assumption.id in rejected_ids
        order.status = "approved"
        order.operator_notes = feedback
        save_order(state, order)
        state[usage_key(self.agent_name)] = {}

        result: Dict[str, Any] = {
            "status": "approved",
            "mode": "autonomous" if not work_order_active() else order.tier.value,
            "revision": order.revision,
            "steps": [{"id": s.id, "title": s.title} for s in order.steps],
            "message": "Proceed within this work order. Mark each step with "
                       "update_work_step as you start and finish it.",
        }
        rejected = [a.text for a in order.assumptions if a.rejected]
        if rejected:
            result["rejected_assumptions"] = rejected
            result["message"] += (" The human REJECTED the listed assumptions: do not "
                                  "rely on them — adapt the plan accordingly.")
        if feedback:
            result["operator_notes"] = feedback
            result["message"] += " Follow the operator notes."
        return result

    async def update_work_order(
        self,
        reason: str,
        tool_context: ToolContext,
        add_tools: Optional[List[str]] = None,
        add_steps: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Amend your approved work order when you need to go beyond it.

        Call this when a tool call was blocked by the work order guard, or
        before doing something the contract does not cover. The human sees the
        change as a diff.

        Args:
            reason: Why the amendment is needed (what you learned).
            add_tools: Tool names to add to the plan.
            add_steps: Steps to append, each {"title", "tools",
                "expected_outcome"}.

        Returns:
            {"status": "approved" | "revise" | "rejected" | "error", ...}.
        """
        state = tool_context.state
        old = load_order(state, self.agent_name)
        if old is None or old.status != "approved":
            return _error("There is no approved work order to amend — call declare_work_order first.")
        if not str(reason or "").strip():
            return _error("'reason' must explain why the amendment is needed.")

        new_steps = self._parse_steps(add_steps, start=len(old.steps) + 1)
        if isinstance(new_steps, str):
            return _error(new_steps)

        new = old.model_copy(deep=True)
        named = [str(t) for t in add_tools or []]
        for name in named + [t for s in new_steps for t in s.tools]:
            if name not in new.planned_tools and name not in self.exempt:
                new.planned_tools.append(name)
        new.internal_tools = self._internal_named(
            named + [t for s in new_steps for t in s.internal_tools], into=new.internal_tools
        )
        unknown = self._unknown_tools(new.planned_tools)
        if unknown:
            return _error(
                f"Unknown tools {unknown}. You can only plan tools you have: "
                f"{sorted(self.valid_tool_names or [])}."
            )
        new.steps.extend(new_steps)
        self._implied_side_effects(new.planned_tools, new.side_effects)
        new.revision = old.revision + 1

        diff = diff_work_orders(old, new)
        if not any(diff.values()):
            if new.internal_tools != old.internal_tools:
                # Nothing to review: internal tools were never blocked.
                old.internal_tools = new.internal_tools
                save_order(state, old)
                return {
                    "status": "approved",
                    "revision": old.revision,
                    "message": "No amendment needed: those tools are always allowed.",
                }
            return _error("The amendment changes nothing. Name the tools or steps you need.")

        delta_tier = max_tier(
            [tool_tier(t) for t in diff["added_tools"]]
            + ([Tier.SIDE_EFFECT] if diff["added_side_effects"] else [])
        )
        new.recompute_tier()
        force_blocking = len(old.amendments) >= get_settings().web.work_order_max_amendments

        response = await self._review(
            new, delta_tier, tool_context,
            trigger="work_order_amendment",
            extra_context={"diff": diff, "reason": str(reason).strip()},
            force_blocking=force_blocking,
        )
        feedback = (response.instructions or response.free_input or "").strip() if response else ""

        if response is not None and response.action == HITLAction.EDIT:
            return {
                "status": "revise",
                "feedback": feedback or "No feedback provided.",
                "message": "The human asked for a different amendment. Adjust it "
                           "and call update_work_order again, or stay within the current order.",
            }
        if response is not None and not response.approved:
            return {
                "status": "rejected",
                "reason": feedback or "No reason given.",
                "message": "The amendment was rejected. Continue within the current "
                           "work order, or finish and report what could not be done.",
            }

        new.amendments.append({
            "revision": new.revision,
            "reason": str(reason).strip(),
            "diff": diff,
            "operator_notes": feedback,
        })
        new.status = "approved"
        save_order(state, new)
        result = {
            "status": "approved",
            "revision": new.revision,
            "message": "Amendment approved. Proceed within the updated work order.",
        }
        if feedback:
            result["operator_notes"] = feedback
        return result

    async def update_work_step(
        self,
        step_id: str,
        status: str,
        tool_context: ToolContext,
        note: str = "",
    ) -> Dict[str, Any]:
        """Report progress on a step of your approved work order.

        Args:
            step_id: The step id from the approved order (e.g. "S1").
            status: One of pending, in_progress, done, skipped.
            note: Short note: what came out, or why it was skipped.

        Returns:
            {"status": "ok" | "error", ...}.
        """
        state = tool_context.state
        order = load_order(state, self.agent_name)
        if order is None or order.status != "approved":
            return _error("There is no approved work order — call declare_work_order first.")
        if status not in _STEP_STATUSES:
            return _error(f"'status' must be one of {list(_STEP_STATUSES)}.")
        step = order.step(step_id)
        if step is None:
            return _error(f"Unknown step {step_id!r}; steps are {[s.id for s in order.steps]}.")
        step.status = status  # type: ignore[assignment]
        step.note = str(note or "")
        save_order(state, order)
        if work_order_active():
            try:
                await self.handler.notify({
                    "kind": "progress",
                    "agent_name": self.agent_name,
                    "revision": order.revision,
                    "step": step.model_dump(mode="json"),
                    "_session": session_context(tool_context),
                })
            except Exception:  # noqa: BLE001 - a notice must never fail the run
                logger.exception("%s: work step notice failed", self.agent_name)
        return {"status": "ok", "step": step.id, "step_status": step.status}


def make_work_order_tools(
    agent_name: str,
    valid_tool_names: Optional[Iterable[str]] = None,
    internal_tools: Iterable[str] = (),
) -> List[FunctionTool]:
    return WorkOrderToolset(agent_name, valid_tool_names, internal_tools=internal_tools).tools()
