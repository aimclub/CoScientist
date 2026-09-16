"""A2A 0.3 adapter for persistent façade task records."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks.task_store import TaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    DataPart,
    Message,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from CoScientist.integrations.codesynapse.facade import CodesynapseFacade, StartRequest
from CoScientist.integrations.codesynapse.models import A2ATaskRecord, ArtifactPart, RunState, TraceEvent


def _a2a_state(state: RunState) -> TaskState:
    if state == RunState.COMPLETED:
        return TaskState.completed
    if state == RunState.CANCELLED:
        return TaskState.canceled
    if state in {RunState.FAILED, RunState.INTERRUPTED}:
        return TaskState.failed
    return TaskState.working


def _artifact_parts(part: ArtifactPart) -> list[Any]:
    if part.text is not None:
        return [TextPart(text=part.text)]
    if part.data is not None:
        return [DataPart(data=part.data)]
    return [
        DataPart(
            data={
                "artifact_id": part.artifact_id,
                "checksum_sha256": part.checksum_sha256,
                "mime_type": part.mime_type,
            }
        )
    ]


def task_from_record(record: A2ATaskRecord, *, context_id: str) -> Task:
    """Produce a current A2A task view from durable façade state."""

    artifacts = []
    if record.artifacts is not None:
        for part in (
            record.artifacts.final_report,
            record.artifacts.structured_result,
            record.artifacts.artifacts_manifest,
            record.artifacts.error,
        ):
            if part is not None:
                artifacts.append(
                    Artifact(
                        artifact_id=f"{record.a2a_task_id}:{part.name}",
                        name=part.name,
                        description=part.mime_type,
                        parts=_artifact_parts(part),
                    )
                )
    return Task(
        id=record.a2a_task_id,
        context_id=context_id,
        status=TaskStatus(state=_a2a_state(record.state)),
        artifacts=artifacts or None,
    )


def progress_from_trace(event: TraceEvent, *, a2a_task_id: str, context_id: str) -> TaskStatusUpdateEvent:
    """Expose a redacted trace fact as a non-terminal standard A2A update."""

    tool_name = event.data.get("tool_name")
    subject = " · ".join(part for part in (event.agent, tool_name) if isinstance(part, str) and part)
    if event.type.endswith(".started"):
        action = "started"
    elif event.type.endswith(".completed"):
        action = "completed"
    elif event.type.endswith(".failed"):
        action = "failed"
    elif event.type.endswith(".cancelled"):
        action = "cancelled"
    else:
        action = event.type
    summary = event.summary or (f"{subject} {action}" if subject else f"CoScientist {action}")
    metadata: dict[str, Any] = {
        "event_id": event.event_id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "type": event.type,
    }
    if event.agent:
        metadata["agent"] = event.agent
    if isinstance(tool_name, str) and tool_name:
        metadata["tool_name"] = tool_name
    progress_data = {
        "schema_version": "coscientist-a2a-progress-v1",
        "event_id": event.event_id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "type": event.type,
        "agent": event.agent,
        "tool_name": tool_name if isinstance(tool_name, str) else None,
    }
    return TaskStatusUpdateEvent(
        task_id=a2a_task_id,
        context_id=context_id,
        final=False,
        status=TaskStatus(
            state=TaskState.working,
            message=Message(
                message_id=event.event_id,
                role=Role.agent,
                task_id=a2a_task_id,
                context_id=context_id,
                parts=[TextPart(text=summary), DataPart(data=progress_data)],
            ),
        ),
        metadata=metadata,
    )


class FacadeTaskStore(TaskStore):
    """A2A task store view backed by the façade's durable task repository."""

    def __init__(self, facade: CodesynapseFacade) -> None:
        self._facade = facade

    async def save(self, task: Task, context=None) -> None:  # A2A persists through the façade instead.
        return None

    async def get(self, task_id: str, context=None) -> Task | None:
        record = await self._facade.get_task(task_id)
        return task_from_record(record, context_id=record.coscientist_run_id) if record else None

    async def delete(self, task_id: str, context=None) -> None:
        return None


class FacadeAgentExecutor(AgentExecutor):
    """Streams façade trace progress and terminal state through one A2A request."""

    def __init__(self, facade: CodesynapseFacade) -> None:
        self._facade = facade

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        research_request = context.get_user_input()
        integration_context = metadata.get("context")
        if not isinstance(integration_context, dict):
            integration_context = {}
        a2a_task_id = str(context.task_id or uuid4())
        external_run_id = str(metadata.get("external_run_id") or a2a_task_id)
        project_id = str(metadata.get("project_id") or context.context_id or a2a_task_id)
        async def publish_progress(event: TraceEvent) -> None:
            await event_queue.enqueue_event(
                progress_from_trace(
                    event,
                    a2a_task_id=a2a_task_id,
                    context_id=context.context_id or event.run_id,
                )
            )

        record = await self._facade.start(
            StartRequest(
                external_run_id=external_run_id,
                tenant_id=str(metadata.get("tenant_id") or "root"),
                project_id=project_id,
                research_request=research_request,
                context=integration_context,
                control_token_hash=(
                    hashlib.sha256(str(metadata["control_capability_token"]).encode("utf-8")).hexdigest()
                    if metadata.get("control_capability_token")
                    else None
                ),
                trace_callback_url=(
                    str(metadata["trace_callback_url"])
                    if metadata.get("trace_callback_url") and metadata.get("trace_capability_token")
                    else None
                ),
                trace_capability_token=(
                    str(metadata["trace_capability_token"])
                    if metadata.get("trace_callback_url") and metadata.get("trace_capability_token")
                    else None
                ),
                artifact_upload_url=(
                    str(metadata["artifact_upload_url"])
                    if metadata.get("artifact_upload_url") and metadata.get("artifact_finalize_url")
                    and metadata.get("artifact_capability_token")
                    else None
                ),
                artifact_finalize_url=(
                    str(metadata["artifact_finalize_url"])
                    if metadata.get("artifact_upload_url") and metadata.get("artifact_finalize_url")
                    and metadata.get("artifact_capability_token")
                    else None
                ),
                artifact_capability_token=(
                    str(metadata["artifact_capability_token"])
                    if metadata.get("artifact_upload_url") and metadata.get("artifact_finalize_url")
                    and metadata.get("artifact_capability_token")
                    else None
                ),
                a2a_task_id=a2a_task_id,
                progress_subscriber=publish_progress,
            )
        )
        try:
            await event_queue.enqueue_event(
                task_from_record(record, context_id=context.context_id or record.coscientist_run_id)
            )
            terminal = await self._facade.wait_for_terminal_task(record.a2a_task_id)
            await event_queue.enqueue_event(
                task_from_record(terminal, context_id=context.context_id or terminal.coscientist_run_id)
            )
        finally:
            self._facade.unsubscribe_progress(record.a2a_task_id, publish_progress)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.task_id is None:
            raise ValueError("task id is required for cancellation")
        await self._facade.cancel(context.task_id)
        record = await self._facade.get_task(context.task_id)
        if record is not None:
            await event_queue.enqueue_event(task_from_record(record, context_id=context.context_id or record.coscientist_run_id))


def make_agent_card(url: str) -> AgentCard:
    """Return the fixed, versioned card registered in a Codesynapse tenant."""

    return AgentCard(
        name="coscientist",
        description="Long-running scientific research pipeline with standard A2A progress streaming and task polling.",
        url=url,
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/markdown", "application/json"],
        skills=[
            AgentSkill(
                id="research",
                name="research",
                description="Run the complete CoScientist research pipeline.",
                tags=["research", "long-running", "hitl"],
            )
        ],
    )
