"""chemquote — reagent pricing / synthesis-cost MCP server (real, not a stub).

Replaces the microfluidics economics_mcp_stub (stage 5): a real MCP service
that quotes Russian chemical-supplier price lists by SMILES/structure and
costs synthesis routes against them. See MCP_Economic_model.md at the repo
root for the full tool reference. Set MCP__ECONOMICS_URL in .env to enable —
without it EconomicsAgent simply runs with no tool (see `optional=True` on
its ToolEntry in assembly/bindings.py), same degradation as paper_analysis /
papers_search when their URL is unset.
"""
from typing import Optional

from CoScientist.config import get_settings

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

settings = get_settings()
ECONOMICS_URL = settings.mcp.economics_url


def _http_mcp_toolset(url: Optional[str]) -> Optional[McpToolset]:
    if not url:
        return None
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=url, sse_read_timeout=60 * 2.0)
    )


economics_toolset_instance = _http_mcp_toolset(ECONOMICS_URL)
