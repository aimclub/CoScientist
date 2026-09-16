"""Process-isolated execution of one CoScientist manager run.

The façade process owns all durable state.  The child process contains only
the manager, so cancellation can terminate an uncooperative provider/tool call
without killing the HTTP control plane.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import queue
import traceback
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from CoScientist.hitl.handler import AbstractHITLHandler
from CoScientist.hitl.models import HITLRequest, HITLResponse


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


class _ChildTraceRecorder:
    def __init__(self, events) -> None:
        self._events = events

    async def emit(self, event_type: str, **fields: Any) -> None:
        self._events.put(("trace", event_type, _json_safe(fields)))


class _ChildHITLHandler(AbstractHITLHandler):
    def __init__(self, events, controls) -> None:
        self._events = events
        self._controls = controls

    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        request_id = str(uuid4())
        self._events.put(("hitl", request_id, request.model_dump(mode="json")))
        while True:
            message = await asyncio.to_thread(self._controls.get)
            if message[0] == "cancel":
                raise asyncio.CancelledError
            if message[0] == "hitl_response" and message[1] == request_id:
                return HITLResponse.model_validate(message[2])


def _run_manager_child(payload: dict[str, Any], events, controls) -> None:
    async def run() -> str:
        from CoScientist.main import CoScientistManager
        from CoScientist.integrations.codesynapse.trace_plugin import CodesynapseTracePlugin

        manager = CoScientistManager(
            app_name=f"codesynapse-{payload['coscientist_run_id']}",
            user_id=payload["tenant_id"],
            session_id=payload["coscientist_run_id"],
            initial_state={"codesynapse_context": payload["context"]},
            hitl_handler=_ChildHITLHandler(events, controls),
            plugins=[CodesynapseTracePlugin(_ChildTraceRecorder(events))],
        )
        try:
            return str(await manager.run(payload["research_request"], verbose=False))
        finally:
            await manager.close()

    try:
        events.put(("result", asyncio.run(run())))
    except BaseException as exc:  # transmit a serialisable terminal error to parent
        events.put(("error", type(exc).__name__, str(exc), traceback.format_exc()))


class ProcessManagerPipelineExecutor:
    """Run the existing manager in a killable child process."""

    def __init__(
        self,
        *,
        terminate_grace_seconds: float = 5.0,
        worker_target: Callable[..., None] = _run_manager_child,
    ) -> None:
        self._terminate_grace_seconds = terminate_grace_seconds
        self._worker_target = worker_target

    async def execute(self, request: object, hitl_handler: AbstractHITLHandler) -> str:
        context = mp.get_context("spawn")
        events = context.Queue()
        controls = context.Queue()
        payload = {
            "coscientist_run_id": request.coscientist_run_id,
            "tenant_id": request.tenant_id,
            "research_request": request.research_request,
            "context": request.context,
        }
        process = context.Process(target=self._worker_target, args=(payload, events, controls), daemon=True)
        process.start()
        try:
            while True:
                try:
                    message = await asyncio.to_thread(events.get, True, 0.1)
                except queue.Empty:
                    if not process.is_alive():
                        raise RuntimeError(f"manager process exited with code {process.exitcode}")
                    continue
                kind, *values = message
                if kind == "trace":
                    recorder = getattr(request, "trace_recorder", None)
                    if recorder is not None:
                        await recorder.emit(values[0], **values[1])
                elif kind == "hitl":
                    response = await hitl_handler.handle_request(HITLRequest.model_validate(values[1]))
                    controls.put(("hitl_response", values[0], response.model_dump(mode="json")))
                elif kind == "result":
                    return values[0]
                elif kind == "error":
                    raise RuntimeError(f"manager process failed: {values[0]}: {values[1]}")
        except asyncio.CancelledError:
            controls.put(("cancel",))
            raise
        finally:
            await self._stop_process(process)
            events.close()
            controls.close()

    async def _stop_process(self, process) -> None:
        if not process.is_alive():
            await asyncio.to_thread(process.join)
            return
        process.terminate()
        await asyncio.to_thread(process.join, self._terminate_grace_seconds)
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join)
