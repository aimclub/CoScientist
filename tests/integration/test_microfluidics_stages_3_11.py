"""Live headless smoke test of the microfluidics stages 3–11.

Runs the NEW part of the graph — design (B) → experiment (C) → report (D) — on
a seeded ТЗ + literature analysis, and checks that it reaches node 11 with a
`final_report`, that the 7⇄8 loop actually cycles and terminates, and that the
report does not pass stubbed numbers off as measurements.

Scope, and why it is what it is: nodes 3, 4, 5, 9 and 10 are STUBS, so modules
B, C and D need nothing but an LLM endpoint. Module A is NOT stubbed —
ResearchAgent talks to the ITMO-hosted MCP services — so the ROOT is not run
here; the modules are invoked in the fixed order RootOrchestrator is prompted
to use. The full-graph run (root + module A) lives in
test_microfluidics_e2e.py and needs the VPN.

Requires the real LLM (.env) and network; HITL is disabled for the run.

Run from the repo root:
    pytest tests/integration/test_microfluidics_stages_3_11.py -q -s
"""
import asyncio
import contextlib
import os
import sys

# Must be set BEFORE any CoScientist import: HITL handlers and tools are wired
# at import/build time from settings. With HITL off, EquipmentAgent's approval
# tools are simply not attached, so the loop runs unattended.
os.environ.setdefault("HITL__ENABLED", "false")

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from CoScientist.assembly import build_system  # noqa: E402
from CoScientist.config import get_settings  # noqa: E402
from CoScientist.assembly.schema import resolve_config_path  # noqa: E402

APP, USER, SESSION = "microfluidics_stages_3_11", "test_user", "session_3_11"

# The modules in the order RootOrchestrator is told to run them (A→B→C→D).
MODULES = ("ModuleB_Design", "ModuleC_Experiment", "ReportAgent")

# What module A would have left in the state.
SEED_TZ = {
    "original_request": (
        "Нужен отечественный ПАВ для повышения нефтеотдачи (МУН): работа в "
        "минерализованной воде с ионами Ca2+/Mg2+ при 60–90 °C, критично "
        "низкое межфазное натяжение нефть/вода. Синтез должен быть реализуем "
        "на проточной микрофлюидной установке из доступного в РФ сырья."
    ),
    "blocks": [
        {"title": "Тип задачи", "usage": "Определяет сценарий",
         "fields": [{"name": "Тип задачи", "value": "Разработка ПАВ",
                     "status": "задано заказчиком"}]},
        {"title": "Целевой продукт",
         "fields": [
             {"name": "Функция продукта", "value": "ПАВ для МУН",
              "status": "задано заказчиком"},
             {"name": "CAS целевого вещества"},
         ]},
        {"title": "Критерии качества",
         "fields": [
             {"name": "Межфазное натяжение", "value": "< 0.01 мН/м",
              "status": "задано заказчиком"},
             {"name": "Солеустойчивость", "value": "до 100 г/л NaCl",
              "status": "задано заказчиком"},
             {"name": "Термостабильность", "value": "60–90 °C",
              "status": "задано заказчиком"},
         ]},
    ],
}

SEED_SEARCH_RESULTS = (
    "LIT-01. Классы ПАВ для МУН в минерализованной воде: сульфонаты "
    "(SDBS) — дёшевы, но осаждаются Ca2+/Mg2+ выше 50 г/л; бетаины (CAPB) — "
    "устойчивы к жёсткости и к 90 °C, МПН до 0.008 мН/м в смеси с "
    "со-ПАВ. LIT-02. Маршруты синтеза: сульфатирование жирных спиртов "
    "хлорсульфоновой кислотой с последующей нейтрализацией; амидирование "
    "жирных кислот с кватернизацией для бетаинов. LIT-03. Проточный синтез: "
    "экзотермика сульфатирования требует узкого канала и контроля времени "
    "контакта; описан микрореактор с T-образным смесителем."
)

# What module A hands on: the structured literature analysis (routes with step
# products and yields, so the economics stage can cost them).
SEED_LITERATURE_ANALYSIS = {
    "target_molecule": {"fixed": False, "name": "", "smiles": "", "cas": "",
                        "source": "не задано"},
    "analogues": [
        {"name": "Додецилбензолсульфонат натрия (SDBS)",
         "smiles": "CCCCCCCCCCCCc1ccc(cc1)S(=O)(=O)[O-].[Na+]",
         "compound_class": "сульфонаты",
         "properties": [{"name": "Солеустойчивость", "value": "до 50 г/л",
                         "conditions": "Ca2+/Mg2+"}],
         "relevance": "дёшев, но осаждается в жёсткой воде", "sources": []},
        {"name": "Кокамидопропилбетаин (CAPB)",
         "smiles": "CCCCCCCCCCCC(=O)NCCC[N+](C)(C)CC(=O)[O-]",
         "compound_class": "бетаины",
         "properties": [{"name": "МПН", "value": "0.008 мН/м",
                         "conditions": "в смеси с со-ПАВ, 90 °C"}],
         "relevance": "устойчив к жёсткости и 90 °C", "sources": []},
    ],
    "synthesis_routes": [
        {"product": "додецилсульфат натрия (CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+])",
         "steps": [
             {"operation": "сульфатирование",
              "reagents": ["1-dodecanol (CCCCCCCCCCCCO)", "chlorosulfonic acid (OS(=O)(=O)Cl)"],
              "products": ["dodecyl hydrogen sulfate (CCCCCCCCCCCCOS(=O)(=O)O)"],
              "yield_value": "90 %",
              "conditions": [{"name": "Температура", "value": "25 °C", "conditions": ""}]},
             {"operation": "нейтрализация",
              "reagents": ["продукт стадии 1", "sodium hydroxide ([Na+].[OH-])"],
              "products": ["sodium dodecyl sulfate (CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+])"],
              "yield_value": "95 %",
              "conditions": [{"name": "Температура", "value": "30 °C", "conditions": ""}]},
         ],
         "flow_suitability": "экзотермика — узкий канал, контроль времени контакта",
         "sources": []},
    ],
    "facts": [{"statement": SEED_SEARCH_RESULTS, "query_id": "LIT-01", "sources": []}],
    "gaps": [],
}

SEED_STATE = {
    "structured_tz": SEED_TZ,
    "target_molecule": SEED_LITERATURE_ANALYSIS["target_molecule"],
    "literature_analysis": SEED_LITERATURE_ANALYSIS,
}

KICKOFF = "Выполни свою стадию по данным из состояния сессии."


async def _run_stages_3_to_11():
    system = build_system(config_path=resolve_config_path("microfluidics"))

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP, user_id=USER, session_id=SESSION, state=dict(SEED_STATE)
    )

    tool_calls: list[str] = []
    for module in MODULES:
        runner = Runner(
            agent=system.agent(module), app_name=APP, session_service=session_service
        )
        async for event in runner.run_async(
            user_id=USER,
            session_id=SESSION,
            new_message=types.Content(role="user", parts=[types.Part(text=KICKOFF)]),
        ):
            if not (event.content and event.content.parts):
                continue
            for part in event.content.parts:
                call = getattr(part, "function_call", None)
                if call:
                    tool_calls.append(call.name)
                    print(f"[smoke] {module}: -> {call.name}()")
        print(f"[smoke] {module}: done")

    session = await session_service.get_session(
        app_name=APP, user_id=USER, session_id=SESSION
    )
    return dict(session.state), tool_calls


def test_stages_3_to_11_reach_the_report():
    state, tool_calls = asyncio.run(_run_stages_3_to_11())

    # Module B — every design stage left its artifact for the next one.
    for key in ("design_candidates", "synthesis_routes", "economics"):
        assert state.get(key), f"module B produced no {key}"
    print(f"\n[smoke] B: candidates -> routes -> economics "
          f"({len(str(state['economics']))} chars)")

    # Module C — the plan was made and the rig ran against it.
    assert state.get("experiment_plan"), "no experiment plan (node 6)"
    assert state.get("experiment_journal"), "the rig produced no journal (node 7)"

    # The stubs behind nodes 3, 4, 5, 9, 10 were really called.
    module_b_stubs = ["molecular_design_stub", "retrosynthesis_stub"]
    if not get_settings().mcp.microfluidic_economic_url:
        module_b_stubs.append("economics_mcp_stub")  # else the real MCP server
    for stub in module_b_stubs:
        assert stub in tool_calls, f"{stub} never called — module B faked its answer"
    assert "rig_mcp_stub" in tool_calls, "node 7 never touched the rig"

    # The 7⇄8 loop terminated deliberately, not by exhausting max_iterations.
    assert "finish_optimization" in tool_calls, (
        "the optimizer never called finish_optimization — the loop only ended "
        "because max_iterations ran out"
    )

    # The optimizer shares `experiment_plan` with node 6, and ADK writes its
    # FINAL text there — including on the turn that ends the loop. So a parting
    # summary would silently overwrite the plan and leave the report without
    # one. The plan must survive the loop's exit.
    plan = str(state["experiment_plan"])
    assert len(plan) > 800, f"experiment_plan shrank to a summary: {plan!r}"
    assert "Итоги оптимизации" in plan, (
        "the optimizer dropped its rationale section from the plan"
    )

    # Module D — node 11 answered, and consumed node 5 (a dead end otherwise).
    report = state.get("final_report") or ""
    assert report, "the graph never reached node 11 with a final_report"
    assert len(report) > 500, f"final_report is a stub answer: {report!r}"
    print(f"[smoke] D: final_report {len(report)} chars")

    # The report must own up to the stubs rather than present them as data.
    assert "аглушк" in report.lower() or "stub" in report.lower(), (
        "the report does not disclose that stages 3–11 ran on stubs:\n"
        f"{report[:2000]}"
    )
    print(f"[smoke] tool calls in order: {tool_calls}")
