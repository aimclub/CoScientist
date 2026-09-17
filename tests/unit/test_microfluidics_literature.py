"""Module A hand-off: literature findings accumulate, the target molecule is
read from the ТЗ, and a fixed molecule from the ТЗ wins in the analysis."""
from types import SimpleNamespace

from google.genai import types

from CoScientist.microfluidics.literature import (
    collect_literature_finding,
    extract_target_molecule,
    inject_target_molecule,
    pin_target_molecule,
)
from CoScientist.microfluidics.models import LiteratureAnalysis


def _ctx(state, request=""):
    content = types.Content(role="user", parts=[types.Part(text=request)])
    return SimpleNamespace(state=state, user_content=content)


def _tz(fixed="да", smiles="CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]", smiles_status="задано заказчиком"):
    return {
        "original_request": "Синтезировать SDS на проточном реакторе",
        "blocks": [
            {"title": "Тип задачи", "fields": [
                {"name": "Задача с фиксированной молекулой", "value": fixed,
                 "status": "задано заказчиком"},
            ]},
            {"title": "Целевой продукт", "fields": [
                {"name": "Конкретное целевое вещество", "value": "Додецилсульфат натрия",
                 "status": "задано заказчиком"},
                {"name": "SMILES", "value": smiles, "status": smiles_status},
                {"name": "CAS", "value": "Не задано", "status": "не задано"},
            ]},
        ],
    }


# ── Target molecule ──────────────────────────────────────────────────────────

def test_fixed_molecule_is_read_from_the_tz():
    target = extract_target_molecule(_tz())
    assert target.fixed is True
    assert target.name == "Додецилсульфат натрия"
    assert target.smiles.startswith("CCCCCCCCCCCC")
    assert target.cas == ""  # "Не задано" is not a value
    assert target.source == "ТЗ"


def test_explicit_no_is_not_fixed_even_with_smiles():
    assert extract_target_molecule(_tz(fixed="нет")).fixed is False


def test_smiles_without_the_flag_means_fixed():
    tz = _tz()
    tz["blocks"][0]["fields"] = []
    assert extract_target_molecule(tz).fixed is True


def test_no_target_in_the_tz():
    target = extract_target_molecule({"blocks": []})
    assert target.fixed is False and target.source == "не задано"


def test_malformed_tz_does_not_raise():
    assert extract_target_molecule({"blocks": "garbage"}).fixed is False


def test_inject_writes_the_state_key():
    state = {"structured_tz": _tz()}
    inject_target_molecule(_ctx(state))
    assert state["target_molecule"]["fixed"] is True


# ── Findings ─────────────────────────────────────────────────────────────────

def test_findings_accumulate_across_tasks():
    state = {}
    state["search_results"] = "ответ 1"
    collect_literature_finding(_ctx(state, "LIT-01: маршруты синтеза SDS"))
    state["search_results"] = "ответ 2"
    collect_literature_finding(_ctx(state, "LIT-02: свойства аналогов"))

    findings = state["literature_findings"]
    assert [f["query_id"] for f in findings] == ["LIT-01", "LIT-02"]
    assert [f["result"] for f in findings] == ["ответ 1", "ответ 2"]


def test_retry_of_the_same_task_replaces_its_answer():
    state = {"search_results": "пусто"}
    collect_literature_finding(_ctx(state, "LIT-01: запрос"))
    state["search_results"] = "полный ответ"
    collect_literature_finding(_ctx(state, "LIT-01: переформулированный запрос"))
    assert [f["result"] for f in state["literature_findings"]] == ["полный ответ"]


def test_stale_search_results_are_not_recorded_twice():
    state = {"search_results": "ответ 1"}
    collect_literature_finding(_ctx(state, "LIT-01: запрос"))
    # LIT-02 failed and wrote nothing — the copied state still holds LIT-01's answer.
    collect_literature_finding(_ctx(state, "LIT-02: запрос"))
    assert len(state["literature_findings"]) == 1


# ── Pinning ──────────────────────────────────────────────────────────────────

def test_tz_molecule_wins_in_the_analysis():
    analysis = LiteratureAnalysis.model_validate({
        "target_molecule": {"fixed": False, "name": "SDBS", "source": "литература"},
        "gaps": ["нет данных по ККМ"],
    }).model_dump()
    state = {"structured_tz": _tz(), "literature_analysis": analysis}
    pin_target_molecule(_ctx(state))
    pinned = state["literature_analysis"]
    assert pinned["target_molecule"]["name"] == "Додецилсульфат натрия"
    assert pinned["target_molecule"]["fixed"] is True
    assert pinned["gaps"] == ["нет данных по ККМ"]


def test_literature_choice_stays_when_the_tz_fixes_nothing():
    analysis = {"target_molecule": {"fixed": False, "name": "SDBS", "source": "литература"}}
    state = {"structured_tz": {"blocks": []}, "literature_analysis": analysis}
    pin_target_molecule(_ctx(state))
    assert state["literature_analysis"]["target_molecule"]["name"] == "SDBS"
