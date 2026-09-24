"""Regression: gaps-only finalization must not silently erase synthesis routes."""
import asyncio
from types import SimpleNamespace

import pytest
from google.adk.tools.set_model_response_tool import SetModelResponseTool

from CoScientist.microfluidics.models import SynthesisRoutes


def test_missing_routes_returns_retry_feedback_without_finalizing():
    tool = SetModelResponseTool(SynthesisRoutes)
    context = SimpleNamespace(actions=SimpleNamespace(set_model_response=None))

    result = asyncio.run(tool.run_async(args={"gaps": ["Условия не подтверждены"]}, tool_context=context))

    assert "error" in result
    assert "routes" in result["error"]
    assert context.actions.set_model_response is None

    routes = [{"route_id": "GPN-1", "product": {"name": "Product"},
               "steps": [{"operation": "Hydrolysis", "reactants": [{"name": "Feed"}],
                          "conditions": [{"name": "Temperature", "value": "25 °C"}]}]}]
    result = asyncio.run(tool.run_async(args={"routes": routes, "gaps": []}, tool_context=context))
    assert "error" not in result
    assert context.actions.set_model_response["routes"][0]["steps"][0]["reactants"][0]["name"] == "Feed"
    assert result["routes"][0]["steps"][0]["conditions"][0]["value"] == "25 °C"


@pytest.mark.parametrize("steps", [None, []])
def test_routes_without_operations_do_not_finalize(steps):
    route = {"route_id": "GPN-1", "product": {"name": "Product"}}
    if steps is not None:
        route["steps"] = steps
    context = SimpleNamespace(actions=SimpleNamespace(set_model_response=None))
    result = asyncio.run(SetModelResponseTool(SynthesisRoutes).run_async(
        args={"routes": [route]}, tool_context=context,
    ))
    assert "error" in result
    assert context.actions.set_model_response is None


def test_explicit_no_routes_remains_supported():
    assert SynthesisRoutes(routes=[], gaps=["Сервис и литература не дали маршрутов"]).routes == []


def test_routes_are_required_in_tool_declaration():
    declaration = SetModelResponseTool(SynthesisRoutes)._get_declaration()
    required = (declaration.parameters_json_schema["required"]
                if declaration.parameters_json_schema else declaration.parameters.required)
    assert "routes" in required
