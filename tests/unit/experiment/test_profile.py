"""Experiment profile, settings, HITL, prompts, Fedot hard-stop."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from CoScientist.assembly.schema import load_config, resolve_config_path
from CoScientist.config.settings import ExperimentsSettings, Settings
from CoScientist.hitl.models import HITLAction, HITLRequest
from CoScientist.web.handler import WebHITLHandler

def test_experiments_settings_defaults_and_nested_env(monkeypatch):
    defaults = ExperimentsSettings()
    assert defaults.route_fedot is True
    assert defaults.route_coder_mcp is False
    assert defaults.route_alembic is False
    assert defaults.fallback_research == ["research"]
    assert defaults.fallback_medical == ["medical"]
    assert defaults.require_task_design is True
    assert defaults.task_max_attempts == 2
    assert defaults.max_plan_tasks == 8

    monkeypatch.setenv("EXPERIMENTS__ROUTE_FEDOT", "false")
    monkeypatch.setenv("EXPERIMENTS__MAX_PLAN_TASKS", "6")
    configured = Settings(_env_file=None)
    assert configured.experiments.route_fedot is False
    assert configured.experiments.max_plan_tasks == 6


def test_experiment_profile_is_isolated_and_preserves_a2a_contract():
    from CoScientist.assembly import build_system
    from CoScientist.experiments.review import ExperimentReviewSessionAgent

    config = load_config(resolve_config_path("experiments"))
    assert config.root.name == "OrchestratorAgent"
    orch = config.agent("OrchestratorAgent")
    assert orch.cls == "llm"
    assert orch.children == []
    assert "ExperimentModuleAgent" in orch.subordinates
    assert "TaskExecutorAgent" not in orch.subordinates
    # Target contract: no keyword-rewrite callbacks. Structural fan-out merge +
    # state-keyed module-first gate survive; research-vs-compute is decided by
    # the module's inventory, never by matching words in the request.
    assert "coalesce_experiment_module_calls" in orch.callbacks.after_model
    assert "suppress_experiment_module_after_completed" in orch.callbacks.after_model
    assert "redirect_research_to_experiment_module" not in orch.callbacks.after_model
    assert "normalize_experiment_module_brief" not in orch.callbacks.after_model
    assert "inject_upstream_artifacts" not in orch.callbacks.before_agent

    module = config.agent("ExperimentModuleAgent")
    assert module.a2a.key == "task_execution"
    assert module.a2a.port == 8004
    assert module.children == [
        "ToolPreparerAgent",
        "ExperimentPlannerAgent",
        "ExperimentExecutorAgent",
        "ExperimentResultReviewAgent",
    ]
    hyp = config.agent("HypothesesAgent")
    assert hyp.prompt == "hypotheses"
    assert hyp.model == "openai/gemini-3.7-flash"
    assert hyp.tools == ["research_graph"]
    assert "commit_experiment_hypotheses" in hyp.callbacks.after_agent
    assert "seed_hypotheses_from_em_request" in hyp.callbacks.before_model
    assert "enforce_hypothesis_research_commit" in hyp.callbacks.after_model
    assert "normalize_em_hypothesis_commit" in hyp.callbacks.after_model
    assert hyp.callbacks.after_model.index("enforce_hypothesis_research_commit") < (
        hyp.callbacks.after_model.index("normalize_em_hypothesis_commit")
    )
    assert "capture_hypotheses_after_research_commit" in hyp.callbacks.after_tool
    # Root must be bootstrapped before inject_research_context renders the
    # {research_context?} placeholder, so a fresh graph never reads EMPTY.
    assert hyp.callbacks.before_agent.index("bootstrap_research_question_if_empty") < (
        hyp.callbacks.before_agent.index("inject_research_context")
    )
    preparer = config.agent("ToolPreparerAgent")
    assert "assess_experiment_inventory_feasibility" in preparer.callbacks.after_agent
    assert config.agent("ExperimentPlannerAgent").callbacks.before_agent[0] == (
        "skip_when_experiment_stage_complete"
    )
    assert config.agent("ExperimentExecutorAgent").callbacks.before_agent[0] == (
        "skip_when_experiment_stage_complete"
    )
    assert config.agent("ExperimentResultReviewAgent").callbacks.before_agent == [
        "skip_when_experiment_stage_complete",
        "skip_when_experiment_not_feasible",
    ]
    assert "skip_when_experiment_stage_complete" in config.agent("ToolPreparerAgent").callbacks.before_agent
    # Three-lane target: science/compute → EM only (no orch→Coder shadow science).
    assert "CoderAgent" not in orch.subordinates
    assert "McpBuilderAgent" not in orch.subordinates
    # The orchestrator now carries the retrieval tool: choosing a lane requires
    # knowing whether ready-made MCP tools can do the work, and asking that
    # question is cheaper than routing a computable task into a literature review
    # and discovering it there. test_assembly.py::test_orchestrator_tool_discovery_gate
    # holds the matching invariant on the prompt side.
    assert "retrieval" in (orch.tools or [])
    assert "McpBuilderAgent" in config.agents
    # Coder + McpBuilder remain EM-internal Executor routes as well.
    # Research/Medical are shared: orch lanes for cheap single-domain asks,
    # Executor routes for mixed evidence+compute plans.
    assert "CoderAgent" in config.agent("ExperimentExecutorAgent").subordinates
    assert "McpBuilderAgent" in config.agent("ExperimentExecutorAgent").subordinates
    assert "ResearchAgent" in config.agent("ExperimentExecutorAgent").subordinates
    assert "MedicalAgent" in config.agent("ExperimentExecutorAgent").subordinates
    assert "ResearchAgent" in orch.subordinates
    research = config.agent("ResearchAgent")
    assert "reset_research_searches" in research.callbacks.before_agent
    assert research.callbacks.after_tool == [
        "log_research_tool_calls",
        "count_research_searches",
    ]
    assert "MedicalAgent" in orch.subordinates
    mcp_builder = config.agent("McpBuilderAgent")
    assert mcp_builder.callbacks.before_tool == ["pin_alembic_build_args"]
    assert mcp_builder.callbacks.after_tool == ["await_alembic_job_if_experiment"]
    fedot = config.agent("FedotAgent")
    fedot_before = fedot.callbacks.before_agent
    assert "refuse_when_fedot_deliverable" not in fedot_before
    assert "inject_upstream_artifacts" not in fedot_before
    assert "refuse_when_fedot_deliverable" not in config.agent("CoderAgent").callbacks.before_agent
    assert fedot.callbacks.before_tool == ["pin_fedot_alembic_task"]
    assert fedot.prompt == "experiment_fedot_route"
    assert "task_tracker" not in (fedot.tools or [])
    assert "task_tracker" not in (config.agent("ExperimentAgent").tools or [])
    assert config.agent("ExperimentAgent").callbacks.before_tool == [
        "force_schema_s3_upload"
    ]
    assert config.agent("ExperimentExecutorAgent").callbacks.before_tool == [
        "guard_experiment_route"
    ]
    assert config.agent("ExperimentExecutorAgent").callbacks.after_tool == [
        "mark_experiment_route_returned"
    ]
    retriever = config.agent("ToolRetrieverAgent")
    assert retriever.prompt == "experiment_tool_retriever"
    assert "persist_experiment_em_request" in retriever.callbacks.before_agent
    assert "reset_experiment_retrieval_budget" in retriever.callbacks.before_agent
    assert "inject_experiment_retrieve_facets" not in (retriever.callbacks.before_model or [])
    assert "enforce_experiment_retrieval_budget" in retriever.callbacks.after_model
    assert "persist_experiment_retrieved_capabilities" in retriever.callbacks.after_agent

    reranker = config.agent("ToolReranker")
    assert reranker.callbacks.after_model == ["sanitize_json_output"]
    assert "collect_reranked_tools" in reranker.callbacks.after_agent
    assert "collect_reranked_tools_from_model" not in reranker.callbacks.after_model

    planner = config.agent("ExperimentPlannerAgent")
    assert planner.model == "openai/gemini-3.7-flash"
    assert planner.include_contents == "none"
    assert "skip_retriever_context" in planner.callbacks.before_model
    # ExperimentPlan is enforced by sanitize_json_output + deterministic critique.
    assert planner.output_schema is None

    system = build_system(config)
    for name in ("ExperimentPlannerAgent", "ExperimentResultReviewAgent"):
        review_agent = system.agent(name)
        assert isinstance(review_agent, ExperimentReviewSessionAgent)
        assert review_agent.hitl_handler is not None  # fail-closed even headless
    assert system.agent("ExperimentPlannerAgent").include_contents == "none"


def test_planner_and_coder_prompts_cover_multi_h_and_anti_fabrication():
    from unittest.mock import MagicMock

    from CoScientist.experiments.prompts import templates as exp_prompts

    ctx = MagicMock()
    ctx.render_tools.return_value = ""
    ctx.render_agents.return_value = ""
    planner = exp_prompts.experiment_planner(ctx)
    coder = exp_prompts.experiment_coder_route(ctx)
    executor = exp_prompts.experiment_executor(ctx)
    retriever = exp_prompts.experiment_tool_retriever(ctx)
    assert "hypothesis_refs" in planner and "AUTHORITATIVE" in planner
    assert "operations is AUTHORITATIVE" in planner
    assert "design.operation_ref" in planner
    assert "Do NOT invent extra hypotheses" in planner
    assert "HypothesesAgent" in planner
    assert "PREFERRED over coder when a repo fits" in planner
    assert "Bind exact inventory server_id+tool" in planner
    assert "risks/assumptions only at plan root" in planner
    assert "Mandatory markdown/HTML reports are forbidden" in planner
    assert "NEVER add a narrative task" in planner
    assert "Leftover MCP for a different operation is not coverage" in planner
    assert "required route=coder" in planner
    assert "role=data" in planner
    assert "different-family" in planner
    assert "Cover every distinct operation" in retriever
    assert "one non-optional" in planner and "distinct target" in planner
    assert "also_tests" in planner
    assert "Uncovered hypothesis_refs" in planner
    assert "ANTI-FABRICATION" in coder
    assert "hardcoded" in coder.lower()
    assert "simulated/hardcoded" in executor.lower() or "fabricated" in executor.lower()
    assert "phase is still" in executor and "reporting" in executor


def test_research_prompt_requires_both_literature_tools():
    from unittest.mock import MagicMock

    from CoScientist.agents.prompts.templates import research

    ctx = MagicMock()
    ctx.has_tool.side_effect = lambda key: key in {"paper_analysis", "papers_search"}
    ctx.render_tools.return_value = ""
    ctx.render_hitl.return_value = ""
    prompt = research(ctx)
    sci_at = prompt.find("`explore_scientific_database`")
    papers_at = prompt.find("ALWAYS call `search_papers`")
    assert sci_at != -1
    assert papers_at != -1
    assert sci_at < papers_at
    assert "Do not treat the RAG answer as the end of a literature review" in prompt
    assert "Never invent tool names" in prompt
    assert "fall back to `tavily_search`" in prompt
    assert "immediately fall back" not in prompt
    assert "argument `keywords`" in prompt


def test_fedot_tool_skips_legacy_hard_stop_for_experiment_runtime(monkeypatch):
    import CoScientist.tools.fedotmas_tools as module

    calls = []

    def hard_stop(state):
        calls.append(state)
        return True

    class FakePostgres:
        def __init__(self, settings):
            pass

        async def initialize(self):
            return None

        async def close(self):
            return None

        async def get_server(self, server_id):
            return None

    monkeypatch.setattr(module, "should_hard_stop_fedot", hard_stop)
    monkeypatch.setattr(module, "PostgresClient", FakePostgres)

    context = SimpleNamespace(
        state={
            "experiment_runtime": {"run_id": "EXRUN-1"},
            "fedot_deliverable_ready": True,
            "filtered_tools": [],
        }
    )
    result = asyncio.run(module.fedot_toolset.fedot_tool("task", context))
    assert calls == []
    assert result["status"] == "error"  # reached normal no-server validation

    legacy = SimpleNamespace(state={"fedot_deliverable_ready": True})
    legacy_result = asyncio.run(module.fedot_toolset.fedot_tool("task", legacy))
    assert len(calls) == 1
    assert legacy_result["already_delivered"] is True


def test_web_hitl_timeout_is_fail_closed_only_for_experiment_review():
    async def scenario():
        handler = WebHITLHandler()
        experiment = await handler.handle_request(
            HITLRequest(
                agent_name="ExperimentPlannerAgent",
                action_type=HITLAction.APPROVE,
                message="Approve experiment plan",
                context={"experiment_review_kind": "plan"},
                timeout_seconds=0.001,
            )
        )
        assert experiment.approved is False
        assert experiment.timed_out is True

        legacy = await handler.handle_request(
            HITLRequest(
                agent_name="CoderAgent",
                action_type=HITLAction.APPROVE,
                message="Approve outward action",
                timeout_seconds=0.001,
            )
        )
        assert legacy.approved is True
        assert legacy.timed_out is False

    asyncio.run(scenario())


def test_hard_stop_never_fires_under_experiment_runtime():
    """EM owns anti-dup via the state machine; session hard-stop must not fire."""
    from CoScientist.tools.fedot_artifact_handoff import should_hard_stop_fedot

    state = {
        "experiment_runtime": {"run_id": "EXRUN-1", "active_attempt_id": "ATT-4"},
        "experiment_active_envelope": {"attempt_id": "ATT-4"},
        "fedot_deliverable_ready": True,
        "executor_tool_match": {"matched": True},
    }
    assert should_hard_stop_fedot(state) is False

    state["experiment_active_envelope"] = {"attempt_id": "ATT-5"}
    assert should_hard_stop_fedot(state) is False


def test_hard_stop_unchanged_without_experiment_runtime():
    """Non-EM flows keep the legacy (attempt-agnostic) behavior."""
    from CoScientist.tools.fedot_artifact_handoff import should_hard_stop_fedot

    state = {"fedot_deliverable_ready": True, "executor_tool_match": {"matched": True}}
    assert should_hard_stop_fedot(state) is True


def test_glued_imperative_ask_splits_into_internal_ops():
    from CoScientist.context_init.operations import parse_glued_imperative_operations

    l2 = (
        "Generate GSK-3beta inhibitors with high activity. "
        "Suggest some small molecules that inhibit KRAS G12C - a target "
        "responsible for non-small cell lung cancer. "
        "Generate high activity tyrosine-protein kinase BTK inhibitors. "
        "Generate 2 molecules that would help with a blood lipid spectrum disorder."
    )
    ops = parse_glued_imperative_operations(l2)
    assert [op.operation_id for op in ops] == ["OP-1", "OP-2", "OP-3", "OP-4"]
    assert ops[0].statement.startswith("Generate GSK-3beta")
    assert "1." not in l2
