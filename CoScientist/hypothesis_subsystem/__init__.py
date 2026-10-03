"""
Hypothesis Agent Subsystem — public API.

Provides:
  * build_hypothesis_subsystem() — wires Generator+Critic+MooseChemMCPTool into an
    AgentTool, for standalone use (tests, direct embedding).
  * HypothesisSubsystemAgent — an ADK LlmAgent subclass that the assembly
    framework instantiates via ``class: custom:hypothesis_subsystem`` in
    system.yaml. The assembler wraps it in an AgentTool and attaches it to
    the OrchestratorAgent as a single black-box entry point.

Internal architecture:
    HypothesisGenerator (LlmAgent with tools)
        ├── retrieve_validation_tools → FedotMAS RAG DB / static fallback
        ├── generate_via_moosechem → MooseChemMCPTool (MCP server)
        └── run_critic_loop → HypothesisLoopCoordinator
                                 └── HypothesisCriticAgent (critic_agent.py)
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool

from CoScientist.config import get_settings
from CoScientist.hypothesis_subsystem.audit import HypothesisAuditLogger
from CoScientist.hypothesis_subsystem.base_tool import BaseHypothesisTool
from CoScientist.hypothesis_subsystem.generator_agent import (
    add_critic_loop_tool,
    build_hypothesis_generator,
    generate_via_moosechem,
    retrieve_validation_tools,
    run_critic_loop,
)
from CoScientist.hypothesis_subsystem.loop_coordinator import HypothesisLoopCoordinator
from CoScientist.hypothesis_subsystem.moosechem_mcp_tool import MooseChemMCPTool
from CoScientist.hypothesis_subsystem.prompts import SUBSYSTEM_STRATEGY_APPENDIX
import logging as _stdlib_logging
from CoScientist.hypothesis_subsystem.tool_registry import HypothesisToolRegistry


# ============================================================================
# Internal helpers
# ============================================================================

def _merge_tools(internal_tools, assembler_tools):
    """Union the subsystem's internal strategy tools with the assembler's
    declared tools, keyed by tool name, the assembler's wiring winning for any
    name both provide.

    The regression this guards against: ``HypothesisSubsystemAgent`` used to
    REPLACE the assembler's tools with its internal MooseChem pair, silently
    dropping the ``research_graph`` worker surface declared in system.yaml — and
    with it the agent's only way to create Hypothesis/VerificationMethod/
    ConfirmationCriteria nodes. Merging keeps the graph surface attached while
    still guaranteeing the strategy tools exist for a standalone build (no
    assembler, ``assembler_tools is None``).
    """
    if assembler_tools is None:
        return list(internal_tools)

    def _name(tool):
        return getattr(tool, "name", None) or getattr(tool, "__name__", None)

    merged = list(assembler_tools)
    have = {_name(t) for t in merged}
    for tool in internal_tools:
        if _name(tool) not in have:
            merged.append(tool)
    return merged


def _make_inject_state(
    registry: HypothesisToolRegistry,
    loop_coordinator: HypothesisLoopCoordinator,
    audit: HypothesisAuditLogger,
):
    """Return a before_agent_callback that injects subsystem objects into state."""

    async def inject_state(callback_context):
        callback_context.state["hypothesis_registry"] = registry
        callback_context.state["loop_coordinator"] = loop_coordinator
        callback_context.state["hypothesis_audit"] = audit
        return None

    return inject_state


def _wire_generator(
    model: str,
    registry: HypothesisToolRegistry,
    audit: HypothesisAuditLogger,
) -> LlmAgent:
    """Build and fully wire the HypothesisGenerator LlmAgent.

    Returns the bare generator (NOT wrapped in AgentTool) so the assembly
    framework can wrap it itself.
    """
    loop_coordinator = HypothesisLoopCoordinator(model=model, audit=audit)

    generator_agent = build_hypothesis_generator(
        model=model,
        tool_registry=registry,
        audit=audit,
    )

    add_critic_loop_tool(generator_agent)

    # Compose inject_state ON TOP of any existing before_agent callback.
    original_before = generator_agent.before_agent_callback

    async def inject_state(callback_context):
        callback_context.state["hypothesis_registry"] = registry
        callback_context.state["loop_coordinator"] = loop_coordinator
        callback_context.state["hypothesis_audit"] = audit
        if original_before is None:
            return None
        import inspect as _inspect
        if _inspect.iscoroutinefunction(original_before):
            return await original_before(callback_context)
        else:
            return original_before(callback_context)

    generator_agent.before_agent_callback = inject_state

    return generator_agent


# ============================================================================
# Public API
# ============================================================================

def build_hypothesis_subsystem(
    model: Optional[str] = None,
) -> AgentTool:
    """Build the complete HypothesisGenerator+Critic subsystem as a single AgentTool.

    The caller receives a single AgentTool that the OrchestratorAgent can use
    as a drop-in replacement for the old HypothesesAgent. The internal
    architecture (retrieval + MooseChemMCPTool + LoopCoordinator +
    HypothesisCriticAgent) is hidden behind the AgentTool boundary.

    Args:
        model: LLM model identifier. Defaults to settings.llm.main_model.

    Returns:
        An AgentTool wrapping the HypothesisGenerator.
    """
    settings = get_settings()
    model = model or settings.llm.main_model

    audit = HypothesisAuditLogger(_stdlib_logging.getLogger("hypothesis_subsystem"))
    registry = HypothesisToolRegistry()
    registry.register(MooseChemMCPTool())

    generator_agent = _wire_generator(model, registry, audit)
    return AgentTool(agent=generator_agent)


class HypothesisSubsystemAgent(LlmAgent):
    """Assembly-level adapter for ``class: custom:hypothesis_subsystem``.

    The assembly framework instantiates this class, passes it ``name``,
    ``description``, ``output_key``, and any ``options`` from system.yaml,
    then wraps the resulting instance in an :class:`AgentTool` and attaches
    it to the OrchestratorAgent.

    Internally it builds the full hypothesis generation subsystem
    (retrieve_validation_tools + MooseChemMCPTool + LoopCoordinator +
    HypothesisCriticAgent) and exposes the HypothesisGenerator LlmAgent
    attributes — model, instruction, tools, output_schema — so the ADK
    runtime treats it as a regular LlmAgent.

    The ``before_agent_callback`` from system.yaml is composed ON TOP of the
    internal state-injection callback. ADK's canonical_before_agent_callbacks
    accepts either a single callable or a list, and runs a list in order.
    We normalize to a list with our state-injection FIRST, then hand the
    whole chain to ADK — no manual composer that would try to call the
    assembler-provided LIST as one function (the original TypeError).

    Constructor args match what :func:`CoScientist.assembly.assembler._build_custom_agent`
    passes for ``issubclass(cls, LlmAgent)`` custom classes.
    """

    def __init__(
        self,
        name: str = "HypothesisGenerator",
        description: str = "",
        model: Any = None,
        output_key: Optional[str] = None,
        **kwargs: Any,
    ):
        settings = get_settings()
        model_str: str = (
            model if isinstance(model, str)
            else (kwargs.pop("model_str", None) or settings.llm.main_model)
        )

        # Extract assembler-provided callbacks and tools BEFORE building the
        # generator, so we can (a) compose the callbacks with the internal
        # state-injection callback and (b) use the assembler's tool wiring when
        # the agent was built through system.yaml.
        assembler_before_agent = kwargs.pop("before_agent_callback", None)
        assembler_tools = kwargs.pop("tools", None)
        # The assembler-rendered instruction is the graph-aware "hypotheses"
        # prompt. It MUST reach the wrapper: it is what teaches research_commit
        # and the Hypothesis/VerificationMethod/ConfirmationCriteria shape. When
        # built standalone (tests embedding the subsystem) it is absent and the
        # MooseChem-only GENERATOR_INSTRUCTION is used instead.
        assembler_instruction = kwargs.pop("instruction", None)

        audit = HypothesisAuditLogger(
            _stdlib_logging.getLogger("hypothesis_subsystem")
        )
        registry = HypothesisToolRegistry()
        registry.register(MooseChemMCPTool())

        loop_coordinator = HypothesisLoopCoordinator(model=model_str, audit=audit)
        generator = build_hypothesis_generator(
            model=model_str,
            tool_registry=registry,
            audit=audit,
        )
        add_critic_loop_tool(generator)

        # ---- Compose before_agent callbacks ----
        # ADK's canonical_before_agent_callbacks accepts either a single callable
        # or a list, and runs a list in order. Do NOT wrap them in a manual
        # composer that would try to call the assembler-provided LIST as one
        # function (the original TypeError). Normalize to a list with our
        # state-injection FIRST, then hand the whole chain to ADK.
        _inject = _make_inject_state(registry, loop_coordinator, audit)
        before_callbacks: list = [_inject]
        if assembler_before_agent is not None:
            if isinstance(assembler_before_agent, list):
                before_callbacks.extend(assembler_before_agent)
            else:
                before_callbacks.append(assembler_before_agent)

        # Tools: UNION the assembler wiring (declared in system.yaml: the
        # research_graph worker surface + the MooseChem strategy tools) with the
        # subsystem's own strategy tools. The assembler's wiring wins on any name
        # both provide; a standalone build (no assembler) still gets the full
        # MooseChem pipeline. Merging — never replacing — is what keeps
        # research_graph attached, i.e. what lets this agent create
        # Hypothesis/VerificationMethod/ConfirmationCriteria at all.
        internal_tools: list = [
            FunctionTool(retrieve_validation_tools),
            FunctionTool(generate_via_moosechem),
            FunctionTool(run_critic_loop),
        ]
        tools = _merge_tools(internal_tools, assembler_tools)

        # Instruction: the assembler's graph-aware prompt when present, plus the
        # strategy appendix describing the internal MooseChem pipeline. A
        # standalone build falls back to the generator's own instruction.
        instruction = assembler_instruction or generator.instruction
        if instruction and SUBSYSTEM_STRATEGY_APPENDIX.strip() not in instruction:
            instruction = (
                instruction.rstrip("\n") + "\n\n"
                + SUBSYSTEM_STRATEGY_APPENDIX.strip() + "\n"
            )

        super().__init__(
            name=name,
            description=description,
            model=generator.model,
            instruction=instruction,
            tools=tools,
            output_schema=generator.output_schema,
            output_key=output_key or generator.output_key,
            before_agent_callback=before_callbacks,
            **kwargs,
        )


# ---- Exports ------------------------------------------------------------

__all__ = [
    "build_hypothesis_subsystem",
    "HypothesisSubsystemAgent",
    "HypothesisToolRegistry",
    "HypothesisAuditLogger",
    "BaseHypothesisTool",
    "MooseChemMCPTool",
    "HypothesisLoopCoordinator",
    "build_hypothesis_generator",
]
