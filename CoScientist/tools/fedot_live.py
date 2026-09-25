from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict, deque
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


SessionKey = tuple[str, str]

_MAX_RUNS_PER_SESSION = 5
_MAX_SESSIONS = 20
_MAX_TAIL_EVENTS = 5000
# Kept for good however long the run gets: without them a late viewer cannot
# reset itself or draw the pipeline shape.
_HEAD_TYPES = frozenset({"run_start", "config"})


class FedotLiveRun:
    """One ``fedot_tool`` run, published into its web session's channel.

    Every event is stamped with the run id and a wall-clock ``ts`` (the viewer
    times the run from these, so a replay shows the real durations) and kept, so
    a page opened after the run started — or after it ended — can be replayed
    the whole thing instead of showing an empty graph.
    """

    def __init__(self, bus: "FedotLiveBroadcaster", key: SessionKey, run_id: str) -> None:
        self.key = key
        self.run_id = run_id
        self._bus = bus
        self._head: list[dict] = []
        self._tail: deque[dict] = deque(maxlen=_MAX_TAIL_EVENTS)

    @property
    def history(self) -> list[dict]:
        return [*self._head, *self._tail]

    def event(self, payload: dict) -> None:
        item = {**payload, "run_id": self.run_id, "ts": time.time()}
        (self._head if item.get("type") in _HEAD_TYPES else self._tail).append(item)
        self._bus._deliver(self.key, item)

    def publish_config(self, config: dict) -> None:
        self.event({"type": "config", "config": config})


class FedotLiveBroadcaster:
    """Fan-out of ``fedot_tool`` runs to viewers, one channel per web session.

    A run belongs to the session whose agent launched it (``session_key`` — the
    same ``(user_id, session_id)`` the knowledge graph is scoped by), so a page
    opened for one session never draws another session's FEDOT.MAS. A viewer that
    names no session (a bare ``/fedot-demo/``) sees every session's runs, as
    before.
    """

    def __init__(self) -> None:
        self._runs: OrderedDict[SessionKey, deque[FedotLiveRun]] = OrderedDict()
        self._subscribers: list[tuple[Optional[SessionKey], asyncio.Queue]] = []
        self._last_key: Optional[SessionKey] = None

    def begin_run(self, key: SessionKey) -> FedotLiveRun:
        run = FedotLiveRun(self, key, uuid.uuid4().hex[:12])
        self._runs.setdefault(key, deque(maxlen=_MAX_RUNS_PER_SESSION)).append(run)
        self._runs.move_to_end(key)
        while len(self._runs) > _MAX_SESSIONS:
            self._runs.popitem(last=False)
        self._last_key = key
        return run

    def latest_run(self, key: Optional[SessionKey] = None) -> Optional[FedotLiveRun]:
        runs = self._runs.get(key if key is not None else self._last_key)
        return runs[-1] if runs else None

    def subscribe(self, key: Optional[SessionKey] = None) -> asyncio.Queue:
        """A queue that replays the latest run of ``key`` (any session if None), then follows live."""
        q: asyncio.Queue = asyncio.Queue()
        run = self.latest_run(key)
        if run is not None:
            for item in run.history:
                q.put_nowait(item)
        self._subscribers.append((key, q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers = [(k, sub) for k, sub in self._subscribers if sub is not q]

    def _deliver(self, key: SessionKey, item: dict) -> None:
        self._last_key = key
        for wanted, q in list(self._subscribers):
            if wanted is None or wanted == key:
                q.put_nowait(item)


fedot_live = FedotLiveBroadcaster()


class FedotLivePlugin(BasePlugin):
    def __init__(self, run: FedotLiveRun, name: str = "fedot_live") -> None:
        super().__init__(name)
        self._bus = run
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
