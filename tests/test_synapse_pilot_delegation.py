from types import SimpleNamespace

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from CoScientist.agents.callbacks.pilot_delegation import (
    require_pilot_tool,
    require_pilot_tool_call,
    require_pilot_expected_tool,
)


def _event(name, *, invocation_id="run-1", result=None):
    response = types.FunctionResponse(
        name=name, response={"result": "ok"} if result is None else result
    )
    return SimpleNamespace(
        invocation_id=invocation_id,
        get_function_responses=lambda: [response],
    )


def _context(*events):
    invocation = SimpleNamespace(
        invocation_id="run-1", session=SimpleNamespace(events=list(events))
    )
    return SimpleNamespace(_invocation_context=invocation)


def _request():
    declarations = [
        types.FunctionDeclaration(name=name, description=name)
        for name in ("retrieve_tools", "ResearchAgent", "TaskExecutorAgent")
    ]
    return LlmRequest(
        config=types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=declarations)]
        )
    )


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([], "retrieve_tools"),
        ([_event("retrieve_tools")], "ResearchAgent"),
        ([_event("retrieve_tools"), _event("ResearchAgent")], "TaskExecutorAgent"),
    ],
)
def test_pilot_requires_the_next_real_tool_call(events, expected):
    context = _context(*events)
    request = _request()

    require_pilot_tool(context, request)

    assert [
        declaration.name
        for tool in request.config.tools
        for declaration in tool.function_declarations or []
    ] == [expected]
    assert (
        request.config.tool_config.function_calling_config.mode
        == types.FunctionCallingConfigMode.ANY
    )

    with pytest.raises(RuntimeError, match=expected):
        require_pilot_tool_call(
            context,
            LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text="Done")])
            ),
        )
    assert (
        require_pilot_tool_call(
            context,
            LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(name=expected, args={})
                        )
                    ],
                )
            ),
        )
        is None
    )


def test_pilot_contract_ignores_another_invocation_and_releases_after_both_agents():
    context = _context(
        _event("retrieve_tools", invocation_id="old-run"),
        _event("retrieve_tools"),
        _event("ResearchAgent"),
        _event("TaskExecutorAgent"),
    )
    request = _request()

    require_pilot_tool(context, request)

    assert len(request.config.tools[0].function_declarations) == 3
    assert request.config.tool_config is None
    assert (
        require_pilot_tool_call(
            context,
            LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text="Report")])
            ),
        )
        is None
    )


def test_pilot_contract_does_not_count_a_failed_agent_response():
    request = _request()
    require_pilot_tool(
        _context(
            _event("retrieve_tools"),
            _event("ResearchAgent", result={"error": "failed"}),
        ),
        request,
    )
    assert request.config.tools[0].function_declarations[0].name == "ResearchAgent"


def test_pilot_contract_does_not_count_unavailable_retrieval():
    request = _request()

    with pytest.raises(RuntimeError, match="retrieve_tools failed"):
        require_pilot_tool(
            _context(
                _event(
                    "retrieve_tools",
                    result={"status": "error", "message": "Embedder not initialized"},
                )
            ),
            request,
        )


def test_pilot_profile_wires_contract_without_changing_regular_demo():
    from CoScientist.assembly import build_system
    from CoScientist.assembly.schema import load_config, resolve_config_path

    pilot = load_config(resolve_config_path("synapse_pilot"))
    regular = load_config(resolve_config_path("synapse_demo"))
    pilot_callbacks = pilot.agent("OrchestratorAgent").callbacks
    regular_callbacks = regular.agent("OrchestratorAgent").callbacks

    assert "require_pilot_tool" in pilot_callbacks.before_model
    assert pilot_callbacks.after_model[0] == "require_pilot_tool_call"
    assert pilot_callbacks.before_tool[0] == "require_pilot_expected_tool"
    assert "guard_unknown_tools" not in pilot_callbacks.after_model
    assert "require_pilot_tool" not in regular_callbacks.before_model

    orchestrator = build_system(pilot, remote_subagents=True).root
    assert {tool.name for tool in orchestrator.tools if hasattr(tool, "name")} >= {
        "ResearchAgent",
        "TaskExecutorAgent",
    }
    assert require_pilot_tool in orchestrator.canonical_before_model_callbacks
    assert require_pilot_tool_call in orchestrator.canonical_after_model_callbacks
    assert require_pilot_expected_tool in orchestrator.canonical_before_tool_callbacks


def test_pilot_reasoning_matches_gpt_oss_gateway_without_changing_regular_demo():
    from CoScientist.assembly.schema import load_config, resolve_config_path

    pilot = load_config(resolve_config_path("synapse_pilot"))
    regular = load_config(resolve_config_path("synapse_demo"))

    assert pilot.defaults.reasoning == "medium"
    assert pilot.agent("HypothesesAgent").reasoning == "medium"
    assert regular.defaults.reasoning is False
    assert regular.agent("HypothesesAgent").reasoning == "high"


def test_pilot_rejects_out_of_order_registered_tool():
    context = _context(_event("retrieve_tools"), _event("ResearchAgent"))
    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_function_call(name="get_server_info", args={})],
        )
    )
    assert require_pilot_tool_call(context, response) is None

    blocked = require_pilot_expected_tool(
        SimpleNamespace(name="get_server_info"), {}, context
    )
    assert "expected TaskExecutorAgent" in blocked["error"]
    assert "get_server_info" in blocked["error"]
    assert (
        require_pilot_expected_tool(
            SimpleNamespace(name="TaskExecutorAgent"), {}, context
        )
        is None
    )
