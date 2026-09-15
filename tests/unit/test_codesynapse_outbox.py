import asyncio

import httpx

from CoScientist.integrations.codesynapse.delivery import TraceDeliveryClient, TraceOutboxDispatcher
from CoScientist.integrations.codesynapse.models import TraceEvent
from CoScientist.integrations.codesynapse.store import InMemoryIntegrationStore


def test_outbox_dispatcher_delivers_pending_events_once_in_sequence_order():
    async def scenario():
        store = InMemoryIntegrationStore()
        for sequence in (2, 1):
            await store.append_event(
                TraceEvent(
                    event_id=f"event-{sequence}",
                    run_id="run-1",
                    sequence=sequence,
                    tenant_id="root",
                    project_id="project-1",
                    type="tool.completed",
                )
            )
        delivered = []

        class Client:
            async def deliver(self, events):
                delivered.append([event.sequence for event in events])
                return True

        dispatcher = TraceOutboxDispatcher(store, Client())
        assert await dispatcher.flush_run("run-1") == 2
        assert await dispatcher.flush_run("run-1") == 0
        assert delivered == [[1, 2]]

    asyncio.run(scenario())


def test_outbox_retries_a_terminal_event_without_a_new_trace_event():
    async def scenario():
        store = InMemoryIntegrationStore()
        await store.append_event(
            TraceEvent(
                event_id="terminal-1",
                run_id="run-1",
                sequence=1,
                tenant_id="root",
                project_id="project-1",
                type="run.completed",
            )
        )
        attempts = 0

        class Client:
            async def deliver(self, events):
                nonlocal attempts
                attempts += 1
                return attempts == 2

        dispatcher = TraceOutboxDispatcher(store, Client())
        await dispatcher.retry_pending("run-1", sleep=lambda _delay: asyncio.sleep(0))

        assert attempts == 2
        assert await store.pending_events("run-1") == []

    asyncio.run(scenario())


def test_trace_delivery_treats_a_transport_failure_as_a_retryable_callback_failure():
    async def failing_post(*_args, **_kwargs):
        raise httpx.ConnectError("Codesynapse is temporarily unavailable")

    event = TraceEvent(
        event_id="event-1",
        run_id="run-1",
        sequence=1,
        tenant_id="root",
        project_id="project-1",
        type="run.completed",
    )
    client = TraceDeliveryClient(
        callback_url="http://codesynapse.internal/events",
        capability_token="capability",
        post=failing_post,
    )

    assert asyncio.run(client.deliver([event])) is False
