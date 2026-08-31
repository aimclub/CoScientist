"""Unit tests for the microfluidics stage 3–11 stubs (no LLM, no services).

Stages 3–11 are wired against STUBS: the external services (molecular design,
retrosynthesis, CFD, the rig) are not connected yet, so each stub returns a
static, canonical answer. That keeps the graph runnable end to end. The point
of these tests is the contract the graph depends on — the shape of the answer
and its determinism — so that swapping a stub body for the real service later
is a visible, testable change.

Economics (stage 5) has already graduated to the real chemquote MCP service
(CoScientist/tools/economics_tools.py) and is NOT covered here — like
``finish_optimization``, it is real wiring, not a placeholder, so it is out
of scope for a stub-contract test.

Run from the repo root:  pytest tests/unit/test_microfluidics_stubs.py -q
"""
import pytest
from dotenv import load_dotenv

load_dotenv()

from CoScientist.microfluidics.stubs import (  # noqa: E402
    cfd_mcp_stub,
    finish_optimization,
    molecular_design_stub,
    retrosynthesis_stub,
    rig_mcp_stub,
)

STUBS = (
    molecular_design_stub,
    retrosynthesis_stub,
    cfd_mcp_stub,
    rig_mcp_stub,
)

CALLS = {
    molecular_design_stub: {"requirements": "ПАВ для МУН, минерализованная вода"},
    retrosynthesis_stub: {"smiles": "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]"},
    cfd_mcp_stub: {"geometry": "T-junction, 200 мкм", "flow": "0.5 мл/мин"},
    rig_mcp_stub: {"command": "set_flow_rate(0.5)"},
}


# ── every stub is honest about being a stub ──────────────────────────────────

@pytest.mark.parametrize("stub", STUBS, ids=lambda s: s.__name__)
def test_stub_is_marked_as_a_stub(stub):
    """A reader (and the prompt docs) must never mistake a stub for the real
    service — the marker is what makes the swap point findable."""
    assert "STUB" in (stub.__doc__ or ""), f"{stub.__name__}: docstring lacks STUB"


@pytest.mark.parametrize("stub", STUBS, ids=lambda s: s.__name__)
def test_stub_answer_is_deterministic(stub):
    """Same input → byte-identical answer: a headless graph run must be
    reproducible while the services are stubbed."""
    assert stub(**CALLS[stub]) == stub(**CALLS[stub])


@pytest.mark.parametrize("stub", STUBS, ids=lambda s: s.__name__)
def test_stub_flags_itself_in_its_answer(stub):
    """The answer carries the marker too, so stubbed values are recognisable
    in the report and in the session state."""
    assert stub(**CALLS[stub])["stub"] is True


# ── per-stub contracts (what the downstream node reads) ──────────────────────

def test_molecular_design_returns_smiles_candidates_with_properties():
    """Node 3: analogues + literature facts → SMILES candidates + properties."""
    result = molecular_design_stub(**CALLS[molecular_design_stub])

    candidates = result["candidates"]
    assert candidates, "molecular design must propose at least one candidate"
    for candidate in candidates:
        assert candidate["smiles"]
        assert candidate["name"]
        assert candidate["properties"], f"{candidate['name']}: no properties"


def test_retrosynthesis_returns_a_route_with_operating_conditions():
    """Node 4: SMILES → route + the operating conditions node 6 plans against."""
    result = retrosynthesis_stub(**CALLS[retrosynthesis_stub])

    assert result["target_smiles"] == CALLS[retrosynthesis_stub]["smiles"]
    assert result["steps"], "a route needs at least one step"
    for step in result["steps"]:
        assert step["operation"]
        assert step["conditions"]


def test_cfd_returns_simulation_results():
    """Node 9: geometry / flows → simulation result."""
    result = cfd_mcp_stub(**CALLS[cfd_mcp_stub])

    assert result["pressure_drop_bar"] > 0
    assert result["mixing_efficiency"] > 0
    assert result["converged"] is True


def test_rig_returns_status_and_telemetry():
    """Node 10: commands → telemetry + status."""
    result = rig_mcp_stub(**CALLS[rig_mcp_stub])

    assert result["command"] == CALLS[rig_mcp_stub]["command"]
    assert result["status"] == "ok"
    assert result["telemetry"]


# ── the real tool: the only way out of the 7⇄8 loop ──────────────────────────

def _tool_context():
    """A ToolContext stand-in carrying REAL ADK EventActions — escalate is the
    actual field LoopAgent reads, so it must not be faked."""
    from types import SimpleNamespace

    from google.adk.events.event_actions import EventActions

    return SimpleNamespace(actions=EventActions())


def test_finish_optimization_escalates_to_break_the_loop():
    context = _tool_context()

    result = finish_optimization(reason="целевая конверсия достигнута",
                                 tool_context=context)

    assert context.actions.escalate is True, "without escalate the loop never ends"
    assert result["reason"] == "целевая конверсия достигнута"


def test_finish_optimization_is_not_a_stub():
    """It is real wiring, not a placeholder — the loop's exit must survive the
    swap to real services."""
    assert "STUB" not in (finish_optimization.__doc__ or "")
