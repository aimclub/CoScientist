"""Observer plugin: a structured, analysis-ready trace of one benchmark trial.

The system already logs a human-readable event stream (``AGENT_LOG_JSONL``) and
keeps a usage ledger; neither records timings per tool call nor survives a run
the harness has to kill at its deadline. This plugin writes ``trace/events.jsonl``
— one line per agent turn, model call and tool call, with durations, token
counts and errors — and checkpoints the usage ledger to ``metrics.json`` every
``flush_every`` seconds.

Observer only: every callback returns ``None`` and swallows its own errors.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin

_PREVIEW = 1500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _clip(value: Any, n: int = _PREVIEW) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = repr(value)
    return text if len(text) <= n else text[:n] + f"…[+{len(text) - n}]"


class BenchTracePlugin(BasePlugin):
    def __init__(self, events_path: Path, metrics_path: Path, session_key: tuple[str, str],
                 flush_every: float = 30.0):
        super().__init__(name="bench_trace")
        self._events = events_path
        self._metrics = metrics_path
        self._key = session_key
        self._flush_every = flush_every
        self._last_flush = 0.0
        self._t_model: dict[tuple[str, str], float] = {}
        self._t_tool: dict[str, float] = {}
        self._t_agent: dict[tuple[str, str], float] = {}
        events_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = events_path.open("a", encoding="utf-8")

    def _write(self, **rec: Any) -> None:
        try:
            self._fh.write(json.dumps({"t": _now(), **rec}, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()
        except Exception:  # noqa: BLE001
            pass

    def flush_metrics(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._last_flush < self._flush_every:
            return
        self._last_flush = time.monotonic()
        try:
            from CoScientist.logging.metrics import snapshot

            tmp = self._metrics.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot(key=self._key), indent=2, default=str))
            os.replace(tmp, self._metrics)
        except Exception:  # noqa: BLE001
            pass

    # ── agents ───────────────────────────────────────────────────────────────
    async def before_agent_callback(self, *, agent, callback_context):
        self._t_agent[(callback_context.invocation_id, agent.name)] = time.monotonic()
        self._write(ev="agent_start", agent=agent.name)

    async def after_agent_callback(self, *, agent, callback_context):
        t0 = self._t_agent.pop((callback_context.invocation_id, agent.name), None)
        self._write(ev="agent_end", agent=agent.name,
                    ms=round((time.monotonic() - t0) * 1000) if t0 else None)

    # ── model calls ──────────────────────────────────────────────────────────
    async def before_model_callback(self, *, callback_context, llm_request):
        self._t_model[(callback_context.invocation_id, callback_context.agent_name)] = time.monotonic()

    async def after_model_callback(self, *, callback_context, llm_response):
        try:
            t0 = self._t_model.pop((callback_context.invocation_id, callback_context.agent_name), None)
            u = getattr(llm_response, "usage_metadata", None)
            calls = []
            for p in (getattr(getattr(llm_response, "content", None), "parts", None) or []):
                fc = getattr(p, "function_call", None)
                if fc is not None:
                    calls.append(fc.name)
            self._write(
                ev="model", agent=callback_context.agent_name,
                model=getattr(llm_response, "model_version", None),
                ms=round((time.monotonic() - t0) * 1000) if t0 else None,
                prompt_tokens=getattr(u, "prompt_token_count", None),
                output_tokens=getattr(u, "candidates_token_count", None),
                thought_tokens=getattr(u, "thoughts_token_count", None),
                cached_tokens=getattr(u, "cached_content_token_count", None),
                function_calls=calls or None,
                error=getattr(llm_response, "error_code", None) or None,
                error_message=_clip(getattr(llm_response, "error_message", None) or "", 500) or None,
            )
        finally:
            self.flush_metrics()

    async def on_model_error_callback(self, *, callback_context, llm_request, error):
        self._write(ev="model_error", agent=callback_context.agent_name,
                    error=type(error).__name__, message=_clip(str(error), 800))

    # ── tool calls ───────────────────────────────────────────────────────────
    @staticmethod
    def _call_id(tool_context) -> str:
        return str(getattr(tool_context, "function_call_id", None) or id(tool_context))

    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        self._t_tool[self._call_id(tool_context)] = time.monotonic()

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        t0 = self._t_tool.pop(self._call_id(tool_context), None)
        status = None
        if isinstance(result, dict):
            status = result.get("status") or ("error" if result.get("error") else None)
        self._write(ev="tool", agent=getattr(tool_context, "agent_name", None), tool=tool.name,
                    call_id=self._call_id(tool_context),
                    ms=round((time.monotonic() - t0) * 1000) if t0 else None,
                    status=status, args=_clip(tool_args), result=_clip(result))

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error):
        t0 = self._t_tool.pop(self._call_id(tool_context), None)
        self._write(ev="tool", agent=getattr(tool_context, "agent_name", None), tool=tool.name,
                    call_id=self._call_id(tool_context),
                    ms=round((time.monotonic() - t0) * 1000) if t0 else None,
                    status="exception", error=type(error).__name__,
                    args=_clip(tool_args), result=_clip(str(error), 800))

    async def on_run_error_callback(self, *, invocation_context, error):
        self._write(ev="run_error", error=type(error).__name__, message=_clip(str(error), 800))

    async def after_run_callback(self, *, invocation_context):
        self.flush_metrics(force=True)
