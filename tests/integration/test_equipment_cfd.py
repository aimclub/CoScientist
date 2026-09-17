"""Live run of EquipmentAgent alone against the CFD service (emulator deployment).

The state holds an experiment plan; the agent must pick a reactor from
cfd_list_reactors, start a run with its own request_id, follow it to a final
status (polling a pending run) and write the journal. What the CFD service then
reports — succeeded or failed — is its business: the check is that the run
reached the state under its request id and the journal cites it.

The rig is still a stub. HITL is off. Safe ONLY against the emulator: a real
solver run takes hours.

Needs the LLM (.env), MCP_MICROFLUIDIC_CFD_3_TOOLS with its key, and the
network. Run from the repo root:

    pytest tests/integration/test_equipment_cfd.py -q -s
"""
import asyncio
import contextlib
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
    not os.getenv("MCP_MICROFLUIDIC_CFD_3_TOOLS"), reason="MCP_MICROFLUIDIC_CFD_3_TOOLS is not set"
)

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

PLAN = """План опытов (итерация 1).
Опыт 1. Нейтрализация: поток A — додецилгидросульфат, 100 моль/м3; поток B — NaOH,
100 моль/м3; T-образный смеситель с двумя входами; скорость на входе 0.02 м/с;
температура 25 °C; константа скорости 0.01 м3/(моль·с) (оценка из литературы).
Критерий успеха: конверсия A не ниже 90 %, перепад давления не выше 1 бар.
Сначала расчёт CFD, затем одна команда на установку с этим режимом."""


async def _run():
    from CoScientist.assembly import build_system
    from CoScientist.assembly.schema import resolve_config_path

    system = build_system(config_path=resolve_config_path("microfluidics"))
    service = InMemorySessionService()
    await service.create_session(app_name="eq", user_id="u", session_id="s",
                                 state={"experiment_plan": PLAN})
    runner = Runner(agent=system.agent("EquipmentAgent"), app_name="eq", session_service=service)
    calls = []
    async for event in runner.run_async(
        user_id="u", session_id="s",
        new_message=types.Content(role="user", parts=[types.Part(text="Выполни план опытов.")]),
    ):
        for part in (event.content.parts if event.content else None) or []:
            call = getattr(part, "function_call", None)
            if call:
                calls.append(call.name)
                print(f"[eq] -> {call.name} {dict(call.args or {})}"[:300])
    session = await service.get_session(app_name="eq", user_id="u", session_id="s")
    return dict(session.state), calls


def test_equipment_agent_runs_cfd_to_a_final_status():
    state, calls = asyncio.run(_run())

    assert "cfd_list_reactors" in calls
    assert "cfd_run_reactor_experiment" in calls
    runs = state.get("cfd_runs") or {}
    assert runs, "no CFD run reached the state"
    final = {rid: r["status"] for rid, r in runs.items()}
    print("[eq] runs:", final)
    assert any(status in {"succeeded", "failed", "cancelled"} for status in final.values()), final
    journal = str(state.get("experiment_journal") or "")
    assert any(rid in journal for rid in runs), "the journal does not cite the run"
