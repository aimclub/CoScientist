"""Module B hand-off and stage 9: a fixed molecule skips design, the structured
routes fit the economics server, and CFD results are kept as the service gave
them (answers recorded in tests/fixtures/cfd_mcp/)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import CoScientist.assembly.bindings  # noqa: F401 — registers tools, prompts, schemas
from CoScientist.assembly.prompting import PromptContext
from CoScientist.assembly.registry import REGISTRY
from CoScientist.assembly.schema import load_config, resolve_config_path
from CoScientist.hitl.work_order_risk import Tier, tool_tier
from CoScientist.microfluidics.cfd import collect_cfd_result
from CoScientist.microfluidics.design import fixed_target_candidates, use_fixed_target_molecule
from CoScientist.microfluidics.economics import collect_economics_result
from CoScientist.microfluidics.models import DesignCandidates, SynthesisRoutes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CFD_TOOLS = {
    "cfd_list_reactors", "cfd_run_reactor_experiment", "cfd_get_experiment_result",
    "cfd_list_artifacts", "cfd_cancel_run",
}
SDS = "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]"


def _fixture(server, name):
    return json.loads((FIXTURES / f"{server}_mcp" / f"{name}.json").read_text(encoding="utf-8"))


def _tz(fixed="да", smiles=SDS):
    return {"blocks": [
        {"title": "Тип задачи", "fields": [
            {"name": "Задача с фиксированной молекулой", "value": fixed, "status": "задано заказчиком"}]},
        {"title": "Целевой продукт", "fields": [
            {"name": "Конкретное целевое вещество", "value": "Додецилсульфат натрия",
             "status": "задано заказчиком"},
            {"name": "SMILES", "value": smiles or "Не задано",
             "status": "задано заказчиком" if smiles else "не задано"}]},
    ]}


ANALYSIS = {"analogues": [
    {"name": "SDBS", "smiles": "CCCCCCCCCCCCc1ccc(cc1)S(=O)(=O)[O-].[Na+]",
     "properties": [{"name": "ККМ", "value": "1.2 ммоль/л", "conditions": ""}]},
    {"name": "SDS", "smiles": SDS, "compound_class": "алкилсульфаты",
     "properties": [{"name": "ККМ", "value": "8.2 ммоль/л", "conditions": "25 °C"}]},
]}


# ── Fixed target molecule ────────────────────────────────────────────────────

def test_a_fixed_molecule_is_the_only_candidate_with_its_literature_properties():
    result = fixed_target_candidates(_tz(), ANALYSIS)
    assert result.fixed_target is True
    (candidate,) = result.candidates
    assert candidate.smiles == SDS and candidate.source == "ТЗ" and candidate.stub is False
    assert candidate.compound_class == "алкилсульфаты"
    assert [p.value for p in candidate.properties] == ["8.2 ммоль/л"]
    assert result.gaps == []


def test_no_design_is_skipped_when_nothing_is_fixed():
    assert fixed_target_candidates(_tz(fixed="нет"), ANALYSIS) is None
    assert fixed_target_candidates({"blocks": []}, ANALYSIS) is None


def test_a_fixed_molecule_without_smiles_names_the_gap():
    tz = _tz(smiles="")
    tz["blocks"][0]["fields"][0]["value"] = "да"
    result = fixed_target_candidates(tz, {"analogues": []})
    assert result.candidates[0].smiles == ""
    assert any("SMILES" in g for g in result.gaps)


def test_the_callback_answers_for_the_agent_and_fills_the_state():
    state = {"structured_tz": _tz(), "literature_analysis": ANALYSIS}
    content = use_fixed_target_molecule(SimpleNamespace(state=state))
    # ADK validates a before_agent answer against the agent's output_schema.
    answer = DesignCandidates.model_validate_json(content.parts[0].text)
    assert answer.candidates[0].name == "Додецилсульфат натрия"
    DesignCandidates.model_validate(state["design_candidates"])

    state = {"structured_tz": _tz(fixed="нет"), "literature_analysis": ANALYSIS}
    assert use_fixed_target_molecule(SimpleNamespace(state=state)) is None
    assert "design_candidates" not in state


# ── Structured routes ────────────────────────────────────────────────────────

ROUTE = {"routes": [{
    "route_id": "GPN-1",
    "product": {"name": "sodium dodecyl sulfate", "smiles": SDS},
    "source": "ретросинтез", "stub": True,
    "steps": [
        {"operation": "сульфатирование",
         "reactants": [{"name": "1-dodecanol", "smiles": "CCCCCCCCCCCCO"},
                       {"name": "chlorosulfonic acid", "smiles": "OS(=O)(=O)Cl"}],
         "agents": [{"name": "dichloromethane", "smiles": "ClCCl"}],
         "products": [{"name": "dodecyl hydrogen sulfate", "smiles": "CCCCCCCCCCCCOS(=O)(=O)O"}],
         "conditions": [{"name": "Температура", "value": "25 °C"}],
         "yield_fraction": 0.9},
        {"operation": "нейтрализация",
         "reactants": [{"name": "@prev"}, {"name": "sodium hydroxide", "smiles": "[Na+].[OH-]"}],
         "products": [{"name": "sodium dodecyl sulfate", "smiles": SDS}],
         "yield_fraction": None},
    ],
}]}


def test_routes_carry_what_the_economics_server_chains_a_route_by():
    routes = SynthesisRoutes.model_validate(ROUTE)
    step = routes.routes[0].steps[0]
    assert step.reactants[0].smiles and step.products[0].smiles
    assert routes.routes[0].steps[1].reactants[0].name == "@prev"


def test_a_yield_is_a_fraction():
    bad = json.loads(json.dumps(ROUTE))
    bad["routes"][0]["steps"][0]["yield_fraction"] = 75
    with pytest.raises(ValidationError):
        SynthesisRoutes.model_validate(bad)


def test_the_design_agents_answer_in_the_structured_schemas():
    system = load_config(resolve_config_path("microfluidics"))
    assert system.agent("MolDesignAgent").output_schema == "design_candidates"
    assert system.agent("SynthRouteAgent").output_schema == "synthesis_routes"
    assert "use_fixed_target_molecule" in system.agent("MolDesignAgent").callbacks.before_agent


# ── Economics: the recipe needs quantities ───────────────────────────────────

def test_ranking_keeps_the_starting_materials():
    state = {}
    collect_economics_result(
        tool=SimpleNamespace(name="rank_routes_by_cost"),
        args={"target_qty": 100, "target_unit": "g"},
        tool_context=SimpleNamespace(state=state),
        tool_response=_fixture("economics", "rank_routes_by_cost_smiles"),
    )
    materials = state["economics_ranking"]["routes"]["SDS-2"]["starting_materials"]
    assert {"smiles": "CCCCCCCCCCCCO", "qty": "75.572763", "unit": "g"} in materials


# ── CFD ──────────────────────────────────────────────────────────────────────

def test_documented_cfd_tools_are_the_filtered_ones_and_exist_on_the_service():
    from CoScientist.tools.research_tools import CFD_MCP_TOOLS

    documented = {d.name for d in REGISTRY.tool("cfd_mcp").resolved_docs()}
    recorded = {t["name"] for t in _fixture("cfd", "tools")}
    assert documented == set(CFD_MCP_TOOLS) == CFD_TOOLS
    assert CFD_TOOLS <= recorded


def test_documented_cfd_signatures_name_the_required_arguments():
    schemas = {t["name"]: t["inputSchema"] for t in _fixture("cfd", "tools")}
    for doc in REGISTRY.tool("cfd_mcp").resolved_docs():
        for required in schemas[doc.name].get("required", []):
            assert required in doc.signature, f"{doc.name}: {required}"


def test_cfd_tiers():
    assert tool_tier("cfd_run_reactor_experiment") is Tier.COMPUTE
    assert tool_tier("cfd_cancel_run") is Tier.COMPUTE
    for name in ("cfd_list_reactors", "cfd_get_experiment_result", "cfd_list_artifacts"):
        assert tool_tier(name) is Tier.READ


def _cfd(tool, args, response, state):
    collect_cfd_result(tool=SimpleNamespace(name=tool), args=args,
                       tool_context=SimpleNamespace(state=state), tool_response=response)


def test_a_cfd_run_is_kept_under_its_request_id():
    state = {}
    _cfd("cfd_run_reactor_experiment", {"request_id": "contract-dump-run-1"},
         _fixture("cfd", "cfd_run_reactor_experiment"), state)
    run = state["cfd_runs"]["contract-dump-run-1"]
    assert run["status"] == "failed"
    assert run["reactor"] == "t_junction"
    assert run["design"]["inlet_speed_m_per_s"] == 0.02
    assert run["residence_time_s"] == pytest.approx(4.975)
    assert run["error"]["code"] == "compute_nonzero_exit"


def test_a_pending_run_is_replaced_by_its_result():
    state = {}
    _cfd("cfd_run_reactor_experiment", {"request_id": "contract-dump-run-2"},
         _fixture("cfd", "cfd_run_reactor_experiment_pending"), state)
    assert state["cfd_runs"]["contract-dump-run-2"]["status"] == "pending"
    finished = _fixture("cfd", "cfd_get_experiment_result")
    finished["structuredContent"]["request_id"] = "contract-dump-run-2"
    _cfd("cfd_get_experiment_result", {"request_id": "contract-dump-run-2"}, finished, state)
    assert state["cfd_runs"]["contract-dump-run-2"]["status"] == "failed"


def test_cfd_errors_and_listings_change_nothing():
    state = {}
    _cfd("cfd_get_experiment_result", {"request_id": "no-such-run"},
         _fixture("cfd", "cfd_get_experiment_result_unknown"), state)
    _cfd("cfd_run_reactor_experiment", {"request_id": "contract-dump-run-3"},
         _fixture("cfd", "cfd_run_reactor_experiment_single_inlet"), state)
    _cfd("cfd_list_reactors", {}, _fixture("cfd", "cfd_list_reactors"), state)
    assert state == {}


@pytest.mark.parametrize("server", [True, False])
def test_equipment_prompt_follows_the_attached_cfd(server):
    system = load_config(resolve_config_path("microfluidics"))
    key = "cfd_mcp" if server else "cfd_mcp_stub"
    ctx = PromptContext(config=system.agent("EquipmentAgent"), system=system,
                        tool_entries=[REGISTRY.tool(key), REGISTRY.tool("rig_mcp_stub")])
    text = REGISTRY.prompt("microfluidics_equipment")(ctx)
    assert ("cfd_get_experiment_result" in text) is server
    assert ("`cfd_mcp_stub`" in text) is not server
    assert "<<" not in text


def test_report_prompt_has_the_feasibility_and_recipe_sections():
    system = load_config(resolve_config_path("microfluidics"))
    ctx = PromptContext(config=system.agent("ReportAgent"), system=system)
    text = REGISTRY.prompt("microfluidics_report")(ctx)
    assert "ТЭО" in text and "Рецептура" in text
    assert "{economics_ranking?}" in text and "{cfd_runs?}" in text
