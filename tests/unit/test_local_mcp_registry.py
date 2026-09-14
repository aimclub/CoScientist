"""Contract tests for the PostgreSQL-free local MCP registry."""

import asyncio
import importlib
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path

from CoScientist.tools.local_mcp_registry import LOCAL_MCP_TOOLS, local_servers


EXPECTED_SERVERS = {
    "papers-search",
    "chemical",
    "dataset-collection",
    "paper-analysis",
}

EXPECTED_TOOLS = {
    "search_entity",
    "search_papers",
    "download_papers_from_search",
    "fetch_activity_data",
    "name2smiles",
    "smiles2name",
    "smiles2prop",
    "visualize_molecule",
    "extract_reactions",
    "extract_molecules",
    "calculate_docking",
    "retrosynthesis_tree_search",
    "classify_reaction",
    "forward_predict",
    "extract_mols_prop_dataset",
    "explore_chemistry_database",
    "explore_my_papers",
}


def test_local_registry_matches_the_four_compose_mcp_servers():
    assert {server.server_id for server in local_servers()} == EXPECTED_SERVERS
    assert all(server.url.endswith("/mcp") for server in local_servers())


def test_local_registry_tool_surface_matches_the_mcp_smoke_manifest():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("local_mcp_smoke", root / "scripts" / "check-local-mcp.py")
    assert spec is not None and spec.loader is not None
    smoke_manifest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke_manifest)

    expected = {
        (tool_name, server_id)
        for server_id, server in smoke_manifest.SERVERS.items()
        for tool_name in server["tools"]
    }
    actual = {(tool.tool, tool.server_id) for tool in LOCAL_MCP_TOOLS}

    assert actual == expected


def test_retrieve_tools_returns_all_local_tools_without_postgres():
    from CoScientist.tools.retrieval_tools import retrieval_toolset

    async def scenario():
        result = await retrieval_toolset.retrieve_tools("capital city")

        assert result["status"] == "success"
        assert {item["tool"] for item in result["result"]} == EXPECTED_TOOLS
        assert {item["server_id"] for item in result["result"]} == EXPECTED_SERVERS
        assert result["accumulated_count"] == len(EXPECTED_TOOLS)

    asyncio.run(scenario())


def test_retrieve_tools_accumulates_without_duplicate_local_tools():
    from CoScientist.tools.retrieval_tools import retrieval_toolset

    async def scenario():
        context = SimpleNamespace(state={"accumulated_tools": [{"tool": "search_papers"}]})

        result = await retrieval_toolset.retrieve_tools("literature", tool_context=context)

        assert result["status"] == "success"
        assert result["accumulated_count"] == len(EXPECTED_TOOLS)
        assert [item["tool"] for item in context.state["accumulated_tools"]].count("search_papers") == 1
        assert context.state["retrieval_queries"] == ["literature"]

    asyncio.run(scenario())


def test_get_server_info_resolves_a_static_local_server():
    from CoScientist.tools.retrieval_tools import retrieval_toolset

    async def scenario():
        result = await retrieval_toolset.get_server_info("chemical")

        assert result["status"] == "success"
        assert result["result"].server_id == "chemical"
        assert result["result"].url.endswith("/mcp")

    asyncio.run(scenario())


def test_fedot_tool_resolves_selected_server_without_postgres(monkeypatch):
    captured = {}

    class FakeHttpMCPServer:
        def __init__(self, *, url, description):
            self.url = url
            self.description = description

    class FakeMAS:
        def __init__(self, *, mcp_servers, **kwargs):
            captured["servers"] = mcp_servers
            captured["plugins"] = kwargs.get("plugins")

        async def run(self, task_description, **kwargs):
            return {"task": task_description}

    fake_fedotmas = ModuleType("fedotmas")
    fake_fedotmas.MAS = FakeMAS
    fake_fedotmas.HttpMCPServer = FakeHttpMCPServer
    monkeypatch.setitem(sys.modules, "fedotmas", fake_fedotmas)
    sys.modules.pop("CoScientist.tools.fedotmas_tools", None)
    try:
        module = importlib.import_module("CoScientist.tools.fedotmas_tools")

        async def scenario():
            result = await module.FedotMASToolset().fedot_tool(
                "Calculate a molecular property",
                tool_context=SimpleNamespace(state={"filtered_tools": [{"server_id": "chemical"}]}),
            )

            assert result["status"] == "success"
            assert captured["servers"]["chemical"].url == "http://chemical-mcp-server:7331/mcp"
            assert captured["plugins"]

        asyncio.run(scenario())
    finally:
        sys.modules.pop("CoScientist.tools.fedotmas_tools", None)
