"""Run-scoped HITL bridge used by the Codesynapse façade."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from CoScientist.hitl.handler import AbstractHITLHandler
from CoScientist.hitl.models import HITLRequest, HITLResponse

EmitCallable = Callable[..., Awaitable[Any]]


class HITLRequestTimeout(TimeoutError):
    """The human did not answer before the explicit request deadline."""


class HITLRequestCancelled(RuntimeError):
    """The parent run was cancelled while a human answer was pending."""


class CodesynapseHITLHandler(AbstractHITLHandler):
    """A handler whose pending futures are isolated to one CoScientist run."""

    def __init__(self, *, run_id: str, emit: EmitCallable, default_timeout_seconds: float = 900.0) -> None:
        self._run_id = run_id
        self._emit = emit
        self._default_timeout_seconds = default_timeout_seconds
        self._pending: dict[str, asyncio.Future[HITLResponse]] = {}
        self._lock = asyncio.Lock()

    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        request_id = str(uuid4())
        future: asyncio.Future[HITLResponse] = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._pending[request_id] = future
        await self._emit(
            "hitl.requested",
            data={
                "request_id": request_id,
                "agent_name": request.agent_name,
                "action_type": request.action_type.value,
                "message": request.message,
                "options": request.options,
                "context": request.context,
                "invoked_via": request.invoked_via,
            },
        )
        timeout = request.timeout_seconds or self._default_timeout_seconds
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            await self._emit("hitl.expired", data={"request_id": request_id})
            raise HITLRequestTimeout(f"HITL request timed out: {request_id}") from exc
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)
        await self._emit("hitl.resolved", data={"request_id": request_id, "approved": response.approved})
        return response

    async def resolve(self, request_id: str, response: HITLResponse) -> bool:
        """Resolve one request; a stale/replayed request id is harmless."""

        async with self._lock:
            future = self._pending.get(request_id)
            if future is None or future.done():
                return False
            future.set_result(response)
            return True

    async def cancel_pending(self) -> None:
        """Fail all pending requests so the parent execution can terminate promptly."""

        async with self._lock:
            futures = list(self._pending.items())
        for request_id, future in futures:
            if not future.done():
                future.set_exception(HITLRequestCancelled(f"run cancelled: {self._run_id}"))
                await self._emit("hitl.cancelled", data={"request_id": request_id})
