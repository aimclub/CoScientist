"""ADK callbacks that export tool lifecycle facts to the Codesynapse trace."""

from __future__ import annotations

from typing import Optional

from google.adk.plugins.base_plugin import BasePlugin

from CoScientist.integrations.codesynapse.trace import TraceRecorder


class CodesynapseTracePlugin(BasePlugin):
    """Export redacted tool events without changing agent behaviour."""

    def __init__(
        self,
        recorder: TraceRecorder,
        name: str = "codesynapse_trace",
        delegated_tool_names: set[str] | None = None,
    ) -> None:
        super().__init__(name=name)
        self._recorder = recorder
        self._delegated_tool_names = delegated_tool_names

    def _is_delegation(self, tool_name: str) -> bool:
        if self._delegated_tool_names is None:
            try:
                from CoScientist.assembly.schema import get_config

                self._delegated_tool_names = set(get_config().delegatable_names())
            except Exception:  # Trace export must never change research execution.
                self._delegated_tool_names = set()
        return tool_name in self._delegated_tool_names

    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> Optional[dict]:
        is_delegation = self._is_delegation(tool.name)
        await self._recorder.emit(
            "delegation.started" if is_delegation else "tool.started",
            node_id=getattr(tool_context, "function_call_id", None),
            agent=getattr(tool_context, "agent_name", None),
            data={"tool_name": tool.name, "arguments": tool_args},
        )
        return None

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> Optional[dict]:
        failed = isinstance(result, dict) and (result.get("error") or result.get("status") in {"error", "failed", "timeout"})
        is_delegation = self._is_delegation(tool.name)
        await self._recorder.emit(
            "delegation.failed" if is_delegation and failed else
            "delegation.completed" if is_delegation else
            "tool.failed" if failed else "tool.completed",
            node_id=getattr(tool_context, "function_call_id", None),
            agent=getattr(tool_context, "agent_name", None),
            data={"tool_name": tool.name, "result": result},
        )
        return None

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error) -> Optional[dict]:
        await self._recorder.emit(
            "delegation.failed" if self._is_delegation(tool.name) else "tool.failed",
            node_id=getattr(tool_context, "function_call_id", None),
            agent=getattr(tool_context, "agent_name", None),
            data={"tool_name": tool.name, "error": str(error)},
        )
        return None
