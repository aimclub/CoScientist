"""ADK plugin that surfaces a key agent's FINAL answer to an observer sink.

Subordinates are attached as ``AgentTool`` (see ``assembly/assembler.py``), so a
delegation's whole result — the hypotheses HypothesesAgent produced, the
literature ResearchAgent found — reaches the caller as a function_response and
never as an utterance of its own. The chat therefore only ever showed the
orchestrator's paraphrase of it, while the actual deliverable was visible only
as a truncated preview in the tool-activity rail.

This plugin closes an ``AgentTool`` call by reporting the delegated agent's own
answer in full, for the agents that carry ``report_output: true`` in
``system.yaml`` (the "key" agents — everything else, notably the tool-pipeline
internals, stays out of the chat). Consumers render it as a message authored by
that agent.

The sink is invoked as ``await sink(session_key, payload)`` and must never be
able to break a run: every dispatch is guarded. With no sink registered the
plugin is inert, so CLI/A2A runs pay nothing for it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from google.adk.plugins.base_plugin import BasePlugin

from CoScientist.graph.session_scope import SessionKey, session_key

logger = logging.getLogger("CoScientist.logging.agent_output")

AgentOutputSink = Callable[[SessionKey, dict], Awaitable[None]]

# A final answer IS the message — far more room than the tool-activity preview
# gets — but a runaway result must not be pushed into the browser wholesale.
_OUTPUT_LIMIT = 20000

_sink: Optional[AgentOutputSink] = None


def set_agent_output_sink(sink: Optional[AgentOutputSink]) -> None:
    """Register (or clear, with ``None``) the observer for agent outputs."""
    global _sink
    _sink = sink


def reported_agents() -> frozenset[str]:
    """Names of the agents whose final answer belongs in the chat.

    Declared per agent in ``system.yaml`` (``report_output: true``), so the
    profile that describes the system also decides what it reports.
    """
    try:
        from CoScientist.assembly.schema import get_config
        return get_config().reported_output_agents()
    except Exception:  # noqa: BLE001 - an unloadable config must not break a run
        logger.debug("Could not resolve reported agents from the system config")
        return frozenset()


def _as_text(result: Any) -> str:
    """Render an AgentTool result as the text the agent effectively answered.

    A plain LLM agent returns its message; one with an ``output_schema``
    returns the validated object, which reads best as indented JSON.
    """
    if result is None:
        return ""
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            text = str(result)
    if len(text) > _OUTPUT_LIMIT:
        text = text[:_OUTPUT_LIMIT] + "\n… (output truncated)"
    return text


def _caller(tool_context: Any) -> str:
    """The agent that delegated — an AgentTool runs in ITS parent's context."""
    return getattr(tool_context, "agent_name", None) or "system"


class AgentOutputPlugin(BasePlugin):
    """Report the final answer of every agent flagged ``report_output``."""

    def __init__(self, name: str = "agent_output") -> None:
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
            logger.warning("Agent output sink failed: %s", exc)

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> None:
        # An AgentTool is named after the agent it wraps, so the tool name IS
        # the delegated agent — which is what the config flags.
        agent = getattr(tool, "name", "")
        if agent not in reported_agents():
            return None
        text = _as_text(result)
        if not text.strip():
            return None  # nothing was answered; an empty bubble helps nobody
        await self._dispatch(tool_context, {
            "agent": agent,
            "caller": _caller(tool_context),
            "call_id": (
                str(getattr(tool_context, "function_call_id", None))
                if getattr(tool_context, "function_call_id", None) else None
            ),
            "content": text,
        })
        return None  # never override the delegation's own result
