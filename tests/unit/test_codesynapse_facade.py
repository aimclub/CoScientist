import asyncio

import CoScientist.integrations.codesynapse.facade as facade_module

from CoScientist.hitl.models import HITLAction, HITLRequest
from CoScientist.integrations.codesynapse.facade import CodesynapseFacade, StartRequest
from CoScientist.integrations.codesynapse.models import ArtifactPart, RunState
from CoScientist.integrations.codesynapse.store import InMemoryIntegrationStore


class _Executor:
    async def execute(self, request, hitl_handler):
        return "# Scientific report"


def test_facade_start_is_idempotent_and_returns_working_task():
    async def scenario():
        facade = CodesynapseFacade(store=InMemoryIntegrationStore(), executor=_Executor())
        request = StartRequest(
            external_run_id="external-1", tenant_id="tenant-1", project_id="project-1",
            research_request="Find a hypothesis",
        )
        first = await facade.start(request, run_in_background=False)
        second = await facade.start(request, run_in_background=False)

        assert first.a2a_task_id == second.a2a_task_id
        task = await facade.get_task(first.a2a_task_id)
        assert task.state is RunState.COMPLETED
        assert task.artifacts.final_report.text == "# Scientific report"

    asyncio.run(scenario())


def test_facade_idempotency_survives_two_process_local_locks():
    async def scenario():
        store = InMemoryIntegrationStore()
        first_facade = CodesynapseFacade(store=store, executor=_Executor())
        second_facade = CodesynapseFacade(store=store, executor=_Executor())
        request = StartRequest(
            external_run_id="external-1", tenant_id="tenant-1", project_id="project-1",
            research_request="Find a hypothesis",
        )

        first, second = await asyncio.gather(
            first_facade.start(request, run_in_background=True),
            second_facade.start(request, run_in_background=True),
        )

        assert first.a2a_task_id == second.a2a_task_id
        await first_facade.interrupt_non_terminal_tasks()

    asyncio.run(scenario())


def test_facade_marks_non_terminal_tasks_interrupted_on_restart():
    async def scenario():
        gate = asyncio.Event()

        class BlockingExecutor:
            async def execute(self, request, hitl_handler):
                await gate.wait()
                return "unreachable"

        facade = CodesynapseFacade(store=InMemoryIntegrationStore(), executor=BlockingExecutor())
        started = await facade.start(
            StartRequest(
                external_run_id="external-1", tenant_id="tenant-1", project_id="project-1",
                research_request="Find a hypothesis",
            )
        )
        await asyncio.sleep(0)
        interrupted = await facade.interrupt_non_terminal_tasks()

        task = await facade.get_task(started.a2a_task_id)
        assert interrupted == 1
        assert task.state is RunState.INTERRUPTED
        assert task.artifacts.error.data["error_code"] == "interrupted"

    asyncio.run(scenario())


def test_facade_cancel_returns_terminal_cancelled_task():
    async def scenario():
        gate = asyncio.Event()

        class BlockingExecutor:
            async def execute(self, request, hitl_handler):
                await gate.wait()
                return "unreachable"

        facade = CodesynapseFacade(store=InMemoryIntegrationStore(), executor=BlockingExecutor())
        started = await facade.start(
            StartRequest(
                external_run_id="external-1", tenant_id="tenant-1", project_id="project-1",
                research_request="Find a hypothesis",
            )
        )
        await asyncio.sleep(0)
        assert await facade.cancel(started.a2a_task_id)

        task = await facade.get_task(started.a2a_task_id)
        assert task.state is RunState.CANCELLED
        assert task.artifacts.error.data["error_code"] == "cancelled"
        events = await facade._store.replay_events(task.coscientist_run_id)
        assert events[-1].type == "run.cancelled"
        assert [(event.type, event.sequence) for event in events] == [
            ("run.started", 1),
            ("run.cancelled", 2),
        ]

    asyncio.run(scenario())


def test_facade_cancel_does_not_wait_for_executor_and_preserves_cancelled_state():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        class CancellationResistantExecutor:
            async def execute(self, request, hitl_handler):
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    # A transport can defer cancellation while it finishes its
                    # own cleanup. The A2A cancel response must not wait for it.
                    await release.wait()
                return "late report"

        facade = CodesynapseFacade(
            store=InMemoryIntegrationStore(), executor=CancellationResistantExecutor()
        )
        task = await facade.start(
            StartRequest(
                external_run_id="external-1", tenant_id="tenant-1", project_id="project-1",
                research_request="Find a hypothesis",
            )
        )
        await started.wait()
        job = facade._jobs[task.a2a_task_id]
        cancel_task = asyncio.create_task(facade.cancel(task.a2a_task_id))

        try:
            assert await asyncio.wait_for(asyncio.shield(cancel_task), timeout=0.05)
            cancelled = await facade.get_task(task.a2a_task_id)
            assert cancelled.state is RunState.CANCELLED
        finally:
            release.set()
            await asyncio.gather(cancel_task, job, return_exceptions=True)

        terminal = await facade.get_task(task.a2a_task_id)
        assert terminal.state is RunState.CANCELLED

    asyncio.run(scenario())


def test_facade_delivers_trace_events_with_capability_without_jwt():
    async def scenario():
        delivered_run_ids = []

        class Executor:
            async def execute(self, request, hitl_handler):
                return "# Report"

        class Dispatcher:
            async def flush_run(self, run_id):
                delivered_run_ids.append(run_id)

        def delivery_factory(request):
            assert request.trace_callback_url == "http://codesynapse.internal/events"
            assert request.trace_capability_token == "trace-capability"
            return Dispatcher()

        facade = CodesynapseFacade(
            store=InMemoryIntegrationStore(),
            executor=Executor(),
            delivery_factory=delivery_factory,
        )
        await facade.start(
            StartRequest(
                external_run_id="external-1",
                tenant_id="root",
                project_id="project-1",
                research_request="Find a hypothesis",
                trace_callback_url="http://codesynapse.internal/events",
                trace_capability_token="trace-capability",
            ),
            run_in_background=False,
        )

        assert len(delivered_run_ids) >= 2

    asyncio.run(scenario())


def test_facade_delivers_the_terminal_cancel_trace_event():
    async def scenario():
        started = asyncio.Event()
        delivered = []

        class BlockingExecutor:
            async def execute(self, request, hitl_handler):
                started.set()
                await asyncio.Event().wait()

        class Dispatcher:
            async def flush_run(self, run_id):
                delivered.append(run_id)

        facade = CodesynapseFacade(
            store=InMemoryIntegrationStore(),
            executor=BlockingExecutor(),
            delivery_factory=lambda _request: Dispatcher(),
        )
        task = await facade.start(
            StartRequest(
                external_run_id="external-1", coscientist_run_id="run-1",
                tenant_id="root", project_id="project-1", research_request="Find a hypothesis",
            )
        )
        await started.wait()

        assert await facade.cancel(task.a2a_task_id)
        await asyncio.sleep(0)

        assert delivered.count("run-1") >= 2

    asyncio.run(scenario())


def test_facade_runs_only_one_pipeline_at_a_time():
    async def scenario():
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        second_started = asyncio.Event()

        class Executor:
            async def execute(self, request, hitl_handler):
                if request.external_run_id == "external-1":
                    first_started.set()
                    await release_first.wait()
                else:
                    second_started.set()
                return "report"

        facade = CodesynapseFacade(store=InMemoryIntegrationStore(), executor=Executor())
        await facade.start(StartRequest(
            external_run_id="external-1", tenant_id="root", project_id="project-1", research_request="first",
        ))
        await first_started.wait()
        await facade.start(StartRequest(
            external_run_id="external-2", tenant_id="root", project_id="project-1", research_request="second",
        ))
        await asyncio.sleep(0)

        assert not second_started.is_set()
        release_first.set()
        await asyncio.wait_for(second_started.wait(), timeout=1)
        await facade.interrupt_non_terminal_tasks()

    asyncio.run(scenario())


def test_facade_schedules_outbox_retry_after_a_failed_callback():
    async def scenario():
        retries = []

        class Executor:
            async def execute(self, request, hitl_handler):
                return "# Report"

        class Dispatcher:
            async def flush_run(self, run_id):
                return 0

            async def retry_pending(self, run_id, *, sleep):
                retries.append(run_id)

        facade = CodesynapseFacade(
            store=InMemoryIntegrationStore(),
            executor=Executor(),
            delivery_factory=lambda _request: Dispatcher(),
        )
        await facade.start(
            StartRequest(
                external_run_id="external-1",
                coscientist_run_id="run-1",
                tenant_id="root",
                project_id="project-1",
                research_request="Find a hypothesis",
            ),
            run_in_background=False,
        )
        await asyncio.sleep(0)

        assert retries == ["run-1"]

    asyncio.run(scenario())


def test_large_final_report_becomes_capability_backed_artifact(monkeypatch):
    captured = {}

    class ArtifactClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def upload_text(self, **kwargs):
            captured["upload"] = kwargs
            return ArtifactPart(
                name=kwargs["name"],
                mime_type=kwargs["mime_type"],
                artifact_id="artifact-1",
                checksum_sha256="a" * 64,
            )

    monkeypatch.setattr(facade_module, "CodesynapseArtifactClient", ArtifactClient)
    request = StartRequest(
        external_run_id="external-1",
        tenant_id="root",
        project_id="project-1",
        research_request="Find a hypothesis",
        artifact_upload_url="http://codesynapse.internal/artifacts/grant",
        artifact_finalize_url="http://codesynapse.internal/artifacts/finalize",
        artifact_capability_token="artifact-capability",
    )

    part = asyncio.run(CodesynapseFacade._report_part(request, "x" * (512 * 1024 + 1)))

    assert part.artifact_id == "artifact-1"
    assert captured["capability_token"] == "artifact-capability"


def test_cancel_by_run_uses_durable_mapping_after_process_restart():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        class BlockingExecutor:
            async def execute(self, request, hitl_handler):
                started.set()
                await release.wait()
                return "report"

        store = InMemoryIntegrationStore()
        first = CodesynapseFacade(store=store, executor=BlockingExecutor())
        await first.start(
            StartRequest(
                external_run_id="external-1",
                coscientist_run_id="run-1",
                tenant_id="root",
                project_id="project-1",
                research_request="Find a hypothesis",
            )
        )
        await started.wait()
        restarted = CodesynapseFacade(store=store, executor=BlockingExecutor())

        assert await restarted.cancel_by_run("run-1")

        task = await store.get_task_by_external_run("external-1")
        assert task.state is RunState.CANCELLED
        release.set()
        await asyncio.gather(*first._jobs.values(), return_exceptions=True)
        terminal = await store.get_task_by_external_run("external-1")
        assert terminal.state is RunState.CANCELLED

    asyncio.run(scenario())


def test_facade_exposes_hitl_timeout_as_a_stable_terminal_error_code():
    async def scenario():
        class TimeoutExecutor:
            async def execute(self, request, hitl_handler):
                await hitl_handler.handle_request(HITLRequest(
                    agent_name="planner", action_type=HITLAction.APPROVE, message="approve", timeout_seconds=0.001,
                ))
                return "unreachable"

        facade = CodesynapseFacade(store=InMemoryIntegrationStore(), executor=TimeoutExecutor())
        task = await facade.start(
            StartRequest(
                external_run_id="external-1", tenant_id="tenant-1", project_id="project-1",
                research_request="Find a hypothesis",
            ),
            run_in_background=False,
        )
        assert task.state is RunState.FAILED
        assert task.artifacts.error.data["error_code"] == "hitl_timeout"

    asyncio.run(scenario())
