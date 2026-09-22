"""ADK plugin: cap large tool results before they enter the LLM context.

A single tool call returning a huge payload (e.g. ``tavily_extract`` of full web
pages → ~240k tokens) can blow past the model's context window and crash the
whole run. This recursively truncates long strings in any tool result so each
call stays bounded.

MUST be the LAST plugin on the Runner: ADK stops at the first plugin whose
``after_tool_callback`` returns non-None, so the event logger / graph-memory
plugins (which return None) still observe the FULL result first, and only then
does this plugin hand a bounded copy to the model.

A plugin that returns non-None also makes ADK SKIP the agent's own
``after_tool`` callbacks (``_tool_caller``: "if no overrides are provided from
the plugins, further run the canonical after_tool_callbacks"). Those callbacks
file tool answers into the state — e.g. ``collect_economics_result`` writes
``economics_ranking`` from a ``rank_routes_by_cost`` answer, which for several
routes is far above the cap. So before truncating, this plugin runs the owning
agent's after_tool callbacks itself, on the FULL result, exactly once; ADK then
does not run them again.

Per-string cap is configurable via TOOL_RESULT_MAX_CHARS (default 12000 ≈ 3k tokens).
"""
from __future__ import annotations

import inspect
import os
from typing import Any, Optional, Tuple

from google.adk.plugins.base_plugin import BasePlugin

try:  # ADK's own runner for callback chains: same binding and stop semantics.
    from google.adk.utils._callback_pipeline import _run_callbacks, _stop_on_non_none
except ImportError:  # pragma: no cover - older ADK without the helper
    _run_callbacks = None

_DEFAULT_MAX_CHARS = 12000


def _truncate(obj: Any, cap: int) -> Tuple[Any, bool]:
    """Recursively cap every string in a JSON-like value. Returns (value, changed)."""
    if isinstance(obj, str):
        if len(obj) > cap:
            return obj[:cap] + f"\n…[truncated {len(obj) - cap} chars to fit the context window]", True
        return obj, False
    if isinstance(obj, dict):
        out, changed = {}, False
        for k, v in obj.items():
            nv, ch = _truncate(v, cap)
            out[k] = nv
            changed = changed or ch
        return out, changed
    if isinstance(obj, list):
        out, changed = [], False
        for v in obj:
            nv, ch = _truncate(v, cap)
            out.append(nv)
            changed = changed or ch
        return out, changed
    return obj, False


async def _run_agent_after_tool_callbacks(tool, tool_args, tool_context, result) -> Any:
    """The owning agent's after_tool chain on ``result``, as ADK would run it:
    in order, stopping at the first non-None answer (which is returned)."""
    invocation = getattr(tool_context, "_invocation_context", None)
    agent = getattr(invocation, "agent", None)
    callbacks = list(getattr(agent, "canonical_after_tool_callbacks", None) or [])
    if not callbacks:
        return None
    kwargs = dict(tool=tool, args=tool_args, tool_context=tool_context, tool_response=result)
    if _run_callbacks is not None:
        return await _run_callbacks(callbacks, _stop_on_non_none, **kwargs)
    for callback in callbacks:  # pragma: no cover - older ADK
        answer = callback(**kwargs)
        if inspect.isawaitable(answer):
            answer = await answer
        if answer is not None:
            return answer
    return None


class ToolResultTruncationPlugin(BasePlugin):
    def __init__(self, max_chars: Optional[int] = None, name: str = "tool_truncation") -> None:
        super().__init__(name=name)
        try:
            self.max_chars = int(os.getenv("TOOL_RESULT_MAX_CHARS", max_chars or _DEFAULT_MAX_CHARS))
        except (TypeError, ValueError):
            self.max_chars = _DEFAULT_MAX_CHARS

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> Optional[dict]:
        if not isinstance(result, (dict, list, str)) or self.max_chars <= 0:
            return None
        truncated, changed = _truncate(result, self.max_chars)
        if not changed:
            # Nothing to shorten: return None so ADK runs the agent's own
            # after_tool callbacks on the result as usual.
            return None
        # Returning the bounded copy makes ADK skip the agent's after_tool
        # callbacks, so run them here first, on the FULL result. An answer
        # they give replaces the result, as it would without this plugin.
        altered = await _run_agent_after_tool_callbacks(tool, tool_args, tool_context, result)
        if altered is not None:
            truncated, _ = _truncate(altered, self.max_chars)
        return truncated
