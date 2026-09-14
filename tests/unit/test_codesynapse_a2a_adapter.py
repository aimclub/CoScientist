import asyncio
import hashlib
from types import SimpleNamespace

from CoScientist.integrations.codesynapse.a2a_adapter import FacadeAgentExecutor, make_agent_card, task_from_record
from CoScientist.integrations.codesynapse.facade import CodesynapseFacade
from CoScientist.integrations.codesynapse.models import A2ATaskRecord, ArtifactPart, RunState, TerminalArtifacts
from CoScientist.integrations.codesynapse.store import InMemoryIntegrationStore


def test_completed_record_becomes_a2a_completed_task_with_named_artifact():
    task = task_from_record(
        A2ATaskRecord(
            a2a_task_id="task-1", external_run_id="external-1", coscientist_run_id="run-1",
            state=RunState.COMPLETED,
            artifacts=TerminalArtifacts(
                state=RunState.COMPLETED,
                final_report=ArtifactPart(name="final_report", mime_type="text/markdown", text="# Report"),
            ),
        ),
        context_id="context-1",
    )

    assert task.status.state == "completed"
    assert task.artifacts[0].name == "final_report"
    assert task.artifacts[0].parts[0].root.text == "# Report"


def test_interrupted_record_becomes_a2a_failed_task_with_structured_error():
    task = task_from_record(
        A2ATaskRecord(
            a2a_task_id="task-1", external_run_id="external-1", coscientist_run_id="run-1",
            state=RunState.INTERRUPTED,
            artifacts=TerminalArtifacts(
                state=RunState.INTERRUPTED,
                error=ArtifactPart(name="error", mime_type="application/json", data={"error_code": "interrupted"}),
            ),
        ),
        context_id="context-1",
    )

    assert task.status.state == "failed"
    assert task.artifacts[0].parts[0].root.data["error_code"] == "interrupted"


def test_a2a_adapter_starts_a_task_without_codesynapse_metadata():
    async def scenario():
        class Executor:
            async def execute(self, request, hitl_handler):
                return "report"

        events = []

        class Queue:
            async def enqueue_event(self, event):
                events.append(event)

        request_context = SimpleNamespace(
            metadata={},
            task_id="task-1",
            context_id="context-1",
            get_user_input=lambda: "Find a hypothesis",
        )

        store = InMemoryIntegrationStore()
        adapter = FacadeAgentExecutor(CodesynapseFacade(store=store, executor=Executor()))
        await adapter.execute(request_context, Queue())

        assert events[0].status.state == "working"
        assert (await store.get_run("task-1")).tenant_id == "root"

    asyncio.run(scenario())


def test_a2a_adapter_streams_redacted_trace_progress_before_terminal_task():
    async def scenario():
        class Executor:
            async def execute(self, request, hitl_handler):
                await request.trace_recorder.emit(
                    "tool.started",
                    agent="ResearchAgent",
                    data={"tool_name": "tavily_search", "api_key": "secret"},
                )
                return "report"

        events = []

        class Queue:
            async def enqueue_event(self, event):
                events.append(event)

        adapter = FacadeAgentExecutor(
            CodesynapseFacade(store=InMemoryIntegrationStore(), executor=Executor())
        )
        request_context = SimpleNamespace(
            metadata={},
            task_id="task-1",
            context_id="context-1",
            get_user_input=lambda: "Find a hypothesis",
        )

        await adapter.execute(request_context, Queue())

        assert events[0].status.state == "working"
        progress = next(
            event
            for event in events
            if getattr(event, "kind", None) == "status-update"
            and event.metadata["type"] == "tool.started"
        )
        assert progress.kind == "status-update"
        assert progress.final is False
        assert progress.status.state == "working"
        assert progress.status.message.parts[0].root.text == "ResearchAgent · tavily_search started"
        assert progress.status.message.parts[1].root.data == {
            "schema_version": "coscientist-a2a-progress-v1",
            "event_id": progress.metadata["event_id"],
            "run_id": progress.metadata["run_id"],
            "sequence": 2,
            "type": "tool.started",
            "agent": "ResearchAgent",
            "tool_name": "tavily_search",
        }
        assert progress.metadata == {
            "event_id": progress.metadata["event_id"],
            "run_id": progress.metadata["run_id"],
            "sequence": 2,
            "type": "tool.started",
            "agent": "ResearchAgent",
            "tool_name": "tavily_search",
        }
        assert events[-1].status.state == "completed"

    asyncio.run(scenario())


def test_codesynapse_agent_card_advertises_streaming():
    assert make_agent_card("http://localhost:8010").capabilities.streaming is True


def test_a2a_adapter_hashes_raw_control_capability_without_jwt():
    async def scenario():
        class Executor:
            async def execute(self, request, hitl_handler):
                return "report"

        class Queue:
            async def enqueue_event(self, event):
                return None

        store = InMemoryIntegrationStore()
        adapter = FacadeAgentExecutor(CodesynapseFacade(store=store, executor=Executor()))
        request_context = SimpleNamespace(
            metadata={
                "external_run_id": "external-1",
                "tenant_id": "root",
                "project_id": "project-1",
                "control_capability_token": "control-capability",
            },
            task_id="task-1",
            context_id="context-1",
            get_user_input=lambda: "Find a hypothesis",
        )

        await adapter.execute(request_context, Queue())

        run = await store.get_run("external-1")
        assert run.tenant_id == "root"
        assert run.project_id == "project-1"
        assert run.control_token_hash == hashlib.sha256(b"control-capability").hexdigest()

    asyncio.run(scenario())


def test_a2a_adapter_passes_trace_capability_without_jwt():
    async def scenario():
        requests = []

        class Executor:
            async def execute(self, request, hitl_handler):
                requests.append(request)
                return "report"

        class Queue:
            async def enqueue_event(self, event):
                return None

        adapter = FacadeAgentExecutor(CodesynapseFacade(store=InMemoryIntegrationStore(), executor=Executor()))
        request_context = SimpleNamespace(
            metadata={
                "external_run_id": "external-1",
                "tenant_id": "root",
                "project_id": "project-1",
                "trace_callback_url": "http://codesynapse.internal/events",
                "trace_capability_token": "trace-capability",
            },
            task_id="task-1",
            context_id="context-1",
            get_user_input=lambda: "Find a hypothesis",
        )

        await adapter.execute(request_context, Queue())
        await asyncio.sleep(0)

        assert requests[0].trace_callback_url == "http://codesynapse.internal/events"
        assert requests[0].trace_capability_token == "trace-capability"

    asyncio.run(scenario())


def test_a2a_adapter_passes_artifact_capability_without_jwt():
    async def scenario():
        requests = []

        class Executor:
            async def execute(self, request, hitl_handler):
                requests.append(request)
                return "report"

        class Queue:
            async def enqueue_event(self, event):
                return None

        adapter = FacadeAgentExecutor(CodesynapseFacade(store=InMemoryIntegrationStore(), executor=Executor()))
        request_context = SimpleNamespace(
            metadata={
                "artifact_upload_url": "http://codesynapse.internal/artifacts/grant",
                "artifact_finalize_url": "http://codesynapse.internal/artifacts/finalize",
                "artifact_capability_token": "artifact-capability",
            },
            task_id="task-1",
            context_id="context-1",
            get_user_input=lambda: "Find a hypothesis",
        )

        await adapter.execute(request_context, Queue())
        await asyncio.sleep(0)

        assert requests[0].artifact_upload_url.endswith("/grant")
        assert requests[0].artifact_capability_token == "artifact-capability"

    asyncio.run(scenario())
