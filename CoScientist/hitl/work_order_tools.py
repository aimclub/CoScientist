"""Work Order tools: declare the contract, amend it, report step progress.

One toolset instance per agent (the assembler builds it with the agent's real
tool names, so a contract can only name tools the agent actually has).

How a contract is confirmed depends on its risk tier (work_order_risk.py):

  read         the human gets a notice card; the tool returns at once;
  compute      a HITL request with a veto window — auto-approved when it runs out;
  side_effect  a HITL request under the operator's global HITL timeout.

With HITL or Work Orders switched off, the contract is still recorded (the guard
keeps working as a budget/scope check) and approved without asking anyone.
"""
from __future__ import annotations

import logging
import re
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
    max_tier,
    tool_tier,
)

logger = logging.getLogger("CoScientist.hitl.work_order")

_STEP_STATUSES = ("pending", "in_progress", "done", "skipped")
_CONFIDENCE_RE = re.compile(r"\s*[\(\[]\s*confidence\s*[:=]\s*(low|medium|high)\s*[\)\]]\s*$", re.I)


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
    ) -> None:
        self.agent_name = agent_name
        # None: the agent's tool surface is resolved at runtime — names can't be checked.
        self.valid_tool_names = (
            None if valid_tool_names is None
            else set(valid_tool_names) - EXEMPT_TOOLS
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

    def _parse_side_effects(self, raw: Optional[List[Any]]) -> List[SideEffect] | str:
        effects: List[SideEffect] = []
        valid = [k.value for k in SideEffectKind]
        for item in raw or []:
            if isinstance(item, str):
                item = {"kind": item}
            if not isinstance(item, dict) or item.get("kind") not in valid:
                return f"Invalid side effect {item!r}: 'kind' must be one of {valid}."
            effects.append(SideEffect(kind=item["kind"], detail=str(item.get("detail") or "")))
        return effects

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
            steps.append(WorkStep(
                id=f"S{start + offset}",
                title=str(item["title"]).strip(),
                tools=[str(t) for t in tools],
                expected_outcome=str(item.get("expected_outcome") or ""),
            ))
        return steps

    @staticmethod
    def _parse_budget(raw: Optional[Dict[str, Any]]) -> Dict[str, int] | str:
        budget: Dict[str, int] = {}
        for tool, limit in (raw or {}).items():
            try:
                value = int(limit)
            except (TypeError, ValueError):
                return f"Budget for {tool!r} must be an integer, got {limit!r}."
            if value < 1:
                return f"Budget for {tool!r} must be at least 1."
            budget[str(tool)] = value
        return budget

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

        Returns None when nobody is asked (off, or a read-tier notice): the
        caller treats that as approved.
        """
        session = session_context(tool_context)
        if not work_order_active():
            return None
        if tier == Tier.READ and not force_blocking:
            try:
                await self.handler.notify({
                    "kind": "declared" if trigger == "work_order" else "amended",
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

        web = get_settings().web
        veto = tier == Tier.COMPUTE and not force_blocking
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
            timeout_seconds=float(web.work_order_veto_seconds) if veto else None,
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
        side_effects: Optional[List[Dict[str, Any]]] = None,
        budget: Optional[Dict[str, int]] = None,
        expected_outcome: str = "",
        fallback: str = "",
    ) -> Dict[str, Any]:
        """Declare your work order BEFORE your first external action.

        The human sees it and may approve, adjust or reject it. After approval
        you may only call the tools you declared, within the budget; to need
        more, call update_work_order with a reason.

        Args:
            goal: What this run must achieve, in one or two sentences.
            done_criteria: How you will know you are done.
            assumptions: Every assumption your plan relies on (data sources,
                units, scope, filters, interpretation of the task). Append
                "(confidence: low|medium|high)" to an item when unsure.
            steps: Ordered steps, each {"title", "tools": [tool names],
                "expected_outcome"}.
            planned_tools: All tool names you intend to call.
            side_effects: Effects beyond reading/computing, each {"kind",
                "detail"}; kind is one of package_install, network_download,
                git_write, long_job, file_delete, external_share.
            budget: Max calls per tool, e.g. {"tavily_search": 3}.
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

        parsed_steps = self._parse_steps(steps)
        if isinstance(parsed_steps, str):
            return _error(parsed_steps)
        effects = self._parse_side_effects(side_effects)
        if isinstance(effects, str):
            return _error(effects)
        parsed_budget = self._parse_budget(budget)
        if isinstance(parsed_budget, str):
            return _error(parsed_budget)

        tools: List[str] = []
        for name in list(planned_tools or []) + [t for s in parsed_steps for t in s.tools]:
            if name not in tools and name not in EXEMPT_TOOLS:
                tools.append(name)
        unknown = self._unknown_tools(tools + list(parsed_budget))
        if unknown:
            return _error(
                f"Unknown tools {unknown}. You can only plan tools you have: "
                f"{sorted(self.valid_tool_names or [])}."
            )
        stray_budget = [t for t in parsed_budget if t not in tools]
        if stray_budget:
            return _error(f"Budget names tools that are not planned: {stray_budget}.")
        self._implied_side_effects(tools, effects)

        parsed_assumptions = []
        for i, text in enumerate(assumptions or [], 1):
            text = str(text)
            m = _CONFIDENCE_RE.search(text)
            parsed_assumptions.append(Assumption(
                id=f"A{i}",
                text=_CONFIDENCE_RE.sub("", text).strip(),
                confidence=m.group(1).lower() if m else "medium",
            ))

        order = WorkOrder(
            agent=self.agent_name,
            goal=str(goal).strip(),
            done_criteria=str(done_criteria or ""),
            assumptions=parsed_assumptions,
            steps=parsed_steps,
            planned_tools=tools,
            side_effects=effects,
            budget=parsed_budget,
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
        add_side_effects: Optional[List[Dict[str, Any]]] = None,
        add_steps: Optional[List[Dict[str, Any]]] = None,
        budget: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Amend your approved work order when you need to go beyond it.

        Call this when a tool call was blocked by the work order guard, or
        before doing something the contract does not cover. The human sees the
        change as a diff.

        Args:
            reason: Why the amendment is needed (what you learned).
            add_tools: Tool names to add to the plan.
            add_side_effects: Side effects to add, each {"kind", "detail"}.
            add_steps: Steps to append, each {"title", "tools",
                "expected_outcome"}.
            budget: New max calls per tool, e.g. {"tavily_search": 5}.

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
        effects = self._parse_side_effects(add_side_effects)
        if isinstance(effects, str):
            return _error(effects)
        parsed_budget = self._parse_budget(budget)
        if isinstance(parsed_budget, str):
            return _error(parsed_budget)

        new = old.model_copy(deep=True)
        for name in list(add_tools or []) + [t for s in new_steps for t in s.tools]:
            if name not in new.planned_tools and name not in EXEMPT_TOOLS:
                new.planned_tools.append(name)
        unknown = self._unknown_tools(new.planned_tools + list(parsed_budget))
        if unknown:
            return _error(
                f"Unknown tools {unknown}. You can only plan tools you have: "
                f"{sorted(self.valid_tool_names or [])}."
            )
        stray_budget = [t for t in parsed_budget if t not in new.planned_tools]
        if stray_budget:
            return _error(f"Budget names tools that are not planned: {stray_budget}.")
        new.steps.extend(new_steps)
        existing = {(e.kind, e.detail) for e in new.side_effects}
        new.side_effects.extend(e for e in effects if (e.kind, e.detail) not in existing)
        self._implied_side_effects(new.planned_tools, new.side_effects)
        new.budget.update(parsed_budget)
        new.revision = old.revision + 1

        diff = diff_work_orders(old, new)
        if not any(diff.values()):
            return _error("The amendment changes nothing. Name the tools, side effects, "
                          "steps or budget you need.")

        delta_tier = max_tier(
            [tool_tier(t) for t in diff["added_tools"]]
            + [tool_tier(t) for t in diff["budget_changes"]]
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
) -> List[FunctionTool]:
    return WorkOrderToolset(agent_name, valid_tool_names).tools()
