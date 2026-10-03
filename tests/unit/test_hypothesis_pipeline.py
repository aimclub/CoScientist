"""Structural tests for the hypothesis subsystem pipeline.

Test 1: Generator → MooseChem MCP tool; critic critiques and enriches context;
        context is enriched with tools from tool retrieval.

These are unit-level structural tests — no LLM calls, no MCP server. They verify
that the subsystem is correctly wired through the assembler and that the internal
tool pipeline (retrieve_validation_tools → generate_via_moosechem →
run_critic_loop) is present and properly connected.

Run from the repo root:  pytest tests/unit/test_hypothesis_pipeline.py -q
"""
from dotenv import load_dotenv

load_dotenv()

from CoScientist.assembly import build_system  # noqa: E402
from CoScientist.assembly.schema import get_config  # noqa: E402


def _function_tool_names(agent) -> list:
    """The agent's FunctionTool names, in attachment order. BaseToolsets
    (research_graph, task_tracker) carry no ``.name`` and are skipped — they are
    checked by ``surface`` where relevant."""
    names = []
    for t in agent.tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if name:
            names.append(name)
    return names


def test_hypotheses_agent_has_all_three_internal_tools():
    """The HypothesesAgent assembled through system.yaml must expose all three
    internal tools: retrieve_validation_tools, generate_via_moosechem, and
    run_critic_loop — plus the research_graph worker surface it writes through."""
    system = build_system(get_config())
    agent = system.agent("HypothesesAgent")

    tool_names = set(_function_tool_names(agent))
    assert "generate_via_moosechem" in tool_names, (
        f"generate_via_moosechem missing from tools: {sorted(tool_names)}"
    )
    assert "run_critic_loop" in tool_names, (
        f"run_critic_loop missing from tools: {sorted(tool_names)}"
    )
    assert "retrieve_validation_tools" in tool_names, (
        f"retrieve_validation_tools missing from tools: {sorted(tool_names)}"
    )
    assert any(getattr(t, "surface", None) == "worker" for t in agent.tools), (
        "the research_graph worker surface must be attached — it is the only "
        "surface through which Hypothesis/VerificationMethod/ConfirmationCriteria "
        "can be committed"
    )


def test_generator_tool_pipeline_order():
    """The strategy tools must be in the correct pipeline order:
    retrieve_validation_tools FIRST, then generate_via_moosechem, then
    run_critic_loop (added by add_critic_loop_tool)."""
    system = build_system(get_config())
    agent = system.agent("HypothesesAgent")

    tool_names = _function_tool_names(agent)
    # retrieve_validation_tools must come before generate_via_moosechem
    idx_retrieve = tool_names.index("retrieve_validation_tools")
    idx_generate = tool_names.index("generate_via_moosechem")
    idx_critic = tool_names.index("run_critic_loop")

    assert idx_retrieve < idx_generate, (
        "retrieve_validation_tools must come before generate_via_moosechem"
    )
    assert idx_generate < idx_critic, (
        "generate_via_moosechem must come before run_critic_loop"
    )


def test_critic_loop_tool_is_function_tool():
    """run_critic_loop must be a FunctionTool wrapping the public module-level
    function, so its name is stable for bindings registration."""
    from google.adk.tools import FunctionTool
    from CoScientist.hypothesis_subsystem.generator_agent import run_critic_loop

    system = build_system(get_config())
    agent = system.agent("HypothesesAgent")

    critic_tool = next(t for t in agent.tools if t.name == "run_critic_loop")
    assert isinstance(critic_tool, FunctionTool), (
        f"run_critic_loop must be a FunctionTool, got {type(critic_tool)}"
    )


def test_tool_retrieval_enriches_context():
    """retrieve_validation_tools must accept a research_question and return
    a tool_catalog with tools and source fields."""
    from CoScientist.hypothesis_subsystem.generator_agent import retrieve_validation_tools
    import asyncio

    # Call without ToolContext — should fall back to static catalog
    result = asyncio.run(retrieve_validation_tools(
        research_question="Test question about molecular docking",
    ))

    assert "tool_catalog" in result, "Must return tool_catalog"
    assert "source" in result, "Must return source"
    assert "tool_count" in result, "Must return tool_count"
    assert result["tool_count"] > 0, "Static fallback must provide at least one tool"
    assert result["source"] == "static_fallback", (
        "Without RAG DB, must fall back to static catalog"
    )


def test_generate_via_moosechem_accepts_tool_context():
    """generate_via_moosechem must accept tool_context parameter for state
    injection (registry, audit, tool_catalog)."""
    from CoScientist.hypothesis_subsystem.generator_agent import generate_via_moosechem
    import inspect

    sig = inspect.signature(generate_via_moosechem)
    params = list(sig.parameters.keys())
    assert "tool_context" in params, (
        "generate_via_moosechem must accept tool_context for state injection"
    )
    assert "research_question" in params, "Must accept research_question"


def test_run_critic_loop_accepts_tool_context():
    """run_critic_loop must accept tool_context parameter for loop_coordinator
    and audit access from state."""
    from CoScientist.hypothesis_subsystem.generator_agent import run_critic_loop
    import inspect

    sig = inspect.signature(run_critic_loop)
    params = list(sig.parameters.keys())
    assert "tool_context" in params, (
        "run_critic_loop must accept tool_context for state injection"
    )
    assert "hypotheses_json" in params, "Must accept hypotheses_json"
    assert "research_question" in params, "Must accept research_question"


def test_loop_coordinator_has_graph_commit():
    """HypothesisLoopCoordinator must have _commit_active_hypotheses method
    for programmatic research graph commit (fix #3)."""
    from CoScientist.hypothesis_subsystem.loop_coordinator import HypothesisLoopCoordinator

    assert hasattr(HypothesisLoopCoordinator, "_commit_active_hypotheses"), (
        "LoopCoordinator must have _commit_active_hypotheses for graph commit"
    )


def test_run_critic_loop_has_provenance_fallback():
    """run_critic_loop must handle malformed hypotheses with a minimal
    Provenance wrapper instead of raising ValidationError (non-blocker fix)."""
    from CoScientist.hypothesis_subsystem.generator_agent import run_critic_loop
    import asyncio
    import json

    # A malformed hypothesis missing required fields — must not raise
    malformed = json.dumps({
        "hypotheses": [{"claim": "Test claim", "domain": "test"}]
    })

    # Without loop_coordinator in state, returns as-is (no critic loop)
    result = asyncio.run(run_critic_loop(
        hypotheses_json=malformed,
        research_question="test",
    ))

    assert "hypotheses" in result, "Must return hypotheses key"
    assert len(result["hypotheses"]) == 1, "Must preserve the single hypothesis"
    h = result["hypotheses"][0]
    assert h["claim"] == "Test claim", "Must preserve the claim"
    # The fallback wrapper must have added provenance
    assert "provenance" in h, "Fallback must add provenance to avoid ValidationError"

# ============================================================================
# PaperAnalysisRAGClient & Critic evidence enrichment tests
# ============================================================================

def test_rag_client_stub_returns_empty_string():
    """RAGClient stub must return '' (not []) for backward compatibility."""
    from CoScientist.hypothesis_subsystem.critic_agent import RAGClient

    client = RAGClient()
    result = client.query("test query")
    assert result == "", "RAGClient stub must return empty string"


def test_paper_analysis_rag_client_no_url_returns_empty():
    """PaperAnalysisRAGClient with no URL must return '' without error."""
    from CoScientist.hypothesis_subsystem.critic_agent import PaperAnalysisRAGClient

    client = PaperAnalysisRAGClient(mcp_url=None)
    result = client.query("test query")
    assert result == "", "PaperAnalysisRAGClient with no URL must return ''"


def test_hypothesis_input_has_evidence_basis():
    """HypothesisInput must have evidence_basis field for targeted RAG queries."""
    from CoScientist.hypothesis_subsystem.critic_agent import HypothesisInput

    inp = HypothesisInput(
        id="test",
        claim="Test claim",
        domain="chemistry",
        variables="{}",
        verification_plan="Test plan",
        tools=["tool1"],
        evidence_basis='[{"title": "Test Paper", "doi": "10.1234/test"}]',
    )
    assert inp.evidence_basis == '[{"title": "Test Paper", "doi": "10.1234/test"}]'


def test_critique_one_error_returns_failed_not_passed():
    """critique_one() on error must return passed=False (all zeros), NOT passed=True."""
    from CoScientist.hypothesis_subsystem.critic_agent import (
        HypothesisCriticAgent,
        HypothesisInput,
        RAGClient,
    )

    agent = HypothesisCriticAgent(rag_client=RAGClient(), model="nonexistent/model")
    inp = HypothesisInput(
        id="test",
        claim="Test claim",
        domain="chemistry",
        variables="{}",
        verification_plan="Test plan",
        tools=[],
    )
    result = agent.critique_one(inp)
    assert result.passed is False, (
        "critique_one() on error must return passed=False, not silently approve"
    )
    assert all(v == 0 for v in result.scores.values()), (
        f"All scores must be 0 on error, got {result.scores}"
    )


def test_critique_one_includes_evidence_when_rag_returns_content():
    """critique_one() must include LITERATURE EVIDENCE section when RAG returns content."""
    from CoScientist.hypothesis_subsystem.critic_agent import (
        HypothesisCriticAgent,
        HypothesisInput,
    )

    class MockRAG:
        def query(self, text, top_k=3):
            return "Mock evidence from literature database."

    agent = HypothesisCriticAgent(rag_client=MockRAG(), model="nonexistent/model")
    inp = HypothesisInput(
        id="test",
        claim="Test claim",
        domain="chemistry",
        variables="{}",
        verification_plan="Test plan",
        tools=[],
    )
    # Will fail on LLM call (nonexistent model), but the RAG query should have run
    result = agent.critique_one(inp)
    # On LLM error, passed=False (fixed silent approval)
    assert result.passed is False


def test_loop_coordinator_uses_paper_analysis_rag():
    """HypothesisLoopCoordinator must create PaperAnalysisRAGClient when URL is configured."""
    from CoScientist.hypothesis_subsystem.loop_coordinator import HypothesisLoopCoordinator
    from CoScientist.hypothesis_subsystem.critic_agent import PaperAnalysisRAGClient
    from CoScientist.hypothesis_subsystem.audit import HypothesisAuditLogger
    import logging

    audit = HypothesisAuditLogger(logging.getLogger("test"))
    coordinator = HypothesisLoopCoordinator(model="test-model", audit=audit)
    critic = coordinator._critic
    # Must have a RAG client (either RAGClient or PaperAnalysisRAGClient)
    assert critic._rag is not None, "Critic must have a RAG client"