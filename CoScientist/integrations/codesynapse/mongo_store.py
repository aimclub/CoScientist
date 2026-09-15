"""Motor-compatible persistent store for CoScientist integration records."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from CoScientist.integrations.codesynapse.models import A2ATaskRecord, IntegrationRun, TERMINAL_RUN_STATES, TraceEvent
from CoScientist.integrations.codesynapse.store import DuplicateIdentityError


class MongoIntegrationStore:
    """Owns only CoScientist collections in its dedicated MongoDB database."""

    def __init__(self, database: Any) -> None:
        self._runs = database["integration_runs"]
        self._tasks = database["a2a_tasks"]
        self._events = database["trace_outbox"]

    @staticmethod
    def _document(model: Any) -> dict[str, Any]:
        return model.model_dump(mode="python")

    async def create_run(self, run: IntegrationRun) -> IntegrationRun:
        if await self._runs.find_one({"external_run_id": run.external_run_id}):
            raise DuplicateIdentityError(f"external run already exists: {run.external_run_id}")
        try:
            await self._runs.insert_one(self._document(run))
        except Exception as exc:
            if getattr(exc, "code", None) == 11000:
                raise DuplicateIdentityError(f"external run already exists: {run.external_run_id}") from exc
            raise
        return run.model_copy(deep=True)

    async def get_run(self, external_run_id: str) -> IntegrationRun | None:
        document = await self._runs.find_one({"external_run_id": external_run_id})
        return IntegrationRun.model_validate(document) if document else None

    async def get_run_by_coscientist_run(self, coscientist_run_id: str) -> IntegrationRun | None:
        document = await self._runs.find_one({"coscientist_run_id": coscientist_run_id})
        return IntegrationRun.model_validate(document) if document else None

    async def save_run(self, run: IntegrationRun) -> IntegrationRun:
        run.updated_at = datetime.now(timezone.utc)
        await self._runs.replace_one({"external_run_id": run.external_run_id}, self._document(run), upsert=False)
        return run.model_copy(deep=True)

    async def save_run_if_non_terminal(self, run: IntegrationRun) -> bool:
        run.updated_at = datetime.now(timezone.utc)
        result = await self._runs.replace_one(
            {
                "external_run_id": run.external_run_id,
                "state": {"$nin": [state.value for state in TERMINAL_RUN_STATES]},
            },
            self._document(run),
            upsert=False,
        )
        return result.matched_count == 1

    async def save_task(self, task: A2ATaskRecord) -> A2ATaskRecord:
        task.updated_at = datetime.now(timezone.utc)
        try:
            await self._tasks.replace_one({"a2a_task_id": task.a2a_task_id}, self._document(task), upsert=True)
        except Exception as exc:
            if getattr(exc, "code", None) == 11000:
                raise DuplicateIdentityError(f"task already exists for external run {task.external_run_id}") from exc
            raise
        return task.model_copy(deep=True)

    async def save_task_if_non_terminal(self, task: A2ATaskRecord) -> bool:
        task.updated_at = datetime.now(timezone.utc)
        result = await self._tasks.replace_one(
            {
                "a2a_task_id": task.a2a_task_id,
                "state": {"$nin": [state.value for state in TERMINAL_RUN_STATES]},
            },
            self._document(task),
            upsert=False,
        )
        return result.matched_count == 1

    async def get_task(self, a2a_task_id: str) -> A2ATaskRecord | None:
        document = await self._tasks.find_one({"a2a_task_id": a2a_task_id})
        return A2ATaskRecord.model_validate(document) if document else None

    async def get_task_by_external_run(self, external_run_id: str) -> A2ATaskRecord | None:
        document = await self._tasks.find_one({"external_run_id": external_run_id})
        return A2ATaskRecord.model_validate(document) if document else None

    async def append_event(self, event: TraceEvent) -> bool:
        if await self._events.find_one({"event_id": event.event_id}):
            return False
        document = self._document(event)
        document.update({"delivery_state": "pending", "attempt_count": 0, "next_attempt_at": event.occurred_at})
        try:
            await self._events.insert_one(document)
        except Exception as exc:
            if getattr(exc, "code", None) == 11000:
                return False
            raise
        return True

    async def replay_events(self, run_id: str, *, after_sequence: int = 0) -> list[TraceEvent]:
        cursor = self._events.find({"run_id": run_id, "sequence": {"$gt": after_sequence}}).sort("sequence", 1)
        return [TraceEvent.model_validate(document) async for document in cursor]

    async def pending_events(self, run_id: str) -> list[TraceEvent]:
        cursor = self._events.find({"run_id": run_id, "delivery_state": "pending"}).sort("sequence", 1)
        return [TraceEvent.model_validate(document) async for document in cursor]

    async def mark_events_delivered(self, event_ids: list[str]) -> None:
        if event_ids:
            await self._events.update_many(
                {"event_id": {"$in": event_ids}},
                {"$set": {"delivery_state": "delivered", "delivered_at": datetime.now(timezone.utc)}},
            )

    async def non_terminal_tasks(self) -> list[A2ATaskRecord]:
        cursor = self._tasks.find({"state": {"$nin": [state.value for state in TERMINAL_RUN_STATES]}})
        return [A2ATaskRecord.model_validate(document) async for document in cursor]

    async def acquire_run_lease(self, external_run_id: str, owner_id: str, ttl_seconds: float) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("lease ttl must be positive")
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        document = await self._runs.find_one_and_update(
            {
                "external_run_id": external_run_id,
                "$or": [
                    {"lease_expires_at": {"$exists": False}},
                    {"lease_expires_at": {"$lte": now}},
                    {"lease_owner": owner_id},
                ],
            },
            {"$set": {"lease_owner": owner_id, "lease_expires_at": expires_at}},
            return_document=True,
        )
        return document is not None

    async def release_run_lease(self, external_run_id: str, owner_id: str) -> None:
        await self._runs.update_one(
            {"external_run_id": external_run_id, "lease_owner": owner_id},
            {"$unset": {"lease_owner": "", "lease_expires_at": ""}},
        )
