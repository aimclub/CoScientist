"""The Synapse pilot must retry wrong names without skipping delegation."""

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
    _names: tuple[str, ...] = PrivateAttr()
    _calls: int = PrivateAttr(default=0)
    _offered: list[tuple[str, ...]] = PrivateAttr(default_factory=list)

    def __init__(self, names: tuple[str, ...]):
        super().__init__(model="scripted-pilot")
        self._names = names

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
        if self._calls < len(self._names):
            name = self._names[self._calls]
            if name.startswith("retrieve_tools"):
                args = {"query": "surfactants"}
            elif name == "get_server_info":
                args = {}
            else:
                args = {"request": "Study surfactants"}
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


@pytest.mark.parametrize(
    ("calls", "offered"),
    [
        (
            ("retrieve_tools", "research_agent", "ResearchAgent", "TaskExecutorAgent"),
            [
                ("retrieve_tools",),
                ("ResearchAgent",),
                ("ResearchAgent",),
                ("TaskExecutorAgent",),
            ],
        ),
        (
            ("retrieve_tools", "tavily_search", "ResearchAgent", "TaskExecutorAgent"),
            [
                ("retrieve_tools",),
                ("ResearchAgent",),
                ("ResearchAgent",),
                ("TaskExecutorAgent",),
            ],
        ),
        (
            (
                "retrieve_tools<|channel|>commentary",
                "retrieve_tools",
                "ResearchAgent",
                "get_server_info",
                "TaskExecutorAgent",
            ),
            [
                ("retrieve_tools",),
                ("retrieve_tools",),
                ("ResearchAgent",),
                ("TaskExecutorAgent",),
                ("TaskExecutorAgent",),
            ],
        ),
    ],
)
def test_synapse_pilot_retries_wrong_tool_then_delegates(calls, offered):
    seen = []

    async def retrieve_tools(query: str) -> dict:
        seen.append("retrieve_tools")
        return {"status": "ok"}

    async def get_server_info() -> dict:
        seen.append("get_server_info")
        return {"status": "ok"}

    async def ResearchAgent(request: str) -> dict:
        seen.append("ResearchAgent")
        return {"status": "ok"}

    async def TaskExecutorAgent(request: str) -> dict:
        seen.append("TaskExecutorAgent")
        return {"status": "ok"}

    pilot = load_config(resolve_config_path("synapse_pilot"))
    orchestrator = build_system(pilot, remote_subagents=True).root
    model = PilotModel(calls)
    agent = LlmAgent(
        name="TestPilotOrchestrator",
        model=model,
        instruction="Complete the pilot delegation sequence.",
        tools=[retrieve_tools, get_server_info, ResearchAgent, TaskExecutorAgent],
        before_model_callback=orchestrator.before_model_callback,
        after_model_callback=orchestrator.after_model_callback,
        before_tool_callback=orchestrator.before_tool_callback,
        after_tool_callback=orchestrator.after_tool_callback,
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
    observed_calls = [
        call.name for event in events for call in event.get_function_calls()
    ]
    observed_responses = [
        response
        for event in events
        for response in event.get_function_responses()
    ]
    assert observed_calls == list(calls)
    assert [response.name for response in observed_responses] == list(calls)
    assert seen == ["retrieve_tools", "ResearchAgent", "TaskExecutorAgent"]
    assert model.offered[: len(calls)] == offered
    for response in observed_responses:
        if response.name in seen:
            assert response.response.get("status") == "ok"
        else:
            assert response.response.get("error")
