"""ADK plugin that streams every tool call/result to an observer sink.

Why a plugin and not the event stream: subordinate agents are attached as
``AgentTool`` (see ``assembly/assembler.py``), and an AgentTool delegation runs
its agent in a *nested* Runner with its own child ADK session. Only the
delegation's own function_call/function_response surfaces in the parent
``run_async`` stream — everything the sub-agent does inside (e.g.
``ResearchAgent`` calling ``tavily_search``) never reaches a consumer of the
top-level events. Tool callbacks, on the other hand, fire in nested runners
too, which is exactly why the console trace in ``event_logger`` sees them.

The web UI registers a sink here to show the full picture live. With no sink
registered the plugin is inert, so CLI/A2A runs pay nothing for it.

The sink is invoked as ``await sink(session_key, payload)`` and must never be
able to break a run: every dispatch is guarded.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from google.adk.plugins.base_plugin import BasePlugin

from CoScientist.graph.session_scope import SessionKey, session_key

logger = logging.getLogger("CoScientist.logging.tool_activity")

ToolActivitySink = Callable[[SessionKey, dict], Awaitable[None]]

# Tool args and results are only rendered as a compact preview by observers, and
# a raw result can be megabytes (search dumps, file contents). Cap them here so
# the sink never carries more than a glance's worth of payload.
_PREVIEW_LIMIT = 1500

_sink: Optional[ToolActivitySink] = None


def set_tool_activity_sink(sink: Optional[ToolActivitySink]) -> None:
    """Register (or clear, with ``None``) the observer for tool activity."""
    global _sink
    _sink = sink


def _preview(value: Any) -> Any:
    """Return a small JSON-safe rendering of ``value``.

    Structure is preserved while it stays under the cap — observers render a
    dict of arguments far more readably than its escaped JSON text. Anything
    larger degrades to a truncated string.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    try:
        text = value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, default=str,
        )
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > _PREVIEW_LIMIT:
        return text[:_PREVIEW_LIMIT] + " …"
    if isinstance(value, str):
        return value
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _agent_name(tool_context: Any) -> str:
    return getattr(tool_context, "agent_name", None) or "system"


def _call_id(tool_context: Any) -> Optional[str]:
    """The id ADK assigns to this function call.

    Lets an observer pair a result with its own call instead of guessing by
    tool name — which is wrong as soon as an agent runs the same tool twice.
    """
    call_id = getattr(tool_context, "function_call_id", None)
    return str(call_id) if call_id else None


class ToolActivityPlugin(BasePlugin):
    """Report every tool call, result, and error to the registered sink."""

    def __init__(self, name: str = "tool_activity") -> None:
        super().__init__(name=name)

    async def _dispatch(self, tool_context: Any, payload: dict) -> None:
        sink = _sink
        if sink is None:
            return
        try:
            key = session_key(tool_context)
        except Exception:  # noqa: BLE001 - context shapes vary across ADK paths
            return
        payload.setdefault("timestamp", datetime.now().isoformat())
        try:
            await sink(key, payload)
        except Exception as exc:  # noqa: BLE001 - an observer must not fail a run
            logger.warning("Tool activity sink failed: %s", exc)

    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> None:
        await self._dispatch(tool_context, {
            "phase": "call",
            "author": _agent_name(tool_context),
            "tool": getattr(tool, "name", "?"),
            "call_id": _call_id(tool_context),
            "args": _preview(tool_args),
        })
        return None  # never override the tool's own execution

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> None:
        await self._dispatch(tool_context, {
            "phase": "result",
            "author": _agent_name(tool_context),
            "tool": getattr(tool, "name", "?"),
            "call_id": _call_id(tool_context),
            "result": _preview(result),
        })
        return None

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error) -> None:
        # ADK re-raises a tool error when no plugin supplies a replacement
        # response, so ``after_tool_callback`` never fires for it: this is the
        # only closing record such a call will ever get.
        await self._dispatch(tool_context, {
            "phase": "error",
            "author": _agent_name(tool_context),
            "tool": getattr(tool, "name", "?"),
            "call_id": _call_id(tool_context),
            "error": _preview(str(error)),
        })
        return None
