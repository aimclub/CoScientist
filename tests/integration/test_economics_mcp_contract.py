"""Live contract of the economics MCP server — what EconomicsAgent relies on.

The agent's tool docs (assembly/bindings.py: economics_mcp), its prompt and the
state collector (microfluidics/economics.py) were written against the answers
recorded in tests/fixtures/economics_mcp/. This checks the live server still
gives them: the six tools with their required arguments, English names that
resolve, and a costed route of the recorded shape.

Needs MCP_MICROFLUIDIC_ECONOMIC in .env and the network that reaches it;
skipped otherwise. Run from the repo root:

    pytest tests/integration/test_economics_mcp_contract.py -q -s
"""
import asyncio
import os

import pytest
from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("MCP_MICROFLUIDIC_ECONOMIC")
pytestmark = pytest.mark.skipif(not URL, reason="MCP_MICROFLUIDIC_ECONOMIC is not set")

REQUIRED = {
    "search_reagents_by_name": {"query"},
    "get_price": {"name"},
    "search_by_structure": set(),
    "resolve_chemicals": {"names"},
    "estimate_synthesis_cost": {"reagents"},
    "rank_routes_by_cost": {"routes"},
}

SDS_ROUTE = {
    "route_id": "SDS",
    "steps": [
        {"reactants": [{"smiles": "CCCCCCCCCCCCO"}, {"smiles": "OS(=O)(=O)Cl"}],
         "products": [{"smiles": "CCCCCCCCCCCCOS(=O)(=O)O"}], "yield": 0.9},
        {"reactants": ["@prev", {"smiles": "[Na+].[OH-]"}],
         "products": [{"smiles": "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]"}], "yield": 0.95},
    ],
}


async def _session_calls(calls):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(URL, timeout=30, sse_read_timeout=600) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            results = [await session.call_tool(name, args) for name, args in calls]
            return tools, results


def _run(calls=()):
    try:
        return asyncio.run(_session_calls(list(calls)))
    except OSError as exc:  # unreachable from here (no VPN) — not a contract failure
        pytest.skip(f"economics server unreachable: {exc}")


def test_tools_and_required_arguments():
    tools, _ = _run()
    schemas = {t.name: t.inputSchema for t in tools}
    for name, required in REQUIRED.items():
        assert name in schemas, f"the server has no {name}"
        assert set(schemas[name].get("required", [])) == required, name


def test_english_names_resolve():
    _, (result,) = _run([("resolve_chemicals", {"names": ["1-dodecanol", "chlorosulfonic acid"]})])
    assert not result.isError
    items = result.structuredContent["items"]
    assert all(i["canonical_smiles"] and not i["error"] for i in items), items


def test_a_route_by_structure_is_costed():
    _, (result,) = _run([("rank_routes_by_cost", {
        "routes": [SDS_ROUTE], "target_qty": 100, "target_unit": "g",
        "include_breakdown": True,
    })])
    assert not result.isError
    route = result.structuredContent["routes"][0]
    assert route["route_id"] == "SDS"
    assert route["status"] in {"ok", "partial"}
    assert route["currency"] and route["cost_per_unit"] is not None
    assert {"smiles", "qty", "unit"} <= set(route["starting_materials"][0])
    assert "line_items" in route["estimate"]


def test_an_error_is_an_is_error_answer():
    _, (result,) = _run([("resolve_chemicals", {"names": []})])
    assert result.isError
    assert "resolve_chemicals" in result.content[0].text
