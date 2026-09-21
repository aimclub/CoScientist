"""Which plan step an experiment task belongs to, and how far along that step is.

Both defects were read off one live graph — session_892e756a of 2026-09-21,
the richest study in the operator's history:

    XT1..XT7  -elaborates->  PS3        (all seven, on one step)
    PS3  «Кластеризация метаболитов…»            выполнен
    PS4  «Предсказание LD50 (мышь, все пути)…»   НЕ НАЧАТ
    XT3  «Предсказание LD50 (мышь, все пути)…»   выполнен

So the step that reads "not started" has its work finished under a different
step, and its own card repeats the text of a task hanging off its neighbour —
which is exactly what the operator noticed.

Cause 1: `_outer_step` resolved ONE step for the whole detailed plan (the
tracker step in progress when the plan was approved) and every task got it.
True only while one dispatch covered one step; this dispatch covered four.

Cause 2: a step's status came from the tracker alone, and the tracker is moved
by the work order, which the experiment module does not use — it records
through its own runtime. Nothing carried "my tasks are done" back to the step.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from CoScientist.agents.callbacks.tool_callbacks import (
    _status_from_tasks,
    sync_plan_to_research_graph,
)
from CoScientist.experiments.runtime.graph_bridge import (
    _plan_step_texts,
    _step_for_task,
)

#: The outer plan of that session, verbatim.
STEPS = [
    {"id": "TASK-1", "title": "Сформулировать гипотезу исследования",
     "assignee": "HypothesesAgent", "status": "DONE"},
    {"id": "TASK-2", "title": "Собрать литературные данные о метаболитах и их SMILES",
     "assignee": "TaskExecutorAgent", "status": "DONE"},
    {"id": "TASK-3", "title": "Кластеризация метаболитов по структурному сходству",
     "assignee": "TaskExecutorAgent", "status": "DONE"},
    {"id": "TASK-4", "title": "Предсказание LD50 (мышь, все пути) и домена применимости",
     "assignee": "TaskExecutorAgent", "status": "TODO"},
    {"id": "TASK-5", "title": "ADMET-эндпоинты для токсичного кластера и стоимость синтеза",
     "assignee": "TaskExecutorAgent", "status": "TODO"},
]

#: Its detailed plan, verbatim, with the step a reader assigns by eye.
TASKS = [
    ("EXP-1", "Сбор литературного перечня метаболитов и canonical SMILES", "TASK-2"),
    ("EXP-2", "Структурная кластеризация метаболитов (ECFP4 + Butina)", "TASK-3"),
    ("EXP-3", "Предсказание LD50 (мышь, все пути) по кластерам", "TASK-4"),
    ("EXP-4", "Оценка домена применимости моделей предсказания", "TASK-4"),
    ("EXP-5", "ADMET-профилирование наиболее токсичного кластера", "TASK-5"),
    ("EXP-6", "Оценка стоимости синтеза 3 перспективных соединений", "TASK-5"),
]


# ── which step ──────────────────────────────────────────────────────────────

def test_each_task_lands_on_the_step_it_carries_out():
    """Seven tasks, four steps. Before this, all seven said TASK-3."""
    steps = _plan_step_texts({"_master_active_tasks": STEPS})
    got = {task_id: _step_for_task({"title": title}, steps, "TASK-3")
           for task_id, title, _ in TASKS}
    want = {task_id: expected for task_id, _, expected in TASKS}
    assert got == want, got


def test_a_task_that_serves_no_step_keeps_the_dispatched_one():
    """The seventh task of that plan — assembling figures and tables — carries
    out no step of the outer plan. A guess would be worse than the link it
    already had."""
    steps = _plan_step_texts({"_master_active_tasks": STEPS})
    assert _step_for_task(
        {"title": "Сборка итоговых визуализаций и сравнительных таблиц"},
        steps, "TASK-3") == "TASK-3"


def test_two_steps_that_read_alike_leave_the_link_where_it_was():
    """A lead over the runner-up, not just a floor: when two steps describe the
    same work, the text cannot say which one, and inventing a winner puts a
    confident wrong line on the graph."""
    steps = _plan_step_texts({"_master_active_tasks": [
        {"id": "TASK-1", "title": "Предсказание LD50 по кластерам метаболитов"},
        {"id": "TASK-2", "title": "Предсказание LD50 по кластерам метаболитов"},
    ]})
    assert _step_for_task({"title": "Предсказание LD50 по кластерам метаболитов"},
                          steps, "TASK-9") == "TASK-9"


def test_the_question_counts_when_the_title_is_terse():
    steps = _plan_step_texts({"_master_active_tasks": STEPS})
    task = {"title": "Расчёт",
            "question": "Каковы предсказанные LD50 (мышь, все пути) по кластерам?"}
    assert _step_for_task(task, steps, "TASK-3") == "TASK-4"


def test_no_outer_plan_means_no_invented_step():
    assert _step_for_task({"title": "что угодно"}, [], "") == ""


# ── how far along ───────────────────────────────────────────────────────────

class _Graph:
    """Just enough store to answer `full()`."""

    def __init__(self, nodes, edges):
        self._full = {"nodes": nodes, "edges": edges}

    def full(self):
        return self._full

    def root_id(self):
        return "Q1"


def _graph_of(*task_statuses: tuple[str, str, str]):
    """(task id, status, step id) triples into a graph of steps and tasks."""
    nodes = [{"id": "PS4", "type": "PlanStep", "status": "todo",
              "attrs": {"plan_task_id": "TASK-4"}},
             {"id": "PS5", "type": "PlanStep", "status": "todo",
              "attrs": {"plan_task_id": "TASK-5"}}]
    edges = []
    for task_id, status, step in task_statuses:
        nodes.append({"id": task_id, "type": "ExperimentTask", "status": status})
        edges.append({"type": "elaborates", "from": task_id, "to": step})
    return _Graph(nodes, edges)


def test_a_step_whose_every_task_is_done_is_done():
    derived = _status_from_tasks(_graph_of(("XT3", "done", "PS4"),
                                          ("XT4", "done", "PS4")))
    assert derived == {"PS4": "done"}


def test_a_step_with_work_under_way_is_under_way():
    derived = _status_from_tasks(_graph_of(("XT3", "done", "PS4"),
                                           ("XT4", "running", "PS4")))
    assert derived == {"PS4": "in_progress"}


def test_a_plan_that_has_only_been_written_starts_nothing():
    """`planned` is the plan, not the work: a step with nothing but planned
    tasks under it has not begun."""
    assert _status_from_tasks(_graph_of(("XT3", "planned", "PS4"),
                                        ("XT4", "planned", "PS4"))) == {}


def test_a_failed_task_still_means_the_step_was_started():
    derived = _status_from_tasks(_graph_of(("XT3", "failed", "PS4")))
    assert derived == {"PS4": "in_progress"}


def test_a_skipped_optional_task_does_not_hold_its_step_back():
    derived = _status_from_tasks(_graph_of(("XT3", "done", "PS4"),
                                           ("XT4", "skipped", "PS4")))
    assert derived == {"PS4": "done"}


def test_the_step_of_a_finished_task_stops_saying_not_started(monkeypatch):
    """The defect end to end: the tracker still says TODO, the graph says the
    tasks are done, and the plan column has to show the work."""
    graph = _graph_of(("XT3", "done", "PS4"), ("XT4", "done", "PS4"),
                      ("XT5", "running", "PS5"))
    updates = []
    graph.commit = lambda **kw: updates.append(kw) or SimpleNamespace(
        ok=True, errors=[], committed={"nodes": []})

    state = {"_master_active_tasks": [dict(s) for s in STEPS],
             # the mirror has already created these two steps
             "_vm_by_task": {"gen": "", "ids": {}}}
    # Pretend the steps were mirrored earlier: key them the way the mirror does.
    from CoScientist.agents.callbacks.tool_callbacks import (
        _study_generation, _task_key, _VM_BY_TASK_KEY,
    )
    state[_VM_BY_TASK_KEY] = {
        "gen": _study_generation(graph),
        "ids": {_task_key(STEPS[3]): "PS4", _task_key(STEPS[4]): "PS5"},
    }

    sync_plan_to_research_graph(state["_master_active_tasks"], graph, state)

    moved = {u["id"]: (u["status"], u["reason"])
             for kw in updates for u in (kw.get("status_updates") or [])}
    assert moved.get("PS4", ("",))[0] == "done", moved
    assert moved.get("PS5", ("",))[0] == "in_progress", moved
    assert "experiment tasks" in moved["PS4"][1]

    # And the roadmap the operator reads agrees with the graph.
    tracker = {t["id"]: t["status"] for t in state["_master_active_tasks"]}
    assert tracker["TASK-4"] == "DONE" and tracker["TASK-5"] == "IN_PROGRESS", tracker


def test_a_blocked_step_is_not_talked_out_of_it(monkeypatch):
    """`blocked` is a verdict on the step — a rejected report — not a measure
    of how much of it ran, so finished tasks must not clear it."""
    graph = _graph_of(("XT3", "done", "PS4"))
    updates = []
    graph.commit = lambda **kw: updates.append(kw) or SimpleNamespace(
        ok=True, errors=[], committed={"nodes": []})

    from CoScientist.agents.callbacks.tool_callbacks import (
        _study_generation, _task_key, _VM_BY_TASK_KEY,
    )
    steps = [dict(s) for s in STEPS]
    steps[3]["status"] = "FAILED"          # the tracker's word for blocked
    state = {"_master_active_tasks": steps,
             _VM_BY_TASK_KEY: {"gen": _study_generation(graph),
                               "ids": {_task_key(steps[3]): "PS4"}}}

    sync_plan_to_research_graph(steps, graph, state)

    moved = {u["id"]: u["status"]
             for kw in updates for u in (kw.get("status_updates") or [])}
    assert moved.get("PS4", "blocked") == "blocked", moved
    assert state["_master_active_tasks"][3]["status"] == "FAILED"
