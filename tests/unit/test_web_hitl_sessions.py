import asyncio

import pytest

from CoScientist.hitl.models import HITLAction, HITLRequest
from CoScientist.web.handler import WebHITLHandler


class _Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


def test_hitl_request_and_response_are_scoped_to_session():
    async def scenario():
        handler = WebHITLHandler()
        first_key = ("user_a", "session_a")
        second_key = ("user_b", "session_b")
        first_socket = _Socket()
        second_socket = _Socket()
        await handler.attach_websocket(first_socket, first_key)
        await handler.attach_websocket(second_socket, second_key)

        request_task = asyncio.create_task(handler.handle_request(HITLRequest(
            agent_name="PlannerAgent",
            action_type=HITLAction.APPROVE,
            message="Approve plan",
            context={
                "output": "plan",
                "_session": {"user_id": first_key[0], "session_id": first_key[1]},
            },
        )))
        await asyncio.sleep(0)

        assert len(first_socket.messages) == 1
        assert second_socket.messages == []
        payload = first_socket.messages[0]
        assert "_session" not in payload["context"]

        assert not handler.resolve_request(
            payload["request_id"],
            {"action": "approve", "approved": True},
            second_key,
        )
        assert not request_task.done()
        assert handler.resolve_request(
            payload["request_id"],
            {"action": "approve", "approved": True},
            first_key,
        )
        response = await request_task
        assert response.approved

    asyncio.run(scenario())


def test_unresolved_hitl_is_redelivered_only_until_it_is_resolved():
    async def scenario():
        handler = WebHITLHandler()
        key = ("user_a", "session_a")
        first_socket = _Socket()
        await handler.attach_websocket(first_socket, key)

        request_task = asyncio.create_task(handler.handle_request(HITLRequest(
            agent_name="PlannerAgent",
            action_type=HITLAction.APPROVE,
            message="Approve plan",
            context={"_session": {"user_id": key[0], "session_id": key[1]}},
        )))
        await asyncio.sleep(0)
        request_id = first_socket.messages[0]["request_id"]

        handler.detach_websocket(first_socket, key)
        reconnect_socket = _Socket()
        await handler.attach_websocket(reconnect_socket, key)
        assert [message["request_id"] for message in reconnect_socket.messages] == [
            request_id
        ]

        assert handler.resolve_request(
            request_id,
            {"action": "approve", "approved": True},
            key,
        )
        assert (await request_task).approved

        late_socket = _Socket()
        await handler.attach_websocket(late_socket, key)
        assert late_socket.messages == []

    asyncio.run(scenario())


def test_cancelled_hitl_is_removed_and_not_redelivered_on_reconnect():
    async def scenario():
        handler = WebHITLHandler()
        key = ("user_a", "session_a")
        first_socket = _Socket()
        await handler.attach_websocket(first_socket, key)

        request_task = asyncio.create_task(handler.handle_request(HITLRequest(
            agent_name="PlannerAgent",
            action_type=HITLAction.APPROVE,
            message="Approve plan",
            context={"_session": {"user_id": key[0], "session_id": key[1]}},
        )))
        await asyncio.sleep(0)
        request_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request_task

        assert handler.pending_summary() == []
        assert first_socket.messages[-1]["type"] == "hitl_cancelled"

        reconnect_socket = _Socket()
        await handler.attach_websocket(reconnect_socket, key)
        assert reconnect_socket.messages == []

    asyncio.run(scenario())


def _request(key, timeout_seconds=None):
    return HITLRequest(
        agent_name="ResearchAgent",
        action_type=HITLAction.APPROVE,
        message="Work order",
        context={"_session": {"user_id": key[0], "session_id": key[1]}},
        trigger="work_order",
        timeout_seconds=timeout_seconds,
    )


def test_request_timeout_overrides_the_global_auto_approve_timeout():
    """A Work Order veto window is shorter than the operator's global timeout:
    the request's own timeout_seconds must win, and running out approves."""
    async def scenario():
        handler = WebHITLHandler()
        handler.hitl_timeout_seconds = 300
        key = ("user_a", "session_a")
        socket = _Socket()
        await handler.attach_websocket(socket, key)

        response = await asyncio.wait_for(
            handler.handle_request(_request(key, timeout_seconds=0.05)), timeout=2
        )
        assert response.approved
        assert socket.messages[0]["timeout_seconds"] == 0.05
        assert socket.messages[-1]["type"] == "hitl_timeout"

    asyncio.run(scenario())


def test_hold_stops_the_auto_approve_countdown():
    async def scenario():
        handler = WebHITLHandler()
        key = ("user_a", "session_a")
        other_key = ("user_b", "session_b")
        socket = _Socket()
        await handler.attach_websocket(socket, key)

        task = asyncio.create_task(handler.handle_request(_request(key, timeout_seconds=0.1)))
        await asyncio.sleep(0)
        request_id = socket.messages[0]["request_id"]

        assert not await handler.hold_request(request_id, other_key)
        assert await handler.hold_request(request_id, key)
        assert socket.messages[-1] == {"type": "hitl_hold", "request_id": request_id}

        await asyncio.sleep(0.25)
        assert not task.done(), "a held request must wait for the human"

        # A reconnecting tab gets the request without a countdown.
        late = _Socket()
        await handler.attach_websocket(late, key)
        assert late.messages[0]["timeout_seconds"] == 0
        assert late.messages[0]["held"] is True

        assert handler.resolve_request(request_id, {"action": "reject", "approved": False}, key)
        response = await task
        assert not response.approved

    asyncio.run(scenario())


def test_notify_reaches_only_its_session_and_is_logged():
    async def scenario():
        handler = WebHITLHandler()
        key = ("user_a", "session_a")
        other_key = ("user_b", "session_b")
        mine, other = _Socket(), _Socket()
        await handler.attach_websocket(mine, key)
        await handler.attach_websocket(other, other_key)

        await handler.notify({
            "kind": "progress",
            "agent_name": "ResearchAgent",
            "step": {"id": "S1", "status": "done"},
            "_session": {"user_id": key[0], "session_id": key[1]},
        })

        assert other.messages == []
        assert mine.messages[0]["type"] == "work_order_notice"
        assert mine.messages[0]["kind"] == "progress"
        assert "_session" not in mine.messages[0]
        assert handler.get_event_log(key)[0]["type"] == "work_order_notice"
        assert handler.get_event_log(other_key) == []

    asyncio.run(scenario())


def test_hitl_request_and_its_answer_are_recorded_in_the_session_transcript():
    """A reload, export or import rebuilds the chat from the transcript, so an
    answered HITL card and the answer must both be in it — and only in its own
    session's transcript."""
    async def scenario():
        handler = WebHITLHandler()
        recorded = []
        handler.set_recorder(lambda session_key, event: recorded.append((session_key, event)))
        key = ("user_a", "session_a")
        socket = _Socket()
        await handler.attach_websocket(socket, key)

        task = asyncio.create_task(handler.handle_request(_request(key, timeout_seconds=5)))
        await asyncio.sleep(0)
        request_id = socket.messages[0]["request_id"]
        await handler.hold_request(request_id, key)
        assert handler.resolve_request(request_id, {
            "action": "approve",
            "approved": True,
            "instructions": "go",
            "form_values": {"rejected_assumption_ids": ["A1"]},
        }, key)
        await task

        assert [session_key for session_key, _ in recorded] == [key, key]
        request_event, response_event = (event for _, event in recorded)
        assert request_event["type"] == "hitl_request"
        assert request_event["request_id"] == request_id
        # Recorded as sent: a later hold must not rewrite the history copy.
        assert request_event["timeout_seconds"] == 5
        assert "held" not in request_event
        assert response_event["type"] == "hitl_response"
        assert response_event["request_id"] == request_id
        assert response_event["instructions"] == "go"
        assert response_event["form_values"] == {"rejected_assumption_ids": ["A1"]}

        timed_out = await asyncio.wait_for(
            handler.handle_request(_request(key, timeout_seconds=0.05)), timeout=2
        )
        assert timed_out.approved
        assert recorded[-1][1]["type"] == "hitl_timeout"

    asyncio.run(scenario())


def test_the_structured_experiment_plan_reaches_the_browser():
    """The plan card is drawn from ``context.experiment_plan``.

    The handler forwards the request context verbatim minus ``_session``, so
    this pins that the plan is not stripped on the way out — the browser falls
    back to the Markdown blob when it is missing, which is the view this
    replaced.
    """
    async def scenario():
        handler = WebHITLHandler()
        key = ("user_a", "session_a")
        socket = _Socket()
        await handler.attach_websocket(socket, key)

        plan = {"kind": "experiment_plan", "revision": 2, "task_count": 3,
                "matrix": [{"task_id": "EXP-1"}], "tasks": [{"id": "EXP-1"}]}
        task = asyncio.create_task(handler.handle_request(HITLRequest(
            agent_name="ExperimentPlannerAgent",
            action_type=HITLAction.APPROVE,
            message="Review and explicitly approve the experiment plan.",
            context={
                "output": "# Experiment plan · revision 2",
                "experiment_review_kind": "plan",
                "experiment_plan": plan,
                "_session": {"user_id": key[0], "session_id": key[1]},
            },
        )))
        await asyncio.sleep(0)

        context = socket.messages[0]["context"]
        assert context["experiment_plan"] == plan
        assert context["output"].startswith("# Experiment plan")
        assert "_session" not in context

        handler.resolve_request(socket.messages[0]["request_id"],
                                {"action": "approve", "approved": True}, key)
        await task

    asyncio.run(scenario())
