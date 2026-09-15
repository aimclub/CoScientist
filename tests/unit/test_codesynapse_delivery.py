import asyncio

from CoScientist.integrations.codesynapse.delivery import TraceDeliveryClient
from CoScientist.integrations.codesynapse.models import TraceEvent


class _Response:
    status_code = 204


def test_trace_delivery_uses_only_the_per_run_capability():
    async def scenario():
        captured = {}

        async def post(url, *, headers, json):
            captured.update(url=url, headers=headers, body=json)
            return _Response()

        delivered = await TraceDeliveryClient(
            callback_url="http://codesynapse.internal/events",
            capability_token="trace-capability",
            post=post,
        ).deliver([
            TraceEvent(
                event_id="event-1",
                run_id="run-1",
                sequence=1,
                tenant_id="root",
                project_id="project-1",
                type="run.started",
            )
        ])

        assert delivered
        assert captured["headers"] == {"Authorization": "Bearer trace-capability"}
        assert captured["body"]["events"][0]["event_id"] == "event-1"

    asyncio.run(scenario())
