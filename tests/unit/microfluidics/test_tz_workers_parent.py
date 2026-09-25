"""The parallel ТЗ workers are built on demand, outside ``sub_agents``. They
still hang under TZSpecAgent, or the ToolsViewer renders each of them as a
separate root instead of a branch of the agent tree."""
import asyncio

from google.adk.agents import BaseAgent, LlmAgent
from google.adk.apps.app import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types

from CoScientist.logging import tool_activity
from CoScientist.microfluidics.tz_agent import TZSessionAgent
from CoScientist.microfluidics.tz_builder import SECTION_GROUPS


def test_workers_are_children_of_the_tz_agent():
    agent = TZSessionAgent(name="TZSpecAgent", model="gemini-2.0-flash")
    group = SECTION_GROUPS[0]

    assert agent._worker(group).parent_agent is agent
    assert agent._fill_worker(group).parent_agent is agent


class _OneCall(BaseLlm):
    model: str = "scripted"

    async def generate_content_async(self, llm_request, stream=False):
        answered = any(p.function_response for c in llm_request.contents for p in c.parts or [])
        part = (types.Part(text="done") if answered
                else types.Part(function_call=types.FunctionCall(name="fill", args={})))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def fill() -> dict:
    return {"ok": True}


class _Spawner(BaseAgent):
    """Runs a worker it built itself, the way TZSessionAgent does."""

    async def _run_async_impl(self, ctx):
        worker = LlmAgent(name=f"{self.name}_task", model=_OneCall(), tools=[FunctionTool(fill)],
                          disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)
        worker.parent_agent = self
        async for event in worker.run_async(ctx.model_copy()):
            yield event


def test_agent_start_names_the_runtime_parent_and_its_instance():
    records = []

    async def sink(_key, payload):
        records.append(payload)

    async def go():
        service = InMemorySessionService()
        runner = Runner(app=App(name="t", root_agent=_Spawner(name="Spec"),
                                plugins=[tool_activity.ToolActivityPlugin()]),
                        session_service=service)
        session = await service.create_session(app_name="t", user_id="u")
        message = types.Content(role="user", parts=[types.Part(text="go")])
        async for _ in runner.run_async(user_id="u", session_id=session.id, new_message=message):
            pass

    tool_activity.set_tool_activity_sink(sink)
    try:
        asyncio.run(go())
    finally:
        tool_activity.set_tool_activity_sink(None)

    starts = {p["author"]: p for p in records if p["phase"] == "agent_start"}
    assert starts["Spec_task"]["parent"] == "Spec"
    assert starts["Spec_task"]["parent_instance"] == starts["Spec"]["agent_instance"]
