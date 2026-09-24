"""The rig campaign A2A block before optimization. Offline: never contacts services."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from CoScientist.microfluidics.a2a_optimization import adapter, campaign
from CoScientist.microfluidics.a2a_optimization.contracts import prepare_inputs

ROOT = Path(__file__).resolve().parents[2]

CAMPAIGN_RESULT = {
    "route_id": "RTE-1",
    "stop_reason": "budget",
    "best": {"params": {"molar_ratio": 3, "temperature_c": 25}, "objective_value": 0.9977,
             "objective_std": 0, "replicates": 0, "target_reached": True, "nmr": None},
    "recipe": {"topology_id": "knoevenagel/1", "batch": None,
               "feed_concentrations": {"O=C1CC(=O)NC(=O)N1": 2, "COc1cc(C=O)ccc1O": 6},
               "feed_units": None,
               "stages": [{"stage_id": 1, "flows": [{"channel": 0, "flow_ul_min": 117.647}]}]},
    "flags": [
        {"code": "not_converged", "severity": "warning", "message": "..."},
        {"code": "no_physical_confirmation", "severity": "blocker", "message": "..."},
    ],
}


def inputs():
    route = {
        "route_id": "RTE-1", "product": {"name": "fixture"}, "overall_status": "eligible",
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
        "economics_ranking": {"target_qty": 100, "target_unit": "g",
            "preferred_currency": "RUB", "rank_by": "per_unit", "routes": {
                "RTE-1": {"status": "ok", "rank": 1, "currency": "RUB",
                          "cost_per_unit": "42.10", "cost_packs": "50.00"},
            }},
    }


def response(state="TASK_STATE_SUBMITTED", *, phase="", artifacts=None):
    task = {"id": "task-1", "status": {"state": state, "message": {"parts": [
        {"text": "service reply"}, {"data": {"phase": phase}},
    ]}}}
    if artifacts is not None:
        task["artifacts"] = artifacts
    return {"jsonrpc": "2.0", "result": {"task": task}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(campaign.URL_ENV, "https://campaign.test/a2a")
    fake = Mock()
    fake.send_message.return_value = response()
    fake.get_task.return_value = response("TASK_STATE_WORKING")
    monkeypatch.setattr(campaign, "_client", lambda: fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def test_sends_the_optimization_handoff_once(client):
    ctx = SimpleNamespace(state=inputs())
    first = run(campaign.campaign_start(ctx))
    assert run(campaign.campaign_start(ctx)) == first
    client.send_message.assert_called_once()
    call = client.send_message.call_args.kwargs
    assert json.loads(call["text"].split("\n\n", 1)[1]) == prepare_inputs(inputs())
    assert first["experiment_id"].startswith("campaign-")
    # The campaign has its own task; the optimizer's is untouched.
    assert adapter.ACTIVE_KEY not in ctx.state and adapter.RESULT_KEY not in ctx.state
    # Nothing to report while the task is only submitted.
    assert campaign.RESULT_KEY not in ctx.state


def test_unset_url_sends_nothing(client, monkeypatch):
    monkeypatch.delenv(campaign.URL_ENV)
    ctx = SimpleNamespace(state=inputs())
    assert run(campaign.campaign_start(ctx))["state"] == "not_configured"
    assert campaign.ACTIVE_KEY not in ctx.state
    client.send_message.assert_not_called()


def test_invalid_input_is_not_sent(client):
    ctx = SimpleNamespace(state=inputs())
    del ctx.state["qualified_routes"]
    assert run(campaign.campaign_start(ctx))["state"] == "invalid_input"
    assert ctx.state[campaign.INPUT_ERROR_KEY]["state"] == "invalid_input"
    client.send_message.assert_not_called()


@pytest.mark.parametrize("part", [
    {"data": {"campaign_result": CAMPAIGN_RESULT}},
    {"data": CAMPAIGN_RESULT},
    {"text": json.dumps({"campaign_result": CAMPAIGN_RESULT})},
    {"data": {"optimization": {"current": {"status": "completed", "raw": CAMPAIGN_RESULT}}}},
])
def test_completed_result_is_normalized(client, part):
    ctx = SimpleNamespace(state=inputs())
    run(campaign.campaign_start(ctx))
    client.get_task.return_value = response("TASK_STATE_COMPLETED", artifacts=[{"parts": [part]}])
    record = run(campaign.campaign_get_status(ctx))
    assert record["state"] == "completed"

    result = ctx.state[campaign.RESULT_KEY]
    current = result["current"]
    assert current["experiment_id"] == record["experiment_id"]
    assert current["context_id"] == record["context_id"]
    assert current["task_id"] == "task-1"
    assert current["route_id"] == "RTE-1"
    assert current["a2a_state"] == "TASK_STATE_COMPLETED"
    assert current["status"] == "completed"
    assert current["stop_reason"] == "budget"
    assert current["best"] == CAMPAIGN_RESULT["best"]
    assert current["recipe"] == CAMPAIGN_RESULT["recipe"]
    assert current["flags"] == CAMPAIGN_RESULT["flags"]
    assert current["raw"] == CAMPAIGN_RESULT
    assert current["received_at"]
    assert result["history"] == [{k: v for k, v in current.items() if k != "raw"}]
    assert result["has_blockers"] is True


def test_failed_task_without_result_is_still_reported(client):
    ctx = SimpleNamespace(state=inputs())
    run(campaign.campaign_start(ctx))
    client.get_task.return_value = response("TASK_STATE_FAILED")
    run(campaign.campaign_get_status(ctx))
    result = ctx.state[campaign.RESULT_KEY]
    assert result["current"]["status"] == "failed"
    assert result["current"]["best"] is None and result["current"]["flags"] == []
    assert result["current"]["route_id"] == "RTE-1"  # the only route handed off
    assert result["has_blockers"] is False


def test_history_grows_only_on_new_results():
    ctx = SimpleNamespace(state={})
    record = {"experiment_id": "campaign-1", "task_id": "task-1", "context_id": "ctx-1",
              "state": "completed", "task": response("TASK_STATE_COMPLETED", artifacts=[
                  {"parts": [{"data": {"campaign_result": CAMPAIGN_RESULT}}]}])["result"]["task"]}
    campaign._publish(ctx, record)
    campaign._publish(ctx, record)
    assert len(ctx.state[campaign.RESULT_KEY]["history"]) == 1
    better = {**CAMPAIGN_RESULT, "flags": []}
    record["task"]["artifacts"] = [{"parts": [{"data": {"campaign_result": better}}]}]
    campaign._publish(ctx, record)
    result = ctx.state[campaign.RESULT_KEY]
    assert len(result["history"]) == 2 and result["has_blockers"] is False
    assert "raw" not in result["history"][0]


def test_approval_sends_the_approve_token(client):
    ctx = SimpleNamespace(state=inputs())
    client.send_message.return_value = response("TASK_STATE_INPUT_REQUIRED", phase="approval")
    run(campaign.campaign_start(ctx))
    client.send_message.return_value = response("TASK_STATE_WORKING")
    assert run(campaign.campaign_approve(ctx))["state"] == "working"
    assert client.send_message.call_args.kwargs["text"] == "Approve"
    assert client.send_message.call_args.kwargs["task_id"] == "task-1"


def test_client_targets_the_endpoint_from_env(monkeypatch):
    monkeypatch.setenv(campaign.URL_ENV, "https://mcp2.rzhevskyrobotics.com/a2a")
    client = campaign._client()
    assert client.base_url + client.rpc_path == "https://mcp2.rzhevskyrobotics.com/a2a"
    assert (client.send_method, client.get_method) == ("SendMessage", "GetTask")
    assert client.headers == {"A2A-Version": "1.0"}


def test_session_agent_keeps_polling_the_campaign():
    from CoScientist.microfluidics.a2a_optimization.session_agent import (
        CampaignSessionAgent,
        OptimizationSessionAgent,
    )

    def feedback(cls, state):
        agent = cls.model_construct()
        return agent._unfinished_feedback(SimpleNamespace(session=SimpleNamespace(state=state)))

    assert "campaign_get_status" in feedback(CampaignSessionAgent, {campaign.ACTIVE_KEY: {"state": "working"}})
    assert feedback(CampaignSessionAgent, {adapter.ACTIVE_KEY: {"state": "working"}}) is None
    assert "optimization_get_status" in feedback(OptimizationSessionAgent, {adapter.ACTIVE_KEY: {"state": "working"}})


def test_campaign_module_is_the_last_before_report():
    from CoScientist.assembly import bindings  # noqa: F401
    from CoScientist.agents.prompts.templates import microfluidics_optimizer, microfluidics_report
    from CoScientist.assembly.registry import REGISTRY
    from CoScientist.hitl.work_order_risk import Tier, tool_tier

    agents = yaml.safe_load((ROOT / "CoScientist/agents/microfluidics.yaml").read_text())["agents"]
    modules = [m for m in agents["RootOrchestrator"]["subordinates"]
               if agents[m].get("enabled", True) is not False]
    assert modules.index("ModuleC_Optimization") + 1 == modules.index("ReportAgent")
    # The reactor module is kept but switched off: the pipeline stops after the campaign.
    assert agents["ModuleC_Reactor"]["enabled"] is False
    assert agents["ModuleC_Optimization"]["children"] == ["OptimizationAgent"]
    entry = REGISTRY.tool("campaign_a2a")
    assert {tool.__name__ for tool in entry.factory()} == {doc.name for doc in entry.resolved_docs()}
    for name in ("campaign_start", "campaign_provide_input", "campaign_approve"):
        assert tool_tier(name) == Tier.SIDE_EFFECT
    ctx = SimpleNamespace(render_tools=lambda: "", render_hitl=lambda: "")
    assert "{optimization?}" in microfluidics_optimizer(ctx)
    assert "{optimization?}" in microfluidics_report(ctx)
