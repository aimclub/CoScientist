"""The Synapse pilot must retry an unknown name without skipping delegation."""

import asyncio

import pytest
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import PrivateAttr

from CoScientist.assembly import build_system
from CoScientist.assembly.schema import load_config, resolve_config_path


class PilotModel(BaseLlm):
    _wrong_name: str = PrivateAttr()
    _calls: int = PrivateAttr(default=0)
    _offered: list[tuple[str, ...]] = PrivateAttr(default_factory=list)

    def __init__(self, wrong_name: str):
        super().__init__(model="scripted-pilot")
        self._wrong_name = wrong_name

    @property
    def offered(self) -> list[tuple[str, ...]]:
        return self._offered

    async def generate_content_async(self, llm_request, stream=False):
        offered = tuple(
            declaration.name
            for tool in llm_request.config.tools or []
            for declaration in tool.function_declarations or []
        )
        self._offered.append(offered)
        names = (
            "retrieve_tools",
            self._wrong_name,
            "ResearchAgent",
            "TaskExecutorAgent",
        )
        if self._calls < len(names):
            name = names[self._calls]
            args = (
                {"query": "surfactants"}
                if name == "retrieve_tools"
                else {"request": "Study surfactants"}
            )
            content = types.Content(
                role="model",
                parts=[types.Part.from_function_call(name=name, args=args)],
            )
        else:
            content = types.Content(
                role="model", parts=[types.Part(text="Pilot delegation completed")]
            )
        self._calls += 1
        yield LlmResponse(content=content)


@pytest.mark.parametrize("wrong_name", ["research_agent", "tavily_search"])
def test_synapse_pilot_retries_unknown_tool_then_delegates(wrong_name):
    seen = []

    async def retrieve_tools(query: str) -> dict:
        seen.append("retrieve_tools")
        return {"status": "ok"}

    async def ResearchAgent(request: str) -> dict:
        seen.append("ResearchAgent")
        return {"status": "ok"}

    async def TaskExecutorAgent(request: str) -> dict:
        seen.append("TaskExecutorAgent")
        return {"status": "ok"}

    pilot = load_config(resolve_config_path("synapse_pilot"))
    orchestrator = build_system(pilot, remote_subagents=True).root
    model = PilotModel(wrong_name)
    agent = LlmAgent(
        name="TestPilotOrchestrator",
        model=model,
        instruction="Complete the pilot delegation sequence.",
        tools=[retrieve_tools, ResearchAgent, TaskExecutorAgent],
        before_model_callback=orchestrator.before_model_callback,
        after_model_callback=orchestrator.after_model_callback,
    )

    async def run():
        sessions = InMemorySessionService()
        await sessions.create_session(
            app_name="test_pilot", user_id="user", session_id="session"
        )
        runner = Runner(agent=agent, app_name="test_pilot", session_service=sessions)
        return [
            event
            async for event in runner.run_async(
                user_id="user",
                session_id="session",
                new_message=types.Content(
                    role="user", parts=[types.Part(text="Run the pilot")]
                ),
            )
        ]

    events = asyncio.run(run())
    assert seen == ["retrieve_tools", "ResearchAgent", "TaskExecutorAgent"]
    assert model.offered[:4] == [
        ("retrieve_tools",),
        ("ResearchAgent",),
        ("ResearchAgent",),
        ("TaskExecutorAgent",),
    ]
    assert any(
        response.name == wrong_name
        for event in events
        for response in event.get_function_responses()
    )
