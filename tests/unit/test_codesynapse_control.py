import asyncio
import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from CoScientist.integrations.codesynapse.control_api import RunCapabilityValidator, make_control_router
from CoScientist.integrations.codesynapse.models import TraceEvent


def test_capability_validator_accepts_only_matching_run_hash():
    async def scenario():
        validator = RunCapabilityValidator({"run-1": hashlib.sha256(b"token-1").hexdigest()})

        assert await validator.authorize("run-1", "Bearer token-1")
        assert not await validator.authorize("run-1", "Bearer token-2")
        assert not await validator.authorize("run-2", "Bearer token-1")

    asyncio.run(scenario())


def test_control_router_requires_capability_and_exposes_replay():
    class Facade:
        async def resolve_hitl(self, run_id, request_id, response):
            return run_id == "run-1" and request_id == "request-1" and response.approved

        async def cancel_by_run(self, run_id):
            return run_id == "run-1"

    class Store:
        async def replay_events(self, run_id, *, after_sequence=0):
            return [
                TraceEvent(
                    event_id="event-1",
                    run_id=run_id,
                    sequence=after_sequence + 1,
                    tenant_id="root",
                    project_id="project-1",
                    type="run.started",
                )
            ]

    validator = RunCapabilityValidator({"run-1": hashlib.sha256(b"token-1").hexdigest()})
    app = FastAPI()
    app.include_router(make_control_router(Facade(), Store(), validator))
    client = TestClient(app)
    headers = {"Authorization": "Bearer token-1"}

    resolved = client.post(
        "/internal/runs/run-1/hitl/request-1/resolve",
        headers=headers,
        json={"action": "approve", "approved": True},
    )
    replay = client.get("/internal/runs/run-1/trace?after_sequence=0", headers=headers)

    assert resolved.status_code == 204
    assert replay.json()["events"][0]["event_id"] == "event-1"


def test_control_router_rejects_a_stale_hitl_response():
    class Facade:
        async def resolve_hitl(self, run_id, request_id, response):
            return False

        async def cancel_by_run(self, run_id):
            return False

    class Store:
        async def replay_events(self, run_id, *, after_sequence=0):
            return []

    validator = RunCapabilityValidator({"run-1": hashlib.sha256(b"token-1").hexdigest()})
    app = FastAPI()
    app.include_router(make_control_router(Facade(), Store(), validator))
    response = TestClient(app).post(
        "/internal/runs/run-1/hitl/already-finished/resolve",
        headers={"Authorization": "Bearer token-1"},
        json={"action": "approve", "approved": True},
    )

    assert response.status_code == 409
