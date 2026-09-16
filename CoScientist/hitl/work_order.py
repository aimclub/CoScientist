"""Work Order — the contract an executor agent declares before it acts.

Before its first external action an agent states WHAT it is going to do and on
WHICH assumptions: goal, done criteria, assumptions, steps, tools, side effects,
budget and the outcome it expects. The human reviews that contract (by risk
tier, see work_order_risk.py) and the guard (work_order_guard.py) then keeps
the agent inside it. Needing more is not forbidden — it is an amendment the
agent must justify, and the human sees it as a diff.

State lives in flat, per-agent keys that are always written whole: AgentTool
forwards a sub-agent's ``state_delta`` to the parent, and mutating a nested dict
in place produces no delta at all.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from CoScientist.hitl.work_order_risk import SideEffectKind, Tier, order_tier

StepStatus = Literal["pending", "in_progress", "done", "skipped"]
OrderStatus = Literal["pending", "approved", "rejected"]


def order_key(agent_name: str) -> str:
    return f"work_order:{agent_name}"


def usage_key(agent_name: str) -> str:
    return f"work_order_usage:{agent_name}"


class WorkStep(BaseModel):
    id: str
    title: str
    tools: List[str] = Field(default_factory=list)
    # Internal tools the agent named for this step: allowed anyway, kept out of
    # `tools` (and so out of the tier), shown only when the viewer asks for them.
    internal_tools: List[str] = Field(default_factory=list)
    expected_outcome: str = ""
    status: StepStatus = "pending"
    note: str = ""


class Assumption(BaseModel):
    id: str
    text: str
    rejected: bool = False


class SideEffect(BaseModel):
    kind: SideEffectKind
    detail: str = ""


class WorkOrder(BaseModel):
    agent: str
    goal: str
    done_criteria: str = ""
    assumptions: List[Assumption] = Field(default_factory=list)
    steps: List[WorkStep] = Field(default_factory=list)
    planned_tools: List[str] = Field(default_factory=list)
    # Internal tools the agent named anywhere in the order (see WorkStep).
    internal_tools: List[str] = Field(default_factory=list)
    side_effects: List[SideEffect] = Field(default_factory=list)
    # tool name -> max calls; a tool absent from the budget is not capped.
    budget: Dict[str, int] = Field(default_factory=dict)
    expected_outcome: str = ""
    fallback: str = ""
    tier: Tier = Tier.READ
    status: OrderStatus = "pending"
    revision: int = 1
    amendments: List[Dict[str, Any]] = Field(default_factory=list)
    deviations: List[Dict[str, Any]] = Field(default_factory=list)
    operator_notes: str = ""

    def side_effect_kinds(self) -> set:
        return {s.kind for s in self.side_effects}

    def recompute_tier(self) -> Tier:
        self.tier = order_tier(self.planned_tools, self.side_effect_kinds())
        return self.tier

    def step(self, step_id: str) -> Optional[WorkStep]:
        return next((s for s in self.steps if s.id == step_id), None)


def load_order(state: Any, agent_name: str) -> Optional[WorkOrder]:
    raw = state.get(order_key(agent_name)) if state is not None else None
    if not raw:
        return None
    try:
        return WorkOrder.model_validate(raw)
    except Exception:  # noqa: BLE001 - a corrupt entry behaves as "no order"
        return None


def save_order(state: Any, order: WorkOrder) -> None:
    state[order_key(order.agent)] = order.model_dump(mode="json")


_STEP_MARK = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]", "skipped": "[-]"}


def render_work_order(order: WorkOrder) -> str:
    """Plain-text rendering for the console handler, logs and the card fallback."""
    lines = [
        f"Work Order: {order.agent} (rev {order.revision}, tier {order.tier.value})",
        f"Goal: {order.goal}",
    ]
    if order.done_criteria:
        lines.append(f"Done when: {order.done_criteria}")
    if order.assumptions:
        lines.append("\nAssumptions:")
        for a in order.assumptions:
            mark = " (rejected)" if a.rejected else ""
            lines.append(f"  {a.id}. {a.text}{mark}")
    if order.steps:
        lines.append("\nSteps:")
        for s in order.steps:
            tools = f" — {', '.join(s.tools)}" if s.tools else ""
            lines.append(f"  {_STEP_MARK.get(s.status, '[ ]')} {s.id}. {s.title}{tools}")
            if s.expected_outcome:
                lines.append(f"      expect: {s.expected_outcome}")
    if order.planned_tools:
        lines.append(f"\nTools: {', '.join(order.planned_tools)}")
    if order.side_effects:
        lines.append("Side effects: " + "; ".join(
            f"{s.kind.value}" + (f" ({s.detail})" if s.detail else "") for s in order.side_effects
        ))
    if order.budget:
        lines.append("Budget: " + ", ".join(f"{k} ≤ {v}" for k, v in order.budget.items()))
    if order.expected_outcome:
        lines.append(f"Expected outcome: {order.expected_outcome}")
    if order.fallback:
        lines.append(f"If it fails: {order.fallback}")
    return "\n".join(lines)


def diff_work_orders(old: WorkOrder, new: WorkOrder) -> Dict[str, Any]:
    """What an amendment adds or raises — the part the human has to judge."""
    old_steps = {s.id for s in old.steps}
    old_effects = {(s.kind, s.detail) for s in old.side_effects}
    return {
        "added_tools": [t for t in new.planned_tools if t not in old.planned_tools],
        "added_side_effects": [
            s.model_dump(mode="json") for s in new.side_effects
            if (s.kind, s.detail) not in old_effects
        ],
        "added_steps": [s.model_dump(mode="json") for s in new.steps if s.id not in old_steps],
        "budget_changes": {
            tool: {"from": old.budget.get(tool), "to": limit}
            for tool, limit in new.budget.items()
            if old.budget.get(tool) != limit
        },
    }
