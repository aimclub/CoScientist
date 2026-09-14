"""Idempotent MongoDB index setup for CoScientist-owned integration collections."""

from __future__ import annotations

from typing import Any


INDEXES: dict[str, tuple[tuple[list[tuple[str, int]], dict[str, Any]], ...]] = {
    "integration_runs": (([("external_run_id", 1)], {"unique": True, "name": "external_run_id_unique"}), ([("tenant_id", 1), ("project_id", 1), ("state", 1)], {"name": "project_state"})),
    "a2a_tasks": (([("a2a_task_id", 1)], {"unique": True, "name": "a2a_task_id_unique"}), ([("external_run_id", 1)], {"unique": True, "name": "task_external_run_unique"})),
    "trace_outbox": (([("event_id", 1)], {"unique": True, "name": "event_id_unique"}), ([("run_id", 1), ("sequence", 1)], {"unique": True, "name": "run_sequence_unique"}), ([("delivery_state", 1), ("next_attempt_at", 1)], {"name": "delivery_queue"})),
    "hitl_requests": (([("run_id", 1), ("request_id", 1)], {"unique": True, "name": "run_request_unique"}), ([("status", 1), ("deadline_at", 1)], {"name": "pending_deadline"})),
}


async def apply_indexes(database: Any) -> None:
    """Create all indexes safely on every deployment before façade readiness."""

    for collection_name, definitions in INDEXES.items():
        collection = database[collection_name]
        for keys, options in definitions:
            await collection.create_index(keys, **options)


async def main() -> None:
    from motor.motor_asyncio import AsyncIOMotorClient

    from CoScientist.integrations.codesynapse.settings import CodesynapseIntegrationSettings

    settings = CodesynapseIntegrationSettings()
    if not settings.mongo_uri:
        raise RuntimeError("CODESYNAPSE_MONGO_URI is required for migrations")
    client = AsyncIOMotorClient(settings.mongo_uri)
    try:
        await apply_indexes(client[settings.mongo_database])
    finally:
        client.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
