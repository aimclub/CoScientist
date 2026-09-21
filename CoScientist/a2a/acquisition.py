"""MASDA acquisition receipts and deterministic finalization checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

from google.genai import types

from CoScientist.config import get_settings
from CoScientist.graph.session_scope import GRAPH_SCOPE_SESSION_KEY

RECEIPTS_STATE_KEY = "dataset_acquisition_receipts"
FINALIZATION_STATE_KEY = "dataset_acquisition_finalization"
REPORT_CONTEXT_STATE_KEY = "dataset_acquisition_report_context"
INCOMPLETE_MARKER = "[MASDA_ACQUISITION_INCOMPLETE]"
MASDA_AGENT = "MasdaDatasetsAgent"


def _tasks(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = state.get("_master_active_tasks") or state.get("active_tasks") or []
    return [task for task in value if isinstance(task, dict)]


def assigned_masda_task_id(state: Mapping[str, Any]) -> Optional[str]:
    pending = [task for task in _tasks(state)
               if task.get("assignee") == MASDA_AGENT and task.get("status") != "DONE"]
    if len(pending) == 1 and pending[0].get("id"):
        return str(pending[0]["id"])
    return None


def build_receipt(*, state: Mapping[str, Any], server_task_id: str,
                  path: Path, record_count: int) -> dict[str, Any]:
    resolved = path.resolve()
    data = resolved.read_bytes()
    return {
        "provider": "masda", "status": "completed",
        "server_task_id": server_task_id,
        "session_id": str(state.get(GRAPH_SCOPE_SESSION_KEY) or ""),
        "local_path": str(resolved), "record_count": int(record_count),
        "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }


def record_success(state: MutableMapping[str, Any], receipt: dict[str, Any],
                   task_id: Optional[str]) -> dict[str, Any]:
    """Record a successful acquisition and return the ADK state delta.

    AgentTool runs this agent in a copied child session.  Returning the exact
    changed keys lets the caller put them on ``EventActions.state_delta``, which
    is the only state AgentTool forwards to its parent session.
    """
    key = task_id or f"masda:{receipt['server_task_id']}"
    receipts = dict(state.get(RECEIPTS_STATE_KEY) or {})
    receipts[key] = receipt
    state[RECEIPTS_STATE_KEY] = receipts
    delta: dict[str, Any] = {RECEIPTS_STATE_KEY: receipts}
    if not task_id:
        return delta
    tasks = list(state.get("_master_active_tasks") or state.get("active_tasks") or [])
    for task in tasks:
        if isinstance(task, dict) and task.get("id") == task_id:
            task["status"] = "DONE"
            task["acquisition_receipt_id"] = key
            break
    state["_master_active_tasks"] = tasks
    active_tasks = list(state.get("active_tasks") or tasks)
    for task in active_tasks:
        if isinstance(task, dict) and task.get("id") == task_id:
            task["status"] = "DONE"
            task["acquisition_receipt_id"] = key
            break
    state["active_tasks"] = active_tasks
    delta["_master_active_tasks"] = tasks
    delta["active_tasks"] = active_tasks
    return delta


def validate_receipt(state: Mapping[str, Any], task_id: str) -> tuple[bool, str, Optional[dict[str, Any]]]:
    receipt = (state.get(RECEIPTS_STATE_KEY) or {}).get(task_id)
    if not isinstance(receipt, dict):
        return False, "missing acquisition receipt", None
    if receipt.get("provider") != "masda" or receipt.get("status") != "completed":
        return False, "receipt is not a completed MASDA acquisition", receipt
    session_id = str(state.get(GRAPH_SCOPE_SESSION_KEY) or "")
    if not session_id or receipt.get("session_id") != session_id:
        return False, "receipt belongs to another session", receipt
    if not receipt.get("server_task_id"):
        return False, "receipt has no MASDA server task id", receipt
    try:
        path = Path(str(receipt.get("local_path") or ""))
        workspace_id = str(state.get("coder_workspace_id") or "")
        workspace = (Path(get_settings().code_exec.workspace_root) / workspace_id).resolve()
        resolved = path.resolve()
        if not path.is_absolute() or not workspace_id or not resolved.is_relative_to(workspace):
            return False, "receipt path is outside the current workspace", receipt
        data = resolved.read_bytes()
    except (OSError, RuntimeError, ValueError):
        return False, "receipt artifact is not readable", receipt
    if len(data) != receipt.get("size_bytes"):
        return False, "receipt artifact size does not match", receipt
    if hashlib.sha256(data).hexdigest() != receipt.get("sha256"):
        return False, "receipt artifact SHA-256 does not match", receipt
    return True, "completed", receipt


def validated_masda_paths(state: Mapping[str, Any]) -> set[str]:
    paths = set()
    for task in _tasks(state):
        if task.get("assignee") != MASDA_AGENT or not task.get("id"):
            continue
        valid, _, receipt = validate_receipt(state, str(task["id"]))
        if valid and receipt:
            paths.add(str(Path(receipt["local_path"]).resolve()))
    return paths


def require_masda_acquisition(callback_context):
    """Prevent a successful report when a planned MASDA acquisition is unproven."""
    if get_settings().dataset.provider != "masda":
        return None
    state = callback_context.state
    tasks = [task for task in _tasks(state) if task.get("assignee") == MASDA_AGENT]
    if not tasks:
        return None
    state.pop(REPORT_CONTEXT_STATE_KEY, None)
    failures = []
    verified = []
    for task in tasks:
        task_id = str(task.get("id") or "<missing-id>")
        valid, reason, receipt = validate_receipt(state, task_id)
        if not valid or task.get("status") != "DONE":
            failures.append(f"{task_id}: {reason}")
        elif receipt:
            verified.append({
                "task_id": task_id,
                "task_status": "DONE",
                "acquisition_receipt_id": task.get("acquisition_receipt_id"),
                "receipt": receipt,
            })
    if not failures:
        state[FINALIZATION_STATE_KEY] = {"status": "completed"}
        state[REPORT_CONTEXT_STATE_KEY] = (
            "### Verified dataset acquisition\n"
            "The following JSON is generated by the deterministic MASDA completion "
            "gate from validated session state. Treat it as the acquisition source "
            "of truth; a separate receipt JSON file is not required.\n\n"
            "```json\n"
            + json.dumps({
                "dataset_acquisition_finalization": state[FINALIZATION_STATE_KEY],
                "validated_receipts": verified,
            }, ensure_ascii=False, indent=2)
            + "\n```"
        )
        return None
    state[FINALIZATION_STATE_KEY] = {"status": "incomplete", "reasons": failures}
    text = (f"{INCOMPLETE_MARKER}\n\n# Incomplete dataset acquisition\n\n"
            "The run could not be finalized as a successful MASDA acquisition.\n\n"
            + "\n".join(f"- {reason}" for reason in failures))
    return types.Content(role="model", parts=[types.Part.from_text(text=text)])


__all__ = ["FINALIZATION_STATE_KEY", "INCOMPLETE_MARKER", "RECEIPTS_STATE_KEY",
           "REPORT_CONTEXT_STATE_KEY",
           "assigned_masda_task_id", "build_receipt", "record_success",
           "require_masda_acquisition", "validate_receipt", "validated_masda_paths"]
