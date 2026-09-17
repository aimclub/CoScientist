"""EconomicsAgent on the real economics server: the documented tool surface, the
risk tiers, the prompt branch, and the numbers kept from the server's answers.

The answers are the ones recorded from the live server
(scripts/mcp_contract_dump.py -> tests/fixtures/economics_mcp/).
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import CoScientist.assembly.bindings  # noqa: F401 — registers the tools
from CoScientist.assembly.registry import REGISTRY
from CoScientist.hitl.work_order_risk import Tier, tool_tier
from CoScientist.microfluidics.economics import (
    collect_economics_result,
    structured_result,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "economics_mcp"
ECONOMICS_TOOLS = {
    "search_reagents_by_name", "get_price", "search_by_structure",
    "resolve_chemicals", "estimate_synthesis_cost", "rank_routes_by_cost",
}


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _call(tool, args, response, state):
    collect_economics_result(
        tool=SimpleNamespace(name=tool), args=args,
        tool_context=SimpleNamespace(state=state), tool_response=response,
    )


# ── Tool surface ─────────────────────────────────────────────────────────────

def test_documented_tools_are_the_filtered_ones():
    from CoScientist.tools.research_tools import ECONOMICS_MCP_TOOLS

    documented = {d.name for d in REGISTRY.tool("economics_mcp").resolved_docs()}
    assert documented == set(ECONOMICS_MCP_TOOLS) == ECONOMICS_TOOLS


def test_documented_tools_exist_on_the_recorded_server():
    recorded = {t["name"] for t in _fixture("tools")}
    assert ECONOMICS_TOOLS <= recorded


def test_documented_required_arguments_match_the_server():
    schemas = {t["name"]: t["inputSchema"] for t in _fixture("tools")}
    docs = {d.name: d.signature for d in REGISTRY.tool("economics_mcp").resolved_docs()}
    for name, schema in schemas.items():
        if name not in docs:
            continue
        for required in schema.get("required", []):
            assert required in docs[name], f"{name}: {required} missing from the signature"


def test_no_single_identifier_braces_in_the_docs():
    """ADK injects {identifier} from session state: a doc must never contain one."""
    import re

    for doc in REGISTRY.tool("economics_mcp").resolved_docs():
        text = " ".join([doc.signature, doc.purpose, *doc.usage])
        assert not re.search(r"\{\s*[A-Za-z_][A-Za-z0-9_]*\??\s*\}", text), doc.name


def test_tiers():
    for name in ECONOMICS_TOOLS:
        assert tool_tier(name) is Tier.READ
    assert tool_tier("rig_mcp_stub") is Tier.SIDE_EFFECT
    assert tool_tier("cfd_mcp_stub") is Tier.COMPUTE


# ── Answers ──────────────────────────────────────────────────────────────────

def test_structured_result_reads_the_recorded_answers():
    assert "routes" in structured_result(_fixture("rank_routes_by_cost_smiles"))
    assert structured_result(_fixture("resolve_chemicals_error")) is None
    assert structured_result({"error": "MCP tool execution failed: timeout"}) is None


def test_structured_result_falls_back_to_the_text_content():
    answer = {"content": [{"type": "text", "text": json.dumps({"routes": []})}], "isError": False}
    assert structured_result(answer) == {"routes": []}


def test_a_priced_ranking_is_kept():
    state = {}
    args = {"routes": [{"route_id": "SDS-2"}], "target_qty": 100, "target_unit": "g"}
    _call("rank_routes_by_cost", args, _fixture("rank_routes_by_cost_smiles"), state)

    ranking = state["economics_ranking"]
    assert (ranking["target_qty"], ranking["target_unit"]) == (100, "g")
    route = ranking["routes"]["SDS-2"]
    assert route["status"] == "partial"
    assert route["currency"] == "RUB"
    assert route["cost_per_unit"] == "1748.31"
    assert route["missing"] == [{"smiles": "O=S(=O)(O)Cl", "reason": "no_match"}]
    assert state["economics_raw"]["routes"][0]["estimate"]["line_items"]


def test_an_invalid_route_is_kept_with_its_reasons():
    state = {}
    _call("rank_routes_by_cost", {"target_qty": 100, "target_unit": "g"},
          _fixture("rank_routes_by_cost"), state)
    route = state["economics_ranking"]["routes"]["SDS-1"]
    assert route["status"] == "invalid"
    assert route["cost_per_unit"] is None
    assert route["warnings"]


def test_a_recalculated_route_replaces_the_old_entry():
    state = {}
    _call("rank_routes_by_cost", {"target_qty": 100, "target_unit": "g"},
          _fixture("rank_routes_by_cost"), state)
    fixed = _fixture("rank_routes_by_cost_smiles")
    fixed["structuredContent"]["routes"][0]["route_id"] = "SDS-1"
    _call("rank_routes_by_cost", {"target_qty": 100, "target_unit": "g"}, fixed, state)
    assert state["economics_ranking"]["routes"]["SDS-1"]["status"] == "partial"


def test_estimates_accumulate():
    state = {}
    args = {"reagents": [{"name": "глицерин", "qty": 100, "unit": "g"}]}
    _call("estimate_synthesis_cost", args, _fixture("estimate_synthesis_cost"), state)
    _call("estimate_synthesis_cost", args, _fixture("estimate_synthesis_cost"), state)
    estimates = state["economics_estimates"]
    assert len(estimates) == 2
    assert estimates[0]["total_by_currency"]["RUB"]["packs"] == "64000.00"


def test_errors_and_lookups_change_nothing():
    state = {}
    _call("rank_routes_by_cost", {}, _fixture("resolve_chemicals_error"), state)
    _call("get_price", {"name": "ацетон"}, _fixture("get_price"), state)
    assert state == {}


# ── Prompt ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("server", [True, False])
def test_prompt_follows_the_attached_tools(server):
    from CoScientist.assembly.prompting import PromptContext
    from CoScientist.assembly.schema import load_config, resolve_config_path

    system = load_config(resolve_config_path("microfluidics"))
    key = "economics_mcp" if server else "economics_mcp_stub"
    ctx = PromptContext(
        config=system.agent("EconomicsAgent"), system=system,
        tool_entries=[REGISTRY.tool(key)],
    )
    text = REGISTRY.prompt("microfluidics_economics")(ctx)
    assert ("rank_routes_by_cost" in text) is server
    assert ("economics_mcp_stub" in text) is not server
    assert "<<" not in text
