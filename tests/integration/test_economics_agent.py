"""Live run of EconomicsAgent alone: the real LLM, the real economics server, the
Work Order with a check of every step — answered by a recording auto-responder.

Module B is connected on its own, so nothing else runs: the state is seeded
with what modules A and B leave (ТЗ, literature analysis, synthesis routes) and
only EconomicsAgent is invoked. The checks are about the plumbing the human
relies on, not about prices:

  * the Work Order is declared, every tool step says what it SENDS, and only
    the six economics tools are planned;
  * each finished step reaches the human with the calls the system recorded;
  * rank_routes_by_cost ran and its numbers landed in economics_ranking;
  * the work report was submitted;
  * a step sent back is redone (second test).

Needs the LLM (.env), MCP_MICROFLUIDIC_ECONOMIC and the network. Run from the
repo root:

    pytest tests/integration/test_economics_agent.py -q -s
"""
import asyncio
import contextlib
import os
import sys

# Before any CoScientist import: HITL tools and Work Orders are wired at build time.
os.environ["HITL__ENABLED"] = "true"
os.environ.setdefault("WORK_ORDER__ENABLED", "true")

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

from CoScientist.hitl.handler import AbstractHITLHandler  # noqa: E402
from CoScientist.hitl.models import HITLAction, HITLResponse  # noqa: E402

AGENT = "EconomicsAgent"
ECONOMICS_TOOLS = {
    "search_reagents_by_name", "get_price", "search_by_structure",
    "resolve_chemicals", "estimate_synthesis_cost", "rank_routes_by_cost",
}

SEED_TZ = {
    "original_request": "Нужен ПАВ для МУН, синтез на проточной установке из сырья, доступного в РФ.",
    "blocks": [
        {"title": "Масштаб результата", "fields": [
            {"name": "Минимальная масса образца", "value": "100 г", "status": "задано заказчиком"},
        ]},
        {"title": "Ограничения по поставкам", "fields": [
            {"name": "Предпочтительные поставщики", "value": "российские", "status": "задано заказчиком"},
        ]},
    ],
}

# Stage 4's structured hand-off (SynthesisRoutes).
SEED_ROUTES = {"routes": [{
    "route_id": "GPN-1",
    "product": {"name": "sodium dodecyl sulfate", "smiles": "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]"},
    "source": "ретросинтез", "stub": True,
    "steps": [
        {"operation": "Сульфатирование",
         "reactants": [{"name": "1-dodecanol", "smiles": "CCCCCCCCCCCCO"},
                       {"name": "chlorosulfonic acid", "smiles": "OS(=O)(=O)Cl"}],
         "agents": [{"name": "dichloromethane", "smiles": "ClCCl"}],
         "products": [{"name": "dodecyl hydrogen sulfate", "smiles": "CCCCCCCCCCCCOS(=O)(=O)O"}],
         "conditions": [{"name": "Температура", "value": "25 °C"},
                        {"name": "Растворитель", "value": "дихлорметан, 5 мл на 1 г спирта"}],
         "yield_fraction": 0.9},
        {"operation": "Нейтрализация",
         "reactants": [{"name": "@prev"}, {"name": "sodium hydroxide", "smiles": "[Na+].[OH-]"}],
         "products": [{"name": "sodium dodecyl sulfate", "smiles": "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]"}],
         "conditions": [{"name": "Температура", "value": "30 °C"}],
         "yield_fraction": 0.95},
    ],
}], "gaps": []}

SEED_STATE = {
    "structured_tz": SEED_TZ,
    "target_molecule": {"fixed": False, "name": "", "smiles": "", "cas": "", "source": "не задано"},
    "literature_analysis": {"synthesis_routes": [], "analogues": [], "facts": [], "gaps": []},
    "synthesis_routes": SEED_ROUTES,
}

KICKOFF = "Выполни свою стадию по данным из состояния сессии."


class RecordingResponder(AbstractHITLHandler):
    """Approves everything, except the steps listed in ``send_back`` (once each)."""

    def __init__(self, send_back=()):
        self.send_back = set(send_back)
        self.requests = []
        self.notices = []

    async def handle_request(self, request):
        self.requests.append(request)
        step = (request.context or {}).get("step") or {}
        if request.trigger == "work_step" and step.get("id") in self.send_back:
            self.send_back.discard(step["id"])
            return HITLResponse(
                action=HITLAction.EDIT, approved=False,
                instructions="Повтори шаг и перечисли в result каждое вещество с его SMILES.",
            )
        return HITLResponse(action=HITLAction.APPROVE, approved=True)

    async def notify(self, payload):
        self.notices.append(payload)


async def _run(responder):
    from CoScientist.agents.common import hitl_handler
    from CoScientist.assembly import build_system
    from CoScientist.assembly.schema import resolve_config_path

    hitl_handler.set_delegate(responder)
    system = build_system(config_path=resolve_config_path("microfluidics"))
    service = InMemorySessionService()
    await service.create_session(app_name="econ", user_id="u", session_id="s", state=dict(SEED_STATE))
    runner = Runner(agent=system.agent(AGENT), app_name="econ", session_service=service)
    calls = []
    async for event in runner.run_async(
        user_id="u", session_id="s",
        new_message=types.Content(role="user", parts=[types.Part(text=KICKOFF)]),
    ):
        for part in (event.content.parts if event.content else None) or []:
            if getattr(part, "function_call", None):
                calls.append(part.function_call.name)
                print(f"[econ] -> {part.function_call.name}")
    session = await service.get_session(app_name="econ", user_id="u", session_id="s")
    return dict(session.state), calls


def _by_trigger(responder, trigger):
    return [r for r in responder.requests if r.trigger == trigger]


def test_economics_agent_runs_its_work_order_step_by_step():
    responder = RecordingResponder()
    state, calls = asyncio.run(_run(responder))

    orders = _by_trigger(responder, "work_order")
    assert orders, "no work order was put before the human"
    order = orders[0].context["work_order"]
    assert set(order["planned_tools"]) <= ECONOMICS_TOOLS
    tool_steps = [s for s in order["steps"] if s["tools"]]
    assert tool_steps and all(s["inputs"] for s in tool_steps), order["steps"]

    steps = _by_trigger(responder, "work_step")
    assert steps, "no step was put before the human"
    assert any(r.context["step_calls"] for r in steps), "steps reached the human without calls"
    assert all(r.context["step"]["result"] for r in steps if r.context["step"]["status"] == "done")

    assert "rank_routes_by_cost" in calls
    ranking = state.get("economics_ranking") or {}
    assert ranking.get("routes"), "the server's ranking was not kept"
    assert _by_trigger(responder, "work_report"), "no work report was submitted"
    assert state.get("economics")


def test_a_step_sent_back_is_redone():
    responder = RecordingResponder(send_back={"S1"})
    asyncio.run(_run(responder))
    s1 = [r for r in _by_trigger(responder, "work_step") if r.context["step"]["id"] == "S1"]
    assert len(s1) >= 2, "S1 was not submitted again after it was sent back"
    assert s1[-1].context["step"]["review"]["round"] >= 2
