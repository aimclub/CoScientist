import asyncio

from CoScientist.integrations.codesynapse.store import InMemoryIntegrationStore
from CoScientist.integrations.codesynapse.trace import TraceRecorder, batch_events


def test_recorder_sequences_and_redacts_events():
    async def scenario():
        store = InMemoryIntegrationStore()
        recorder = TraceRecorder(store, run_id="run-1", tenant_id="tenant-1", project_id="project-1")

        first = await recorder.emit("run.started", data={"api_key": "secret"})
        second = await recorder.emit("agent.completed")

        assert (first.sequence, second.sequence) == (1, 2)
        assert first.data == {"api_key": "***redacted***"}

    asyncio.run(scenario())


def test_batch_events_keeps_critical_event_separate():
    async def scenario():
        store = InMemoryIntegrationStore()
        recorder = TraceRecorder(store, run_id="run-1", tenant_id="tenant-1", project_id="project-1")
        events = [
            await recorder.emit("tool.started"),
            await recorder.emit("run.started"),
            await recorder.emit("tool.completed"),
        ]
        batches = batch_events(events, max_events=100, max_bytes=1024 * 1024)
        assert [[event.type for event in batch] for batch in batches] == [
            ["tool.started"], ["run.started"], ["tool.completed"],
        ]

    asyncio.run(scenario())
