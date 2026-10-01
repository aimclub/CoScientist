"""The orchestrator does not end its turn with plan steps left open.

A step that no work order and no experiment task covers is closed only by an
`update_task_status` call. When the orchestrator forgot it, the run reported,
then paused on the roadmap and asked the operator to accept a limited result
for work that had been done. The guard turns such a final answer back into a
`get_active_tasks` call, at most twice per invocation.

Run from the repo root:  pytest tests/unit/test_open_tasks_guard.py -q
"""
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv
from google.adk.models import LlmResponse
from google.genai import types

load_dotenv()

from CoScientist.agents.callbacks import make_open_tasks_guard  # noqa: E402


def _ctx(*statuses, invocation="inv-1", state=None):
    state = state if state is not None else {}
    state.setdefault("_master_active_tasks", [
        {"id": f"TASK-{i + 1}", "status": status, "title": f"step {i + 1}"}
        for i, status in enumerate(statuses)
    ])
    return SimpleNamespace(state=state, invocation_id=invocation,
                           agent_name="OrchestratorAgent")


def _final(text="Here is the answer."):
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _call(name="ResearchAgent"):
    return LlmResponse(content=types.Content(role="model", parts=[
        types.Part.from_function_call(name=name, args={"request": "go"})]))


def _calls(response):
    return [p.function_call.name for p in response.content.parts if p.function_call]


def test_a_final_answer_over_an_open_step_is_turned_into_a_tracker_read():
    guard = make_open_tasks_guard()
    ctx = _ctx("DONE", "IN_PROGRESS", "TODO")
    out = guard(ctx, _final())
    assert out is not None
    assert _calls(out) == ["get_active_tasks"], "a text reply would end the turn"
    note = out.content.parts[0].text
    assert "TASK-2" in note and "TASK-3" in note and "TASK-1" not in note
    assert "update_task_status" in note


@pytest.mark.parametrize("closed", ["FAILED", "CANCELLED", "SKIPPED"])
def test_a_step_closed_without_success_is_the_operators_call_not_a_reminder(closed):
    """The roadmap still pauses on it, but nothing was forgotten: the step was
    closed. Asking the orchestrator again would only cost a model call."""
    guard = make_open_tasks_guard()
    assert guard(_ctx("DONE", closed), _final()) is None
    out = guard(_ctx(closed, "TODO"), _final())
    assert out is not None
    note = out.content.parts[0].text
    assert "TASK-2" in note and "TASK-1" not in note


def test_two_reminders_then_the_answer_passes():
    guard = make_open_tasks_guard(max_rounds=2)
    ctx = _ctx("DONE", "TODO")
    assert guard(ctx, _final()) is not None
    assert guard(ctx, _final()) is not None
    assert guard(ctx, _final()) is None, "no third round: the run must not loop"


def test_a_new_invocation_starts_counting_again():
    guard = make_open_tasks_guard(max_rounds=1)
    state = {}
    assert guard(_ctx("TODO", state=state), _final()) is not None
    assert guard(_ctx("TODO", state=state), _final()) is None
    assert guard(_ctx("TODO", state=state, invocation="inv-2"), _final()) is not None


@pytest.mark.parametrize("statuses", [(), ("DONE", "DONE")])
def test_a_closed_or_absent_plan_is_left_alone(statuses):
    assert make_open_tasks_guard()(_ctx(*statuses), _final()) is None


def test_tool_calls_and_streaming_chunks_are_not_final_answers():
    guard = make_open_tasks_guard()
    assert guard(_ctx("TODO"), _call()) is None
    chunk = _final()
    chunk.partial = True
    assert guard(_ctx("TODO"), chunk) is None


def test_an_accepted_limited_outcome_is_not_nagged(monkeypatch):
    import CoScientist.execution_control as execution_control
    from CoScientist.experiments.outcome.reconciliation import roadmap_digest

    ctx = _ctx("DONE", "TODO")
    ctx.state["scientific_limited_scope_acceptance"] = {
        "accepted": True, "decision_source": "human", "run_id": "run-1",
        "roadmap_digest": roadmap_digest(ctx.state), "accepted_task_ids": ["TASK-2"],
    }
    monkeypatch.setattr(execution_control, "current_run",
                        lambda: SimpleNamespace(run_id="run-1"))
    assert make_open_tasks_guard()(ctx, _final()) is None


def test_an_experiment_awaiting_review_is_left_to_its_own_pause():
    """Only the roadmap pause is the tracker's business."""
    ctx = _ctx("TODO", state={
        "experiment_plan_review_paused": True,
        "experiment_review_pause_reason": "plan_review_timeout",
        "experiment_module_outcome": {"status": "blocked", "stage": "plan_review",
                                      "reason": "plan_review_timeout", "accepted": False},
    })
    assert make_open_tasks_guard()(ctx, _final()) is None


# ── wiring ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("profile", ["system", "experiments"])
def test_the_orchestrator_can_close_steps_and_is_guarded(profile):
    from CoScientist.assembly.schema import load_config, resolve_config_path

    cfg = load_config(resolve_config_path(profile)).agent("OrchestratorAgent")
    assert "task_tracker" in cfg.tools, "the guard asks for update_task_status"
    assert cfg.callbacks.after_model[-1] == "guard_open_tasks"


def test_a_manager_closing_a_step_is_not_recorded_as_its_executor():
    from CoScientist.tools.task_tracker import task_tracker_instance

    state = {"_master_active_tasks": [
        {"id": "TASK-1", "status": "IN_PROGRESS", "assignee": "ResearchAgent",
         "executors": ["ResearchAgent"], "last_executor": "ResearchAgent"},
    ]}
    out = task_tracker_instance.update_task_status(
        "TASK-1", "DONE", SimpleNamespace(state=state, agent_name="OrchestratorAgent"))
    assert out["result"] == "success"
    task = state["_master_active_tasks"][0]
    assert task["status"] == "DONE"
    assert task["executors"] == ["ResearchAgent"]
    assert task["last_executor"] == "ResearchAgent"
