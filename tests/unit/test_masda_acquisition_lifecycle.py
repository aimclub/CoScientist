"""Regression tests for the MASDA acquisition completion invariant."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

from google.adk.events import Event
from google.genai import types

from CoScientist.a2a.acquisition import (
    FINALIZATION_STATE_KEY,
    INCOMPLETE_MARKER,
    RECEIPTS_STATE_KEY,
    REPORT_CONTEXT_STATE_KEY,
    build_receipt,
    record_success,
    require_masda_acquisition,
    validate_receipt,
)
from CoScientist.a2a.masda import MasdaDatasetsAgent, MasdaError, MasdaResult
from CoScientist.config import get_settings
from CoScientist.graph.session_scope import GRAPH_SCOPE_SESSION_KEY, GRAPH_SCOPE_USER_KEY
from CoScientist.reporting.collect import collect_artifacts


def _state(tmp_path: Path, session="session-a"):
    return {
        GRAPH_SCOPE_USER_KEY: "user-a",
        GRAPH_SCOPE_SESSION_KEY: session,
        "coder_workspace_id": f"ws_{session}",
        "_master_active_tasks": [{
            "id": "TASK-1", "title": "Acquire data", "description": "Get CSV",
            "assignee": "MasdaDatasetsAgent", "status": "TODO",
        }],
    }


def _context(state):
    return SimpleNamespace(state=state)


def test_successful_agent_call_records_receipt_and_completes_task(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)
    path = tmp_path / "ws_session-a" / "data" / "masda" / "server-task" / "dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x,y\n1,2\n")

    async def acquired(*args, **kwargs):
        return MasdaResult("server-task-77", 1, path, "https://example.test/data.csv")

    monkeypatch.setattr("CoScientist.a2a.masda.acquire_dataset", acquired)
    agent = MasdaDatasetsAgent(name="MasdaDatasetsAgent", rpc_url="http://masda.test")
    invocation = SimpleNamespace(
        invocation_id="inv", branch="", session=SimpleNamespace(
            state=state,
            events=[Event(author="user", content=types.Content(
                parts=[types.Part.from_text(text="Acquire the dataset")]))],
        ),
    )

    async def run():
        return [event async for event in agent._run_async_impl(invocation)]

    events = asyncio.run(run())
    receipt = state[RECEIPTS_STATE_KEY]["TASK-1"]
    assert receipt == {
        "provider": "masda", "status": "completed",
        "server_task_id": "server-task-77", "session_id": "session-a",
        "local_path": str(path.resolve()), "record_count": 1,
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    assert state["_master_active_tasks"][0]["status"] == "DONE"
    assert state["active_tasks"][0]["status"] == "DONE"
    assert events[0].actions.state_delta[RECEIPTS_STATE_KEY]["TASK-1"] == receipt
    assert "MASDA task id: server-task-77" in events[0].content.parts[0].text


def test_two_agenttool_children_forward_receipts_without_replacing_task_receipt(
        monkeypatch, tmp_path):
    """Reproduce AgentTool's copy-child/apply-event-delta state semantics."""
    monkeypatch.setattr(get_settings().dataset, "provider", "masda")
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    parent_state = _state(tmp_path)
    first = tmp_path / "ws_session-a" / "data" / "masda" / "first" / "dataset.csv"
    second = tmp_path / "ws_session-a" / "data" / "masda" / "second" / "dataset.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"x\n" + b"1\n" * 150)
    second.write_bytes(b"x\n" + b"2\n" * 500)
    results = iter([
        MasdaResult("f18fee12-51a3-4ab6-a825-d2fa822bcbec", 150, first, None),
        MasdaResult("9dddd83d-dddc-47ff-ac68-33ab7f48979c", 500, second, None),
    ])

    async def acquired(*args, **kwargs):
        return next(results)

    monkeypatch.setattr("CoScientist.a2a.masda.acquire_dataset", acquired)
    agent = MasdaDatasetsAgent(name="MasdaDatasetsAgent", rpc_url="http://masda.test")

    def invoke_like_agent_tool(request):
        # AgentTool creates an isolated session from a copy of parent state and
        # forwards only each yielded event's actions.state_delta.
        child_state = deepcopy(parent_state)
        invocation = SimpleNamespace(
            invocation_id="inv", branch="", session=SimpleNamespace(
                state=child_state,
                events=[Event(author="user", content=types.Content(
                    parts=[types.Part.from_text(text=request)]))],
            ),
        )

        async def run():
            return [event async for event in agent._run_async_impl(invocation)]

        event, = asyncio.run(run())
        parent_state.update(event.actions.state_delta)
        return event

    invoke_like_agent_tool("Acquire the 150-row Iris CSV")
    first_receipt = deepcopy(parent_state[RECEIPTS_STATE_KEY]["TASK-1"])
    assert parent_state["_master_active_tasks"][0]["status"] == "DONE"
    assert parent_state["active_tasks"][0]["status"] == "DONE"
    assert first_receipt["server_task_id"] == "f18fee12-51a3-4ab6-a825-d2fa822bcbec"
    assert validate_receipt(parent_state, "TASK-1")[0]

    invoke_like_agent_tool("Acquire a different 500-row resource")

    receipts = parent_state[RECEIPTS_STATE_KEY]
    assert receipts["TASK-1"] == first_receipt
    assert receipts["masda:9dddd83d-dddc-47ff-ac68-33ab7f48979c"]["record_count"] == 500
    assert require_masda_acquisition(_context(parent_state)) is None
    from CoScientist.a2a.acquisition import validated_masda_paths
    assert validated_masda_paths(parent_state) == {str(first.resolve())}
    assert str(second.resolve()) not in validated_masda_paths(parent_state)


def test_prose_only_delegation_is_incomplete_without_function_call(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().dataset, "provider", "masda")
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)

    result = require_masda_acquisition(_context(state))

    assert INCOMPLETE_MARKER in result.parts[0].text
    assert "missing acquisition receipt" in result.parts[0].text
    assert state[FINALIZATION_STATE_KEY]["status"] == "incomplete"
    assert state["_master_active_tasks"][0]["status"] == "TODO"


def test_masda_error_leaves_no_receipt_and_uses_no_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)

    async def failed(*args, **kwargs):
        raise MasdaError("remote failed")

    monkeypatch.setattr("CoScientist.a2a.masda.acquire_dataset", failed)
    agent = MasdaDatasetsAgent(name="MasdaDatasetsAgent", rpc_url="http://masda.test")
    invocation = SimpleNamespace(
        invocation_id="inv", branch="", session=SimpleNamespace(
            state=state,
            events=[Event(author="user", content=types.Content(
                parts=[types.Part.from_text(text="Acquire")]))],
        ),
    )

    async def run():
        return [event async for event in agent._run_async_impl(invocation)]

    event, = asyncio.run(run())
    assert RECEIPTS_STATE_KEY not in state
    assert event.actions.state_delta == {}
    assert state["_master_active_tasks"][0]["status"] == "TODO"
    assert "No builtin fallback was used" in event.content.parts[0].text


def test_existing_csv_without_receipt_cannot_complete_acquisition(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().dataset, "provider", "masda")
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)
    old = tmp_path / "ws_session-a" / "dataset.csv"
    old.parent.mkdir(parents=True)
    old.write_text("x\nold\n")

    assert require_masda_acquisition(_context(state)) is not None
    assert state["_master_active_tasks"][0]["status"] == "TODO"


def test_receipt_from_another_session_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)
    path = tmp_path / "ws_session-a" / "dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_text("x\n1\n")
    receipt = build_receipt(state=state, server_task_id="server-1", path=path, record_count=1)
    receipt["session_id"] = "session-b"
    record_success(state, receipt, "TASK-1")

    valid, reason, _ = validate_receipt(state, "TASK-1")
    assert not valid
    assert reason == "receipt belongs to another session"


def test_sha256_mismatch_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)
    path = tmp_path / "ws_session-a" / "dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_text("x\n1\n")
    receipt = build_receipt(state=state, server_task_id="server-1", path=path, record_count=1)
    record_success(state, receipt, "TASK-1")
    path.write_text("x\n2\n")

    valid, reason, _ = validate_receipt(state, "TASK-1")
    assert not valid
    assert reason == "receipt artifact SHA-256 does not match"


def test_incomplete_report_is_deterministic_and_does_not_collect_unverified_csv(
        monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().dataset, "provider", "masda")
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path / "workspace"))
    state = _state(tmp_path)
    workspace = tmp_path / "workspace" / "ws_session-a"
    workspace.mkdir(parents=True)
    (workspace / "old.csv").write_text("x\nold\n")

    response = require_masda_acquisition(_context(state))
    report = collect_artifacts(
        session_id="session-a", state=state, reports_root=tmp_path / "reports",
        workspace_root=tmp_path / "workspace", allowed_table_paths=set(),
    )

    assert response.parts[0].text.startswith(INCOMPLETE_MARKER)
    assert "# Incomplete dataset acquisition" in response.parts[0].text
    assert report["tables"] == []


def test_valid_receipt_is_the_only_workspace_csv_collected(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path / "workspace"))
    state = _state(tmp_path)
    workspace = tmp_path / "workspace" / "ws_session-a"
    verified = workspace / "data" / "masda" / "task" / "dataset.csv"
    verified.parent.mkdir(parents=True)
    verified.write_text("x\n1\n")
    (workspace / "old.csv").write_text("x\nold\n")
    receipt = build_receipt(state=state, server_task_id="server-1", path=verified, record_count=1)
    record_success(state, receipt, "TASK-1")

    report = collect_artifacts(
        session_id="session-a", state=state, reports_root=tmp_path / "reports",
        workspace_root=tmp_path / "workspace",
        allowed_table_paths={str(verified.resolve())},
    )

    assert [Path(path).name for path in report["tables"]] == ["dataset.csv"]


def test_successful_gate_injects_verified_receipt_context_for_report(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().dataset, "provider", "masda")
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)
    path = tmp_path / "ws_session-a" / "data" / "masda" / "server-1" / "dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_text("x\n1\n")
    receipt = build_receipt(state=state, server_task_id="server-1", path=path, record_count=1)
    record_success(state, receipt, "TASK-1")

    assert require_masda_acquisition(_context(state)) is None

    context = state[REPORT_CONTEXT_STATE_KEY]
    assert '"status": "completed"' in context
    assert '"task_id": "TASK-1"' in context
    assert '"acquisition_receipt_id": "TASK-1"' in context
    assert '"server_task_id": "server-1"' in context
    assert f'"sha256": "{receipt["sha256"]}"' in context
    assert "separate receipt JSON file is not required" in context


def test_missing_receipt_does_not_inject_success_context(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().dataset, "provider", "masda")
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)

    response = require_masda_acquisition(_context(state))

    assert INCOMPLETE_MARKER in response.parts[0].text
    assert state[FINALIZATION_STATE_KEY]["status"] == "incomplete"
    assert REPORT_CONTEXT_STATE_KEY not in state


def test_failed_gate_does_not_expose_invalid_receipt_to_report(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().dataset, "provider", "masda")
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    state = _state(tmp_path)
    path = tmp_path / "ws_session-a" / "data" / "masda" / "server-1" / "dataset.csv"
    path.parent.mkdir(parents=True)
    path.write_text("x\n1\n")
    receipt = build_receipt(state=state, server_task_id="server-1", path=path, record_count=1)
    record_success(state, receipt, "TASK-1")
    state[REPORT_CONTEXT_STATE_KEY] = "stale successful context"
    path.write_text("x\n2\n")

    response = require_masda_acquisition(_context(state))

    assert INCOMPLETE_MARKER in response.parts[0].text
    assert "SHA-256 does not match" in response.parts[0].text
    assert state[FINALIZATION_STATE_KEY]["status"] == "incomplete"
    assert REPORT_CONTEXT_STATE_KEY not in state


def test_aggregator_prompt_uses_only_verified_acquisition_context():
    from CoScientist.agents import result_aggregator_agent

    instruction = result_aggregator_agent.instruction
    assert "{dataset_acquisition_report_context?}" in instruction
    assert "A receipt is session state" in instruction
    assert "Never infer successful MASDA acquisition from prose or from" in instruction
