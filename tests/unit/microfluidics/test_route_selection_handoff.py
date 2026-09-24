"""Module A → Module B: only the selected route travels on.

Regression for the session where route selection kept LIT-ROUTE-01 and
dropped 02–04, yet all four reached ``qualified_routes`` as ``eligible`` (03
with a Pd catalyst the ТЗ forbids), the designer invented three candidates,
the economics guard forced costing all four, and the A2A hand-off would have
shipped all four. The dropped routes now stay in the report's audit only.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from CoScientist.microfluidics.design import use_selected_route_product
from CoScientist.microfluidics.route_compliance import gate_economics, guard_economics_routes
from CoScientist.microfluidics.route_selection import (
    ROUTE_CANDIDATES_AUDIT_KEY,
    SELECTION_AUDIT_KEY,
    RouteSelectionSessionAgent,
    finalize_route_selection,
)
"""
ADDUCT = "COc1cc(C=C2C(=O)NC(=O)NC2=O)ccc1O"
TRICARBONITRILE = "COc1cc(-c2c(N)c(C#N)c(C#N)c(C#N)c2CC#N)ccc1O"


def _lit_route(route_id, product, smiles, *, reactants, agents, temperature, yield_value):
    return {
        "route_id": route_id, "product": product, "product_smiles": smiles,
        "steps": [{
            "operation": "condensation", "reactants": reactants, "agents": agents,
            "products": [product], "yield_value": yield_value,
            "conditions": [{"name": "температура", "value": temperature}],
        }],
        "flow_suitability": "подходит", "sources": ["SRC-1"],
    }


ROUTES = [
    _lit_route("LIT-ROUTE-01", "vanillin-barbituric acid adduct", ADDUCT,
               reactants=["vanillin", "barbituric acid"], agents=["water"], temperature="25 °C",
               yield_value="не указан"),
    _lit_route("LIT-ROUTE-02", "vanillin-barbituric acid adduct (coacervate)", ADDUCT,
               reactants=["vanillin", "barbituric acid"], agents=["PDADMAC-PAA"], temperature="25 °C",
               yield_value="не указан"),
    _lit_route("LIT-ROUTE-03", "GDF10", "",
               reactants=["ferulic acid", "lauric acid"], agents=["CAL-B", "Pd catalyst"],
               temperature="60 °C", yield_value="84 %"),
    _lit_route("LIT-ROUTE-04", "tricarbonitrile", TRICARBONITRILE,
               reactants=["vanillin", "malononitrile dimer salt"], agents=["acetic acid"],
               temperature="45 °C", yield_value="74 %"),
]
IDS = [route["route_id"] for route in ROUTES]


def selection(selected="LIT-ROUTE-01", ids=IDS):
    return {
        "decisions": [{
            "route_id": route_id, "product": route_id,
            "recommendation": "оставить" if route_id == selected else "отсеять",
            "reason": f"причина для {route_id}",
            "hard_violations": ["Pd-катализатор запрещён ТЗ"] if route_id == "LIT-ROUTE-03" else [],
        } for route_id in ids],
        "selected_route_id": selected,
        "selection_reason": "лучший по ТЗ",
    }


def state_for(route_selection):
    return {
        "structured_tz": {"original_request": "фенольная присадка, водная среда, 25 °C"},
        "literature_analysis": {"synthesis_routes": copy.deepcopy(ROUTES), "facts": [], "gaps": []},
        "route_selection": route_selection,
    }


def finalize(state):
    return json.loads(finalize_route_selection(SimpleNamespace(state=state)).parts[0].text)


# ── the selected route is the only active route ─────────────────────────────

def test_selected_route_is_the_only_active_route():
    state = state_for(selection())
    payload = finalize(state)
    assert [r["route_id"] for r in state["synthesis_routes"]["routes"]] == ["LIT-ROUTE-01"]
    assert state["qualified_routes"]["status"] == "ok"
    assert [r["route_id"] for r in state["qualified_routes"]["routes"]] == ["LIT-ROUTE-01"]
    assert [r["route_id"] for r in state["literature_analysis"]["synthesis_routes"]] == ["LIT-ROUTE-01"]
    assert payload["status"] == "selected_route_forwarded"
    assert payload["active_route_ids"] == ["LIT-ROUTE-01"]
    assert payload["rejected_route_ids"] == ["LIT-ROUTE-02", "LIT-ROUTE-03", "LIT-ROUTE-04"]


def test_dropped_routes_stay_in_the_audit_with_their_reasons():
    state = state_for(selection())
    finalize(state)
    audit = state[ROUTE_CANDIDATES_AUDIT_KEY]
    assert [r["route_id"] for r in audit] == ["LIT-ROUTE-02", "LIT-ROUTE-03", "LIT-ROUTE-04"]
    assert audit[1]["steps"][0]["agents"] == ["CAL-B", "Pd catalyst"]  # the full route, lossless
    rejected = {d["route_id"]: d for d in state["qualified_routes"]["rejected"]}
    assert list(rejected) == ["LIT-ROUTE-02", "LIT-ROUTE-03", "LIT-ROUTE-04"]
    assert rejected["LIT-ROUTE-03"]["overall_status"] == "rejected"
    assert rejected["LIT-ROUTE-03"]["reasons"] == ["причина для LIT-ROUTE-03", "Pd-катализатор запрещён ТЗ"]
    assert rejected["LIT-ROUTE-04"]["product"] == "tricarbonitrile"
    assert [d["route_id"] for d in state[SELECTION_AUDIT_KEY]["decisions"]] == IDS


def test_route_without_a_decision_still_gets_a_reason():
    partial = selection(ids=["LIT-ROUTE-01", "LIT-ROUTE-02"])
    state = state_for(partial)
    finalize(state)
    rejected = {d["route_id"]: d["reasons"] for d in state["qualified_routes"]["rejected"]}
    assert rejected["LIT-ROUTE-02"] == ["причина для LIT-ROUTE-02"]
    assert "LIT-ROUTE-01" in rejected["LIT-ROUTE-04"][0]


# ── without a usable selection every candidate is forwarded, as before ─────

@pytest.mark.parametrize("route_selection", [
    selection(selected=""),                                        # all «отсеять»
    {"decisions": "not a list", "selected_route_id": "LIT-ROUTE-01"},  # unparsable
    None,                                                          # never written
])
def test_without_a_usable_selection_every_candidate_is_forwarded(route_selection):
    state = state_for(route_selection)
    payload = finalize(state)
    assert [r["route_id"] for r in state["synthesis_routes"]["routes"]] == IDS
    assert [r["route_id"] for r in state["qualified_routes"]["routes"]] == IDS
    assert state["qualified_routes"]["rejected"] == []
    assert [r["route_id"] for r in state[ROUTE_CANDIDATES_AUDIT_KEY]] == IDS
    assert [r["route_id"] for r in state["literature_analysis"]["synthesis_routes"]] == IDS
    assert payload["status"] == "candidates_forwarded" and payload["rejected_route_ids"] == []


def test_selected_id_that_is_no_literature_route_forwards_every_candidate():
    state = state_for(selection(selected="LIT-ROUTE-99", ids=[*IDS, "LIT-ROUTE-99"]))
    finalize(state)
    assert [r["route_id"] for r in state["qualified_routes"]["routes"]] == IDS


def test_the_session_agent_delta_carries_the_narrowed_hand_off():
    """What AgentTool forwards to the parent is this event's state_delta."""
    state = state_for(None)
    agent = RouteSelectionSessionAgent.model_construct(name="RouteSelectionAgent")
    ctx = SimpleNamespace(session=SimpleNamespace(state=state), invocation_id="inv", branch=None)
    events = list(agent._post_final_events(ctx, json.dumps(selection())))
    delta = events[0].actions.state_delta
    assert [r["route_id"] for r in delta["synthesis_routes"]["routes"]] == ["LIT-ROUTE-01"]
    assert [r["route_id"] for r in delta["qualified_routes"]["routes"]] == ["LIT-ROUTE-01"]
    assert [r["route_id"] for r in delta[ROUTE_CANDIDATES_AUDIT_KEY]] == IDS[1:]
    assert "Выбран маршрут: **LIT-ROUTE-01**" in events[0].content.parts[0].text


# ── downstream stages see one route ─────────────────────────────────────────

def _costing_args(state, route_ids):
    by_id = {r["route_id"]: r for r in state["synthesis_routes"]["routes"]}
    audit = {r["route_id"]: r for r in state[ROUTE_CANDIDATES_AUDIT_KEY]}
    routes = []
    for route_id in route_ids:
        steps = by_id[route_id]["steps"] if route_id in by_id else audit[route_id]["steps"]
        routes.append({"route_id": route_id, "steps": [
            {"reactants": [{"name": "a"}], "products": [{"name": "b"}],
             "yield": step.get("yield_fraction")} for step in steps]})
    return {"routes": routes}


def test_economics_costs_only_the_selected_route():
    state = state_for(selection())
    finalize(state)
    context = SimpleNamespace(state=state)
    assert gate_economics(context) is None
    tool = SimpleNamespace(name="rank_routes_by_cost")
    assert guard_economics_routes(tool=tool, args=_costing_args(state, ["LIT-ROUTE-01"]), tool_context=context) is None
    blocked = guard_economics_routes(tool=tool, args=_costing_args(state, ["LIT-ROUTE-01", "LIT-ROUTE-02"]),
                                     tool_context=context)
    assert blocked and blocked["eligible_route_ids"] == ["LIT-ROUTE-01"]


# ── design takes the selected route's product ───────────────────────────────

def _design(state):
    answer = use_selected_route_product(SimpleNamespace(state=state))
    return answer, state.get("design_candidates")


def test_design_takes_the_selected_product_after_the_hand_off():
    state = state_for(selection())
    finalize(state)
    answer, candidates = _design(state)
    assert answer is not None
    assert [(c["smiles"], c["route_ids"]) for c in candidates["candidates"]] == [(ADDUCT, ["LIT-ROUTE-01"])]


@pytest.mark.parametrize("stored", [selection("LIT-ROUTE-04"), json.dumps(selection("LIT-ROUTE-04"))],
                         ids=["dict", "json"])
def test_design_finds_the_selected_route_among_several(stored):
    """A session finalized before this change still has every route in state."""
    state = state_for(stored)
    state["synthesis_routes"] = {"routes": [
        {"route_id": r["route_id"], "product": {"name": r["product"], "smiles": r["product_smiles"]}}
        for r in ROUTES]}
    _, candidates = _design(state)
    assert [(c["smiles"], c["route_ids"]) for c in candidates["candidates"]] == [
        (TRICARBONITRILE, ["LIT-ROUTE-04"])]


def test_design_without_a_selection_and_several_routes_runs_the_designer():
    answer, candidates = _design(state_for(selection(selected="")))
    assert answer is None and candidates is None


def test_design_without_a_selection_uses_the_only_route():
    state = state_for(None)
    state["literature_analysis"]["synthesis_routes"] = [copy.deepcopy(ROUTES[0])]
    _, candidates = _design(state)
    assert candidates["candidates"][0]["smiles"] == ADDUCT


def test_selected_route_without_smiles_is_a_gap_not_an_invention():
    state = state_for(selection("LIT-ROUTE-03"))
    finalize(state)
    answer, candidates = _design(state)
    assert answer is not None
    assert candidates["candidates"] == [] and "SMILES" in candidates["gaps"][0]


def test_route_selection_prompt_no_longer_promises_every_route_downstream():
    import CoScientist.agents.prompts.templates  # noqa: F401 - registers the prompts
    from CoScientist.assembly.registry import REGISTRY

    prompt = REGISTRY.prompt("microfluidics_route_selection")(None)
    assert "ТОЛЬКО выбранный" in prompt
    assert "все candidates будут переданы" not in prompt
"""