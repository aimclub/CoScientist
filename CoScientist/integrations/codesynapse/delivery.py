"""HTTP delivery of durable trace batches to Codesynapse."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from CoScientist.integrations.codesynapse.models import TraceEvent
from CoScientist.integrations.codesynapse.trace import batch_events

PostCallable = Callable[..., Awaitable[Any]]


class TraceDeliveryClient:
    """Deliver a batch using a per-run capability, never a JWT."""

    def __init__(self, *, callback_url: str, capability_token: str, post: PostCallable | None = None) -> None:
        self._callback_url = callback_url
        self._capability_token = capability_token
        self._post = post

    async def deliver(self, events: list[TraceEvent]) -> bool:
        if not events:
            return True
        headers = {"Authorization": f"Bearer {self._capability_token}"}
        payload = {"events": [event.model_dump(mode="json") for event in events]}
        try:
            if self._post is not None:
                response = await self._post(self._callback_url, headers=headers, json=payload)
                return 200 <= response.status_code < 300
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self._callback_url, headers=headers, json=payload)
                return response.is_success
        except httpx.HTTPError:
            # A delivery failure must leave the durable outbox pending. It is
            # not a failure of the scientific run itself.
            return False


class TraceOutboxDispatcher:
    """Flush one run in sequence; delivery is safe to retry after a failure."""

    def __init__(self, store, client: TraceDeliveryClient) -> None:
        self._store = store
        self._client = client

    async def flush_run(self, run_id: str) -> int:
        delivered_count = 0
        for batch in batch_events(await self._store.pending_events(run_id)):
            if not await self._client.deliver(batch):
                break
            await self._store.mark_events_delivered([event.event_id for event in batch])
            delivered_count += len(batch)
        return delivered_count

    async def retry_pending(
        self,
        run_id: str,
        *,
        sleep: Callable[[float], Awaitable[None]],
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
    ) -> None:
        """Retry a durable run outbox until every event receives a 2xx response."""

        delay = initial_delay_seconds
        while await self._store.pending_events(run_id):
            await self.flush_run(run_id)
            if not await self._store.pending_events(run_id):
                return
            await sleep(delay)
            delay = min(delay * 2, max_delay_seconds)
