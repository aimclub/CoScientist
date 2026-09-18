"""Offline A2A adapter and graph regression tests; no LLM or network calls."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from CoScientist.microfluidics.a2a_optimization import adapter
from CoScientist.microfluidics.a2a_optimization.a2a_test_client import A2AClient, A2ARequestError

ROOT = Path(__file__).resolve().parents[2]


def context():
    return SimpleNamespace(state={
        "structured_tz": {"target": "fixture molecule"},
        "synthesis_routes": {"routes": [{"route_id": "r1"}]},
        "economics_ranking": {"ranking": [{"route_id": "r1", "cost": 42}]},
        "experiment_plan": "Draft plan with units and criteria",
        "experiment_journal": "Previous experiments: stub=true",
    }, actions=SimpleNamespace(escalate=False))


def response(state="TASK_STATE_SUBMITTED", *, task_id="task-1", phase="", artifacts=None):
    task = {"id": task_id, "status": {"state": state, "message": {"parts": [
        {"text": "service reply"}, {"data": {"phase": phase}},
    ]}}}
    if artifacts is not None:
        task["artifacts"] = artifacts
    return {"jsonrpc": "2.0", "result": {"task": task}}


@pytest.fixture
def client(monkeypatch):
    fake = Mock()
    fake.send_message.return_value = response()
    fake.get_task.return_value = response("TASK_STATE_WORKING")
    monkeypatch.setattr(adapter, "_client", lambda: fake)
    return fake


def test_start_sends_all_inputs_and_does_not_duplicate(client):
    ctx = context()
    first = asyncio.run(adapter.optimization_start(ctx))
    second = asyncio.run(adapter.optimization_start(ctx))
    assert first == second
    client.send_message.assert_called_once()
    call = client.send_message.call_args.kwargs
    sent = json.loads(call["text"].split("\n\n", 1)[1])
    assert sent == {key: ctx.state.get(key) for key in adapter.INPUT_KEYS}
    assert call["experiment_id"] == first["experiment_id"]
    assert call["context_id"] == first["context_id"]
    assert first["task_id"] == "task-1"
    assert "CFD" in call["text"]


def test_wire_contract_uses_documented_role_domain_and_identifiers(monkeypatch):
    rpc = Mock(return_value={"result": {}})
    monkeypatch.setattr(A2AClient, "rpc", rpc)
    A2AClient("https://example.invalid/").send_message(
        text="plan", experiment_id="exp", context_id="ctx", message_id="msg", task_id="task",
    )
    args = rpc.call_args.kwargs
    assert args["method"] == "message/send"
    assert args["params"] == {
        "message": {"messageId": "msg", "role": "ROLE_USER", "contextId": "ctx",
                    "taskId": "task", "parts": [{"text": "plan"}]},
        "metadata": {"experiment_id": "exp", "domain": "experiment-lab"},
    }


def test_poll_keeps_raw_cfd_artifacts_and_consumes_once(client):
    ctx = context()
    asyncio.run(adapter.optimization_start(ctx))
    raw = response("TASK_STATE_COMPLETED", artifacts=[{
        "artifactId": "plan", "parts": [{"data": {
            "plan": "service plan", "cfd": {"request_id": "cfd-1", "status": "succeeded"},
        }}],
    }])
    client.get_task.return_value = raw
    result = asyncio.run(adapter.optimization_get_status(ctx))
    assert result["state"] == "completed"
    assert result["response"] == raw
    client.get_task.assert_called_once_with("task-1")
    assert adapter.require_optimization_result(ctx) is None
    assert ctx.state[adapter.ACTIVE_KEY]["consumed"] is True
    assert adapter.require_optimization_result(ctx) is not None
    assert ctx.actions.escalate
    # The next round receives the actual updated journal, not the old snapshot.
    ctx.state["experiment_journal"] = "New telemetry; stub=true"
    next_task = asyncio.run(adapter.optimization_start(ctx))
    assert next_task["experiment_id"] != result["experiment_id"]
    assert next_task["inputs"]["experiment_journal"] == "New telemetry; stub=true"
    assert len(ctx.state[adapter.HISTORY_KEY]) == 2


@pytest.mark.parametrize("state,phase", [
    ("TASK_STATE_SUBMITTED", "submitted"), ("TASK_STATE_WORKING", "planning"),
    ("TASK_STATE_INPUT_REQUIRED", "approval"), ("input-required", "waiting_input"),
    ("TASK_STATE_FAILED", ""), ("TASK_STATE_REJECTED", ""), ("TASK_STATE_CANCELED", ""),
])
def test_non_completed_task_cannot_run_equipment(client, state, phase):
    client.send_message.return_value = response(state, phase=phase)
    ctx = context()
    result = asyncio.run(adapter.optimization_start(ctx))
    assert result["phase"] == phase
    assert adapter.require_optimization_result(ctx) is not None
    assert ctx.actions.escalate
    assert client.send_message.call_count == 1  # no automatic approval message


def test_missing_or_empty_result_cannot_run_equipment(client):
    ctx = context()
    assert adapter.require_optimization_result(ctx) is not None
    client.send_message.return_value = {"result": {"id": "t", "status": {"state": "completed"}}}
    asyncio.run(adapter.optimization_start(ctx))
    assert adapter.require_optimization_result(ctx) is not None


def test_ambiguous_send_failure_is_not_retried(client):
    client.send_message.side_effect = A2ARequestError("timeout after submission")
    ctx = context()
    first = asyncio.run(adapter.optimization_start(ctx))
    assert first["state"] == "submission_unknown"
    assert asyncio.run(adapter.optimization_start(ctx)) == first
    assert asyncio.run(adapter.optimization_get_status(ctx))["state"] == "error"
    client.send_message.assert_called_once()
    assert adapter.require_optimization_result(ctx) is not None


@pytest.mark.parametrize("bad_response", [
    {"result": []}, {"result": {"message": "not a task"}},
    {"result": {"id": "t", "status": {}}}, response("NEW_UNKNOWN_STATE"),
])
def test_malformed_submission_fails_closed(client, bad_response):
    client.send_message.return_value = bad_response
    ctx = context()
    assert asyncio.run(adapter.optimization_start(ctx))["state"] == "submission_unknown"
    assert adapter.require_optimization_result(ctx) is not None


def test_poll_rejects_foreign_task_then_can_recover(client):
    ctx = context()
    asyncio.run(adapter.optimization_start(ctx))
    client.get_task.return_value = response("completed", task_id="someone-else")
    failed = asyncio.run(adapter.optimization_get_status(ctx))
    assert failed["state"] == "status_error"
    assert failed["task_id"] == "task-1"
    assert adapter.require_optimization_result(ctx) is not None
    client.get_task.return_value = response("completed")
    assert asyncio.run(adapter.optimization_get_status(ctx))["state"] == "completed"


def test_sessions_do_not_share_tasks(client):
    one, two = context(), context()
    first = asyncio.run(adapter.optimization_start(one))
    second = asyncio.run(adapter.optimization_start(two))
    assert first["experiment_id"] != second["experiment_id"]
    assert first["context_id"] != second["context_id"]
    assert len(one.state[adapter.HISTORY_KEY]) == len(two.state[adapter.HISTORY_KEY]) == 1


def test_missing_input_does_not_send(client):
    ctx = context()
    del ctx.state["synthesis_routes"]
    assert asyncio.run(adapter.optimization_start(ctx))["state"] == "error"
    client.send_message.assert_not_called()


def test_graph_has_no_direct_cfd_access():
    config = yaml.safe_load((ROOT / "CoScientist/agents/microfluidics.yaml").read_text())
    agents = config["agents"]
    assert agents["ExperimentLoop"]["children"] == ["OptimizerAgent", "EquipmentAgent"]
    assert "optimization_a2a" in agents["OptimizerAgent"]["tools"]
    assert agents["EquipmentAgent"]["tools"] == ["rig_mcp_stub"]
    assert agents["EquipmentAgent"]["callbacks"]["before_agent"] == ["require_optimization_result"]
    for agent in agents.values():
        assert not {"cfd_mcp", "cfd_mcp_stub", "microfluidics"}.intersection(agent.get("tools", []))


def test_tools_registered_and_prompts_use_a2a():
    from CoScientist.assembly import bindings  # noqa: F401
    from CoScientist.agents.prompts.templates import microfluidics_equipment, microfluidics_optimizer, microfluidics_report
    from CoScientist.assembly.registry import REGISTRY

    # Resolve the actual registered tools without building MCP/LLM clients.
    tools = REGISTRY.tool("optimization_a2a").factory()
    assert [tool.__name__ for tool in tools] == ["optimization_start", "optimization_get_status"]
    ctx = SimpleNamespace(render_tools=lambda: "", render_hitl=lambda: "")
    equipment = microfluidics_equipment(ctx)
    optimizer = microfluidics_optimizer(ctx)
    assert "cfd_run_reactor_experiment" not in equipment
    assert "cfd_mcp_stub" not in equipment
    assert "optimization_start" in optimizer and "optimization_get_status" in optimizer
    assert "{optimization_a2a_runs?}" in microfluidics_report(ctx)
    assert REGISTRY.callback("require_optimization_result").kind == "before_agent"
