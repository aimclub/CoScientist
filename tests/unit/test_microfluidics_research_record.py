"""Stage recorders write the microfluidics pipeline into the research graph,
and the literature agent's summary + tables render from literature_analysis."""
from __future__ import annotations

import pytest

from CoScientist.graph.research.store import ResearchGraphStore
from CoScientist.microfluidics import research_record as rr
from CoScientist.microfluidics.literature_report import (
    MARKDOWN_KEY, publish_literature_summary, render_literature_markdown,
)


class _Ctx:
    def __init__(self, state):
        self.state = state


TZ = {
    "original_request": "Нужен беззольный фенольный антиоксидант с третичным амином",
    "blocks": [
        {"title": "Целевой продукт", "fields": [
            {"name": "Целевое вещество", "value": "2,6-ди-трет-бутил-4-(диметиламинометил)фенол",
             "status": "задано заказчиком"}]},
        {"title": "Критерии качества", "fields": [
            {"name": "Минимальная чистота образца", "value": "80 %", "status": "задано заказчиком"},
            {"name": "Масса образца", "value": "1 г", "status": "задано заказчиком"},
            {"name": "Метод анализа", "value": "Не задано", "status": "не задано"}]},
    ],
}
QUERIES = {"queries": [
    {"id": "LIT-01", "task": "Реакция Манниха 2,6-ДТБФ", "extract": ["условия", "выход"]},
    {"id": "LIT-02", "task": "Аналоги Агидол", "extract": ["SMILES"]},
]}
ANALYSIS = {
    "target_molecule": {"fixed": True, "name": "Агидол-3",
                        "smiles": "CN(C)Cc1cc(C(C)(C)C)c(O)c(C(C)(C)C)c1", "source": "ТЗ"},
    "source_records": [
        {"source_id": "S1", "title": "Mannich bases of hindered phenols", "url": "https://example.org/abc",
         "source_type": "paper", "full_text_available": True, "verified_by": "evidence_verifier"},
        {"source_id": "S2", "title": "RU patent", "external_id": "RU123", "source_type": "patent"},
    ],
    "analogues": [{"name": "Агидол-1", "smiles": "Cc1cc(C(C)(C)C)c(O)c(C(C)(C)C)c1",
                   "compound_class": "экранированный фенол",
                   "properties": [{"name": "Тпл", "value": "70 °C"}],
                   "relevance": "тот же класс", "sources": ["https://example.org/abc"]}],
    "synthesis_routes": [{
        "product": "Агидол-3",
        "steps": [{"operation": "аминометилирование (Манних)",
                   "reagents": ["2,6-ДТБФ", "CH2O", "Me2NH"], "products": ["Агидол-3"],
                   "yield_value": "85 %",
                   "conditions": [{"name": "T", "value": "60 °C"}, {"name": "t", "value": "2 ч"}],
                   "evidence": [{"source_id": "S1", "locator": "p. 3", "verification_status": "verified"}]}],
        "flow_suitability": "гомогенная, подходит", "sources": ["https://example.org/abc"],
        "evidence": [{"source_id": "S1", "verification_status": "verified"}],
    }],
    "facts": [{"statement": "Избыток формальдегида даёт бис-продукт", "query_id": "LIT-01",
               "evidence": [{"source_id": "S2", "verification_status": "unverified"}]}],
    "gaps": ["нет данных по кинетике"],
}
DESIGN = {"fixed_target": True, "candidates": [
    {"name": "Агидол-3", "smiles": "CN(C)Cc1cc(C(C)(C)C)c(O)c(C(C)(C)C)c1",
     "compound_class": "экранированный фенол", "tz_fit": "все требования", "source": "ТЗ"}]}
ROUTES = {"routes": [{
    "route_id": "GPN-1", "product": {"name": "Агидол-3", "smiles": "CN(C)Cc1cc(C(C)(C)C)c(O)c(C(C)(C)C)c1"},
    "source": "ретросинтез", "overall_status": "eligible",
    "steps": [{"operation": "Манних", "reactants": [{"name": "2,6-DTBP"}, {"name": "formaldehyde"},
                                                    {"name": "dimethylamine"}],
               "products": [{"name": "Agidol-3"}], "conditions": [{"name": "T", "value": "60 °C"}],
               "conditions_status": "reported", "yield_fraction": 0.85, "yield_status": "reported"}],
}, {
    "route_id": "GPN-2", "product": {"name": "Агидол-3", "smiles": "CN(C)Cc1cc(C(C)(C)C)c(O)c(C(C)(C)C)c1"},
    "source": "ретросинтез", "overall_status": "rejected",
    "steps": [{"operation": "бромирование + аминирование", "reactants": [{"name": "Br2"}],
               "products": [{"name": "Agidol-3"}], "conditions": [], "conditions_status": "missing",
               "conditions_missing_reason": "нет", "yield_fraction": None, "yield_status": "missing",
               "yield_missing_reason": "нет"}],
}]}
RANKING = {"target_qty": 1, "target_unit": "g", "preferred_currency": "RUB", "routes": {
    "GPN-1": {"status": "ranked", "rank": 1, "currency": "RUB", "cost_per_unit": "12.5", "cost_packs": "5400"},
}}


@pytest.fixture
def graph(tmp_path, monkeypatch):
    store = ResearchGraphStore(directory=str(tmp_path), active_file="research_active.json")
    monkeypatch.setattr(rr, "_graph", lambda ctx: store)
    monkeypatch.setattr(rr, "REPORTS_DIR", tmp_path / "reports")
    return store


def _types(store):
    counts = {}
    for _, d in store.full_graph().nodes(data=True):
        counts[d.get("type")] = counts.get(d.get("type"), 0) + 1
    return counts


def _edge_types(store):
    return {d.get("type") for _, _, d in store.full_graph().edges(data=True)}


def test_full_pipeline_is_recorded(graph):
    state = {"structured_tz": TZ, "tz_literature_queries": QUERIES}
    ctx = _Ctx(state)

    rr.record_research_question(ctx)
    rec = state[rr.RECORD_KEY]
    assert rec["question"] and len(rec["constraints"]) == 2
    assert set(rec["lit_methods"]) == {"LIT-01", "LIT-02"}
    # Only configured services become Tool nodes; the experiment module always.
    assert _types(graph)["Tool"] == len(rr._tools()) >= 1

    state["literature_analysis"] = ANALYSIS
    rr.record_literature_evidence(ctx)
    rec = state[rr.RECORD_KEY]
    assert len(rec["literature_evidence"]) == 3  # analogue + route + fact
    assert graph.full_graph().nodes[rec["lit_methods"]["LIT-01"]]["status"] == "done"

    state["design_candidates"] = DESIGN
    rr.record_design_hypotheses(ctx)
    assert len(state[rr.RECORD_KEY]["hypotheses"]) == 1

    state["synthesis_routes"] = ROUTES
    state["qualified_routes"] = {"status": "ok"}
    rr.record_synthesis_routes(ctx)
    rec = state[rr.RECORD_KEY]
    assert set(rec["routes"]) == {"GPN-1", "GPN-2"}
    h = next(iter(rec["hypotheses"].values()))
    assert graph.full_graph().nodes[h]["status"] == "under_verification"

    state["economics_ranking"] = RANKING
    rr.record_economics_evidence(ctx)
    assert len(state[rr.RECORD_KEY]["economics_evidence"]) == 1

    state["optimization_result"] = {"task_id": "t-1", "status": "completed", "result": {"yield": "83 %"}}
    state["optimization_summary"] = "оптимизация завершена"
    rr.record_experiment_evidence(ctx)
    assert len(state[rr.RECORD_KEY]["experiment_evidence"]) == 1
    assert graph.full_graph().nodes[rec["routes"]["GPN-1"]]["status"] == "done"

    state["final_report"] = "# Отчёт\n\nРекомендован маршрут GPN-1."
    rr.record_conclusion(ctx)
    rec = state[rr.RECORD_KEY]
    assert rec["conclusion"] and rec["report"]
    assert state["final_report_path"].endswith(".md")
    assert graph.full_graph().nodes[rec["question"]]["status"] == "closed"

    types_ = _types(graph)
    assert types_["ResearchQuestion"] == 1 and types_["Hypothesis"] == 1
    assert types_["VerificationMethod"] == 4 and types_["Evidence"] == 5
    assert types_["Conclusion"] == 1 and types_["Report"] == 1
    assert {"motivates", "tested_by", "produces", "based_on", "uses", "relates_to",
            "contextualizes", "defines_scope", "derived_from"} <= _edge_types(graph)


def test_recorders_skip_quietly_without_state(graph):
    ctx = _Ctx({})
    for fn in (rr.record_research_question, rr.record_literature_evidence,
               rr.record_design_hypotheses, rr.record_synthesis_routes,
               rr.record_economics_evidence, rr.record_experiment_evidence,
               rr.record_conclusion):
        assert fn(ctx) is None
    assert graph.is_empty()


def test_literature_markdown_has_summary_and_tables():
    md = render_literature_markdown(ANALYSIS, "сводка оркестратора", QUERIES)
    assert md.startswith("## Литература: саммари и таблицы")
    for heading in ("### Саммари", "Таблица 1. Источники", "Таблица 2. Аналоги",
                    "Таблица 3. Маршруты", "Таблица 3а", "Таблица 4. Факты", "### Пробелы"):
        assert heading in md
    assert "| S1 | paper |" in md
    assert "Агидол-1" in md and "85 %" in md and "подтверждено (1)" in md
    assert "сводка оркестратора" in md and "нет данных по кинетике" in md


def test_publish_literature_summary_sets_state_and_posts(monkeypatch):
    import asyncio
    from CoScientist.logging import agent_output

    posted = []

    async def fake_report(context, payload):
        posted.append(payload)

    monkeypatch.setattr(agent_output, "report_output", fake_report)
    state = {"literature_analysis": ANALYSIS}
    # No Content is returned: the agent has an output_schema, and ADK would
    # save an after_agent Content event to output_key through that schema.
    assert asyncio.run(publish_literature_summary(_Ctx(state))) is None
    assert MARKDOWN_KEY in state
    assert posted and posted[0]["content"] == state[MARKDOWN_KEY]
    assert asyncio.run(publish_literature_summary(_Ctx({}))) is None
