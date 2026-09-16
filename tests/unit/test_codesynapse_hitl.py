import asyncio

import pytest

from CoScientist.hitl.models import HITLAction, HITLRequest, HITLResponse
from CoScientist.integrations.codesynapse.hitl import CodesynapseHITLHandler, HITLRequestCancelled, HITLRequestTimeout


def test_hitl_handler_resolves_only_matching_run_request():
    async def scenario():
        emitted = []

        async def emit(event_type, **kwargs):
            emitted.append((event_type, kwargs))

        handler = CodesynapseHITLHandler(run_id="run-1", emit=emit)
        request = HITLRequest(agent_name="planner", action_type=HITLAction.APPROVE, message="approve", timeout_seconds=1)
        waiting = asyncio.create_task(handler.handle_request(request))
        await asyncio.sleep(0)
        request_id = emitted[0][1]["data"]["request_id"]

        assert await handler.resolve(
            request_id,
            HITLResponse(action=HITLAction.APPROVE, approved=True),
        )
        response = await waiting
        assert response.approved
        assert [item[0] for item in emitted] == ["hitl.requested", "hitl.resolved"]

    asyncio.run(scenario())


def test_hitl_handler_times_out_and_can_cancel_pending_request():
    async def scenario():
        async def emit(*args, **kwargs):
            return None

        timeout_handler = CodesynapseHITLHandler(run_id="run-1", emit=emit)
        with pytest.raises(HITLRequestTimeout):
            await timeout_handler.handle_request(
                HITLRequest(agent_name="planner", action_type=HITLAction.APPROVE, message="approve", timeout_seconds=0.001)
            )

        cancel_handler = CodesynapseHITLHandler(run_id="run-1", emit=emit)
        waiting = asyncio.create_task(cancel_handler.handle_request(
            HITLRequest(agent_name="planner", action_type=HITLAction.APPROVE, message="approve", timeout_seconds=1)
        ))
        await asyncio.sleep(0)
        await cancel_handler.cancel_pending()
        with pytest.raises(HITLRequestCancelled):
            await waiting

    asyncio.run(scenario())
