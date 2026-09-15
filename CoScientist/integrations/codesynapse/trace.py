"""Ordered trace creation and batching for Codesynapse callbacks."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from CoScientist.integrations.codesynapse.models import TraceEvent
from CoScientist.integrations.codesynapse.redaction import redact
from CoScientist.integrations.codesynapse.store import IntegrationStore


def is_critical_event(event: TraceEvent) -> bool:
    """Return whether an event must leave the outbox without batching delay."""

    return (
        event.type.startswith("run.")
        or event.type == "hitl.requested"
        or event.type in {"agent.completed", "agent.failed", "delegation.completed", "delegation.failed"}
    )


def _event_size(event: TraceEvent) -> int:
    return len(json.dumps(event.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"))


def batch_events(
    events: list[TraceEvent], *, max_events: int = 100, max_bytes: int = 1024 * 1024
) -> list[list[TraceEvent]]:
    """Group ordered events without allowing critical events into a delayed batch."""

    if max_events <= 0 or max_bytes <= 0:
        raise ValueError("batch limits must be positive")

    batches: list[list[TraceEvent]] = []
    current: list[TraceEvent] = []
    current_bytes = 0
    for event in sorted(events, key=lambda item: item.sequence):
        size = _event_size(event)
        if is_critical_event(event):
            if current:
                batches.append(current)
                current, current_bytes = [], 0
            batches.append([event])
            continue
        if current and (len(current) >= max_events or current_bytes + size > max_bytes):
            batches.append(current)
            current, current_bytes = [], 0
        current.append(event)
        current_bytes += size
    if current:
        batches.append(current)
    return batches


class TraceRecorder:
    """Assigns persisted monotonic sequences and writes redacted trace events."""

    def __init__(
        self,
        store: IntegrationStore,
        *,
        run_id: str,
        tenant_id: str,
        project_id: str,
        initial_sequence: int = 0,
        on_event: Callable[[TraceEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._sequence = initial_sequence
        self._initialized = False
        self._on_event = on_event

    async def emit(self, event_type: str, *, data: dict[str, Any] | None = None, **fields: Any) -> TraceEvent:
        event_id = str(uuid4())
        if not self._initialized:
            self._sequence = max(self._sequence, await self._last_persisted_sequence())
            self._initialized = True
        while True:
            self._sequence += 1
            event = TraceEvent(
                event_id=event_id,
                run_id=self._run_id,
                sequence=self._sequence,
                tenant_id=self._tenant_id,
                project_id=self._project_id,
                type=event_type,
                data=redact(data or {}),
                **fields,
            )
            if await self._store.append_event(event):
                if self._on_event is not None:
                    await self._on_event(event)
                return event
            self._sequence = await self._last_persisted_sequence()

    async def _last_persisted_sequence(self) -> int:
        events = await self._store.replay_events(self._run_id)
        return max((event.sequence for event in events), default=0)
