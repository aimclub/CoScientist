"""Live run of module B alone: design -> routes -> economics on the real LLM and
the real economics server, with the design and retrosynthesis stubs.

The state is seeded with what module A leaves. Two runs:

  * nothing fixed in the ТЗ — the design agent answers in DesignCandidates, the
    route agent in SynthesisRoutes (structured output next to a stub tool), and
    the economics agent costs those routes on the server;
  * the molecule fixed in the ТЗ — design is skipped (no design stub call, no
    LLM), the molecule itself goes on.

HITL is off: this checks the hand-off between the stages, not the human's
cards (see test_economics_agent.py for those).

Needs the LLM (.env), MCP_MICROFLUIDIC_ECONOMIC and the network. Run from the
repo root:

    pytest tests/integration/test_microfluidics_module_b.py -q -s
"""
import asyncio
import contextlib
import copy
import os
import sys

os.environ["HITL__ENABLED"] = "false"

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(errors="replace")

import pytest  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.getenv("MCP_MICROFLUIDIC_ECONOMIC"), reason="MCP_MICROFLUIDIC_ECONOMIC is not set"
)

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

SDS = "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]"

SEED_TZ = {
    "original_request": (
        "Нужен ПАВ для повышения нефтеотдачи в минерализованной воде при 60–90 °C, "
        "синтез на проточной установке из сырья, доступного в РФ."
    ),
    "blocks": [
        {"title": "Тип задачи", "fields": [
            {"name": "Задача с фиксированной молекулой", "value": "нет", "status": "задано заказчиком"}]},
        {"title": "Целевой продукт", "fields": [
            {"name": "Функция продукта", "value": "ПАВ для МУН", "status": "задано заказчиком"}]},
        {"title": "Критерии качества", "fields": [
            {"name": "Межфазное натяжение", "value": "< 0.01 мН/м", "status": "задано заказчиком"}]},
        {"title": "Масштаб результата", "fields": [
            {"name": "Минимальная масса образца", "value": "100 г", "status": "задано заказчиком"}]},
    ],
}

SEED_ANALYSIS = {
    "target_molecule": {"fixed": False, "name": "", "smiles": "", "cas": "", "source": "не задано"},
    "analogues": [
        {"name": "Додецилсульфат натрия (SDS)", "smiles": SDS, "compound_class": "алкилсульфаты",
         "properties": [{"name": "ККМ", "value": "8.2 ммоль/л", "conditions": "25 °C"}],
         "relevance": "простой синтез, чувствителен к жёсткости", "sources": []},
    ],
    "synthesis_routes": [
        {"product": f"sodium dodecyl sulfate ({SDS})",
         "steps": [
             {"operation": "сульфатирование в микрореакторе",
              "reagents": ["1-dodecanol (CCCCCCCCCCCCO)", "chlorosulfonic acid (OS(=O)(=O)Cl)"],
              "products": ["dodecyl hydrogen sulfate (CCCCCCCCCCCCOS(=O)(=O)O)"],
              "yield_value": "92 %",
              "conditions": [{"name": "Температура", "value": "20 °C", "conditions": ""},
                             {"name": "Растворитель", "value": "dichloromethane, 5 мл на 1 г спирта",
                              "conditions": ""}]},
             {"operation": "нейтрализация",
              "reagents": ["продукт стадии 1", "sodium hydroxide ([Na+].[OH-])"],
              "products": [f"sodium dodecyl sulfate ({SDS})"],
              "yield_value": "95 %",
              "conditions": [{"name": "Температура", "value": "30 °C", "conditions": ""}]},
         ],
         "flow_suitability": "экзотермика — узкий канал", "sources": ["doi:10.0000/example"]},
    ],
    "facts": [], "gaps": [],
}

KICKOFF = "Выполни свою стадию по данным из состояния сессии."


async def _run_module(state):
    from CoScientist.assembly import build_system
    from CoScientist.assembly.schema import resolve_config_path

    system = build_system(config_path=resolve_config_path("microfluidics"))
    service = InMemorySessionService()
    await service.create_session(app_name="b", user_id="u", session_id="s", state=state)
    runner = Runner(agent=system.agent("ModuleB_Design"), app_name="b", session_service=service)
    calls = []
    async for event in runner.run_async(
        user_id="u", session_id="s",
        new_message=types.Content(role="user", parts=[types.Part(text=KICKOFF)]),
    ):
        for part in (event.content.parts if event.content else None) or []:
            if getattr(part, "function_call", None):
                calls.append((event.author, part.function_call.name))
                print(f"[B] {event.author} -> {part.function_call.name}")
    session = await service.get_session(app_name="b", user_id="u", session_id="s")
    return dict(session.state), calls


def test_module_b_hands_structured_routes_to_the_economics_server():
    from CoScientist.microfluidics.models import DesignCandidates, SynthesisRoutes

    state, calls = asyncio.run(_run_module({
        "structured_tz": SEED_TZ,
        "target_molecule": SEED_ANALYSIS["target_molecule"],
        "literature_analysis": SEED_ANALYSIS,
    }))

    candidates = DesignCandidates.model_validate(state["design_candidates"])
    assert candidates.candidates and not candidates.fixed_target
    routes = SynthesisRoutes.model_validate(state["synthesis_routes"])
    assert routes.routes, "no routes"
    assert any(r.source == "литература" for r in routes.routes), "the literature route was not taken"
    assert all(r.steps and r.steps[0].products for r in routes.routes)

    names = [name for _, name in calls]
    assert "molecular_design_stub" in names and "retrosynthesis_stub" in names
    assert "rank_routes_by_cost" in names
    ranking = state.get("economics_ranking") or {}
    assert ranking.get("routes"), "the server's ranking was not kept"
    assert state.get("economics")


def test_a_fixed_molecule_skips_design():
    from CoScientist.microfluidics.models import DesignCandidates, SynthesisRoutes

    tz = copy.deepcopy(SEED_TZ)
    tz["blocks"][0]["fields"][0]["value"] = "да"
    tz["blocks"][1]["fields"] += [
        {"name": "Конкретное целевое вещество", "value": "Додецилсульфат натрия", "status": "задано заказчиком"},
        {"name": "SMILES", "value": SDS, "status": "задано заказчиком"},
    ]
    state, calls = asyncio.run(_run_module({
        "structured_tz": tz,
        "literature_analysis": SEED_ANALYSIS,
    }))

    candidates = DesignCandidates.model_validate(state["design_candidates"])
    assert candidates.fixed_target
    assert [c.smiles for c in candidates.candidates] == [SDS]
    assert "molecular_design_stub" not in [name for _, name in calls]
    routes = SynthesisRoutes.model_validate(state["synthesis_routes"])
    assert routes.routes
