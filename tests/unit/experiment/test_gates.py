"""Orchestrator gates: coalesce, module suppression, feasibility, retrieval budget."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import yaml

from .helpers import (
    _research_call_response,
)


def test_experiment_retrieval_budget_stops_repeated_llm_tool_calls():
    from google.adk.models import LlmResponse
    from google.genai import types

    from CoScientist.experiments.context import (
        enforce_experiment_retrieval_budget,
        reset_experiment_retrieval_budget,
    )

    context = SimpleNamespace(state={"retrieval_queries": ["prior request"]})
    reset_experiment_retrieval_budget(context)
    repeated_call = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="retrieve_tools",
                        args={"query": "KRAS G12C candidates"},
                    )
                )
            ],
        )
    )

    assert enforce_experiment_retrieval_budget(context, repeated_call) is None
    # Budget is 5 request-local retrieve_tools calls counted after the baseline.
    context.state["retrieval_queries"].extend(
        ["query one", "query two", "query three", "query four", "query five"]
    )
    stopped = enforce_experiment_retrieval_budget(context, repeated_call)

    assert stopped is not None
    assert "EXPERIMENT_RETRIEVAL_BUDGET_EXHAUSTED" in stopped.content.parts[0].text
    assert context.state["experiment_retrieval_budget_exhausted"] is True


def test_coalesce_merges_parallel_experiment_module_calls():
    from google.adk.models import LlmResponse
    from google.genai import types

    from CoScientist.experiments.runtime.coalesce import (
        coalesce_experiment_module_calls,
    )

    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="ExperimentModuleAgent",
                        args={"request": "Generate KRAS G12C inhibitors."},
                    )
                ),
                types.Part(
                    function_call=types.FunctionCall(
                        name="ExperimentModuleAgent",
                        args={"request": "Dock the generated molecules."},
                    )
                ),
            ],
        )
    )
    state = {}
    ctx = SimpleNamespace(state=state, user_content=None, agent_name="OrchestratorAgent")

    assert coalesce_experiment_module_calls(ctx, response) is None
    parts = response.content.parts
    assert len(parts) == 1
    merged = parts[0].function_call.args["request"]
    assert "Generate KRAS G12C inhibitors." in merged
    assert "Dock the generated molecules." in merged
    assert state.get("experiment_module_dispatched") is True


def test_enforce_experiment_module_first_does_not_rewrite_research():
    from CoScientist.experiments.runtime.coalesce import (
        enforce_experiment_module_first,
    )

    state: dict = {}
    response = _research_call_response("Dock aspirin against COX-2 and report affinity.")
    ctx = SimpleNamespace(state=state, user_content=None, agent_name="OrchestratorAgent")

    # Clean architecture: no-op, never rewrites ResearchAgent to ExperimentModuleAgent
    assert enforce_experiment_module_first(ctx, response) is None
    fc = response.content.parts[0].function_call
    assert fc.name == "ResearchAgent"


def test_suppress_experiment_module_after_completed_and_success():
    from google.adk.models import LlmResponse
    from google.genai import types

    from CoScientist.experiments.runtime.coalesce import (
        suppress_experiment_module_after_completed,
    )

    state = {
        "experiment_runtime": {
            "phase": "completed",
            "tasks_ok": True,
            "tasks": [{"id": "EXP-1", "status": "success", "result_ok": True}],
        }
    }
    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="ExperimentModuleAgent",
                        args={"request": "Run more experiments."},
                    )
                )
            ],
        )
    )
    ctx = SimpleNamespace(state=state, user_content=None, agent_name="OrchestratorAgent")
    suppress_experiment_module_after_completed(ctx, response)
    # The call should be stripped/suppressed
    fcs = [
        p.function_call.name
        for p in response.content.parts
        if getattr(p, "function_call", None)
    ]
    assert "ExperimentModuleAgent" not in fcs


def test_suppress_experiment_module_allows_retry_when_tasks_failed():
    from google.adk.models import LlmResponse
    from google.genai import types

    from CoScientist.experiments.runtime.coalesce import (
        suppress_experiment_module_after_completed,
    )

    state = {
        "experiment_runtime": {
            "phase": "completed",
            "tasks_ok": False,
            "tasks": [{"id": "EXP-1", "phase": "failed", "result_ok": False}],
        }
    }
    response = LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="ExperimentModuleAgent",
                        args={"request": "Retry failed computation with alternative tool."},
                    )
                )
            ],
        )
    )
    ctx = SimpleNamespace(state=state, user_content=None, agent_name="OrchestratorAgent")
    suppress_experiment_module_after_completed(ctx, response)
    # The call should NOT be suppressed because tasks failed and orchestrator may retry
    fcs = [
        p.function_call.name
        for p in response.content.parts
        if getattr(p, "function_call", None)
    ]
    assert "ExperimentModuleAgent" in fcs


def test_orchestrator_subordinates_clean_lanes():
    yaml_path = Path("CoScientist/agents/experiments.yaml")
    assert yaml_path.is_file()
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    agents = data.get("agents", {})
    orch = agents.get("OrchestratorAgent", {})
    subordinates = orch.get("subordinates", [])

    # Orchestrator has HypothesesAgent, ResearchAgent, ExperimentModuleAgent
    assert "HypothesesAgent" in subordinates
    assert "ResearchAgent" in subordinates
    assert "ExperimentModuleAgent" in subordinates

    # Orchestrator does NOT have McpBuilderAgent or PlannerAgent at root
    assert "McpBuilderAgent" not in subordinates
    assert "PlannerAgent" not in subordinates


def test_early_feasibility_skips_check_for_explicit_module_call():
    """An orchestrator-chosen EM call is never second-guessed."""
    from CoScientist.experiments.context.builder import RETRIEVED_CAPABILITIES_KEY
    from CoScientist.experiments.runtime.guards import (
        NO_MATCHING_TOOL_STATE_KEY,
        assess_experiment_inventory_feasibility,
    )

    state = {
        "experiment_source_request": (
            "Сделай обзор литературы по роли гиппокампа в консолидации памяти."
        ),
        RETRIEVED_CAPABILITIES_KEY: [
            {
                "tool": "generate_case_mols",
                "server_id": "d36e",
                "description": "Generate case molecules with a GAN.",
            },
        ],
    }
    assess_experiment_inventory_feasibility(
        SimpleNamespace(state=state, agent_name="ToolPreparerAgent")
    )
    assert state.get(NO_MATCHING_TOOL_STATE_KEY) in (None, "")
