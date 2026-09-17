"""Deterministic bridge: approved ExperimentPlan / TaskResults → research graph.

After a plan is approved each task becomes a ``VerificationMethod`` node linked
to the hypothesis it tests (``Hypothesis —tested_by→ VM``). Hypotheses with no
covering task are postponed (``no_method_this_stage``), not dropped and not
turned into extra EXP tasks. After ``record_result`` the outcome becomes
``Evidence`` (+``GeneratedData`` for file artifacts) linked via
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
_VM_IDS_KEY = "experiment_graph_vm_ids"  # state-level: survives replans
_RUNTIME_KEY = "experiment_runtime"
_MAX_GENERATED_DATA = 5
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

    return {
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


def publish_plan_to_graph(store: Any, state: MutableMapping[str, Any]) -> None:
    """Write the approved plan into the research graph (best-effort, idempotent).

    Each plan task → one ``VerificationMethod`` node plus ``tested_by`` edges
    from every hypothesis the task's design covers (only for hypothesis ids that
    actually exist as graph nodes). Formulated hypotheses with no covering task
    are postponed; a postponed hypothesis a task now lists is revived to
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
        graph_nodes = _graph_nodes(store)

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        ref_to_task: dict[str, str] = {}
        for index, task in enumerate(tasks):
            task_id = str(task.get("id") or "").strip()
            if not task_id:
                continue
            attrs = _vm_attrs(task, plan_id)
            existing_vm = vm_ids.get(task_id)
            if existing_vm and existing_vm in graph_nodes:
                # id-only draft = attrs merge on the existing node (no duplicate).
                nodes.append({"id": existing_vm, "attrs": attrs})
                continue
            ref = f"vm{index}"
            ref_to_task[ref] = task_id
            nodes.append({"type": "VerificationMethod", "ref": ref, "attrs": attrs})
            for hid in _task_hypothesis_ids(task.get("design") or {}):
                if graph_nodes.get(hid, {}).get("type") == "Hypothesis":
                    edges.append({"type": "tested_by", "from": hid, "to": f"#{ref}"})

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
            task_id = ref_to_task.get(str(echo.get("ref") or ""))
            if task_id and echo.get("id"):
                vm_ids[task_id] = str(echo["id"])
        state[_VM_IDS_KEY] = vm_ids

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
            f"vms={len(vm_ids)} edges={len(edges)} stale={len(stale)} "
            f"postponed={postponed} revived={revived}",
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
                    "source_ref": source_ref,
                    "task_id": str(task_id),
                    "result_id": str(task_result.get("result_id") or ""),
                },
            })
            edges.append({"type": "produces", "from": vm_id, "to": "#e0"})
            task = _task_by_id(state, task_id)
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


__all__ = ["publish_plan_to_graph", "publish_result_to_graph"]
