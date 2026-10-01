"""DatasetIntakeAgent: the coder describes an attached dataset before planning.

Offline: a stand-in coder echoes its request and writes a sandbox binding into
state, as the real one does when it starts a sandbox.
"""
import asyncio
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from CoScientist.agents.callbacks.tool_callbacks import (
    DATASET_CONTEXT_STATE_KEY,
    DATASET_REPORT_FOR_STATE_KEY,
    DATASET_REPORT_STATE_KEY,
    inject_dataset_context,
)
from CoScientist.agents.custom_agents import DatasetIntakeAgent


class FakeCoder(BaseAgent):
    model_config = {"arbitrary_types_allowed": True}
    calls: list = []

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        request = ctx.user_content.parts[0].text
        self.calls.append((request, ctx.session.state.get("dataset_url")))
        yield Event(
            author=self.name, invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part(text="3 CSV files, 120 rows")]),
            actions=EventActions(state_delta={"sandbox_session_id": "sbx-1"}),
        )


async def _run(state: dict, coder: FakeCoder):
    intake = DatasetIntakeAgent(name="DatasetIntakeAgent", subordinates=[coder])
    service = InMemorySessionService()
    await service.create_session(app_name="t", user_id="u", session_id="s", state=state)
    runner = Runner(app_name="t", agent=intake, session_service=service)
    msg = types.Content(role="user", parts=[types.Part(text="Fit a model to my data")])
    events = [e async for e in runner.run_async(user_id="u", session_id="s", new_message=msg)]
    session = await service.get_session(app_name="t", user_id="u", session_id="s")
    return events, session.state


def test_no_dataset_is_a_silent_no_op():
    coder = FakeCoder(name="CoderAgent", calls=[])
    events, _ = asyncio.run(_run({}, coder))
    assert events == [] and coder.calls == []


def test_dataset_is_analysed_once_and_reported():
    coder = FakeCoder(name="CoderAgent", calls=[])
    url = "http://s3/b/datasets/x.zip?X-Amz-Signature=one"
    events, state = asyncio.run(_run({"dataset_url": url}, coder))
    request, seen_url = coder.calls[0]
    assert "do not start on the user's task" in request and "Fit a model" in request
    assert seen_url == url
    assert state[DATASET_REPORT_STATE_KEY] == "3 CSV files, 120 rows"
    assert state[DATASET_REPORT_FOR_STATE_KEY] == "http://s3/b/datasets/x.zip"
    # Later coder work continues in the sandbox the data is already in.
    assert state["sandbox_session_id"] == "sbx-1"
    assert "Dataset report" in events[-1].content.parts[0].text

    # Same object, re-signed link: not analysed again.
    again = FakeCoder(name="CoderAgent", calls=[])
    state2 = {**state, "dataset_url": "http://s3/b/datasets/x.zip?X-Amz-Signature=two"}
    events2, _ = asyncio.run(_run(state2, again))
    assert events2 == [] and again.calls == []


class _Ctx:
    def __init__(self, state):
        self.state = state


def test_report_reaches_prompts_only_for_its_dataset():
    state = {"dataset_url": "http://s3/b/x.zip?sig=1", DATASET_REPORT_STATE_KEY: "3 CSV files",
             DATASET_REPORT_FOR_STATE_KEY: "http://s3/b/x.zip"}
    inject_dataset_context(_Ctx(state))
    assert "3 CSV files" in state[DATASET_CONTEXT_STATE_KEY]
    state["dataset_url"] = "http://s3/b/other.zip"
    inject_dataset_context(_Ctx(state))
    assert "3 CSV files" not in state[DATASET_CONTEXT_STATE_KEY]
    assert "other.zip" in state[DATASET_CONTEXT_STATE_KEY]
