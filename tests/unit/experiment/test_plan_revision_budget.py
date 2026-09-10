"""Plan identity is runtime bookkeeping, and the revision budget counts failures.

Observed 2026-09-04 on a live Heracleum session: a human edited the plan through
HITL, the regenerated plan came back as ``PLAN-EXRUN-<uuid>`` where the runtime
held ``PLAN-<uuid>``, the deterministic critique blocked it as "plan_id changed
between revisions", the two-round budget ran out and the module returned
"Experiment plan review is paused for this session" — with zero MCP calls, while
every tool it needed was live and indexed.

Two things were wrong. The model was being asked for fields only the runtime can
know, and the budget was never reset on success, so it bounded a whole session
rather than a run of consecutive failures.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from CoScientist.config.settings import ExperimentsSettings
from CoScientist.experiments import review as review_mod
from CoScientist.experiments.critique.validator import validate_and_critique_plan
from CoScientist.experiments.review import (
    ExperimentReviewSessionAgent,
    _stamp_context_invariants,
)

from .helpers import _inventory, _plan, _task


def _context(plan) -> dict:
    return {
        "experiment_run_id": plan.experiment_run_id,
        "source_request": plan.source_request,
        "available_mcp_capabilities": _inventory(),
    }


# --------------------------------------------------------------------------
# plan identity


def test_plan_identity_is_stamped_from_the_runtime():
    previous = _plan(_task("EXP-1"))
    payload = previous.model_dump(mode="json")
    payload["plan_id"] = "PLAN-EXRUN-invented-by-the-model"
    payload["revision"] = 1

    stamped = _stamp_context_invariants(payload, _context(previous), previous)

    assert stamped["plan_id"] == previous.plan_id
    assert stamped["revision"] == previous.revision + 1


def test_a_first_plan_keeps_the_identity_it_came_with():
    plan = _plan(_task("EXP-1"))
    payload = plan.model_dump(mode="json")

    stamped = _stamp_context_invariants(payload, _context(plan), None)

    assert stamped["plan_id"] == plan.plan_id
    assert stamped["revision"] == plan.revision


@pytest.mark.parametrize(
    ("plan_id", "revision"),
    [
        ("PLAN-EXRUN-acceptance", 2),   # prefix drift, revision fine
        ("PLAN-acceptance", 1),         # identity fine, revision not incremented
        ("PLAN-EXRUN-acceptance", 1),   # both wrong
    ],
)
def test_stamping_defuses_both_bookkeeping_blockers(plan_id, revision):
    """Neither validator check can fire on a model formatting slip any more."""
    previous = _plan(_task("EXP-1"))
    payload = previous.model_dump(mode="json")
    payload["plan_id"] = plan_id
    payload["revision"] = revision

    stamped = _stamp_context_invariants(payload, _context(previous), previous)
    _, critique = validate_and_critique_plan(
        stamped, settings=ExperimentsSettings(), available_tools=_inventory(),
        previous_plan=previous,
    )

    bookkeeping = [
        i for i in critique.issues
        if "plan_id changed" in i.message or "must increment revision" in i.message
    ]
    assert bookkeeping == [], [i.message for i in bookkeeping]


def test_the_validator_still_guards_identity_when_nothing_stamped_it():
    """The checks stay meaningful: they just stop punishing the model."""
    previous = _plan(_task("EXP-1"))
    payload = previous.model_dump(mode="json")
    payload["plan_id"] = "PLAN-EXRUN-acceptance"

    _, critique = validate_and_critique_plan(
        payload, settings=ExperimentsSettings(), available_tools=_inventory(),
        previous_plan=previous,
    )

    assert any("plan_id changed" in i.message for i in critique.issues)


# --------------------------------------------------------------------------
# budget


def test_a_plan_that_validates_resets_the_revision_budget(monkeypatch):
    """The budget bounds CONSECUTIVE failures, not the lifetime of a session."""
    plan = _plan(_task("EXP-1"))
    state = {
        "experiment_context": _context(plan),
        "experiment_plan_revision_count": 3,
        "experiment_inventory_blocker_hits": 1,
    }
    monkeypatch.setenv("COSCIENTIST_EXPERIMENT_HITL_AUTO_APPROVE", "1")
    # approve_plan resets the counters too; stub it so only the new reset can pass.
    monkeypatch.setattr(review_mod, "approve_plan", lambda _state: None)
    monkeypatch.setattr(review_mod, "_publish_approved_plan_to_graph", lambda *_a, **_k: None)

    agent = ExperimentReviewSessionAgent(name="Reviewer", review_kind="plan")
    ctx = SimpleNamespace(session=SimpleNamespace(state=state), invocation_id="inv-1")
    response = asyncio.run(agent._review_plan(ctx, plan.model_dump_json()))

    assert response.approved, state.get("experiment_plan_validation_errors")
    assert state["experiment_plan_revision_count"] == 0
    assert state["experiment_inventory_blocker_hits"] == 0


def test_a_replan_starts_from_a_full_revision_budget():
    """A rejected result review opens a new planning round, not a spent one."""
    from CoScientist.experiments.runtime import mark_result_review

    from .helpers import _approved_state

    state = _approved_state(_plan(_task("EXP-1")))
    state["experiment_runtime"]["phase"] = "reporting"
    state["experiment_plan_revision_count"] = 3
    state["experiment_inventory_blocker_hits"] = 2

    out = mark_result_review(state, approved=False, feedback="metrics missing")

    assert out["phase"] == "replan_requested"
    assert state["experiment_plan_revision_count"] == 0
    assert state["experiment_inventory_blocker_hits"] == 0


def test_the_budget_leaves_room_for_a_human_round():
    """Two rounds could not absorb one HITL edit plus one planner slip."""
    assert ExperimentsSettings().max_plan_revisions >= 4
