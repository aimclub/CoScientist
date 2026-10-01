"""The planner stage runs once per session; the orchestrator re-plans on demand.

In `planner` start mode every invocation walked PlanningPipelineAgent from the
top, so a follow-up message or "continue the outstanding tasks" planned the
study again over the work already done. Now the stage runs once; afterwards the
orchestrator starts the turn and calls the planner itself when the plan has to
change — and that re-plan keeps the steps already DONE.

Run from the repo root:  pytest tests/unit/test_planner_stage.py -q
"""
import asyncio
from types import SimpleNamespace
from typing import AsyncGenerator

from dotenv import load_dotenv
from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

from CoScientist.agents.planner_stage_plugin import (  # noqa: E402
    PLANNER_STAGE_DONE_STATE_KEY,
    PlannerStagePlugin,
)


def _say(agent, ctx, text):
    return Event(invocation_id=ctx.invocation_id, author=agent.name, branch=ctx.branch,
                 content=types.Content(role="model", parts=[types.Part(text=text)]))


class _Recorder(BaseAgent):
    runs: list

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        self.runs.append(ctx.invocation_id)
        yield _say(self, ctx, f"{self.name} ran")


def test_a_follow_up_starts_at_the_orchestrator_with_a_real_runner():
    async def scenario():
        planner = _Recorder(name="PlannerAgent", runs=[])
        orchestrator = _Recorder(name="OrchestratorAgent", runs=[])
        pipeline = SequentialAgent(name="PlanningPipelineAgent",
                                   sub_agents=[planner, orchestrator])
        service = InMemorySessionService()
        runner = Runner(app_name="t", agent=pipeline, session_service=service,
                        plugins=[PlannerStagePlugin()])
        session = await service.create_session(app_name="t", user_id="u")

        async def ask(text):
            message = types.Content(role="user", parts=[types.Part(text=text)])
            return [e async for e in runner.run_async(
                user_id="u", session_id=session.id, new_message=message)]

        await ask("first request")
        events = await ask("follow-up")
        assert len(planner.runs) == 1, "the planner stage ran again on a follow-up"
        assert len(orchestrator.runs) == 2, "a bypassed stage must not stop the pipeline"
        assert any("Planner stage skipped" in (p.text or "")
                   for e in events if e.content for p in e.content.parts)
        stored = await service.get_session(app_name="t", user_id="u", session_id=session.id)
        assert stored.state[PLANNER_STAGE_DONE_STATE_KEY] is True
        await runner.close()

    asyncio.run(scenario())


# ── the decision itself ─────────────────────────────────────────────────────

def _enter(plugin, name, state, invocation, sub_agents=()):
    agent = SimpleNamespace(name=name, sub_agents=list(sub_agents))
    ctx = SimpleNamespace(state=state, invocation_id=invocation)
    return asyncio.run(plugin.before_agent_callback(agent=agent, callback_context=ctx))


def _stage(plugin, state, invocation):
    planner = SimpleNamespace(name="PlannerAgent")
    _enter(plugin, "PlanningPipelineAgent", state, invocation, [planner])
    return _enter(plugin, "PlannerAgent", state, invocation)


def test_the_first_stage_runs_and_later_ones_are_bypassed():
    plugin, state = PlannerStagePlugin(), {}
    assert _stage(plugin, state, "inv-1") is None
    assert _stage(plugin, state, "inv-2") is not None
    assert _stage(plugin, state, "inv-3") is not None


def test_an_on_demand_call_from_the_orchestrator_is_never_bypassed():
    """The AgentTool runs the same planner in a child runner: same state copy,
    a different invocation."""
    plugin, state = PlannerStagePlugin(), {}
    _stage(plugin, state, "inv-1")
    assert _enter(plugin, "PlannerAgent", dict(state), "child-inv") is None


def test_orchestrator_mode_has_no_planner_stage_to_bypass():
    """No sequential parent records an invocation, so every call is on demand."""
    plugin = PlannerStagePlugin()
    state = {PLANNER_STAGE_DONE_STATE_KEY: True}
    assert _enter(plugin, "PlannerAgent", state, "inv-1") is None


def test_a_session_planned_before_the_marker_existed_counts_as_planned():
    plugin = PlannerStagePlugin()
    state = {"_master_active_tasks": [{"id": "TASK-1", "status": "DONE"}]}
    assert _stage(plugin, state, "inv-9") is not None


# ── re-planning from the current state ──────────────────────────────────────

def _plan(state, *titles):
    from CoScientist.tools.task_tracker import task_tracker_instance

    return task_tracker_instance.create_plan(
        [{"title": t, "description": t, "assignee": "ResearchAgent"} for t in titles],
        SimpleNamespace(state=state, agent_name="PlannerAgent"),
    )


def test_a_re_plan_keeps_finished_steps_and_numbers_new_ones_after_them():
    state = {}
    _plan(state, "a", "b", "c")
    state["_master_active_tasks"][0]["status"] = "DONE"
    state["_master_active_tasks"][1]["status"] = "FAILED"
    out = _plan(state, "b again", "d")
    rows = state["_master_active_tasks"]
    assert [(t["id"], t["title"], t["status"]) for t in rows] == [
        ("TASK-1", "a", "DONE"),
        ("TASK-2", "b again", "TODO"),
        ("TASK-3", "d", "TODO"),
    ]
    assert "TASK-1" in out["message"]
    assert [t["id"] for t in out["plan"]] == ["TASK-2", "TASK-3"]


def test_new_ids_never_collide_with_a_kept_one():
    state = {"_master_active_tasks": [
        {"id": "TASK-1", "status": "FAILED", "title": "x"},
        {"id": "TASK-4", "status": "DONE", "title": "y"},
    ]}
    _plan(state, "z")
    assert [t["id"] for t in state["_master_active_tasks"]] == ["TASK-4", "TASK-5"]


def test_a_first_plan_is_numbered_from_one():
    state = {}
    _plan(state, "a", "b")
    assert [t["id"] for t in state["_master_active_tasks"]] == ["TASK-1", "TASK-2"]


def test_the_planner_sees_the_roadmap_it_re_plans():
    from CoScientist.agents.callbacks import inject_current_plan

    state = {}
    inject_current_plan(SimpleNamespace(state=state))
    assert state["current_plan"] == "", "a first plan gets no section at all"

    state["_master_active_tasks"] = [
        {"id": "TASK-1", "status": "DONE", "title": "collect", "assignee": "ResearchAgent"},
        {"id": "TASK-2", "status": "FAILED", "title": "fit", "assignee": "CoderAgent",
         "notes": "no GPU"},
    ]
    inject_current_plan(SimpleNamespace(state=state))
    text = state["current_plan"]
    assert "TASK-1 [DONE] collect" in text and "TASK-2 [FAILED] fit" in text
    assert "no GPU" in text
    assert "do not register them again" in text


# ── wiring ──────────────────────────────────────────────────────────────────

def test_the_planner_prompt_and_callbacks_carry_the_current_plan():
    from CoScientist.assembly import load_config
    from CoScientist.assembly.prompting import PromptContext
    from CoScientist.assembly.registry import REGISTRY

    cfg = load_config()
    planner = cfg.agent("PlannerAgent")
    assert "inject_current_plan" in planner.callbacks.before_agent
    text = REGISTRY.prompt("planner")(PromptContext(config=planner, system=cfg))
    assert "{current_plan?}" in text
    assert "re-plan from the current" in planner.routing
    assert "delegate to the agents yourself" in planner.routing
