"""The module's dispatch budget, and why a review did not approve.

Both defects come from one run — Heracleum, 2026-09-21. The plan went up for
review at 13:36:26, nobody answered, the fail-closed policy rejected it at
13:41:26, and at 13:41:49 the orchestrator's retry was refused with

    suppressed ExperimentModuleAgent: runs=2/2 plan_paused=False

while the call graph held exactly ONE ExperimentModuleAgent node. Two
separate faults in one line:

* `runs=2/2` — `coalesce_experiment_module_calls` incremented the counter on
  every dispatch the orchestrator emitted, and the suppressor, the next
  `after_model` callback, compared it with `>=`. The retry spent a unit of its
  own budget and was then refused by it, so `max_replans=2` bought one run.
* `plan_paused=False` — a review that timed out wrote nothing to state, so the
  reason reaching the operator was the attempt budget rather than the five
  minutes nobody was at the screen.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from CoScientist.config import get_settings
from CoScientist.experiments import review as review_mod
from CoScientist.experiments.review import PAUSE_REASON_STATE_KEY
from CoScientist.experiments.runtime import coalesce as coalesce_mod
from CoScientist.experiments.runtime.coalesce import (
    coalesce_experiment_module_calls,
    suppress_experiment_module_after_completed,
)

_EM = "ExperimentModuleAgent"


def _dispatch(*requests: str):
    """A model turn that calls the module, the way the orchestrator does."""
    parts = [SimpleNamespace(function_call=SimpleNamespace(name=_EM, args={"request": r}),
                             text=None)
             for r in (requests or ("run the experiment",))]
    content = SimpleNamespace(parts=parts, role="model")
    return SimpleNamespace(content=content)


def _turn(state: dict, response=None):
    """Run both after_model callbacks in the order experiments.yaml lists them."""
    response = response if response is not None else _dispatch()
    ctx = SimpleNamespace(state=state, agent_name="OrchestratorAgent",
                          user_content=None)
    coalesce_experiment_module_calls(ctx, response)
    suppress_experiment_module_after_completed(ctx, response)
    names = [getattr(getattr(p, "function_call", None), "name", None)
             for p in response.content.parts]
    return {
        "dispatched": _EM in names,
        "runs": state.get("experiment_module_runs"),
        "text": " ".join(p.text for p in response.content.parts
                         if getattr(p, "text", None)),
    }


@pytest.fixture()
def budget_of_two(monkeypatch):
    monkeypatch.setattr(get_settings().experiments, "max_replans", 2)
    return 2


# ── the budget ──────────────────────────────────────────────────────────────

def test_a_budget_of_two_buys_two_runs(budget_of_two):
    """It bought one: the second dispatch paid for itself and was refused."""
    state: dict = {}

    first = _turn(state)
    assert first["dispatched"] and first["runs"] == 1

    second = _turn(state)
    assert second["dispatched"], f"the retry was refused: {second['text']}"
    assert second["runs"] == 2

    third = _turn(state)
    assert not third["dispatched"], "a third run was allowed on a budget of two"
    assert "attempt budget" in third["text"], third["text"]
    assert state["experiment_module_runs"] == 2, "a refused dispatch was charged"


def test_a_turn_that_asks_for_nothing_costs_nothing(budget_of_two):
    """The suppressor runs after every model turn of the orchestrator, and
    there are a couple of hundred in a run."""
    state: dict = {}
    plain = SimpleNamespace(content=SimpleNamespace(
        parts=[SimpleNamespace(text="thinking out loud", function_call=None)],
        role="model"))
    for _ in range(50):
        _turn(state, plain)
    assert state.get("experiment_module_runs") is None
    assert _turn(state)["runs"] == 1


def test_a_fan_out_of_three_is_one_brief_and_one_unit(budget_of_two):
    """Coalescing is why the counter cannot simply count function calls."""
    state = {"orchestrator_root_goal": "profile the metabolites"}
    response = _dispatch("cluster them", "predict LD50", "write it up")
    out = _turn(state, response)

    calls = [p for p in response.content.parts
             if getattr(getattr(p, "function_call", None), "name", None) == _EM]
    assert len(calls) == 1 and out["runs"] == 1
    assert calls[0].function_call.args["request"] == "profile the metabolites"


def test_a_paused_plan_is_refused_whatever_the_budget_says(budget_of_two):
    state = {"experiment_plan_review_paused": True}
    out = _turn(state)
    assert not out["dispatched"]
    assert "paused" in out["text"], out["text"]
    # And a refusal does not quietly spend the budget it did not use.
    assert state.get("experiment_module_runs") is None


# ── why it did not approve ──────────────────────────────────────────────────

def test_the_operator_is_told_the_review_ran_out_not_the_budget(budget_of_two):
    """The sentence the orchestrator writes into the final report."""
    state = {"experiment_module_runs": 2,
             PAUSE_REASON_STATE_KEY: "plan_review_timeout"}
    out = _turn(state)
    assert not out["dispatched"]
    assert "waiting for a human approval" in out["text"], out["text"]
    assert "2/2 attempts used" in out["text"], out["text"]

    state[PAUSE_REASON_STATE_KEY] = "result_review_timeout"
    assert "experiment result was waiting" in _turn(state)["text"]

    # A budget spent on plans that could not be fixed still says so.
    state[PAUSE_REASON_STATE_KEY] = "max_plan_revisions"
    assert "maximum attempt budget" in _turn(state)["text"]


def test_the_two_modules_agree_on_the_name_of_the_key():
    """coalesce.py keeps the literal rather than importing review at module
    scope; a rename on one side would silently stop matching."""
    assert coalesce_mod._PAUSE_REASON_STATE_KEY == PAUSE_REASON_STATE_KEY


def test_the_reason_crosses_the_agent_tool_boundary():
    """The module runs as an AgentTool: only these keys reach the caller's
    state, so a reason that is not listed is a reason nobody downstream sees."""
    assert PAUSE_REASON_STATE_KEY in review_mod._REVIEW_OWNED_STATE_KEYS


def test_a_timed_out_plan_review_records_why(monkeypatch):
    from .helpers import _inventory, _plan, _task
    from CoScientist.hitl.models import HITLAction, HITLResponse

    plan = _plan(_task("EXP-1"))
    state = {"experiment_context": {
        "experiment_run_id": plan.experiment_run_id,
        "source_request": plan.source_request,
        "available_mcp_capabilities": _inventory(),
    }}
    monkeypatch.delenv("COSCIENTIST_EXPERIMENT_HITL_AUTO_APPROVE", raising=False)
    monkeypatch.setattr(get_settings().experiments, "plan_auto_approve", False)

    async def _nobody_answered(_request):
        # What FailClosedExperimentHITLHandler hands back on a timeout.
        return HITLResponse(action=HITLAction.REJECT, approved=False,
                            timed_out=True,
                            instructions="Experiment review timed out; execution remains paused.")

    agent = review_mod.ExperimentReviewSessionAgent(name="Reviewer", review_kind="plan")
    agent.hitl_handler = SimpleNamespace(handle_request=_nobody_answered)
    ctx = SimpleNamespace(session=SimpleNamespace(state=state), invocation_id="inv-1")

    import asyncio
    response = asyncio.run(agent._review_plan(ctx, plan.model_dump_json()))

    assert response.timed_out and not response.approved
    assert state[PAUSE_REASON_STATE_KEY] == "plan_review_timeout"
    # NOT the blocking flag: a second plan means a second review card, which
    # is the chance the operator missed. The dispatch budget bounds those.
    assert state.get("experiment_plan_review_paused") is False

    # And the next plan round starts from a clean slate.
    state["experiment_plan_revision_count"] = 0
    monkeypatch.setattr(get_settings().experiments, "plan_auto_approve", True)
    monkeypatch.setattr(review_mod, "approve_plan", lambda _s: None)
    monkeypatch.setattr(review_mod, "_publish_approved_plan_to_graph", lambda *_a, **_k: None)
    asyncio.run(agent._review_plan(ctx, plan.model_dump_json()))
    assert state[PAUSE_REASON_STATE_KEY] is None


def test_the_skipped_executor_says_why_it_was_skipped(monkeypatch):
    """`EXPERIMENT_EXECUTION_SKIPPED phase=awaiting_review` was the whole
    message on the run that stopped; the phase is where, not why."""
    from CoScientist.experiments.context.builder import skip_executor_without_runtime

    state = {"experiment_runtime": {"phase": "awaiting_review"},
             PAUSE_REASON_STATE_KEY: "plan_review_timeout"}
    ctx = SimpleNamespace(state=state, agent_name="ExperimentExecutorAgent")
    content = skip_executor_without_runtime(ctx)

    text = " ".join(p.text for p in content.parts)
    assert "plan_review_timeout" in text and "awaiting_review" in text, text


def test_the_coalescer_is_never_registered_without_the_suppressor():
    """The budget is now spent by the suppressor. A profile that registered
    only the coalescer would therefore never spend it, and the module could be
    re-entered without limit."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "CoScientist" / "agents"
    for yaml_file in sorted(root.glob("*.yaml")):
        text = yaml_file.read_text(encoding="utf-8")
        if "coalesce_experiment_module_calls" in text:
            assert "suppress_experiment_module_after_completed" in text, yaml_file.name

