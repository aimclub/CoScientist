"""Offline hand-off, task lifecycle and graph tests. Never contact services."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from CoScientist.microfluidics.a2a_optimization import adapter
from CoScientist.microfluidics.a2a_optimization.a2a_test_client import A2AClient, A2ARequestError
from CoScientist.microfluidics.a2a_optimization.contracts import prepare_inputs
"""
ROOT = Path(__file__).resolve().parents[2]


def inputs():
    route = {
        "route_id": "r1", "product": {"name": "fixture"}, "overall_status": "eligible",
        "steps": [{"operation": "fixture reaction", "reactants": [{"name": "A"}],
                   "products": [{"name": "fixture"}],
                   "conditions": [{"name": "Среда", "value": "water"}],
                   "yield_fraction": 0.8}],
    }
    return {
        "structured_tz": {"original_request": "fixture molecule"},
        "literature_analysis": {"facts": [{"statement": "fixture fact", "sources": ["fixture"]}]},
        "synthesis_routes": {"routes": [route]},
        "qualified_routes": {"status": "ok", "routes": [copy.deepcopy(route)]},
        "economics": "Partial cost, not a complete price",
        "economics_ranking": {"target_qty": 100, "target_unit": "g",
            "preferred_currency": "RUB", "rank_by": "per_unit", "routes": {
                "r1": {"status": "partial", "rank": 1, "currency": "RUB",
                       "cost_per_unit": "42.10", "cost_packs": "50.00", "missing": [{"smiles": "O", "reason": "no price"}]},
            }},
    }


def context():
    return SimpleNamespace(state=inputs())


def response(state="TASK_STATE_SUBMITTED", *, task_id="task-1", phase="", artifacts=None, steps=None):
    progress = {"phase": phase} if steps is None else {"phase": phase, "completed_steps": steps}
    task = {"id": task_id, "status": {"state": state, "message": {"parts": [
        {"text": "service reply"}, {"data": progress},
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


def test_handoff_is_snapshotted_and_sent_once(client):
    ctx = context()
    first = asyncio.run(adapter.optimization_start(ctx))
    assert asyncio.run(adapter.optimization_start(ctx)) == first
    client.send_message.assert_called_once()
    call = client.send_message.call_args.kwargs
    assert json.loads(call["text"].split("\n\n", 1)[1]) == prepare_inputs(inputs())
    assert call["experiment_id"] == first["experiment_id"]
    assert call["context_id"] == first["context_id"]
    assert "CoScientist не исполняет план локально" in call["text"]
    assert "последнего опыта" in call["text"]
    assert "Не запускай физическое оборудование" not in call["text"]
    ctx.state["economics_ranking"]["routes"]["r1"]["cost_per_unit"] = "999"
    assert first["inputs"]["economics_ranking"]["routes"]["r1"]["cost_per_unit"] == "42.10"


@pytest.mark.parametrize("key", ["structured_tz", "literature_analysis", "synthesis_routes", "qualified_routes", "economics_ranking"])
def test_missing_required_inputs_do_not_send(client, key):
    ctx = context()
    del ctx.state[key]
    assert asyncio.run(adapter.optimization_start(ctx))["state"] == "invalid_input"
    client.send_message.assert_not_called()
    # A local validation failure can be corrected without creating a new session.
    ctx.state[key] = inputs()[key]
    assert asyncio.run(adapter.optimization_start(ctx))["state"] == "submitted"


@pytest.mark.parametrize("field,value", [
    ("rank", None), ("rank", True), ("currency", "USD"),
    ("cost_per_unit", "NaN"), ("cost_per_unit", "-1"),
    ("cost_packs", None), ("status", "invalid"), ("stub", True),
])
def test_unusable_ranking_is_rejected(field, value):
    data = inputs()
    data["economics_ranking"]["routes"]["r1"][field] = value
    with pytest.raises(ValueError):
        prepare_inputs(data)


def test_route_ids_and_non_stub_steps_are_required():
    for mutate in (
        lambda d: d["economics_ranking"]["routes"].update({"unknown": {}}),
        lambda d: d["synthesis_routes"]["routes"][0].update(stub=True),
        lambda d: d["synthesis_routes"]["routes"][0].update(steps=[]),
        lambda d: d["synthesis_routes"]["routes"].append(copy.deepcopy(d["synthesis_routes"]["routes"][0])),
    ):
        data = inputs()
        mutate(data)
        with pytest.raises(ValueError):
            prepare_inputs(data)


def test_json_state_values_are_supported_without_changing_numbers():
    data = inputs()
    for key in ("literature_analysis", "synthesis_routes", "qualified_routes", "economics_ranking"):
        data[key] = json.dumps(data[key])
    assert prepare_inputs(data) == prepare_inputs(inputs())


def test_handoff_sends_only_what_an_experiment_is_planned_from():
    data = inputs()
    data["structured_tz"] = {"original_request": "1 г присадки", "blocks": [
        {"title": "Критерии качества", "usage": "internal note", "fields": [
            {"name": "Минимальная чистота", "value": "не ниже 80 %", "status": "задано заказчиком"},
            {"name": "Допустимые примеси", "value": "Не требуется — без ограничения", "status": "не требуется"},
            {"name": "Масса образца", "value": "1 г", "status": "задано заказчиком"}]},
        {"title": "Масштаб результата", "usage": "internal note", "fields": [
            {"name": "Масса образца", "value": "1 г", "status": "задано заказчиком"},
            {"name": "Масштаб следующей проверки", "value": "Не требуется — без ограничения",
             "status": "не требуется"}]},
    ]}
    for routes in (data["synthesis_routes"]["routes"], data["qualified_routes"]["routes"]):
        routes[0]["flow_suitability"] = "flow note"
        routes[0]["selection_rationale"] = "why this route"
        routes[0]["steps"][0]["flow_notes"] = "flow note"
        routes[0]["steps"][0]["evidence"] = [{"source_id": "S1", "quote": "q"}]
    handoff = prepare_inputs(data)

    assert set(handoff) == {"tz", "routes", "economics_ranking"}  # no literature, no economics prose
    assert handoff["tz"] == {"original_request": "1 г присадки", "requirements": {
        "Критерии качества": {"Минимальная чистота": "не ниже 80 %", "Масса образца": "1 г"}}}
    [route] = handoff["routes"]
    assert route["flow_suitability"] == "flow note"
    assert set(route) >= {"route_id", "product", "steps"} and "selection_rationale" not in route
    [step] = route["steps"]
    assert step["conditions"] == [{"name": "Среда", "value": "water"}] and step["yield_fraction"] == 0.8
    assert "flow_notes" not in step and "evidence" not in step


def test_empty_tz_is_not_sent():
    data = inputs()
    data["structured_tz"] = {"original_request": "", "blocks": [{"title": "Сырьё", "fields": [
        {"name": "Растворители", "value": "Не требуется — без ограничения", "status": "не требуется"}]}]}
    with pytest.raises(ValueError, match="structured_tz"):
        prepare_inputs(data)


def test_screening_handoff_accepts_real_experimental_route_without_costing(client):
    data = inputs()
    route = data["synthesis_routes"]["routes"][0]
    route["overall_status"] = "experimental"
    route["steps"][0].pop("yield_fraction")
    route["steps"][0]["yield_status"] = "missing"
    route["steps"][0]["yield_missing_reason"] = "Выход должен быть измерен"
    data["qualified_routes"] = {
        "status": "screening_only", "routes": [], "experimental_routes": [copy.deepcopy(route)],
    }
    del data["economics_ranking"]
    handoff = prepare_inputs(data, planning_only=True)
    assert handoff["handoff_mode"] == "screening"
    assert [route["route_id"] for route in handoff["routes"]] == ["r1"]
    assert "economics_ranking" not in handoff

    ctx = SimpleNamespace(state=data)
    asyncio.run(adapter.optimization_start(ctx, planning_only=True))
    text = client.send_message.call_args.kwargs["text"]
    assert "СКРИНИНГА" in text
    assert '"handoff_mode": "screening"' in text


def test_production_handoff_rejects_screening_only_route_without_costing():
    data = inputs()
    route = data["synthesis_routes"]["routes"][0]
    route["overall_status"] = "experimental"
    data["qualified_routes"] = {
        "status": "screening_only", "routes": [], "experimental_routes": [copy.deepcopy(route)],
    }
    del data["economics_ranking"]
    with pytest.raises(ValueError):
        prepare_inputs(data)


def test_wire_contract_preserves_role_and_domain(monkeypatch):
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


def test_approval_continues_same_task_then_final_results_go_to_report(client):
    ctx = context()
    initial = asyncio.run(adapter.optimization_start(ctx))
    client.get_task.return_value = response("TASK_STATE_INPUT_REQUIRED", phase="approval")
    asyncio.run(adapter.optimization_get_status(ctx))
    client.send_message.return_value = response("TASK_STATE_WORKING")
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "working"
    sent = client.send_message.call_args.kwargs
    assert sent["task_id"] == initial["task_id"]
    assert sent["context_id"] == initial["context_id"]
    assert sent["experiment_id"] == initial["experiment_id"]
    assert sent["message_id"] != initial["message_id"]
    final = response("TASK_STATE_COMPLETED", artifacts=[{"artifactId": "last-result", "parts": [{"data": {
        "measured": 8.2, "unit": "bar", "last_experiment": "exp-last", "cfd_status": "failed",
    }}]}])
    client.get_task.return_value = final
    result = asyncio.run(adapter.optimization_get_status(ctx))
    assert ctx.state[adapter.RESULT_KEY]["task"] == final["result"]["task"]
    assert len(ctx.state[adapter.RESULT_KEY]["responses"]) == 4
    assert asyncio.run(adapter.optimization_start(ctx)) == result
    assert client.send_message.call_count == 2  # completion never creates another task
    assert "experiment_plan" not in ctx.state and "experiment_journal" not in ctx.state


def test_approval_sends_the_bare_execution_token(client):
    """Prose is read as a clarification and re-plans; only "Approve" executes."""
    ctx = context()
    client.send_message.return_value = response("input_required", phase="approval")
    asyncio.run(adapter.optimization_start(ctx))
    client.send_message.return_value = response("working")
    asyncio.run(adapter.optimization_approve(ctx))
    assert client.send_message.call_args.kwargs["text"] == "Approve"


def test_rebuilt_plan_is_not_approved_again_until_a_step_runs(client):
    ctx = context()
    client.send_message.return_value = response("input_required", phase="approval", steps=0)
    asyncio.run(adapter.optimization_start(ctx))
    client.send_message.return_value = response("working")
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "working"
    # The remote answers the confirmation with a fresh design, nothing executed.
    client.get_task.return_value = response(
        "input_required", phase="approval", steps=0, artifacts=[{"parts": [{"data": {"design": 2}}]}])
    asyncio.run(adapter.optimization_get_status(ctx))
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "error"
    assert client.send_message.call_count == 2
    # A plan revised after real progress stays approvable.
    client.get_task.return_value = response(
        "input_required", phase="approval", steps=3, artifacts=[{"parts": [{"data": {"design": 3}}]}])
    asyncio.run(adapter.optimization_get_status(ctx))
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "working"
    assert client.send_message.call_count == 3


def test_clarification_continues_waiting_task(client):
    ctx = context()
    client.send_message.return_value = response("input-required", phase="waiting_input")
    initial = asyncio.run(adapter.optimization_start(ctx))
    client.send_message.return_value = response("working")
    asyncio.run(adapter.optimization_provide_input("Temperature is 25 C per TZ", ctx))
    sent = client.send_message.call_args.kwargs
    assert sent["task_id"] == initial["task_id"]
    assert sent["experiment_id"] == initial["experiment_id"]
    assert sent["context_id"] == initial["context_id"]


def test_planning_only_never_approves_and_is_sticky(client):
    ctx = context()
    client.send_message.return_value = response("input_required", phase="approval")
    asyncio.run(adapter.optimization_start(ctx, planning_only=True))
    assert "РЕЖИМ ТОЛЬКО ПЛАНИРОВАНИЯ" in client.send_message.call_args.kwargs["text"]
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "error"
    assert asyncio.run(adapter.optimization_start(ctx, planning_only=False))["planning_only"]
    client.send_message.assert_called_once()


@pytest.mark.parametrize("state", ["working", "completed", "failed", "canceled", "rejected"])
def test_approval_only_at_approval_phase(client, state):
    ctx = context()
    client.send_message.return_value = response(state)
    asyncio.run(adapter.optimization_start(ctx))
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "error"
    assert asyncio.run(adapter.optimization_provide_input("arbitrary", ctx))["state"] == "error"
    client.send_message.assert_called_once()


def test_timeout_after_approval_polls_same_task_without_duplicate_approval(client):
    ctx = context()
    ready = response("input_required", phase="approval")
    client.send_message.return_value = ready
    asyncio.run(adapter.optimization_start(ctx))
    client.send_message.side_effect = A2ARequestError("timeout after server accepted")
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "followup_unknown"
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "error"
    client.get_task.return_value = ready  # even a stale approval response cannot replay the command
    asyncio.run(adapter.optimization_get_status(ctx))
    assert asyncio.run(adapter.optimization_approve(ctx))["state"] == "error"
    assert client.send_message.call_count == 2
    client.get_task.assert_called_once_with("task-1")


def test_ambiguous_submission_never_retries(client):
    ctx = context()
    client.send_message.side_effect = A2ARequestError("timeout")
    first = asyncio.run(adapter.optimization_start(ctx))
    assert first["state"] == "submission_unknown"
    assert asyncio.run(adapter.optimization_start(ctx)) == first
    client.send_message.assert_called_once()


@pytest.mark.parametrize("bad", [
    {"result": []}, {"result": {"id": "t", "status": {}}}, response("unknown"),
    {"result": {"id": "t", "status": {"state": "completed", "message": "bad"}}},
    response("completed", artifacts=["bad artifact"]),
])
def test_malformed_response_preserved_as_error(client, bad):
    client.send_message.return_value = bad
    ctx = context()
    result = asyncio.run(adapter.optimization_start(ctx))
    assert result["state"] == "submission_unknown"
    assert result["error_response"] == bad


def test_foreign_task_rejected_and_partial_artifacts_preserved(client):
    ctx = context()
    initial = response(artifacts=[{"artifactId": "partial", "parts": [{"text": "partial raw result"}]}])
    client.send_message.return_value = initial
    asyncio.run(adapter.optimization_start(ctx))
    client.get_task.return_value = response("completed", task_id="foreign")
    assert asyncio.run(adapter.optimization_get_status(ctx))["state"] == "status_error"
    client.get_task.return_value = response("failed")
    asyncio.run(adapter.optimization_get_status(ctx))
    assert ctx.state[adapter.RESULT_KEY]["responses"][0] == initial
    assert ctx.state[adapter.RESULT_KEY]["state"] == "failed"


def test_sessions_isolated(client):
    one, two = context(), context()
    a = asyncio.run(adapter.optimization_start(one))
    b = asyncio.run(adapter.optimization_start(two))
    assert a["context_id"] != b["context_id"]
    assert a["experiment_id"] != b["experiment_id"]
    assert len(one.state[adapter.HISTORY_KEY]) == len(two.state[adapter.HISTORY_KEY]) == 1


def test_graph_delegates_entire_experimental_subsystem():
    agents = yaml.safe_load((ROOT / "CoScientist/agents/microfluidics.yaml").read_text())["agents"]
    assert agents["ModuleC_Reactor"]["children"] == ["ReactorAgent"]
    assert not {"ExperimentLoop", "EquipmentAgent", "ExpPlannerAgent"}.intersection(agents)
    assert agents["ReactorAgent"]["output_key"] == "optimization_summary"
    assert agents["ReactorAgent"]["work_order_step_review"]
    for agent in agents.values():
        assert not {"cfd_mcp", "cfd_mcp_stub", "rig_mcp_stub", "microfluidics", "finish_optimization"}.intersection(agent.get("tools", []))


def test_route_selection_has_no_duplicate_hitl_gate():
    agents = yaml.safe_load((ROOT / "CoScientist/agents/microfluidics.yaml").read_text())["agents"]
    assert agents["RootOrchestrator"]["hitl"] is True
    assert agents["RouteSelectionAgent"].get("hitl") is not True


def test_route_selection_commits_output_before_finalization():
    from CoScientist.microfluidics.route_selection import _commit_selection_output

    state = {}
    _commit_selection_output(state, '{"decisions": [], "selection_reason": "automatic"}')
    assert state["route_selection"]["selection_reason"] == "automatic"


def test_registry_and_report_read_original_service_results():
    from CoScientist.assembly import bindings  # noqa: F401
    from CoScientist.agents.prompts.templates import microfluidics_optimizer, microfluidics_report
    from CoScientist.assembly.registry import REGISTRY
    from CoScientist.hitl.work_order_risk import Tier, tool_tier

    entry = REGISTRY.tool("optimization_a2a")
    assert {tool.__name__ for tool in entry.factory()} == {doc.name for doc in entry.resolved_docs()}
    for name in ("optimization_start", "optimization_provide_input", "optimization_approve"):
        assert tool_tier(name) == Tier.SIDE_EFFECT
    ctx = SimpleNamespace(render_tools=lambda: "", render_hitl=lambda: "")
    assert "optimization_approve" in microfluidics_optimizer(ctx)
    report = microfluidics_report(ctx)
    assert "{optimization_result?}" in report and "{optimization_a2a_runs?}" in report
    assert "{experiment_journal?}" not in report
"""