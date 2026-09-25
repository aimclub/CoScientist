"""Plan-bound MCP tools must be the only tools FEDOT/ReAct can call."""
from __future__ import annotations

from types import SimpleNamespace

from CoScientist.tools.fedot_mas_patch import (
    _ALLOWED_MCP_TOOLS,
    allowed_mcp_tools_scope,
    append_bound_mcp_tools,
    bound_mcp_tool_names,
)


def test_bound_mcp_tool_names_from_filtered_tools():
    names = bound_mcp_tool_names([
        {"tool": "generate_mols", "server_id": "srv"},
        {"name": "calculate_docking", "server_id": "dock"},
        {"server_id": "x"},
    ])
    assert names == frozenset({"generate_mols", "calculate_docking"})


def test_append_bound_mcp_tools_lists_only_plan_tools():
    text = append_bound_mcp_tools("Generate candidates.", {"generate_mols"})
    assert "generate_mols" in text
    assert "generate_case_mols" not in text
    assert "out of scope" in text


def test_allowlist_scope_sets_and_resets_filter():
    ts = SimpleNamespace(tool_filter=None)
    with allowed_mcp_tools_scope({"generate_mols"}):
        allowed = _ALLOWED_MCP_TOOLS.get()
        assert allowed == frozenset({"generate_mols"})
        ts.tool_filter = sorted(allowed)
    assert ts.tool_filter == ["generate_mols"]
    assert _ALLOWED_MCP_TOOLS.get() is None
