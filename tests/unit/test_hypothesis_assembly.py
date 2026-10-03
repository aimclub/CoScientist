"""Assembly-level tests for the hypothesis subsystem integration.

These build the real system from CoScientist/agents/system.yaml (no LLM calls).

The hypothesis agent is a GRAPH-WRITING agent: ``HypothesisSubsystemAgent`` must
keep BOTH the ``research_graph`` worker surface — without which no
Hypothesis/VerificationMethod/ConfirmationCriteria node can ever be created (it
is the only role allowed to create them) — AND the MooseChem strategy tools
(retrieve_validation_tools → generate_via_moosechem → run_critic_loop). The
regression this pins: exposing only the strategy pair silently dropped the graph
surface, so the research graph stayed forever empty of hypotheses.

It also pins the two older integration bugs at the assembler boundary:

1. ``before_agent_callback`` arriving as a LIST (two callbacks in system.yaml)
   must reach ADK in canonical list form, with the internal state-injection
   callback FIRST.
2. ``guard_unknown_tools`` must whitelist the agent's REAL tools — the graph
   surface (``research_commit``) and the strategy tools alike — so legitimate
   calls pass and only unknown tools are caught.

Run from the repo root:  pytest tests/unit/test_hypothesis_assembly.py -q
"""
from dotenv import load_dotenv

load_dotenv()

from google.adk.models import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

from CoScientist.assembly import build_system  # noqa: E402
from CoScientist.assembly.schema import get_config  # noqa: E402


class _CallbackContext:
    """Minimal stand-in for CallbackContext — the guard only reads agent_name."""

    agent_name = "HypothesesAgent"


def _llm_response_with_tool(name: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=name, args={}))],
        )
    )


def _function_tool_names(agent) -> set:
    """Names of the agent's function tools. A BaseToolset (research_graph,
    task_tracker) carries no ``.name`` — it is reported by its ``surface`` and
    checked separately."""
    out = set()
    for t in agent.tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None)
        if name:
            out.add(name)
    return out


def test_hypotheses_agent_keeps_graph_surface_and_strategy_tools():
    """The assembler wires BOTH surfaces: the research_graph worker toolset (so
    the agent can create Hypothesis/VerificationMethod/ConfirmationCriteria) and
    the MooseChem strategy tools."""
    system = build_system(get_config())
    agent = system.agent("HypothesesAgent")

    names = _function_tool_names(agent)
    assert {"retrieve_validation_tools", "generate_via_moosechem",
            "run_critic_loop"} <= names, sorted(names)

    # The graph surface is attached as a worker toolset (no .name of its own).
    assert any(getattr(t, "surface", None) == "worker" for t in agent.tools), (
        "HypothesesAgent must carry the research_graph worker surface — it is "
        "the only role allowed to create Hypothesis/VerificationMethod/"
        "ConfirmationCriteria, and without the surface cannot reach the graph"
    )

    # before_agent_callback must be a list (not a single wrapper that tries to
    # call a list) so ADK runs the chain: inject_state FIRST, then the two
    # system.yaml callbacks (before_get_task, inject_research_context).
    assert isinstance(agent.before_agent_callback, list)
    callback_names = [
        getattr(c, "__name__", type(c).__name__)
        for c in agent.canonical_before_agent_callbacks
    ]
    assert callback_names[0] == "inject_state"
    assert callback_names[1:] == ["before_get_task", "inject_research_context"]


def test_instruction_carries_graph_commit_and_strategy():
    """The wrapper's instruction is the graph-aware prompt PLUS the MooseChem
    strategy appendix — it must teach ``research_commit`` AND name the strategy
    tools, so the LLM both generates (MooseChem) and writes (graph)."""
    system = build_system(get_config())
    agent = system.agent("HypothesesAgent")
    instruction = agent.instruction
    assert "generate_via_moosechem" in instruction
    assert "research_commit" in instruction
    assert "HOW YOU GENERATE" in instruction


def test_guard_unknown_tools_accepts_graph_and_strategy_tools():
    """The after_model guard's whitelist covers the graph surface AND the
    strategy tools, so legitimate calls pass and only unknown tools are caught."""
    system = build_system(get_config())
    agent = system.agent("HypothesesAgent")

    guard = agent.after_model_callback
    assert guard is not None

    for name in ("generate_via_moosechem", "run_critic_loop",
                 "retrieve_validation_tools", "research_commit"):
        assert guard(_CallbackContext(), _llm_response_with_tool(name)) is None, name

    # An unknown tool must be caught and replaced with a corrective response.
    caught = guard(_CallbackContext(), _llm_response_with_tool("bogus_tool"))
    assert caught is not None
    assert "bogus_tool" in caught.content.parts[0].text
