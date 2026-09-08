"""ADK plugin that logs every agent's inner activity to stdout.

Attached everywhere the system runs:
- the in-process Runner in ``CoScientistManager`` (``main.py``) — covers the
  web UI and the terminal REPL;
- each A2A server's Runner (``a2a/server.py``) — a sub-agent's reasoning and
  tool use show up on its own server's console (aggregated by run_all);
- the ``App`` exported from ``agent.py`` — so plain ``adk web`` /
  ``adk api_server`` runs get the same console trace without A2A.

This surfaces the whole exchange: the user's input (🧑 USER), what each agent
does internally — thoughts, tool calls, and tool results — and the system's
final answer (✅ FINAL RESPONSE).

The same trace is also appended to a log file (ANSI stripped) — handy when the
terminal scrollback can't hold a long run. Path: AGENT_LOG_FILE (default
``/app/agent_events.log``); set it to "" to keep only the console output.

Disable everything with LOG_AGENT_EVENTS=0 (the older A2A_LOG_EVENTS=0 still
works).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from google.adk.plugins.base_plugin import BasePlugin

# ANSI colors (no-op if the terminal ignores them)
_DIM = "\033[2m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_RESET = "\033[0m"

# File copy of the console trace (ANSI stripped). Best-effort: an unwritable
# path disables the file sink rather than breaking the run. Under run_all every
# A2A server appends to the same file — O_APPEND keeps each capped line intact,
# so they aggregate just like the shared console.
_LOG_FILE = os.getenv("AGENT_LOG_FILE", "/app/agent_events.log")
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
_log_fh = None        # open handle, lazily created
_log_disabled = False  # set once if opening failed, so we stop retrying


def _get_log_fh():
    global _log_fh, _log_disabled
    if _log_disabled or not _LOG_FILE:
        return None
    if _log_fh is None:
        try:
            # Do not inherit the Windows console code page (often cp1251): the
            # trace intentionally contains emoji markers and scientific Unicode.
            _log_fh = open(_LOG_FILE, "a", buffering=1, encoding="utf-8")
        except OSError:
            _log_disabled = True
            return None
    return _log_fh


def _enabled() -> bool:
    value = os.getenv("LOG_AGENT_EVENTS") or os.getenv("A2A_LOG_EVENTS") or "1"
    return value not in ("0", "false", "False")


def _short(value: Any, limit: int = 500) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + " …"


def _agent(ctx: Any) -> str:
    return getattr(ctx, "agent_name", None) or "?"


def _content_text(content: Any) -> str:
    """Join the text parts of a types.Content (user message / event), if any."""
    if content is None:
        return ""
    parts = getattr(content, "parts", None) or []
    texts = [p.text for p in parts if getattr(p, "text", None)]
    return "\n".join(texts).strip()


def _emit(line: str) -> None:
    print(line, flush=True)
    fh = _get_log_fh()
    if fh is not None:
        try:
            fh.write(_ANSI_RE.sub("", line) + "\n")  # line-buffered, flushes on \n
        except OSError:
            pass

class EventLoggerPlugin(BasePlugin):
    """Prints agent thoughts, tool calls, and tool results as they happen."""

    def __init__(self, name: str = "event_logger") -> None:
        super().__init__(name=name)
        # The root agent that receives the real user query. Sub-agents invoked
        # via AgentTool spin up their own nested Runner (with the same plugins),
        # so on_user_message/after_run fire for them too — gating on the root
        # name keeps USER/FINAL to the one top-level exchange (and is robust to
        # parallel sub-agent calls, unlike a shared depth counter).
        self._root_agent_name: Optional[str] = None
        # top-level invocation_id -> text of its latest final-response event.
        self._final_by_invocation: dict[str, str] = {}

    @staticmethod
    def _ctx_agent_name(invocation_context) -> Optional[str]:
        agent = getattr(invocation_context, "agent", None)
        return getattr(agent, "name", None)

    async def on_user_message_callback(self, *, invocation_context, user_message) -> Optional[Any]:
        name = self._ctx_agent_name(invocation_context)
        # The first user message of the process goes to the root agent; remember
        # it so every later top-level run is recognised the same way.
        if self._root_agent_name is None:
            self._root_agent_name = name
        if _enabled() and name == self._root_agent_name:
            text = _content_text(user_message)
            if text:
                _emit(f"{_BOLD}{_CYAN}🧑 USER ► {text}{_RESET}")
        return None

    async def on_event_callback(self, *, invocation_context, event) -> Optional[Any]:
        # Only the root agent's final-response event is the system's answer;
        # sub-agent finals (different agent) are skipped.
        if not (_enabled() and getattr(event, "is_final_response", None) and event.is_final_response()):
            return None
        if self._ctx_agent_name(invocation_context) != self._root_agent_name:
            return None
        text = _content_text(getattr(event, "content", None))
        if text:
            self._final_by_invocation[getattr(invocation_context, "invocation_id", "default")] = text
        return None

    async def after_run_callback(self, *, invocation_context) -> None:
        key = getattr(invocation_context, "invocation_id", "default")
        text = self._final_by_invocation.pop(key, None)
        if _enabled() and text:
            _emit(f"{_BOLD}{_GREEN}✅ FINAL RESPONSE ► {text}{_RESET}")
        return None

    async def after_model_callback(self, *, callback_context, llm_response) -> Optional[Any]:
        if not _enabled() or llm_response is None or llm_response.content is None:
            return None
        agent = _agent(callback_context)
        for part in (llm_response.content.parts or []):
            text = getattr(part, "text", None)
            fc = getattr(part, "function_call", None)
            if text and getattr(part, "thought", False):
                _emit(f"{_DIM}{_MAGENTA}[{agent}] 💭 {_short(text, 700)}{_RESET}")
            elif fc is not None:
                args = _short(dict(getattr(fc, "args", {}) or {}), 400)
                _emit(f"{_YELLOW}[{agent}] 🔧 {_BOLD}{getattr(fc, 'name', '?')}{_RESET}{_YELLOW}({args}){_RESET}")
            elif text:
                _emit(f"{_GREEN}[{agent}] 🗎 {_short(text, 700)}{_RESET}")
        return None

    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> Optional[dict]:
        if _enabled():
            _emit(f"{_CYAN}[{_agent(tool_context)}] ▶ tool {_BOLD}{tool.name}{_RESET}{_CYAN} {_short(tool_args, 400)}{_RESET}")
        return None

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> Optional[dict]:
        if _enabled():
            _emit(f"{_DIM}[{_agent(tool_context)}] ◀ {tool.name} → {_short(result, 500)}{_RESET}")
        return None

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error) -> Optional[dict]:
        if _enabled():
            _emit(f"{_BOLD}[{_agent(tool_context)}] ✖ {tool.name} error: {_short(str(error), 300)}{_RESET}")
        return None
