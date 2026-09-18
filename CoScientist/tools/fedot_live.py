from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.events import Event
from google.adk.plugins import BasePlugin
from google.adk.runners import InvocationContext

_MAX_FIELD_CHARS = 4000
_WORKFLOW_PREFIXES = ("seq_", "par_", "loop_")


def _truncate(value: Any, limit: int = _MAX_FIELD_CHARS) -> str:
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else text[:limit] + f"… ({len(text)} chars total)"


class FedotLiveBroadcaster:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._last_config: Optional[dict] = None

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        if self._last_config is not None:
            q.put_nowait({"type": "config", "config": self._last_config})
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def publish_config(self, config: dict) -> None:
        self._last_config = config
        self._broadcast({"type": "config", "config": config})

    def event(self, payload: dict) -> None:
        self._broadcast(payload)

    def _broadcast(self, payload: dict) -> None:
        for q in list(self._subscribers):
            q.put_nowait(payload)

fedot_live = FedotLiveBroadcaster()


class FedotLivePlugin(BasePlugin):
    def __init__(self, broadcaster: FedotLiveBroadcaster, name: str = "fedot_live") -> None:
        super().__init__(name)
        self._bus = broadcaster
        self._start: dict[str, float] = {}

    def _is_workflow(self, name: str) -> bool:
        return name.startswith(_WORKFLOW_PREFIXES)

    async def before_agent_callback(self, *, agent, callback_context):  # noqa: ANN001
        if self._is_workflow(agent.name):
            return None
        self._start[agent.name] = time.monotonic()
        instruction = str(getattr(agent, "instruction", "") or "")
        try:
            state = dict(callback_context.state.to_dict())
        except Exception:  # noqa: BLE001 — best-effort, tracing must never break the run
            state = {}
        incoming = {k: _truncate(v) for k, v in state.items() if k != "user_query"}
        self._bus.event({
            "type": "agent_start",
            "agent": agent.name,
            "instruction": _truncate(instruction, 8000),
            "incoming": incoming,
        })
        return None

    async def after_agent_callback(self, *, agent, callback_context):  # noqa: ANN001
        t0 = self._start.pop(agent.name, None)
        if t0 is None or self._is_workflow(agent.name):
            return None
        output_key = getattr(agent, "output_key", None)
        produced = ""
        if output_key:
            try:
                produced = str(callback_context.state.to_dict().get(output_key, ""))
            except Exception:  # noqa: BLE001
                produced = ""
        self._bus.event({
            "type": "agent_done",
            "agent": agent.name,
            "ms": int((time.monotonic() - t0) * 1000),
            "output_key": output_key,
            "output": _truncate(produced, 12000),
        })
        return None

    async def on_event_callback(  # noqa: ANN001
        self, *, invocation_context: InvocationContext, event: Event
    ):
        if event.partial:
            return None
        author = event.author or "?"

        usage = event.usage_metadata
        tokens = 0
        if usage is not None:
            tokens = (usage.prompt_token_count or 0) + (usage.candidates_token_count or 0)

        for fc in event.get_function_calls():
            args = fc.args or {}
            target = args.get("agent_name") or args.get("agent") or ""
            self._bus.event({
                "type": "tool", "agent": author, "tool": fc.name,
                "target": str(target), "args": _truncate(args, 200),
            })
        for fr in event.get_function_responses():
            resp = _truncate(fr.response, 200) if fr.response is not None else ""
            is_error = isinstance(fr.response, dict) and fr.response.get("isError") is True
            self._bus.event({
                "type": "tool_result", "agent": author, "tool": fr.name,
                "error": bool(is_error), "text": resp,
            })

        text = ""
        if event.content and event.content.parts:
            text = "".join(p.text or "" for p in event.content.parts if p.text)
        if text.strip():
            self._bus.event({"type": "text", "agent": author, "text": _truncate(text.strip()), "tokens": tokens})
        elif tokens:
            self._bus.event({"type": "tokens", "agent": author, "tokens": tokens})
        return None
