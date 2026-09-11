"""Tests for killable process-backed CoScientist execution."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from CoScientist.hitl.models import HITLAction, HITLResponse
from CoScientist.integrations.codesynapse.process_executor import ProcessManagerPipelineExecutor


def _result_child(_payload, events, _controls):
    events.put(("trace", "agent.started", {"agent": "PlannerAgent"}))
    events.put(("result", "report"))


def _blocking_child(_payload, events, _controls):
    events.put(("trace", "agent.started", {"agent": "PlannerAgent"}))
    time.sleep(60)


def _hitl_child(_payload, events, controls):
    events.put((
        "hitl",
        "request-1",
        {
            "agent_name": "PlannerAgent",
            "action_type": "approve",
            "message": "Approve the plan?",
        },
    ))
    message = controls.get(timeout=10)
    if message[0] == "hitl_response" and message[1] == "request-1":
        events.put(("result", message[2]["action"]))


class _TraceRecorder:
    def __init__(self) -> None:
        self.events = []
        self.started = asyncio.Event()

    async def emit(self, event_type, **fields):
        self.events.append((event_type, fields))
        self.started.set()


def _request(trace_recorder):
    return SimpleNamespace(
        coscientist_run_id="run-1",
        tenant_id="tenant-1",
        research_request="Find a hypothesis",
        context={},
        trace_recorder=trace_recorder,
    )


def test_process_executor_forwards_child_trace_and_result():
    async def scenario():
        recorder = _TraceRecorder()
        result = await ProcessManagerPipelineExecutor(worker_target=_result_child).execute(
            _request(recorder), hitl_handler=object()
        )

        assert result == "report"
        assert recorder.events == [("agent.started", {"agent": "PlannerAgent"})]

    asyncio.run(scenario())


def test_process_executor_cancellation_terminates_a_blocked_child_promptly():
    async def scenario():
        recorder = _TraceRecorder()
        task = asyncio.create_task(
            ProcessManagerPipelineExecutor(terminate_grace_seconds=0.5, worker_target=_blocking_child).execute(
                _request(recorder), hitl_handler=object()
            )
        )
        await asyncio.wait_for(recorder.started.wait(), timeout=10)

        started_at = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert time.monotonic() - started_at < 2

    asyncio.run(scenario())


def test_process_executor_bridges_hitl_response_back_to_the_child():
    class Handler:
        async def handle_request(self, request):
            assert request.agent_name == "PlannerAgent"
            return HITLResponse(action=HITLAction.APPROVE, approved=True)

    result = asyncio.run(
        ProcessManagerPipelineExecutor(worker_target=_hitl_child).execute(
            _request(_TraceRecorder()), hitl_handler=Handler()
        )
    )

    assert result == "approve"
