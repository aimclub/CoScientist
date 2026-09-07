"""Adapter that runs the existing full CoScientist manager for the façade."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from CoScientist.hitl.handler import AbstractHITLHandler
from CoScientist.hitl.models import HITLRequest, HITLResponse


class _ControlLoopHITLHandler(AbstractHITLHandler):
    """Bridge manager-thread HITL requests back to the façade event loop."""

    def __init__(self, delegate: AbstractHITLHandler, control_loop: asyncio.AbstractEventLoop) -> None:
        self._delegate = delegate
        self._control_loop = control_loop

    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        future = asyncio.run_coroutine_threadsafe(
            self._delegate.handle_request(request), self._control_loop
        )
        return await asyncio.wrap_future(future)


class _ControlLoopTraceRecorder:
    """Bridge manager-thread trace writes back to the façade event loop."""

    def __init__(self, delegate: Any, control_loop: asyncio.AbstractEventLoop) -> None:
        self._delegate = delegate
        self._control_loop = control_loop

    async def emit(self, *args: Any, **kwargs: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(
            self._delegate.emit(*args, **kwargs), self._control_loop
        )
        return await asyncio.wrap_future(future)


class PipelineExecutor(Protocol):
    async def execute(self, request: object, hitl_handler: AbstractHITLHandler) -> str: ...


class ManagerPipelineExecutor:
    """Production executor retaining the existing full-manager execution path."""

    async def execute(self, request: object, hitl_handler: AbstractHITLHandler) -> str:
        control_loop = asyncio.get_running_loop()

        def run_in_manager_thread() -> str:
            return asyncio.run(
                self._run_manager(request, hitl_handler, control_loop)
            )

        # ADK integrations can invoke synchronous provider or tool code while
        # advancing their async generator. Keep that work out of the FastAPI
        # loop so A2A tasks/get, tasks/cancel and health checks stay available.
        return await asyncio.to_thread(run_in_manager_thread)

    async def _run_manager(
        self,
        request: object,
        hitl_handler: AbstractHITLHandler,
        control_loop: asyncio.AbstractEventLoop,
    ) -> str:
        # Delayed import keeps contract tests independent of model/MCP setup.
        from CoScientist.main import CoScientistManager

        plugins = []
        trace_recorder = getattr(request, "trace_recorder", None)
        if trace_recorder is not None:
            from CoScientist.integrations.codesynapse.trace_plugin import CodesynapseTracePlugin

            plugins.append(
                CodesynapseTracePlugin(
                    _ControlLoopTraceRecorder(trace_recorder, control_loop)
                )
            )
        manager = CoScientistManager(
            app_name=f"codesynapse-{request.coscientist_run_id}",
            user_id=request.tenant_id,
            session_id=request.coscientist_run_id,
            hitl_handler=_ControlLoopHITLHandler(hitl_handler, control_loop),
            plugins=plugins,
        )
        try:
            return str(await manager.run(request.research_request, verbose=False))
        finally:
            await manager.close()
