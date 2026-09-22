"""Deterministic bridge: approved ExperimentPlan / TaskResults → research graph.

After a plan is approved each task becomes a ``VerificationMethod`` node linked
to the hypothesis it tests (``Hypothesis —tested_by→ VM``) and to each tool the
task names (``VM —uses→ Tool``), carrying the design the human approved rather
than only a route. Hypotheses with no covering task are postponed
(``no_method_this_stage``), not dropped and not turned into extra EXP tasks.
The plan itself, and the round of review it went through, is recorded in the
execution graph by ``execution_bridge``. After ``record_result`` the outcome
becomes ``Evidence`` (+``GeneratedData`` for file artifacts) linked via
``VM —produces→ Evidence`` and ``Evidence —relates_to→ Hypothesis`` so the
background validator can judge the active claim. Writes go through the same
privileged code-path as ``init_research`` (``enforce_permissions=False``):
structural validation stays, per-agent ACLs are not extended, and no LLM agent
gets a new tool.

Every public function here is best-effort by contract: any failure is logged
as a warning and swallowed — a graph problem must never break plan approval or
result recording.
"""
from __future__ import annotations

import logging
import re
from typing import Any, MutableMapping

from CoScientist.experiments.runtime.shared import audit

logger = logging.getLogger(__name__)

_SOURCE = "ExperimentModule"
_PLAN_SOURCE = "experiment-plan-mirror"
#: The agents the outer planner gives an experimental step to. The detailed plan
#: hangs off whichever of the tracker's steps is theirs.
_EXECUTOR_ASSIGNEES = ("ExperimentModuleAgent", "TaskExecutorAgent")
_VM_IDS_KEY = "experiment_graph_vm_ids"  # state-level: survives replans
_XT_IDS_KEY = "experiment_graph_task_ids"  # EXP-n -> XT id, survives replans
_TOOL_IDS_KEY = "experiment_graph_tool_ids"  # tool key -> Tool node id
_RUNTIME_KEY = "experiment_runtime"
_MAX_GENERATED_DATA = 5
#: A task naming forty tools would bury the plan's own shape under its
#: inventory. The VM keeps the full list in ``mcp_servers`` either way.
_MAX_TOOLS_PER_TASK = 8
_TEXT_LIMIT = 800
_HID_RE = re.compile(r"H\d+", re.IGNORECASE)


def _enabled() -> bool:
    try:
        from CoScientist.config import get_settings

        return bool(get_settings().research_graph.enabled)
    except Exception:  # noqa: BLE001
        return False


def _graph_nodes(store: Any) -> dict[str, dict[str, Any]]:
    """id → {type, status} for every node currently in the graph."""
    try:
        return {
            str(n.get("id")): {"type": n.get("type"), "status": n.get("status")}
            for n in (store.overview().get("nodes") or [])
            if isinstance(n, dict) and n.get("id")
        }
    except Exception:  # noqa: BLE001
        return {}


def _vm_ids(state: MutableMapping[str, Any]) -> dict[str, str]:
    raw = state.get(_VM_IDS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def _xt_ids(state: MutableMapping[str, Any]) -> dict[str, str]:
    raw = state.get(_XT_IDS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def _clean(value: Any, limit: int = _TEXT_LIMIT) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _task_hypothesis_ids(design: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for raw in [design.get("hypothesis_ref"), *(design.get("also_tests") or [])]:
        hid = str(raw or "").strip().upper()
        if hid and _HID_RE.fullmatch(hid) and hid not in ids:
            ids.append(hid)
    return ids


def _plan_tasks(state: MutableMapping[str, Any]) -> list[dict[str, Any]]:
    runtime = state.get(_RUNTIME_KEY) or {}
    plan = runtime.get("plan") or {}
    return [t for t in (plan.get("tasks") or []) if isinstance(t, dict)]


def _task_by_id(state: MutableMapping[str, Any], task_id: str) -> dict[str, Any] | None:
    for task in _plan_tasks(state):
        if str(task.get("id") or "") == str(task_id):
            return task
    return None


def _covered_hypothesis_ids(tasks: list[dict[str, Any]]) -> set[str]:
    covered: set[str] = set()
    for task in tasks:
        covered.update(_task_hypothesis_ids(task.get("design") or {}))
    return covered


def _sync_uncovered_hypotheses(
    store: Any, graph_nodes: dict[str, dict[str, Any]], covered: set[str],
) -> tuple[int, int]:
    """Postpone formulated Hs with no task; revive postponed Hs a task now covers.

    Does not touch confirmed/refuted/under_verification. Alternatives that
    HypothesesAgent parked as postponed stay postponed until a task lists them.
    """
    updates: list[dict[str, str]] = []
    for nid, meta in graph_nodes.items():
        if meta.get("type") != "Hypothesis":
            continue
        status = str(meta.get("status") or "")
        if nid in covered:
            if status == "postponed":
                updates.append({
                    "id": nid,
                    "status": "formulated",
                    "reason": "plan task covers this hypothesis",
                })
        elif status == "formulated":
            updates.append({
                "id": nid,
                "status": "postponed",
                "reason": "no_method_this_stage: no plan task tests this hypothesis",
            })
    if not updates:
        return 0, 0
    store.commit(source=_SOURCE, status_updates=updates, enforce_permissions=False)
    postponed = sum(1 for row in updates if row["status"] == "postponed")
    revived = sum(1 for row in updates if row["status"] == "formulated")
    return postponed, revived


def _schedule_hypothesis_judgments(store: Any) -> int:
    """Fire-and-forget judge for Hs that now have evidence. Never raises."""
    try:
        from CoScientist.graph.research.validator import background_validator_plugin

        return int(background_validator_plugin.schedule_for_graph(store) or 0)
    except Exception:  # noqa: BLE001
        return 0


def _vm_attrs(task: dict[str, Any], plan_id: str) -> dict[str, Any]:
    design = task.get("design") or {}
    dataset = design.get("dataset") or {}
    inputs = _clean(dataset.get("name") or dataset.get("source_ref") or "")
    outputs = ", ".join(
        _clean(a.get("name"), 120)
        for a in (task.get("expected_artifacts") or [])
        if isinstance(a, dict) and a.get("name")
    )
    metrics = ", ".join(
        _clean(m.get("name"), 80)
        for m in (design.get("metrics") or [])
        if isinstance(m, dict) and m.get("name")
    )
    mcp_servers = []
    for srv in task.get("mcp_servers") or []:
        if isinstance(srv, dict):
            tools_list = []
            for t in srv.get("tools") or []:
                if isinstance(t, dict):
                    tools_list.append(t.get("name") or "")
                elif isinstance(t, str):
                    tools_list.append(t)
            mcp_servers.append({
                "name": srv.get("name") or srv.get("server_id") or "",
                "url": str(srv.get("url") or ""),
                "tools": [t for t in tools_list if t],
            })

    # The rest of the design, so the graph carries the method a human approved
    # rather than a name and a route. Anything the plan left unset stays out:
    # an attribute whose value is "" reads as "measured and empty".
    criteria = "; ".join(
        _clean(
            f"{c.get('criterion_id')}: {c.get('description')}"
            + (f" [{c['metric']} {c['operator']} {c['target']}]"
               if c.get("metric") and c.get("operator") and c.get("target") is not None
               else ""),
            240,
        )
        for c in (task.get("success_criteria") or [])
        if isinstance(c, dict) and c.get("description")
    )
    baselines = ", ".join(
        _clean(f"{b.get('name')} ({b.get('kind')})", 120)
        for b in (design.get("baselines") or [])
        if isinstance(b, dict) and b.get("name")
    )
    analysis = ", ".join(
        _clean(f"{a.get('name')} [{a.get('role')}]", 120)
        for a in (design.get("analysis_artifacts") or [])
        if isinstance(a, dict) and a.get("name")
    )
    duration = task.get("est_duration_min")
    attrs = {
        "method_type": "computational",
        "inputs": inputs,
        "outputs": _clean(outputs),
        "metrics": _clean(metrics),
        "experiment_question": _clean(design.get("experiment_question")),
        "task_id": str(task.get("id") or ""),
        "plan_id": plan_id,
        "route": str(task.get("route") or ""),
        "mcp_servers": mcp_servers,
    }
    extra = {
        "name": _clean(task.get("name"), 200),
        "cost": f"≈{duration} min" if isinstance(duration, int) and duration > 0 else "",
        "limitations": "; ".join(_clean(w, 200) for w in (task.get("warnings") or []) if w),
        "success_criteria": _clean(criteria, 900),
        "baselines": _clean(baselines, 400),
        "analysis_artifacts": _clean(analysis, 400),
        "dataset_ref": _clean(dataset.get("ref"), 240),
        "operation_ref": _clean(design.get("operation_ref"), 80),
        "depends_on": ", ".join(str(d) for d in (task.get("depends_on") or []) if d),
        "repo_url": _clean(task.get("repo_url"), 240),
    }
    attrs.update({k: v for k, v in extra.items() if v})
    if task.get("optional"):
        attrs["optional"] = True
    return attrs


#: Runtime status -> the five a reader needs. `blocked` is a wait on an
#: upstream task, so it has not started: "planned", not "running".
_TASK_STATUS = {
    "pending": "planned", "ready": "planned", "blocked": "planned",
    "running": "running", "retry_pending": "running",
    "fallback_pending": "running",
    "done": "done", "done_with_warnings": "done",
    "failed": "failed", "skipped": "skipped",
}


def _task_status(state: MutableMapping[str, Any], task_id: str) -> str:
    """The runtime's status for this task, mapped onto the graph's five.

    Read from the RUNTIME, not from the plan: `ExperimentPlan` forbids a status
    field on a task — the plan is what was intended, and how far it got is a
    separate record. Reading the plan therefore reported every task as
    "planned" forever, including the ones that had already run.
    """
    runtime = state.get(_RUNTIME_KEY) or {}
    record = (runtime.get("tasks") or {}).get(task_id) or {}
    return _TASK_STATUS.get(str(record.get("status") or "").strip().lower(),
                            "planned")


def _task_attrs(task: dict[str, Any], plan: dict[str, Any],
                step_task_id: str) -> dict[str, Any]:
    """The task as the plan wrote it. Rendered the same way `_vm_attrs` renders
    the method's copy, so the two cards read alike where they overlap.

    Anything the plan left unset stays out, for the reason `_vm_attrs` gives:
    an attribute whose value is "" reads as measured and empty.
    """
    design = task.get("design") or {}
    dataset = design.get("dataset") or {}
    duration = task.get("est_duration_min")
    tools: list[str] = []
    for srv in task.get("mcp_servers") or []:
        if not isinstance(srv, dict):
            continue
        server = str(srv.get("name") or srv.get("server_id") or "").strip()
        for entry in srv.get("tools") or []:
            name = (entry.get("name") if isinstance(entry, dict)
                    else entry) or ""
            name = str(name).strip()
            if name:
                tools.append(f"{server}:{name}" if server else name)
    attrs = {
        "title": _clean(task.get("name"), 200),
        "description": _clean(task.get("description")),
        "rationale": _clean(task.get("rationale")),
        "experiment_task_id": str(task.get("id") or ""),
        "plan_task_id": step_task_id,
        "plan_id": _clean(plan.get("plan_id"), 80),
        "plan_revision": str(plan.get("revision") or ""),
        "experiment_run_id": _clean(plan.get("experiment_run_id"), 80),
        "route": str(task.get("route") or ""),
        "question": _clean(design.get("experiment_question")),
        "hypothesis_refs": ", ".join(_task_hypothesis_ids(design)),
        "operation_ref": _clean(design.get("operation_ref"), 80),
        "dataset": _clean(dataset.get("name") or dataset.get("source_ref"), 240),
        "baselines": ", ".join(
            _clean(f"{b.get('name')} ({b.get('kind')})", 120)
            for b in (design.get("baselines") or [])
            if isinstance(b, dict) and b.get("name")),
        "metrics": ", ".join(
            _clean(f"{m.get('name')} ({m.get('direction')})"
                   if m.get("direction") else m.get("name"), 80)
            for m in (design.get("metrics") or [])
            if isinstance(m, dict) and m.get("name")),
        "success_criteria": "; ".join(
            _clean(f"{c.get('criterion_id')}: {c.get('description')}"
                   + (f" [{c['metric']} {c['operator']} {c['target']}]"
                      if c.get("metric") and c.get("operator")
                      and c.get("target") is not None else ""), 240)
            for c in (task.get("success_criteria") or [])
            if isinstance(c, dict) and c.get("description")),
        "expected_artifacts": ", ".join(
            _clean(f"{a.get('name')} [{a.get('role')}]"
                   if a.get("role") else a.get("name"), 120)
            for a in (task.get("expected_artifacts") or [])
            if isinstance(a, dict) and a.get("name")),
        "tools": ", ".join(tools),
        "input_data": ", ".join(
            _clean(i.get("location") or i.get("source_artifact_id"), 160)
            for i in (task.get("input_data") or [])
            if isinstance(i, dict)),
        "depends_on": ", ".join(str(d) for d in (task.get("depends_on") or []) if d),
        "cost": f"≈{duration} min" if isinstance(duration, int) and duration > 0 else "",
        "limitations": "; ".join(
            _clean(w, 200) for w in (task.get("warnings") or []) if w),
    }
    attrs = {k: v for k, v in attrs.items() if v}
    if task.get("optional"):
        attrs["optional"] = True
    return attrs


#: Word-prefix length. The two plans are written by different agents in
#: Russian, so the same work arrives as «метаболитов» and «метаболиты»;
#: comparing whole words matches almost nothing. Five characters is not
#: morphology, but it tells «кластеризация» from «предсказание».
_STEM = 5
#: Shorter words are prepositions and noise at this stem length.
_MIN_WORD = 4
#: Enough shared vocabulary to call it the same work, and enough of a lead over
#: the runner-up to be sure which step it is. Both read off the live data:
#: true matches scored 0.40..0.80, wrong ones 0.00..0.25.
_MATCH_FLOOR = 0.34
_MATCH_LEAD = 0.10
_WORD_RE = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)
_STOP_WORDS = frozenset({
    "для", "или", "как", "что", "все", "его", "это", "при", "уже", "без",
    "the", "and", "with", "from", "this", "that", "into",
})


def _words(text: Any) -> set[str]:
    """Content words of a title, stemmed to a prefix."""
    out: set[str] = set()
    for word in _WORD_RE.findall(str(text or "").lower()):
        if len(word) >= _MIN_WORD and word not in _STOP_WORDS:
            out.add(word[:_STEM])
    return out


def _overlap(left: set[str], right: set[str]) -> float:
    """Share of the smaller vocabulary the two have in common.

    Not Jaccard: a step's title is often shorter than its task's, and a long
    task should not be penalised for saying more than the step it serves.
    """
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


#: At least this many shared words before the text is allowed to decide. One
#: word is an accident: «Предсказание LD50 (мышь)» shared exactly «метабол»
#: with «Собрать литературные данные о метаболитах» and nothing with the step
#: it belonged to, which scored a confident 1.00 on the wrong step.
_MIN_SHARED = 2


def _task_match_text(task: dict[str, Any]) -> str:
    """The task's own words, from the fields the PLAN uses.

    `_task_attrs` writes `title` from `name` and `question` from
    `design.experiment_question`; reading the graph's names off a plan task is
    what made this matcher a no-op. Both readers now start here.
    """
    design = task.get("design") or {}
    return f"{task.get('name') or ''} {design.get('experiment_question') or ''}"


def _plan_step_texts(state: MutableMapping[str, Any]) -> list[tuple[str, set[str]]]:
    """(TASK-n, vocabulary) for every step an experiment task could carry out.

    Only steps handed to an executor are candidates. A step assigned to the
    hypothesis generator, the literature agent or the reporter asks for
    something an ExperimentTask does not do, and its description is the worst
    possible distractor: the hypothesis step spells out the pipeline the tasks
    implement, so it shares vocabulary with every one of them.
    """
    out: list[tuple[str, set[str]]] = []
    for step in (state.get("_master_active_tasks") or []):
        if not isinstance(step, dict):
            continue
        task_id = str(step.get("id") or "").strip()
        if not task_id:
            continue
        if str(step.get("assignee") or "") not in _EXECUTOR_ASSIGNEES:
            continue
        out.append((task_id,
                    _words(f"{step.get('title') or ''} "
                           f"{step.get('description') or ''}")))
    return out


def _step_for_task(task: dict[str, Any],
                   steps: list[tuple[str, set[str]]],
                   fallback: str) -> tuple[str, float, float]:
    """Which step of the OUTER plan this experiment task carries out.

    Returns (step id, best score, runner-up score) — the two numbers go into
    the audit line, because a wrong line on the graph is only fixable if it can
    be read back to the pair of titles and the margin that produced it.

    ``fallback`` — the dispatched step — is used when nothing matches well
    enough: a weak guess is left where it used to go rather than moved
    somewhere invented.
    """
    if not steps:
        return fallback, 0.0, 0.0
    mine = _words(_task_match_text(task))
    scored = []
    for task_id, vocab in steps:
        shared = mine & vocab
        scored.append((_overlap(mine, vocab) if len(shared) >= _MIN_SHARED else 0.0,
                       task_id))
    scored.sort(reverse=True)
    best, best_id = scored[0]
    runner = scored[1][0] if len(scored) > 1 else 0.0
    if best >= _MATCH_FLOOR and best - runner >= _MATCH_LEAD:
        return best_id, best, runner
    return fallback, best, runner


def _outer_step(store: Any, state: MutableMapping[str, Any]) -> tuple[str, str]:
    """The outer plan's step the detailed plan elaborates: (PlanStep id, TASK-n).

    Nothing in the code carries an EXP-n -> TASK-n mapping — the experiment plan
    renumbers its own tasks — so it is resolved here, through the one thing both
    plans agree on: the tracker step the orchestrator handed to the executor.
    Returns ("", "") when there is no outer plan or no step of its own, and the
    tasks are then written without the link rather than hung off an invented
    step.
    """
    steps = [t for t in (state.get("_master_active_tasks") or [])
             if isinstance(t, dict)]
    mine = [t for t in steps
            if str(t.get("assignee") or "") in _EXECUTOR_ASSIGNEES]
    if not mine:
        return "", ""
    running = [t for t in mine
               if str(t.get("status") or "").strip().lower() == "in_progress"]
    step = (running or mine)[0]
    task_id = str(step.get("id") or "").strip()
    if not task_id:
        return "", ""
    for node in (_graph_full(store).get("nodes") or []):
        if not isinstance(node, dict) or node.get("type") != "PlanStep":
            continue
        if str((node.get("attrs") or {}).get("plan_task_id") or "") == task_id:
            return str(node.get("id") or ""), task_id
    return "", task_id


def _graph_full(store: Any) -> dict[str, Any]:
    try:
        return store.full() or {}
    except Exception:  # noqa: BLE001
        return {}


def publish_plan_detail_to_graph(store: Any,
                                 state: MutableMapping[str, Any]) -> None:
    """Mirror the approved experiment plan, one ExperimentTask per task.

    Best-effort by this module's contract: any failure is logged and swallowed,
    because a graph problem must never break plan approval.
    """
    if not _enabled():
        return
    try:
        tasks = _plan_tasks(state)
        if not tasks:
            return
        plan = (state.get(_RUNTIME_KEY) or {}).get("plan") or {}
        step_id, step_task_id = _outer_step(store, state)
        # PlanStep node per tracker id, so a task can be linked to the step it
        # carries out rather than to the one that was dispatched.
        step_nodes = {
            str((node.get("attrs") or {}).get("plan_task_id") or ""): str(node.get("id") or "")
            for node in (_graph_full(store).get("nodes") or [])
            if isinstance(node, dict) and node.get("type") == "PlanStep"
        }
        step_texts = _plan_step_texts(state)
        known = _xt_ids(state)
        graph_nodes = _graph_nodes(store)
        matched: list[str] = []

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        updates: list[dict[str, Any]] = []
        ref_to_task: dict[str, str] = {}
        for index, task in enumerate(tasks):
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            own_task_id, best, runner = _step_for_task(task, step_texts,
                                                       step_task_id)
            own_step_id = step_nodes.get(own_task_id, "") or step_id
            matched.append(f"{task_id}->{own_task_id or 'none'}"
                           f"({best:.2f}/{runner:.2f})")
            attrs = _task_attrs(task, plan, own_task_id)
            status = _task_status(state, task_id)
            existing = known.get(task_id)
            if existing and existing in graph_nodes:
                # id-only draft = attrs merge on the node already there, which
                # is what makes a re-approval after a replan idempotent.
                nodes.append({"id": existing, "attrs": attrs})
                if graph_nodes[existing].get("status") != status:
                    updates.append({"id": existing, "status": status,
                                    "reason": f"experiment plan revision "
                                              f"{plan.get('revision') or '?'}"})
                continue
            ref = f"xt{index}"
            ref_to_task[ref] = task_id
            nodes.append({"type": "ExperimentTask", "ref": ref,
                          "status": status, "attrs": attrs})
            if own_step_id:
                edges.append({"type": "elaborates", "from": f"#{ref}",
                              "to": own_step_id})
        if not nodes and not updates:
            return

        result = store.commit(source=_PLAN_SOURCE, nodes=nodes, edges=edges,
                              status_updates=updates, partial_edges=True)
        ok = bool(getattr(result, "ok", None) if not isinstance(result, dict)
                  else result.get("ok"))
        if not ok:
            errors = (result.get("errors") if isinstance(result, dict)
                      else getattr(result, "errors", None))
            audit(logger,
                  f"EXPERIMENT_GRAPH_TASKS_PUBLISH_FAILED errors={errors}",
                  level=logging.WARNING)
            return
        committed = (result.get("committed") if isinstance(result, dict)
                     else getattr(result, "committed", None)) or {}
        for echo in committed.get("nodes") or []:
            ref = str(echo.get("ref") or "")
            if echo.get("id") and (task_id := ref_to_task.get(ref)):
                known[task_id] = str(echo["id"])
        state[_XT_IDS_KEY] = known
        # Every decision, so a wrong line on the graph can be read back to the
        # pair of titles that produced it.
        if matched:
            audit(logger, "EXPERIMENT_GRAPH_TASK_STEPS "
                          f"dispatched={step_task_id or 'none'} "
                          + " ".join(matched))
        if not step_id:
            # Said out loud: the cards are there and the link is not, which is
            # a wiring fact about the run, not a fault of the plan.
            audit(logger, "EXPERIMENT_GRAPH_TASKS_UNLINKED "
                          f"count={len(known)} step={step_task_id or 'none'}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("publishing the experiment plan detail failed: %s", exc)


def _planned_tools(task: dict[str, Any]) -> list[dict[str, str]]:
    """The concrete tools this task's method will run, as Tool node drafts.

    A plan that names its tools only inside a VM attribute leaves the graph
    unable to answer "what does this method actually run?" — the very question
    the feasibility layer exists for. So each named tool becomes a Tool node the
    VM ``uses``. A build task has no tool yet: the repo it will turn into one is
    recorded as ``being_created`` instead, which is what the status is for.
    """
    route = str(task.get("route") or "")
    if route == "alembic_build":
        repo = _clean(task.get("repo_url"), 240)
        if not repo:
            return []
        return [{
            "key": f"repo:{repo}",
            "name": _clean(repo.rstrip("/").rsplit("/", 1)[-1] or repo, 120),
            "location": repo,
            "status": "being_created",
            "requirements": "built into an MCP server by the Alembic pipeline",
        }]

    rows: list[dict[str, str]] = []
    for server in task.get("mcp_servers") or []:
        if not isinstance(server, dict):
            continue
        server_name = _clean(server.get("name") or server.get("server_id"), 120)
        url = _clean(server.get("url"), 240)
        tools = [t for t in (server.get("tools") or []) if isinstance(t, (dict, str))]
        required = [
            t for t in tools
            if not isinstance(t, dict) or t.get("required_for_task", True)
        ]
        for tool in (required or tools):
            name = _clean(tool.get("name") if isinstance(tool, dict) else tool, 120)
            if not name:
                continue
            rows.append({
                "key": f"{server_name}:{name}",
                "name": name,
                "location": url or server_name,
                "status": "available",
                "requirements": (
                    _clean(tool.get("description"), 240) if isinstance(tool, dict) else ""
                ),
                "server": server_name,
            })
            if len(rows) >= _MAX_TOOLS_PER_TASK:
                return rows
    return rows


def _tool_ids(state: MutableMapping[str, Any]) -> dict[str, str]:
    raw = state.get(_TOOL_IDS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def publish_plan_to_graph(store: Any, state: MutableMapping[str, Any]) -> None:
    """Write the approved plan into the research graph (best-effort, idempotent).

    Each plan task → one ``VerificationMethod`` node plus ``tested_by`` edges
    from every hypothesis the task's design covers (only for hypothesis ids that
    actually exist as graph nodes), and one ``Tool`` node per tool the task
    names, joined by ``VM —uses→ Tool``. Formulated hypotheses with no covering
    task are postponed; a postponed hypothesis a task now lists is revived to
    formulated. Re-approval / replan updates the existing VM (attrs merge)
    instead of creating a duplicate; VMs whose tasks disappeared from the plan
    are marked ``failed`` (reason=replanned) when still non-terminal.
    """
    try:
        if not _enabled() or store is None:
            return
        runtime = state.get(_RUNTIME_KEY) or {}
        plan = runtime.get("plan") or {}
        tasks = [t for t in (plan.get("tasks") or []) if isinstance(t, dict)]
        if not tasks:
            return
        plan_id = str(runtime.get("plan_id") or plan.get("plan_id") or "")
        vm_ids = _vm_ids(state)
        tool_ids = _tool_ids(state)
        graph_nodes = _graph_nodes(store)

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        ref_to_task: dict[str, str] = {}
        ref_to_tool: dict[str, str] = {}
        tool_refs: dict[str, str] = {}
        for index, task in enumerate(tasks):
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            attrs = _vm_attrs(task, plan_id)
            existing_vm = vm_ids.get(task_id)
            if existing_vm and existing_vm in graph_nodes:
                # id-only draft = attrs merge on the existing node (no duplicate).
                nodes.append({"id": existing_vm, "attrs": attrs})
                vm_ref = existing_vm
            else:
                ref = f"vm{index}"
                ref_to_task[ref] = task_id
                nodes.append({"type": "VerificationMethod", "ref": ref, "attrs": attrs})
                vm_ref = f"#{ref}"
                for hid in _task_hypothesis_ids(task.get("design") or {}):
                    if graph_nodes.get(hid, {}).get("type") == "Hypothesis":
                        edges.append({"type": "tested_by", "from": hid, "to": f"#{ref}"})
            for tool in _planned_tools(task):
                key = tool["key"]
                known = tool_ids.get(key)
                if known and known in graph_nodes:
                    target = known
                elif key in tool_refs:
                    target = f"#{tool_refs[key]}"
                else:
                    tool_ref = f"tool{len(tool_refs)}"
                    tool_refs[key] = tool_ref
                    ref_to_tool[tool_ref] = key
                    nodes.append({
                        "type": "Tool", "ref": tool_ref, "status": tool["status"],
                        "attrs": {
                            "name": tool["name"],
                            "tool_type": "computational",
                            "location": tool["location"],
                            **({"requirements": tool["requirements"]}
                               if tool.get("requirements") else {}),
                        },
                    })
                    target = f"#{tool_ref}"
                edges.append({"type": "uses", "from": vm_ref, "to": target})

        result = store.commit(
            source=_SOURCE, nodes=nodes, edges=edges, enforce_permissions=False,
        )
        ok = bool(getattr(result, "ok", None) if not isinstance(result, dict) else result.get("ok"))
        committed = (
            result.get("committed") if isinstance(result, dict)
            else getattr(result, "committed", None)
        ) or {}
        if not ok:
            errors = (
                result.get("errors") if isinstance(result, dict)
                else getattr(result, "errors", None)
            )
            audit(logger, f"EXPERIMENT_GRAPH_PLAN_PUBLISH_FAILED plan_id={plan_id} errors={errors}",
                  level=logging.WARNING)
            return
        for echo in committed.get("nodes") or []:
            ref = str(echo.get("ref") or "")
            if not echo.get("id"):
                continue
            if task_id := ref_to_task.get(ref):
                vm_ids[task_id] = str(echo["id"])
            elif tool_key := ref_to_tool.get(ref):
                tool_ids[tool_key] = str(echo["id"])
        state[_VM_IDS_KEY] = vm_ids
        if tool_ids:
            state[_TOOL_IDS_KEY] = tool_ids

        # Tasks dropped by a replan: mark their still-live VMs as failed.
        current = {str(t.get("id") or "") for t in tasks}
        stale = [
            {"id": vm, "status": "failed", "reason": "replanned: task removed from plan"}
            for task_id, vm in vm_ids.items()
            if task_id not in current
            and graph_nodes.get(vm, {}).get("status") in ("planned", "running")
        ]
        if stale:
            store.commit(source=_SOURCE, status_updates=stale, enforce_permissions=False)
        postponed, revived = _sync_uncovered_hypotheses(store, _graph_nodes(store), _covered_hypothesis_ids(tasks))
        audit(
            logger,
            f"EXPERIMENT_GRAPH_PLAN_PUBLISHED plan_id={plan_id} "
            f"vms={len(vm_ids)} tools={len(tool_ids)} edges={len(edges)} "
            f"stale={len(stale)} postponed={postponed} revived={revived}",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        audit(logger, f"EXPERIMENT_GRAPH_PLAN_PUBLISH_FAILED error={exc}",
              level=logging.WARNING)


def _artifact_location(artifact: dict[str, Any]) -> str:
    if artifact.get("bucket") and artifact.get("s3_key"):
        return f"s3://{artifact['bucket']}/{artifact['s3_key']}"
    for key in ("location", "url", "path", "workspace_path"):
        if val := str(artifact.get(key) or "").strip():
            return val
    return ""


def _served_on(task: dict[str, Any] | None) -> str:
    """The MCP servers the task was pointed at, named with their endpoint."""
    names: list[str] = []
    for server in ((task or {}).get("mcp_servers") or [])[:3]:
        if not isinstance(server, dict):
            continue
        name = _clean(server.get("name") or server.get("server_id"), 80)
        url = _clean(server.get("url"), 200)
        label = f"{name} ({url})" if name and url else name or url
        if label:
            names.append(label)
    return ", ".join(names)


def _measured_on(
    task_id: str,
    task: dict[str, Any] | None,
    task_result: dict[str, Any],
    source_ref: str,
) -> str:
    """WHAT the run actually measured, named as exactly as the record allows.

    The research graph requires this on computational Evidence, and it must not
    be padded with the hypothesis' own words: only the dataset the task
    declared, the route that really ran, the MCP servers it ran against and the
    artifact that came back are named here.
    """
    design = (task or {}).get("design") or {}
    dataset = design.get("dataset") if isinstance(design.get("dataset"), dict) else {}
    parts: list[str] = []
    if name := _clean(dataset.get("ref") or dataset.get("name"), 120):
        parts.append(f"dataset {name}")
    route = _clean(task_result.get("route_used") or (task or {}).get("route"), 60)
    served = _served_on(task)
    if route and served:
        parts.append(f"route {route} against {served}")
    elif route or served:
        parts.append(f"route {route}" if route else served)
    if source_ref:
        parts.append(f"artifact {_clean(source_ref, 200)}")
    if not parts:
        # Never invent a measurement target: say plainly that the record names
        # none, so nobody reads the task summary as provenance.
        return (f"experiment task {_clean(task_id, 60)}: the run record names "
                "no dataset, route or artifact")
    return _clean("; ".join(parts), 400)


def _advance_task_card(store: Any, state: MutableMapping[str, Any],
                       task_id: str, final: str, status: str,
                       task_result: dict[str, Any]) -> None:
    """Move the ExperimentTask card to done/failed, with the reason on failure.

    Separate from the method's own transition: a method is the means and may be
    reused; the task is the intention this one run was carrying out, and a
    reader looking at the plan column wants to see which of its tasks are
    still outstanding without cross-referencing the methods.
    """
    try:
        xt_id = _xt_ids(state).get(str(task_id))
        if not xt_id:
            return
        nodes = _graph_nodes(store)
        current = nodes.get(xt_id, {})
        if current.get("type") != "ExperimentTask":
            return
        if current.get("status") == final:
            return
        update: dict[str, Any] = {"id": xt_id, "status": final,
                                  "reason": f"task {task_id} result: {status}"}
        # A card that says a thing failed and not why is the gap the graph
        # reports as `unreasoned_failures`, so the failure carries its message.
        attrs = None
        if final == "failed":
            why = _clean(task_result.get("error")
                         or task_result.get("message")
                         or task_result.get("summary"), 600)
            if why:
                attrs = {"failure_reason": why}
        # planned → done is legal for this type, so no intermediate hop.
        store.commit(source=_PLAN_SOURCE,
                     nodes=[{"id": xt_id, "attrs": attrs}] if attrs else None,
                     status_updates=[update])
    except Exception as exc:  # noqa: BLE001 — never break result recording
        logger.warning("advancing the experiment task card failed: %s", exc)


def publish_result_to_graph(
    store: Any,
    state: MutableMapping[str, Any],
    task_id: str,
    task_result: dict[str, Any],
) -> None:
    """Write one recorded TaskResult into the research graph (best-effort).

    success/partial → ``Evidence`` (subtype=computational) + ``VM —produces→ E``
    and ``Evidence —relates_to→`` every hypothesis the task covers (so the
    store moves those Hs to ``under_verification`` and the background
    validator can judge). File artifacts → ``GeneratedData —derived_from→ E``;
    the task's VM status is advanced ``planned→running→done`` (or ``failed``).
    Skips silently when no VM was published for this task.
    """
    try:
        if not _enabled() or store is None or not isinstance(task_result, dict):
            return
        vm_id = _vm_ids(state).get(str(task_id))
        if not vm_id:
            return
        graph_nodes = _graph_nodes(store)
        if graph_nodes.get(vm_id, {}).get("type") != "VerificationMethod":
            return
        status = str(task_result.get("status") or "")
        final = "done" if status in ("success", "partial") else "failed"
        # VM transitions are planned→running→done/failed; the intermediate hop
        # needs its own commit so the second update validates against `running`.
        if graph_nodes[vm_id].get("status") == "planned" and final == "done":
            store.commit(
                source=_SOURCE,
                status_updates=[{"id": vm_id, "status": "running",
                                 "reason": f"task {task_id} executed"}],
                enforce_permissions=False,
            )

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        artifacts = [a for a in (task_result.get("artifacts") or []) if isinstance(a, dict)]
        task = _task_by_id(state, task_id)
        if status in ("success", "partial"):
            source_ref = next(
                (loc for a in artifacts if (loc := _artifact_location(a))), "",
            )
            nodes.append({
                "type": "Evidence",
                "ref": "e0",
                "attrs": {
                    "subtype": "computational",
                    "content": _clean(task_result.get("summary")) or f"Task {task_id}: {status}",
                    "measured_on": _measured_on(task_id, task, task_result, source_ref),
                    "source_ref": source_ref,
                    "task_id": str(task_id),
                    "result_id": str(task_result.get("result_id") or ""),
                },
            })
            edges.append({"type": "produces", "from": vm_id, "to": "#e0"})
            for hid in _task_hypothesis_ids((task or {}).get("design") or {}):
                if graph_nodes.get(hid, {}).get("type") == "Hypothesis":
                    edges.append({"type": "relates_to", "from": "#e0", "to": hid})
            for i, artifact in enumerate(artifacts[:_MAX_GENERATED_DATA]):
                location = _artifact_location(artifact)
                if not location:
                    continue
                ref = f"gd{i}"
                nodes.append({
                    "type": "GeneratedData",
                    "ref": ref,
                    "attrs": {
                        "description": _clean(artifact.get("name") or artifact.get("description"), 200),
                        "path": location,
                    },
                })
                edges.append({"type": "derived_from", "from": f"#{ref}", "to": "#e0"})
        status_updates = []
        current_vm_status = _graph_nodes(store).get(vm_id, {}).get("status")
        if current_vm_status in ("planned", "running") and current_vm_status != final:
            status_updates.append({
                "id": vm_id, "status": final,
                "reason": f"task {task_id} result: {status}",
            })
        result = store.commit(
            source=_SOURCE, nodes=nodes, edges=edges,
            status_updates=status_updates, enforce_permissions=False,
        )
        ok = bool(getattr(result, "ok", None) if not isinstance(result, dict) else result.get("ok"))
        # The detailed plan's own card moves with the run. Its own commit, under
        # its own source, so the ACL governs it and a failure here cannot cost
        # the evidence that has just been written.
        _advance_task_card(store, state, task_id, final, status, task_result)
        if not ok:
            errors = (
                result.get("errors") if isinstance(result, dict)
                else getattr(result, "errors", None)
            )
            audit(logger, f"EXPERIMENT_GRAPH_RESULT_PUBLISH_FAILED task_id={task_id} errors={errors}",
                  level=logging.WARNING)
            return
        linked = sum(1 for e in edges if e.get("type") == "relates_to")
        judged = _schedule_hypothesis_judgments(store) if status in ("success", "partial") else 0
        audit(
            logger,
            f"EXPERIMENT_GRAPH_RESULT_PUBLISHED task_id={task_id} vm={vm_id} "
            f"vm_status={final} evidence={sum(1 for n in nodes if n.get('type') == 'Evidence')} "
            f"generated_data={sum(1 for n in nodes if n.get('type') == 'GeneratedData')} "
            f"relates_to={linked} scheduled_judgments={judged}",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        audit(logger, f"EXPERIMENT_GRAPH_RESULT_PUBLISH_FAILED task_id={task_id} error={exc}",
              level=logging.WARNING)


__all__ = ["publish_plan_detail_to_graph", "publish_plan_to_graph",
           "publish_result_to_graph"]
