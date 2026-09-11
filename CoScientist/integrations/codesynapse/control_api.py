"""Capability-protected internal control-plane endpoints for Codesynapse."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping

from fastapi import APIRouter, Header, HTTPException, Response

from CoScientist.hitl.models import HITLResponse


class RunCapabilityValidator:
    """Validate a short-lived per-run bearer capability by its stored hash."""

    def __init__(self, token_hashes: Mapping[str, str]) -> None:
        self._token_hashes = dict(token_hashes)

    async def authorize(self, run_id: str, authorization: str | None) -> bool:
        if not authorization or not authorization.startswith("Bearer "):
            return False
        expected = self._token_hashes.get(run_id)
        if expected is None:
            return False
        actual = hashlib.sha256(authorization.removeprefix("Bearer ").encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual, expected)


class StoreCapabilityValidator:
    """Resolve a per-run control capability hash from durable façade state."""

    def __init__(self, store) -> None:
        self._store = store

    async def authorize(self, run_id: str, authorization: str | None) -> bool:
        if not authorization or not authorization.startswith("Bearer "):
            return False
        run = await self._store.get_run_by_coscientist_run(run_id)
        if run is None or not run.control_token_hash:
            return False
        actual = hashlib.sha256(authorization.removeprefix("Bearer ").encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual, run.control_token_hash)


def make_control_router(facade, store, validator) -> APIRouter:
    """Build idempotent HITL, cancellation and trace-replay endpoints."""

    router = APIRouter(prefix="/internal/runs")

    async def require_capability(run_id: str, authorization: str | None) -> None:
        if not await validator.authorize(run_id, authorization):
            raise HTTPException(status_code=401, detail="invalid run capability")

    @router.post("/{run_id}/hitl/{request_id}/resolve", status_code=204)
    async def resolve_hitl(
        run_id: str,
        request_id: str,
        response: HITLResponse,
        authorization: str | None = Header(default=None),
    ):
        await require_capability(run_id, authorization)
        # Codesynapse persists an answer before delivery and can safely replay it,
        # but a completed/cancelled request must not be acknowledged as accepted.
        if not await facade.resolve_hitl(run_id, request_id, response):
            raise HTTPException(status_code=409, detail="HITL request is no longer pending")
        return Response(status_code=204)

    @router.post("/{run_id}/cancel", status_code=204)
    async def cancel_run(run_id: str, authorization: str | None = Header(default=None)):
        await require_capability(run_id, authorization)
        if not await facade.cancel_by_run(run_id):
            raise HTTPException(status_code=404, detail="active run not found")
        return Response(status_code=204)

    @router.get("/{run_id}/trace")
    async def replay_trace(run_id: str, after_sequence: int = 0, authorization: str | None = Header(default=None)):
        await require_capability(run_id, authorization)
        events = await store.replay_events(run_id, after_sequence=after_sequence)
        return {"events": [event.model_dump(mode="json") for event in events]}

    return router
