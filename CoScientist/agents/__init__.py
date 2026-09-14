"""LLM Agents module — agents are assembled from CoScientist/agents/system.yaml.

The YAML is the single source of truth for the system layout (agents, tools,
callbacks, prompts, HITL, A2A exposure). This module builds the in-process
system once and re-exports the agent instances under their historical names so
existing imports keep working.
"""
import copy
import logging
from typing import Any

from CoScientist.logging import get_multi_agent_tracer

logger = logging.getLogger(__name__)

_SYSTEM_EXPORTS = (
    "agent_system", "orchestrator_agent", "root_agent", "run_root",
    "pipeline_pre_agents", "pipeline_post_agents", "planner_agent",
    "hypotheses_agent", "research_agent", "task_execution_agent",
    "medical_agent", "coder_agent", "tool_agent", "tool_retriever_agent",
    "tool_reranker_agent", "tool_websearcher_agent", "fedot_agent",
    "result_aggregator_agent", "tz_agent",
)
_system_initialized = False


def _attach_tracer(system: Any) -> None:
    """Attach optional tracing after the complete agent tree exists."""
    tracer = get_multi_agent_tracer()
    if tracer is None:
        return
    from opik.integrations.adk import track_adk_agent_recursive

    track_adk_agent_recursive(system.run_root, tracer)
    for agent in system.agents.values():
        if isinstance(getattr(agent, "after_model_callback", None), list) and len(agent.after_model_callback) > 1:
            agent.after_model_callback.insert(0, agent.after_model_callback.pop())
        if isinstance(getattr(agent, "before_tool_callback", None), list) and len(agent.before_tool_callback) > 1:
            agent.before_tool_callback.insert(0, agent.before_tool_callback.pop())


def _ensure_system() -> None:
    """Build public agent exports lazily to avoid the assembler import cycle."""
    global _system_initialized
    if _system_initialized:
        return

    from CoScientist.agents.llm_repair import install_json_repair
    from CoScientist.assembly import build_system

    install_json_repair()
    system = build_system()
    globals().update({
        "agent_system": system,
        "orchestrator_agent": system.root,
        "root_agent": system.root,
        "run_root": system.run_root,
        "pipeline_pre_agents": [
            system.agent(name) for name in system.config.pipeline.pre
            if system.config.agent(name).is_enabled()
        ],
        "pipeline_post_agents": [
            system.agent(name) for name in system.config.pipeline.post
            if system.config.agent(name).is_enabled()
        ],
        "planner_agent": system.agents.get("PlannerAgent"),
        "hypotheses_agent": system.agents.get("HypothesesAgent"),
        "research_agent": system.agents.get("ResearchAgent"),
        "task_execution_agent": system.agents.get("TaskExecutorAgent"),
        "medical_agent": system.agents.get("MedicalAgent"),
        "coder_agent": system.agents.get("CoderAgent"),
        "tool_agent": system.agents.get("ToolPreparerAgent"),
        "tool_retriever_agent": system.agents.get("ToolRetrieverAgent"),
        "tool_reranker_agent": system.agents.get("ToolReranker"),
        "tool_websearcher_agent": system.agents.get("ToolWebSearcherAgent"),
        "fedot_agent": system.agents.get("ExperimentAgent"),
        "result_aggregator_agent": system.agents.get("ResultAggregatorAgent"),
        "tz_agent": system.agents.get("TZAgent"),
    })
    _attach_tracer(system)
    _system_initialized = True


def __getattr__(name: str) -> Any:
    if name in _SYSTEM_EXPORTS:
        _ensure_system()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_for_mode():
    """Build an AgentSystem configured for the current start mode from settings.

    Reads ``settings.web.start_mode``:
      * ``"init"`` / ``"planner"`` — PlanningPipelineAgent is root (sequential: PlannerAgent →
        OrchestratorAgent).
      * ``"orchestrator"`` — OrchestratorAgent is root, with PlannerAgent
        added to its subordinates so it can be invoked on demand.
      * ``"orchestrator_planner"`` — OrchestratorAgent is root, provided with
        create_plan_tool directly, while PlannerAgent is disabled.

    Other runtime-tunable parameters (e.g. ``max_searches``) are read from
    ``settings.web`` by individual components at build time.

    Returns:
        An :class:`~CoScientist.assembly.assembler.AgentSystem`.
    """
    from CoScientist.assembly import build_system
    from CoScientist.assembly.schema import load_config
    from CoScientist.config import get_settings
    start_mode = get_settings().web.start_mode

    if start_mode in ("init", "planner"):
        raw_config = load_config()
        patched = copy.deepcopy(raw_config)
        pipeline_agent_name = "PlanningPipelineAgent" if "PlanningPipelineAgent" in patched.agents else "InitAgent"
        if pipeline_agent_name in patched.agents:
            patched.agents[pipeline_agent_name].root = True
            patched.agents[pipeline_agent_name].enabled = True
            patched.agents["OrchestratorAgent"].root = False
            # In Planner mode the PlannerAgent runs first and its output replaces
            # the original user query; inject_original_query restores it so the
            # OrchestratorAgent sees the original request.
            # Must run before redact_link_urls so that any links in the restored
            # query are subsequently redacted into [[linkXXXX]] references.
            orch_cb = patched.agents["OrchestratorAgent"].callbacks.before_model
            if "inject_original_query" not in orch_cb:
                if "redact_link_urls" in orch_cb:
                    orch_cb.insert(orch_cb.index("redact_link_urls"), "inject_original_query")
                else:
                    orch_cb.insert(0, "inject_original_query")
            system = build_system(config=patched)
        else:
            logger.warning(
                "start_mode is set to %r but 'PlanningPipelineAgent' is not present in "
                "the system config; falling back to default build_system()",
                start_mode,
            )
            system = build_system()
        _attach_tracer(system)
        return system

    if start_mode in ("orchestrator_planner", "orchestrator_plan"):
        raw_config = load_config()
        patched = copy.deepcopy(raw_config)

        # Make OrchestratorAgent the root.
        patched.agents["OrchestratorAgent"].root = True
        for name in ("PlanningPipelineAgent", "InitAgent"):
            if name in patched.agents:
                patched.agents[name].root = False
                patched.agents[name].enabled = False

        # Disable PlannerAgent and remove from Orchestrator's subordinates.
        if "PlannerAgent" in patched.agents:
            patched.agents["PlannerAgent"].root = False
            patched.agents["PlannerAgent"].enabled = False

        orch_subs = patched.agents["OrchestratorAgent"].subordinates
        if "PlannerAgent" in orch_subs:
            orch_subs.remove("PlannerAgent")

        # Give OrchestratorAgent the tool for creating/registering plans directly.
        orch_tools = patched.agents["OrchestratorAgent"].tools
        if "create_plan_tool" not in orch_tools:
            orch_tools.append("create_plan_tool")

        system = build_system(config=patched)
        _attach_tracer(system)
        return system

    if start_mode != "orchestrator":
        raise ValueError(
            f"Unknown start_mode {start_mode!r}; expected 'init'/'planner', 'orchestrator', or 'orchestrator_planner'"
        )

    # Load a fresh config and patch it for orchestrator-as-root mode.
    raw_config = load_config()
    patched = copy.deepcopy(raw_config)

    # Make OrchestratorAgent the root.
    patched.agents["OrchestratorAgent"].root = True
    for name in ("PlanningPipelineAgent", "InitAgent"):
        if name in patched.agents:
            patched.agents[name].root = False
            patched.agents[name].enabled = False

    # Add PlannerAgent to OrchestratorAgent's subordinates (if not already).
    orch_subs = patched.agents["OrchestratorAgent"].subordinates
    if "PlannerAgent" not in orch_subs:
        orch_subs.insert(0, "PlannerAgent")

    # Re-validate the patched config and build.
    system = build_system(config=patched)
    _attach_tracer(system)
    return system

__all__ = [
    "agent_system",
    "orchestrator_agent",
    "root_agent",
    "run_root",
    "planner_agent",
    "fedot_agent",
    "research_agent",
    "hypotheses_agent",
    "medical_agent",
    "coder_agent",
    "tool_retriever_agent",
    "tool_reranker_agent",
    "tool_websearcher_agent",
    "task_execution_agent",
    "tool_agent",
    "result_aggregator_agent",
    "pipeline_pre_agents",
    "pipeline_post_agents",
    "tz_agent",
    "build_for_mode",
]
