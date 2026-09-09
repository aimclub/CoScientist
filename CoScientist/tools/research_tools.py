"""Tools for websearch / literature research (MCP toolsets)."""
from typing import Any, Callable, Optional

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

from CoScientist.config import get_settings
from CoScientist.utils.selective_proxy import create_mcp_proxy_httpx_factory

settings = get_settings()
PAPER_ANALYSIS_URL = settings.mcp.paper_analysis_url
PAPERS_SEARCH_URL = settings.mcp.papers_search_url
VAULT_URL = settings.mcp.vault_url
MICROFLUIDICS_URL = settings.mcp.microfluidics_url


_PAPER_ANALYSIS_TIMEOUT = 60 * 15.0  # 30 min — processing many PDFs is slow

def _http_mcp_toolset(
    url: Optional[str],
    sse_read_timeout: float = 60 * 5.0,
    headers: Optional[dict] = None,
    tool_filter: Optional[list] = None,
    httpx_client_factory: Optional[Callable] = None,
) -> Optional[McpToolset]:
    """Build an HTTP MCP toolset, or None when the URL is not configured.

    Returning None (instead of crashing at import on a missing URL) lets the app
    start without these optional services; the ResearchAgent simply runs without
    the corresponding toolset. Set the URLs in .env to enable them.

    ``tool_filter`` names the tools to keep. A server may expose more than an
    agent should see (see the vault below).
    """
    if not url:
        return None
    conn_kwargs: dict[str, Any] = {
        "url": url,
        "sse_read_timeout": sse_read_timeout,
        "headers": headers or {},
    }
    if httpx_client_factory is not None:
        conn_kwargs["httpx_client_factory"] = httpx_client_factory
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(**conn_kwargs),
        tool_filter=tool_filter,
    )


# ---------------------------------------------------------------------------
# Tavily websearch — optionally proxied via SERVICES__PROXY_URL
# ---------------------------------------------------------------------------
_tavily_conn_kwargs: dict[str, Any] = {
    "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={settings.services.tavily_api_key}",
}

if settings.services.proxy_url:
    _tavily_conn_kwargs["httpx_client_factory"] = create_mcp_proxy_httpx_factory(
        settings.services.proxy_url,
        enabled_fn=get_settings().web.use_proxy,
    )

websearch_toolset_instance = McpToolset(
    connection_params=StreamableHTTPConnectionParams(**_tavily_conn_kwargs),
)

# ---------------------------------------------------------------------------
# Microfluidics MCP server — Bearer-token auth, optionally proxied
# (MCP__MICROFLUIDICS_URL / MCP__MICROFLUIDICS_API_KEY in .env).
# ---------------------------------------------------------------------------
_microfluidics_headers = (
    {"Authorization": f"Bearer {settings.mcp.microfluidics_api_key}"}
    if settings.mcp.microfluidics_api_key
    else {}
)

microfluidics_toolset_instance = _http_mcp_toolset(
    MICROFLUIDICS_URL,
    headers=_microfluidics_headers,
    httpx_client_factory=(
        create_mcp_proxy_httpx_factory(
            settings.services.proxy_url,
            enabled_fn=settings.web.use_proxy,
        )
        if settings.services.proxy_url
        else None
    ),
)

# Optional paper-analysis / paper-search MCP servers — only built when configured
# (MCP__PAPER_ANALYSIS_URL / MCP__PAPERS_SEARCH_URL in .env).
paper_analysis_toolset_instance = _http_mcp_toolset(PAPER_ANALYSIS_URL, sse_read_timeout=_PAPER_ANALYSIS_TIMEOUT)

# Per-user OpenAlex credentials forwarded as HTTP headers so the shared remote
# container uses each caller's own rate-limit quota instead of the server's env.
_openalex_headers = {
    k: v
    for k, v in {
        "x-openalex-email": settings.services.openalex_email,
        "x-openalex-api-key": settings.services.openalex_api_key,
    }.items()
    if v
}
papers_search_toolset_instance = _http_mcp_toolset(PAPERS_SEARCH_URL, headers=_openalex_headers)


# ---------------------------------------------------------------------------
# The file vault — worker surface only
# ---------------------------------------------------------------------------
# The server also exposes promote_artifact, cleanup_session,
# update_artifact_metadata, get_session_manifest and list_artifacts. Those are
# framework tools: they promote, delete, or read across a whole session. An
# agent gets the two that move one file, and nothing else. Framework code calls
# the rest through tools/vault_client.py, which does not go through an agent.
#
# get_upload_link and get_download_link both declare user_id / session_id, so
# SessionScopePlugin fills them at the tool boundary and the model never
# supplies a scope.
VAULT_WORKER_TOOLS = ["get_upload_link", "get_download_link"]

vault_toolset_instance = _http_mcp_toolset(VAULT_URL, tool_filter=VAULT_WORKER_TOOLS)
