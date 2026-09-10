"""Tools for fedotmas inference"""

import asyncio
import json
import os
import re
from typing import List, Optional, Dict, Any

from google.adk.tools import BaseTool, ToolContext
from google.adk.tools.base_toolset import BaseToolset
from google.adk.agents.readonly_context import ReadonlyContext

from fedotmas import MAS, HttpMCPServer
from fedotmas.plugins import LangfusePlugin, LoggingPlugin, WebSearchLimitPlugin

from CoScientist.logging.metrics import UsageMetricsPlugin
from CoScientist.tools.fedot_artifact_plugin import ArtifactCapturePlugin, merge_artifacts
from CoScientist.tools.fedot_artifact_handoff import (
    bind_upstream_inputs_to_task,
    materialize_tables_from_artifacts,
    record_fedot_producer_tools,
    should_hard_stop_fedot,
    tables_from_state,
)
from CoScientist.tools.fedot_mas_patch import (
    MetaJsonRecoveryPlugin,
    PatchedMAS,
    PatchedMAW,
    ensure_fedot_openai_proxy_compat,
)
from rag_tools import MCPServer
from rag_tools.storage import PostgresClient
from rag_tools.config.settings import get_settings

settings = get_settings()

# Duplicated from tool_callbacks.FEDOT_DELIVERABLE_READY_KEY (avoid import cycle).
_FEDOT_DELIVERABLE_READY_KEY = "fedot_deliverable_ready"


class FedotMASToolset(BaseToolset):
    """Toolset for fedotmas usage"""
    def __init__(self, prefix: str = "fedot_"):
        super().__init__()
        self.tool_name_prefix = prefix

    def get_tools(
        self,
        readonly_context: Optional[ReadonlyContext]
    ) -> List[BaseTool]:

        tools = [self.fedot_tool]
        return tools
        
    async def close(self) -> None:
        await asyncio.sleep(0)  # Placeholder for async cleanup if needed

    async def fedot_tool(self, task_description: str,  tool_context: ToolContext = None) -> Dict[str, Any]:
        """
        Tool for generating and executing multi-agent pipelines via FEDOT.MAS. Use it for experiments completion and calculations
        
        Args:
            task_description: Clear description of the task, including goals,
                            inputs, constraints, and expected outputs.
        
        Returns:
            Result of the executed MAS pipeline.
        """
        state = tool_context.state if tool_context is not None else {}
        filtered_tools = state.get('filtered_tools') or []
        candidates = filtered_tools or state.get('accumulated_tools') or []
        from CoScientist.experiments.runtime.alembic_bridge import (
            alembic_post_build_context,
            compose_alembic_fedot_task,
        )
        alembic_ctx = alembic_post_build_context(state)
        if alembic_ctx:
            task_description = compose_alembic_fedot_task(alembic_ctx, task_description)
        # The Experiment Module owns anti-duplication through its task/attempt
        # state machine and AgentTool route guard.  Its path must not consult
        # the legacy session-scoped FEDOT deliverable flag.
        if not state.get("experiment_runtime") and should_hard_stop_fedot(state):
            arts = list(state.get("fedot_artifacts") or [])
            return {
                "status": "success",
                "artifacts": arts,
                "already_delivered": True,
                "message": (
                    "FEDOT deliverable already captured; refusing a second run. "
                    "Use existing artifacts / URLs for the Final Response."
                ),
            }
        servers_payload: dict[str, HttpMCPServer] = {}
        envelope = state.get("experiment_active_envelope") or {}
        task_data = envelope.get("task") or {}
        task_servers = task_data.get("mcp_servers") or []

        for srv in task_servers:
            if isinstance(srv, dict) and srv.get("url"):
                sname = srv.get("name") or srv.get("server_id") or "mcp"
                servers_payload[sname] = HttpMCPServer(
                    url=srv["url"],
                    description=srv.get("description", "")
                )

        lookup_tools = filtered_tools or candidates
        for t in lookup_tools:
            if isinstance(t, dict) and t.get("url"):
                sname = t.get("server_name") or t.get("name") or t.get("server_id") or "mcp"
                if sname not in servers_payload:
                    servers_payload[sname] = HttpMCPServer(
                        url=t["url"],
                        description=t.get("description", "")
                    )

        # Deployed web MCPs are stored in state as dicts (see WebToolsDeployerAgent).
        web_servers = state.get('deployed_mcps', [])
        for s in web_servers:
            if isinstance(s, dict) and s.get("url"):
                servers_payload[s['name']] = HttpMCPServer(
                    url=s['url'], description=s.get('description', '')
                )

        # Fallback only when no URL was in plan/state: database lookup
        if not servers_payload:
            servers = []
            postgres = PostgresClient(settings.postgres)
            try:
                await postgres.initialize()
                try:
                    server_ids = {
                        t['server_id']
                        for t in lookup_tools
                        if isinstance(t, dict) and t.get('server_id')
                    }
                    servers = [await postgres.get_server(server_id) for server_id in server_ids]
                finally:
                    await postgres.close()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "fedot_tool: database lookup failed (%s); proceeding with empty servers list", exc
                )

            servers = [server for server in servers if (server is not None and server.protocol == 'http')]
            servers_payload = {server.name: HttpMCPServer(url=server.url, description=server.description)
                               for server in servers}
        if not servers_payload:
            return {
                "status": "error",
                "artifacts": [],
                "error": (
                    "No runnable HTTP MCP server was selected. Retrieve the requested "
                    "tool again instead of starting FEDOT.MAS or escalating to Coder."
                ),
            }

        # Schema-driven handoff: if prior MCP CSVs are in state and the current
        # filtered tools' input_schema names match CSV headers, bind those values
        # into the task so the next step cannot invent placeholders.
        tables = tables_from_state(state)
        if tables and tool_context is not None and not state.get("fedot_artifact_tables"):
            tool_context.state["fedot_artifact_tables"] = tables
        task_description = bind_upstream_inputs_to_task(task_description, tables, lookup_tools)
        envelope = state.get("experiment_active_envelope") or {}
        launch_params = (envelope.get("task") or {}).get("launch_params") or {}
        if isinstance(launch_params, dict) and launch_params:
            for k, v in launch_params.items():
                if k == "num" and v is not None:
                    task_description = (
                        f"{task_description}\n\n"
                        f"REQUIRED MCP args: num={v}. "
                        f"Do not generate more than {v} molecules."
                    )
                elif v is not None and str(v).strip():
                    task_description = (
                        f"{task_description}\n"
                        f"REQUIRED MCP arg: {k}={v}."
                    )

        # F010.A3/A4: an after_tool_callback plugin captures S3 artifact links
        # (results_presigned_url) at the tool-call boundary, BEFORE FEDOT.MAS sub-agents
        # paraphrase them away / hallucinate molecules.
        # NB: passing plugins= REPLACES MAS defaults, so re-include them.
        cap = ArtifactCapturePlugin()
        from CoScientist.config import get_settings as get_app_settings
        web_search_limit = int(os.getenv("COSCIENTIST_FEDOT_WEB_SEARCH_LIMIT", "4"))
        # EM owns a bounded budget. The reranker-fallback path (nobody chose
        # FEDOT; a malformed ranking did) also gets a budget. Every other path
        # stays unbounded unless COSCIENTIST_FEDOT_TIMEOUT_S is set — confirm
        # correct results first (upstream F015), then tighten latency.
        if state.get("experiment_runtime"):
            fedot_timeout_s = float(get_app_settings().experiments.fedot_timeout_s)
        elif not filtered_tools and candidates:
            try:
                fedot_timeout_s = get_app_settings().web.fedot_fallback_timeout_s or None
            except Exception:  # noqa: BLE001 — no budget is better than no run
                fedot_timeout_s = None
        else:
            env_timeout = os.getenv("COSCIENTIST_FEDOT_TIMEOUT_S")
            fedot_timeout_s = float(env_timeout) if env_timeout else None
        result = None
        status, err = "success", None
        try:
            # openai/<id> for config validation; the patched engine strips it
            # again on the wire to the OpenAI-compatible proxy.
            ensure_fedot_openai_proxy_compat()
            # MAS stays the default. MAW splits config design into two smaller
            # LLM calls, which looked like the fix for the dominant failure here
            # ("did not produce <key> in session state"), but measuring it says
            # otherwise: 3 of 11 pipelines built in 4010 s against MAS's 25 of 46
            # in 499 s. Two calls means two places to fail, and the failure was
            # never about config size — 82 of 88 were the missing-output-key
            # error, which MetaJsonRecoveryPlugin below addresses directly.
            # EXPERIMENTS__FEDOT_ENGINE=maw switches engines for a re-measure.
            engine = str(get_app_settings().experiments.fedot_engine).lower()
            engine_cls = PatchedMAS if engine == "mas" else PatchedMAW
            mas = engine_cls(
                mcp_servers=servers_payload,
                # UsageMetricsPlugin bills FEDOT.MAS sub-agents' own LLM traffic
                # against them, same as any other AgentTool sub-runner — without
                # it their model calls are invisible to the cost ledger.
                plugins=[
                    LoggingPlugin(),
                    WebSearchLimitPlugin(max_calls_per_agent=web_search_limit),
                    LangfusePlugin(trace_name="coscientist:fedot"),
                    # Recovers a config the model answered with but ADK could not
                    # store — the single largest cause of FEDOT route failures here.
                    MetaJsonRecoveryPlugin(),
                    cap,
                    UsageMetricsPlugin(),
                ],
            )
            result = await mas.run(task_description, timeout=fedot_timeout_s)
        except (asyncio.TimeoutError, TimeoutError):
            status, err = "timeout", f"FEDOT.MAS exceeded {fedot_timeout_s}s"
        except Exception as e:
            status, err = "error", f"FEDOT.MAS run failed: {e}"

        # Fallback (F010.A4): scan the final MAS state for presigned URLs the
        # plugin's after_tool hook may have missed (only when a result actually
        # came back). Cheap safety net on top of ArtifactCapturePlugin, not a
        # replacement for it.
        if result is not None:
            try:
                _txt = json.dumps(result, default=str, ensure_ascii=False)
            except Exception:
                _txt = str(result)
            known_urls = {a.get("url") for a in cap.captured}
            scanned = [
                {"url": u, "tool": "fedot_state_scan"}
                for u in dict.fromkeys(re.findall(r"https?://[^\s\"'<>)\\]+X-Amz-[^\s\"'<>)\\]+", _txt))
                if u not in known_urls
            ]
            if scanned:
                cap.captured = merge_artifacts(cap.captured, scanned)

        # Alembic/inline MCP tools return molecules in structuredContent. The
        # worker LLM paraphrases them away; materialize from the plugin's
        # pre-paraphrase capture onto the *experiment* tool_context (Fedot's
        # inner ADK session does not carry experiment_runtime).
        if (
            getattr(cap, "inline_molecule_payloads", None)
            and tool_context is not None
            and state.get("experiment_runtime")
        ):
            from CoScientist.tools.fedot_artifact_plugin import (
                molecules_to_csv,
                _write_molecule_csv,
            )

            for item in cap.inline_molecule_payloads:
                payload = item.get("payload") if isinstance(item, dict) else None
                if not isinstance(payload, dict):
                    continue
                art = _write_molecule_csv(
                    payload,
                    tool_name=item.get("tool") if isinstance(item, dict) else None,
                    tool_context=tool_context,
                )
                if art is not None:
                    cap.captured = merge_artifacts(cap.captured, [art])
                else:
                    # Last resort: keep CSV text on the plugin payload for callers.
                    item["csv"] = molecules_to_csv(payload)

        # Some MCPs return a real CSV/JSON payload inline rather than uploading
        # it to S3.  In the experiment path, preserve that exact payload as the
        # single expected workspace artifact instead of weakening evidence
        # requirements or claiming success from prose alone. Prefer this even
        # when a URL scan found transient links: durable workspace evidence
        # beats a signed URL that may not download.
        if (
            result is not None
            and tool_context is not None
            and state.get("experiment_runtime")
            and not any(
                item.get("s3_key") or item.get("workspace_path")
                for item in cap.captured
                if isinstance(item, dict)
            )
        ):
            from CoScientist.experiments.runtime.inline_artifacts import (
                materialize_inline_result,
            )

            inline = materialize_inline_result(tool_context.state, result)
            cap.captured = merge_artifacts(cap.captured, inline)

        # Surface the REAL artifacts in the return value AND shared session state — so the
        # link survives even when FEDOT.MAS timed out AFTER generation (F015 Mode B fix).
        # Merge with artifacts from any prior fedot_tool call in this session.
        if cap.captured and tool_context is not None:
            previous = merge_artifacts(list(tool_context.state.get("fedot_artifacts") or []), cap.captured)
            # Materialize CSV tables onto artifacts (durable) + parallel state key.
            # Never let a bad/non-CSV presigned URL fail the whole tool after MAS success.
            try:
                tables = await asyncio.to_thread(
                    materialize_tables_from_artifacts,
                    previous,
                    list(tool_context.state.get("fedot_artifact_tables") or []),
                )
            except Exception:
                tables = list(tool_context.state.get("fedot_artifact_tables") or [])
            tool_context.state["fedot_artifacts"] = previous
            tool_context.state["fedot_artifact_tables"] = tables
            # Even on timeout: if we already have S3 links, treat as delivered.
            tool_context.state[_FEDOT_DELIVERABLE_READY_KEY] = True
            record_fedot_producer_tools(tool_context.state, lookup_tools)

        ret = {"status": status, "artifacts": cap.captured}
        if result is not None:
            ret["result"] = result
        if err:
            ret["error"] = err
        if getattr(cap, "inline_molecule_payloads", None):
            ret["inline_molecule_tools"] = [
                {
                    "tool": item.get("tool"),
                    "n_molecules": len((item.get("payload") or {}).get("molecules") or []),
                    "tool_args": item.get("tool_args"),
                }
                for item in cap.inline_molecule_payloads
                if isinstance(item, dict)
            ]
            # Keep raw payloads for callers that need durable CSV without S3.
            ret["inline_molecule_payloads"] = [
                item.get("payload")
                for item in cap.inline_molecule_payloads
                if isinstance(item, dict) and isinstance(item.get("payload"), dict)
            ]
        # Success without a captured S3 artifact is a soft signal for retry —
        # never invent molecule payloads here.
        if status == "success" and not cap.captured:
            ret["empty_artifacts"] = True
        return ret
    
fedot_toolset = FedotMASToolset()
fedot_toolset_instance = fedot_toolset.get_tools(None)
