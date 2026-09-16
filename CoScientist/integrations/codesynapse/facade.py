"""Long-running, idempotent façade over the full CoScientist pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from CoScientist.integrations.codesynapse.executor import PipelineExecutor
from CoScientist.integrations.codesynapse.artifact_client import CodesynapseArtifactClient
from CoScientist.integrations.codesynapse.hitl import CodesynapseHITLHandler, HITLRequestTimeout
from CoScientist.integrations.codesynapse.models import (
    A2ATaskRecord,
    ArtifactPart,
    IntegrationRun,
    RunState,
    TERMINAL_RUN_STATES,
    TerminalArtifacts,
    TraceEvent,
)
from CoScientist.integrations.codesynapse.state import transition
from CoScientist.integrations.codesynapse.store import DuplicateIdentityError, IntegrationStore
from CoScientist.integrations.codesynapse.trace import TraceRecorder


logger = logging.getLogger(__name__)

ProgressSubscriber = Callable[[TraceEvent], Awaitable[None]]


class StartRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    external_run_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    research_request: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    coscientist_run_id: str | None = None
    control_token_hash: str | None = None
    trace_callback_url: str | None = Field(default=None, exclude=True)
    trace_capability_token: str | None = Field(default=None, exclude=True)
    artifact_upload_url: str | None = Field(default=None, exclude=True)
    artifact_finalize_url: str | None = Field(default=None, exclude=True)
    artifact_capability_token: str | None = Field(default=None, exclude=True)
    trace_recorder: object | None = Field(default=None, exclude=True)
    a2a_task_id: str | None = None
    progress_subscriber: ProgressSubscriber | None = Field(default=None, exclude=True)


class CodesynapseFacade:
    """Creates one durable task per external identity and executes it asynchronously."""

    def __init__(
        self,
        *,
        store: IntegrationStore,
        executor: PipelineExecutor,
        delivery_factory: Callable[[StartRequest], object | None] | None = None,
        lease_ttl_seconds: float = 3600.0,
    ) -> None:
        self._store = store
        self._executor = executor
        self._delivery_factory = delivery_factory
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._handlers: dict[str, CodesynapseHITLHandler] = {}
        self._task_ids_by_run: dict[str, str] = {}
        self._progress_subscribers: dict[str, set[ProgressSubscriber]] = {}
        self._delivery_dispatchers: dict[str, object] = {}
        self._delivery_retries: dict[str, asyncio.Task[None]] = {}
        self._cancelling_tasks: set[str] = set()
        self._task_locks: dict[str, asyncio.Lock] = {}
        self._start_lock = asyncio.Lock()
        self._execution_capacity = asyncio.Semaphore(1)
        self._lease_owner_id = str(uuid4())
        self._lease_ttl_seconds = lease_ttl_seconds

    def set_delivery_factory(self, delivery_factory: Callable[[StartRequest], object | None]) -> None:
        """Attach trace delivery without coupling durable state to HTTP transport."""

        self._delivery_factory = delivery_factory

    async def start(self, request: StartRequest, *, run_in_background: bool = True) -> A2ATaskRecord:
        """Idempotently create an A2A task, returning a working task immediately."""

        async with self._start_lock:
            existing = await self._store.get_run(request.external_run_id)
            if existing is not None:
                if existing.a2a_task_id is None:
                    raise RuntimeError("existing integration run has no A2A task id")
                task = await self._store.get_task(existing.a2a_task_id)
                if task is None:
                    raise RuntimeError("existing integration run has no persisted task")
                self._subscribe_progress(task.a2a_task_id, request.progress_subscriber)
                return task

            coscientist_run_id = request.coscientist_run_id or str(uuid4())
            a2a_task_id = request.a2a_task_id or str(uuid4())
            run = IntegrationRun(
                external_run_id=request.external_run_id,
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                state=RunState.STARTING,
                a2a_task_id=a2a_task_id,
                coscientist_run_id=coscientist_run_id,
                control_token_hash=request.control_token_hash,
            )
            task = A2ATaskRecord(
                a2a_task_id=a2a_task_id,
                external_run_id=request.external_run_id,
                coscientist_run_id=coscientist_run_id,
                state=RunState.RUNNING,
            )
            # Write the dependent task first: a process crash can then leave an
            # auditable orphan, but never a durable run that cannot answer
            # canonical A2A tasks/get. The unique indexes decide the winner.
            try:
                await self._store.save_task(task)
            except DuplicateIdentityError:
                existing_task = await self._store.get_task_by_external_run(request.external_run_id)
                if existing_task is None:
                    raise
                task = existing_task
                run = run.model_copy(update={
                    "a2a_task_id": task.a2a_task_id,
                    "coscientist_run_id": task.coscientist_run_id,
                })
            try:
                await self._store.create_run(run)
            except DuplicateIdentityError:
                # The process-local lock cannot coordinate two façade replicas.
                # MongoDB's unique external_run_id index is the cross-process
                # idempotency boundary; return the task created by the winner.
                existing = await self._store.get_run(request.external_run_id)
                if existing is None or existing.a2a_task_id is None:
                    raise
                task = await self._store.get_task(existing.a2a_task_id)
                if task is None:
                    raise RuntimeError("existing integration run has no persisted task")
                self._subscribe_progress(task.a2a_task_id, request.progress_subscriber)
                return task
            a2a_task_id = task.a2a_task_id
            coscientist_run_id = task.coscientist_run_id
            self._task_ids_by_run[coscientist_run_id] = a2a_task_id
            self._subscribe_progress(a2a_task_id, request.progress_subscriber)

        if run_in_background:
            if self._delivery_factory is not None:
                self._delivery_dispatchers[coscientist_run_id] = self._delivery_factory(request)
            self._jobs[a2a_task_id] = asyncio.create_task(self._execute(request, a2a_task_id, coscientist_run_id))
            return task
        if self._delivery_factory is not None:
            self._delivery_dispatchers[coscientist_run_id] = self._delivery_factory(request)
        await self._execute(request, a2a_task_id, coscientist_run_id)
        completed = await self._store.get_task(a2a_task_id)
        if completed is None:
            raise RuntimeError("task disappeared during execution")
        return completed

    async def get_task(self, a2a_task_id: str) -> A2ATaskRecord | None:
        return await self._store.get_task(a2a_task_id)

    async def wait_for_terminal_task(self, a2a_task_id: str) -> A2ATaskRecord:
        """Wait without cancelling the durable scientific job when a client disconnects."""

        while True:
            task = await self.get_task(a2a_task_id)
            if task is None:
                raise RuntimeError("A2A task disappeared while streaming")
            if task.state in TERMINAL_RUN_STATES:
                return task
            job = self._jobs.get(a2a_task_id)
            if job is not None:
                await asyncio.shield(job)
            else:
                await asyncio.sleep(0.1)

    def unsubscribe_progress(self, a2a_task_id: str, subscriber: ProgressSubscriber) -> None:
        subscribers = self._progress_subscribers.get(a2a_task_id)
        if subscribers is None:
            return
        subscribers.discard(subscriber)
        if not subscribers:
            self._progress_subscribers.pop(a2a_task_id, None)

    def _subscribe_progress(self, a2a_task_id: str, subscriber: ProgressSubscriber | None) -> None:
        if subscriber is not None:
            self._progress_subscribers.setdefault(a2a_task_id, set()).add(subscriber)

    async def _publish_progress(self, a2a_task_id: str, event: TraceEvent) -> None:
        for subscriber in tuple(self._progress_subscribers.get(a2a_task_id, ())):
            try:
                await subscriber(event)
            except Exception:
                logger.warning(
                    "[A2A_PROGRESS] task_id=%s event_id=%s — subscriber disconnected",
                    a2a_task_id,
                    event.event_id,
                    exc_info=True,
                )
                self.unsubscribe_progress(a2a_task_id, subscriber)

    async def _schedule_outbox_retry(self, run_id: str, dispatcher: object) -> None:
        """Keep retrying a persisted outbox after a callback failure."""

        if not await self._store.pending_events(run_id):
            return
        retry = getattr(dispatcher, "retry_pending", None)
        if not callable(retry):
            return
        existing = self._delivery_retries.get(run_id)
        if existing is not None and not existing.done():
            return
        job = asyncio.create_task(retry(run_id, sleep=asyncio.sleep))
        self._delivery_retries[run_id] = job
        job.add_done_callback(lambda _completed: self._delivery_retries.pop(run_id, None))

    async def _flush_trace_delivery(self, run_id: str, dispatcher: object | None) -> None:
        """Deliver durable events without making callback availability fatal to the run."""

        if dispatcher is None:
            return
        try:
            await dispatcher.flush_run(run_id)
            await self._schedule_outbox_retry(run_id, dispatcher)
        except Exception:
            logger.warning("[TRACE_DELIVERY] run_id=%s — callback attempt failed", run_id, exc_info=True)

    async def cancel(self, a2a_task_id: str) -> bool:
        """Idempotently cancel a live task and publish a terminal cancelled view."""

        lock = self._task_locks.setdefault(a2a_task_id, asyncio.Lock())
        async with lock:
            task = await self._store.get_task(a2a_task_id)
            if task is None:
                return False
            if task.state in TERMINAL_RUN_STATES:
                return task.state == RunState.CANCELLED
            run = await self._store.get_run(task.external_run_id)
            handler = self._handlers.get(task.coscientist_run_id)
            if handler is not None:
                await handler.cancel_pending()

            # The persisted task is the cancellation fence.  It is written
            # before cancelling the in-memory job, so a slow executor cannot
            # later replace the A2A terminal state with a late result.
            self._cancelling_tasks.add(a2a_task_id)
            cancellation_task = self._error_task(
                task.a2a_task_id,
                task.external_run_id,
                task.coscientist_run_id,
                RunState.CANCELLED,
                "cancelled",
            )
            if not await self._store.save_task_if_non_terminal(cancellation_task):
                self._cancelling_tasks.discard(a2a_task_id)
                current = await self._store.get_task(a2a_task_id)
                return current is not None and current.state == RunState.CANCELLED
            if run is not None and run.state not in TERMINAL_RUN_STATES:
                if run.state in {RunState.RUNNING, RunState.WAITING_FOR_HUMAN}:
                    run.state = transition(run.state, RunState.CANCELLING)
                run.state = transition(run.state, RunState.CANCELLED)
                run.terminal_reason = "cancelled"
                run.updated_at = datetime.now(timezone.utc)
                await self._store.save_run_if_non_terminal(run)
                event = await TraceRecorder(
                    self._store,
                    run_id=task.coscientist_run_id,
                    tenant_id=run.tenant_id,
                    project_id=run.project_id,
                ).emit("run.cancelled", data={"error_code": "cancelled"})
                await self._publish_progress(task.a2a_task_id, event)
                await self._flush_trace_delivery(
                    task.coscientist_run_id,
                    self._delivery_dispatchers.get(task.coscientist_run_id),
                )

            # A2A cancellation is an acknowledgement, not a join on the
            # scientific pipeline.  _execute performs eventual cleanup.
            job = self._jobs.get(a2a_task_id)
            if job is not None:
                job.cancel()
        return True

    async def resolve_hitl(self, coscientist_run_id: str, request_id: str, response) -> bool:
        handler = self._handlers.get(coscientist_run_id)
        return await handler.resolve(request_id, response) if handler is not None else False

    async def cancel_by_run(self, coscientist_run_id: str) -> bool:
        task_id = self._task_ids_by_run.get(coscientist_run_id)
        if task_id is None:
            run = await self._store.get_run_by_coscientist_run(coscientist_run_id)
            task_id = run.a2a_task_id if run is not None else None
        return await self.cancel(task_id) if task_id else False

    async def _execute(self, request: StartRequest, a2a_task_id: str, coscientist_run_id: str) -> None:
        """Serialize manager execution while leaving A2A control endpoints responsive."""

        async with self._execution_capacity:
            await self._execute_with_capacity(request, a2a_task_id, coscientist_run_id)

    async def _execute_with_capacity(
        self, request: StartRequest, a2a_task_id: str, coscientist_run_id: str
    ) -> None:
        if not await self._store.acquire_run_lease(
            request.external_run_id, self._lease_owner_id, self._lease_ttl_seconds
        ):
            return
        lock = self._task_locks.setdefault(a2a_task_id, asyncio.Lock())
        try:
            async with lock:
                run = await self._store.get_run(request.external_run_id)
                task = await self._store.get_task(a2a_task_id)
                if run is None or task is None or run.state in TERMINAL_RUN_STATES or task.state in TERMINAL_RUN_STATES:
                    return
                run.state = transition(run.state, RunState.RUNNING)
                run.updated_at = datetime.now(timezone.utc)
                if not await self._store.save_run_if_non_terminal(run):
                    return

            dispatcher = self._delivery_dispatchers.get(coscientist_run_id)

            async def flush_trace_event(event: TraceEvent) -> None:
                await self._publish_progress(a2a_task_id, event)
                await self._flush_trace_delivery(coscientist_run_id, dispatcher)

            recorder = TraceRecorder(
                self._store,
                run_id=coscientist_run_id,
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                on_event=flush_trace_event,
            )

            async def emit_hitl_event(event_type: str, **fields: Any) -> None:
                current = await self._store.get_run(request.external_run_id)
                if current is not None:
                    if event_type == "hitl.requested" and current.state == RunState.RUNNING:
                        current.state = transition(current.state, RunState.WAITING_FOR_HUMAN)
                        await self._store.save_run_if_non_terminal(current)
                    elif event_type in {"hitl.resolved", "hitl.expired"} and current.state == RunState.WAITING_FOR_HUMAN:
                        current.state = transition(current.state, RunState.RUNNING)
                        await self._store.save_run_if_non_terminal(current)
                await recorder.emit(event_type, **fields)

            handler = CodesynapseHITLHandler(run_id=coscientist_run_id, emit=emit_hitl_event)
            self._handlers[coscientist_run_id] = handler
            await recorder.emit("run.started", data={"external_run_id": request.external_run_id})
            execution_request = request.model_copy(update={"coscientist_run_id": coscientist_run_id, "trace_recorder": recorder})
            report = await self._executor.execute(execution_request, handler)
            report_part = await self._report_part(request, report)
            run.state = transition(run.state, RunState.COMPLETED)
            task = A2ATaskRecord(
                a2a_task_id=a2a_task_id,
                external_run_id=request.external_run_id,
                coscientist_run_id=coscientist_run_id,
                state=RunState.COMPLETED,
                artifacts=TerminalArtifacts(
                    state=RunState.COMPLETED,
                    final_report=report_part,
                ),
            )
            event_type = "run.completed"
            event_data: dict[str, Any] = {}
        except asyncio.CancelledError:
            cancelled = a2a_task_id in self._cancelling_tasks
            state = RunState.CANCELLED if cancelled else RunState.INTERRUPTED
            error_code = "cancelled" if cancelled else "interrupted"
            run.state = state
            run.terminal_reason = error_code
            task = self._error_task(a2a_task_id, request.external_run_id, coscientist_run_id, state, error_code)
            event_type = "run.cancelled" if cancelled else "run.failed"
            event_data = {"error_code": error_code}
        except HITLRequestTimeout as exc:
            run.state = RunState.FAILED
            task = self._error_task(a2a_task_id, request.external_run_id, coscientist_run_id, RunState.FAILED, "hitl_timeout", str(exc))
            event_type = "run.failed"
            event_data = {"error_code": "hitl_timeout", "message": str(exc)}
        except Exception as exc:  # terminal failures are surfaced as structured error artifacts
            run.state = RunState.FAILED
            task = self._error_task(a2a_task_id, request.external_run_id, coscientist_run_id, RunState.FAILED, "execution_failed", str(exc))
            event_type = "run.failed"
            event_data = {"error_code": "execution_failed", "message": str(exc)}

        try:
            async with lock:
                persisted_task = await self._store.get_task(a2a_task_id)
                if persisted_task is not None and persisted_task.state == RunState.CANCELLED:
                    return
                if not await self._store.save_task_if_non_terminal(task):
                    return
                run.updated_at = datetime.now(timezone.utc)
                await self._store.save_run_if_non_terminal(run)
            await recorder.emit(event_type, data=event_data)
        finally:
            await self._store.release_run_lease(request.external_run_id, self._lease_owner_id)
            self._jobs.pop(a2a_task_id, None)
            self._handlers.pop(coscientist_run_id, None)
            self._delivery_dispatchers.pop(coscientist_run_id, None)
            self._cancelling_tasks.discard(a2a_task_id)
            self._task_locks.pop(a2a_task_id, None)

    @staticmethod
    async def _report_part(request: StartRequest, report: str) -> ArtifactPart:
        if len(report.encode("utf-8")) <= 512 * 1024:
            return ArtifactPart(name="final_report", mime_type="text/markdown", text=report)
        return await CodesynapseArtifactClient(
            upload_request_url=request.artifact_upload_url or "",
            finalize_url=request.artifact_finalize_url or "",
            capability_token=request.artifact_capability_token or "",
        ).upload_text(
            name="final_report",
            filename="final_report.md",
            text=report,
            mime_type="text/markdown",
        )

    @staticmethod
    def _error_task(
        a2a_task_id: str,
        external_run_id: str,
        coscientist_run_id: str,
        state: RunState,
        error_code: str,
        message: str | None = None,
    ) -> A2ATaskRecord:
        return A2ATaskRecord(
            a2a_task_id=a2a_task_id,
            external_run_id=external_run_id,
            coscientist_run_id=coscientist_run_id,
            state=state,
            artifacts=TerminalArtifacts(
                state=state,
                error=ArtifactPart(
                    name="error",
                    mime_type="application/json",
                    data={"error_code": error_code, "message": message or error_code, "retryable": False},
                ),
            ),
        )

    async def interrupt_non_terminal_tasks(self) -> int:
        """MVP restart rule: pending in-memory execution cannot be resumed."""

        tasks = await self._store.non_terminal_tasks()
        jobs: list[asyncio.Task[None]] = []
        for task in tasks:
            job = self._jobs.pop(task.a2a_task_id, None)
            if job is not None:
                job.cancel()
                jobs.append(job)
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        for task in tasks:
            run = await self._store.get_run(task.external_run_id)
            if run is not None:
                run.state = RunState.INTERRUPTED
                run.terminal_reason = "interrupted"
                run.updated_at = datetime.now(timezone.utc)
                await self._store.save_run(run)
            await self._store.save_task(
                self._error_task(
                    task.a2a_task_id,
                    task.external_run_id,
                    task.coscientist_run_id,
                    RunState.INTERRUPTED,
                    "interrupted",
                )
            )
        return len(tasks)
