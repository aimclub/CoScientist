"""Tools for FEDOT.MAS inference."""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools import BaseTool, ToolContext
from google.adk.tools.base_toolset import BaseToolset

from fedotmas import HttpMCPServer, MAS
from fedotmas.plugins import LoggingPlugin, WebSearchLimitPlugin

try:  # Newer FEDOT.MAS releases provide optional Langfuse telemetry.
    from fedotmas.plugins import LangfusePlugin
except ImportError:  # pragma: no cover - depends on the installed FEDOT.MAS
    LangfusePlugin = None

from CoScientist.logging.metrics import UsageMetricsPlugin
from CoScientist.tools.fedot_artifact_plugin import ArtifactCapturePlugin
from CoScientist.tools.local_mcp_registry import local_server


class FedotMASToolset(BaseToolset):
    """Expose FEDOT.MAS with the MCP servers selected for the current run."""

    def __init__(self, prefix: str = "fedot_"):
        super().__init__()
        self.tool_name_prefix = prefix

    def get_tools(self, readonly_context: Optional[ReadonlyContext]) -> List[BaseTool]:
        return [self.fedot_tool]

    async def close(self) -> None:
        await asyncio.sleep(0)

    async def fedot_tool(
        self, task_description: str, tool_context: ToolContext = None
    ) -> Dict[str, Any]:
        """Generate and execute a FEDOT.MAS pipeline for the requested task."""
        state = tool_context.state if tool_context is not None else {}
        candidates = state.get("filtered_tools") or state.get("accumulated_tools") or []
        server_ids = {
            tool["server_id"]
            for tool in candidates
            if isinstance(tool, dict) and tool.get("server_id")
        }
        servers = [local_server(server_id) for server_id in server_ids]
        servers = [
            server for server in servers
            if server is not None and server.protocol == "http"
        ]
        servers_payload = {
            server.name: HttpMCPServer(url=server.url, description=server.description)
            for server in servers
        }

        # Deployed web MCPs are stored in state as dicts.
        servers_payload.update({
            server["name"]: HttpMCPServer(
                url=server["url"], description=server.get("description", "")
            )
            for server in state.get("deployed_mcps", [])
        })

        capture = ArtifactCapturePlugin()
        timeout_s = None
        if not state.get("filtered_tools") and candidates:
            try:
                from CoScientist.config import get_settings

                timeout_s = get_settings().web.fedot_fallback_timeout_s or None
            except Exception:  # noqa: BLE001 - optional limit must not block execution
                pass

        result = None
        status, error = "success", None
        try:
            plugins = [
                LoggingPlugin(),
                WebSearchLimitPlugin(max_calls_per_agent=4),
                capture,
                UsageMetricsPlugin(),
            ]
            if LangfusePlugin is not None:
                plugins.insert(2, LangfusePlugin(trace_name="coscientist:fedot"))
            mas = MAS(mcp_servers=servers_payload, plugins=plugins)
            result = await mas.run(task_description, timeout=timeout_s)
        except (asyncio.TimeoutError, TimeoutError):
            status, error = "timeout", f"FEDOT.MAS exceeded {timeout_s}s"
        except Exception as exc:  # noqa: BLE001 - return structured tool failure
            status, error = "error", f"FEDOT.MAS run failed: {exc}"

        if result is not None:
            try:
                result_text = json.dumps(result, default=str, ensure_ascii=False)
            except Exception:  # noqa: BLE001
                result_text = str(result)
            known_urls = {artifact.get("url") for artifact in capture.captured}
            for url in dict.fromkeys(
                re.findall(r"https?://[^\s\"'<>)\\]+X-Amz-[^\s\"'<>)\\]+", result_text)
            ):
                if url not in known_urls:
                    capture.captured.append({"url": url, "tool": "fedot_state_scan"})

        if capture.captured and tool_context is not None:
            tool_context.state["fedot_artifacts"] = capture.captured

        response: Dict[str, Any] = {"status": status, "artifacts": capture.captured}
        if result is not None:
            response["result"] = result
        if error:
            response["error"] = error
        return response


fedot_toolset = FedotMASToolset()
fedot_toolset_instance = fedot_toolset.get_tools(None)
