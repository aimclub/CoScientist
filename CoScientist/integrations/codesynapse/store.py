"""Repository contracts and a deterministic in-memory implementation for tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Protocol

from CoScientist.integrations.codesynapse.models import (
    A2ATaskRecord,
    IntegrationRun,
    TERMINAL_RUN_STATES,
    TraceEvent,
)


class DuplicateIdentityError(ValueError):
    """Raised when a caller attempts to create the same external run twice."""


class IntegrationStore(Protocol):
    async def create_run(self, run: IntegrationRun) -> IntegrationRun: ...

    async def get_run(self, external_run_id: str) -> IntegrationRun | None: ...

    async def get_run_by_coscientist_run(self, coscientist_run_id: str) -> IntegrationRun | None: ...

    async def append_event(self, event: TraceEvent) -> bool: ...

    async def replay_events(self, run_id: str, *, after_sequence: int = 0) -> list[TraceEvent]: ...

    async def pending_events(self, run_id: str) -> list[TraceEvent]: ...

    async def mark_events_delivered(self, event_ids: list[str]) -> None: ...

    async def save_run(self, run: IntegrationRun) -> IntegrationRun: ...

    async def save_run_if_non_terminal(self, run: IntegrationRun) -> bool: ...

    async def save_task(self, task: A2ATaskRecord) -> A2ATaskRecord: ...

    async def save_task_if_non_terminal(self, task: A2ATaskRecord) -> bool: ...

    async def get_task(self, a2a_task_id: str) -> A2ATaskRecord | None: ...

    async def get_task_by_external_run(self, external_run_id: str) -> A2ATaskRecord | None: ...

    async def non_terminal_tasks(self) -> list[A2ATaskRecord]: ...

    async def acquire_run_lease(self, external_run_id: str, owner_id: str, ttl_seconds: float) -> bool: ...

    async def release_run_lease(self, external_run_id: str, owner_id: str) -> None: ...


class InMemoryIntegrationStore:
    """Async in-memory repository with the same idempotency semantics as MongoDB.

    It is intentionally a test/local adapter; production uses MongoDB.
    """

    def __init__(self) -> None:
        self._runs: dict[str, IntegrationRun] = {}
        self._events: dict[str, TraceEvent] = {}
        self._events_by_run: dict[str, list[TraceEvent]] = {}
        self._delivered_event_ids: set[str] = set()
        self._tasks: dict[str, A2ATaskRecord] = {}
        self._leases: dict[str, tuple[str, datetime]] = {}
        self._lock = asyncio.Lock()

    async def create_run(self, run: IntegrationRun) -> IntegrationRun:
        async with self._lock:
            if run.external_run_id in self._runs:
                raise DuplicateIdentityError(f"external run already exists: {run.external_run_id}")
            stored = run.model_copy(deep=True)
            self._runs[stored.external_run_id] = stored
            return stored.model_copy(deep=True)

    async def get_run(self, external_run_id: str) -> IntegrationRun | None:
        async with self._lock:
            run = self._runs.get(external_run_id)
            return run.model_copy(deep=True) if run else None

    async def get_run_by_coscientist_run(self, coscientist_run_id: str) -> IntegrationRun | None:
        async with self._lock:
            for run in self._runs.values():
                if run.coscientist_run_id == coscientist_run_id:
                    return run.model_copy(deep=True)
            return None

    async def save_run(self, run: IntegrationRun) -> IntegrationRun:
        async with self._lock:
            if run.external_run_id not in self._runs:
                raise KeyError(f"external run not found: {run.external_run_id}")
            self._runs[run.external_run_id] = run.model_copy(deep=True)
            return self._runs[run.external_run_id].model_copy(deep=True)

    async def save_run_if_non_terminal(self, run: IntegrationRun) -> bool:
        async with self._lock:
            current = self._runs.get(run.external_run_id)
            if current is None or current.state in TERMINAL_RUN_STATES:
                return False
            self._runs[run.external_run_id] = run.model_copy(deep=True)
            return True

    async def save_task(self, task: A2ATaskRecord) -> A2ATaskRecord:
        async with self._lock:
            conflicting = next(
                (stored for stored in self._tasks.values()
                 if stored.external_run_id == task.external_run_id and stored.a2a_task_id != task.a2a_task_id),
                None,
            )
            if conflicting is not None:
                raise DuplicateIdentityError(f"task already exists for external run {task.external_run_id}")
            self._tasks[task.a2a_task_id] = task.model_copy(deep=True)
            return self._tasks[task.a2a_task_id].model_copy(deep=True)

    async def save_task_if_non_terminal(self, task: A2ATaskRecord) -> bool:
        async with self._lock:
            current = self._tasks.get(task.a2a_task_id)
            if current is None or current.state in TERMINAL_RUN_STATES:
                return False
            self._tasks[task.a2a_task_id] = task.model_copy(deep=True)
            return True

    async def get_task(self, a2a_task_id: str) -> A2ATaskRecord | None:
        async with self._lock:
            task = self._tasks.get(a2a_task_id)
            return task.model_copy(deep=True) if task else None

    async def get_task_by_external_run(self, external_run_id: str) -> A2ATaskRecord | None:
        async with self._lock:
            task = next((item for item in self._tasks.values() if item.external_run_id == external_run_id), None)
            return task.model_copy(deep=True) if task else None

    async def non_terminal_tasks(self) -> list[A2ATaskRecord]:
        async with self._lock:
            return [
                task.model_copy(deep=True)
                for task in self._tasks.values()
                if task.state not in TERMINAL_RUN_STATES
            ]

    async def acquire_run_lease(self, external_run_id: str, owner_id: str, ttl_seconds: float) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("lease ttl must be positive")
        async with self._lock:
            now = datetime.now(timezone.utc)
            current = self._leases.get(external_run_id)
            if current is not None and current[0] != owner_id and current[1] > now:
                return False
            self._leases[external_run_id] = (owner_id, now + timedelta(seconds=ttl_seconds))
            return True

    async def release_run_lease(self, external_run_id: str, owner_id: str) -> None:
        async with self._lock:
            current = self._leases.get(external_run_id)
            if current is not None and current[0] == owner_id:
                self._leases.pop(external_run_id, None)

    async def append_event(self, event: TraceEvent) -> bool:
        """Store a new event, returning False for an idempotent duplicate."""

        async with self._lock:
            if event.event_id in self._events or any(
                stored.run_id == event.run_id and stored.sequence == event.sequence
                for stored in self._events.values()
            ):
                return False
            stored = event.model_copy(deep=True)
            self._events[stored.event_id] = stored
            self._events_by_run.setdefault(stored.run_id, []).append(stored)
            return True

    async def replay_events(self, run_id: str, *, after_sequence: int = 0) -> list[TraceEvent]:
        async with self._lock:
            return [
                event.model_copy(deep=True)
                for event in sorted(self._events_by_run.get(run_id, []), key=lambda item: item.sequence)
                if event.sequence > after_sequence
            ]

    async def pending_events(self, run_id: str) -> list[TraceEvent]:
        async with self._lock:
            return [
                event.model_copy(deep=True)
                for event in sorted(self._events_by_run.get(run_id, []), key=lambda item: item.sequence)
                if event.event_id not in self._delivered_event_ids
            ]

    async def mark_events_delivered(self, event_ids: list[str]) -> None:
        async with self._lock:
            self._delivered_event_ids.update(event_ids)
