"""Real RDKit tests on the user's phenolic antioxidant brief; no LLM/services."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdkit import Chem

from scripts.microfluidics.test_molecular_design_offline import run_async

from CoScientist.microfluidics.models import DesignCandidates
from CoScientist.microfluidics.molecular_design import molecular_design

CASE = Path(__file__).resolve().parent / "fixtures/molecular_design/phenolic_antioxidant.json"


@pytest.fixture
def case():
    return json.loads(CASE.read_text())


def run(case, **overrides):
    state = {key: copy.deepcopy(case[key]) for key in ("structured_tz", "literature_analysis")}
    request = {**case["requirements"], **overrides}
    result = run_async(molecular_design(json.dumps(request), SimpleNamespace(state=state)))
    assert state["molecular_design_result"] == result
    return result


def test_screening_rejects_bisether_without_free_phenolic_oh(case):
    result = run(case, generate=False)
    assert result["status"] == "ok"
    assert result["enumerated"] == 0
    expected = {a["name"] for a in case["literature_analysis"]["analogues"]} - {"гидрохинон-бис(2-гидроксиэтил)эфир"}
    assert {c["name"] for c in result["candidates"]} == expected
    assert [r["name"] for r in result["rejected"]] == ["гидрохинон-бис(2-гидроксиэтил)эфир"]
    assert result["rejected"][0]["reason"] == "Структурные ограничения"


def test_no_claimed_purity_or_stability_from_unreferenced_general_facts(case):
    result = run(case)
    assert result["status"] == "ok"
    for checks in result["criteria_checks"].values():
        assert len(checks) == 2
        assert all(check["status"] == "unknown" and not check["observed"] for check in checks)
    for candidate in result["candidates"]:
        assert "Полное соответствие ТЗ не подтверждено" in candidate["tz_fit"]
        assert candidate["stub"] is False
        assert all("Расчёт RDKit" in p["conditions"] for p in candidate["properties"])
    assert all(c["name"] != "MolWt" for c in case["requirements"]["criteria"])


def test_generation_produces_valid_unique_phenols_without_inherited_properties(case):
    result = run(case)
    assert result["status"] == "ok"
    assert 0 < result["enumerated"] <= 100
    phenol = Chem.MolFromSmarts("[c][OX2H]")
    smiles = [c["smiles"] for c in result["candidates"]]
    assert len(smiles) == len(set(smiles))
    assert all(Chem.MolFromSmiles(s).HasSubstructMatch(phenol) for s in smiles)
    generated = [c for c in result["candidates"] if c["source"] == "дизайн"]
    assert generated
    for candidate in generated:
        assert not candidate["sources"]
        assert "BRICS" in candidate["derivation"]
        assert "гипотеза" in candidate["risks"]
    # Provenance survives the output model used by the actual agent.
    parsed = DesignCandidates.model_validate(result).model_dump()
    assert [c["derivation"] for c in parsed["candidates"]] == [c["derivation"] for c in result["candidates"]]


def test_default_limit_prioritizes_original_analogues_when_all_checks_unknown(case):
    result = run(case, max_candidates=10)
    assert len(result["candidates"]) == 10
    assert all(c["source"] == "литература" for c in result["candidates"])
    assert result["eligible_count"] >= len(result["candidates"])


def test_same_input_has_same_result(case):
    assert run(case) == run(case)


def test_numeric_mass_filter_when_explicitly_requested_as_synthetic_control(case):
    # 150 is a test control, NOT a threshold inferred from the user's brief.
    result = run(case, generate=False, criteria=[{"name": "MolWt", "maximum": 150.0, "unit": "g/mol"}])
    assert result["status"] == "ok"
    for candidate in result["candidates"]:
        check = result["criteria_checks"][candidate["smiles"]][0]
        assert check["status"] == "pass" and check["observed"][0] <= 150
    assert any(r["reason"] == "Нарушены числовые ограничения" for r in result["rejected"])


def test_empty_literature_does_not_invent_candidates(case):
    case["literature_analysis"]["analogues"] = []
    result = run(case)
    assert result["status"] == "no_candidates"
    assert result["candidates"] == []


def test_route_product_with_explicit_smiles_is_a_route_backed_candidate(case):
    product = "O=C1NC(=O)NC(=O)C1=Cc1ccc(O)c(OC)c1"
    case["literature_analysis"]["analogues"] = []
    case["literature_analysis"]["synthesis_routes"] = [{
        "route_id": "LIT-ROUTE-01",
        "product": "Продукт конденсации",
        "product_smiles": product,
        "sources": ["paper-1"],
    }]
    result = run(case, generate=False)
    assert result["status"] == "ok"
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["route_ids"] == ["LIT-ROUTE-01"]
    assert candidate["derivation"] == "Продукт литературного маршрута"


@pytest.mark.parametrize("pattern", ["", "invalid[", "[c"])
def test_invalid_smarts_returns_explicit_error(case, pattern):
    result = run(case, required_smarts=[pattern])
    assert result["status"] == "error"
    assert result["candidates"] == []
    assert result["gaps"]


def test_fixed_target_bypasses_enumeration(case):
    case["structured_tz"]["blocks"] = [
        {"title": "Тип задачи", "fields": [{"name": "Фиксированная молекула", "value": "Да", "status": "задано заказчиком"}]},
        {"title": "Целевой продукт", "fields": [
            {"name": "Целевое вещество", "value": "ванилин", "status": "задано заказчиком"},
            {"name": "SMILES", "value": "COc1cc(C=O)ccc1O", "status": "задано заказчиком"},
        ]},
    ]
    result = run(case)
    assert result["status"] == "fixed_target"
    assert result["fixed_target"] is True
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["name"] == "ванилин"
