"""STUB tools for the microfluidics stages 3–11 — and the real ones.

Stages 3–11 (molecular design, retrosynthesis, CFD, the rig) are wired against
the stubs below BEFORE those services exist, so the graph can be assembled and
run end to end today. Every stub returns a static, canonical answer for the
ПАВ / МУН case, marked ``"stub": True`` so a stubbed value stays recognisable
in the session state and in the final report.

Connecting a real service later means replacing the BODY of one function: the
name stays registered in ``assembly/bindings.py``, so neither the YAML nor the
graph changes. Keep the return shape — the downstream node reads it (see
``tests/unit/test_microfluidics_stubs.py`` for the contracts).

Economics (stage 5) has already graduated: it is wired to the real chemquote
MCP service (see ``CoScientist/tools/economics_tools.py`` and
``MCP_Economic_model.md``), not a local-function body swap like the others —
chemquote is a remote MCP server with its own multi-tool surface, so its
ToolEntry (key ``"economics"``) replaces the stub entry outright rather than
reusing this module.

``finish_optimization`` is NOT a stub either: it is the real escape hatch of
the 7⇄8 optimization loop.
"""
from __future__ import annotations

from typing import Any, Dict

from google.adk.tools import ToolContext


def molecular_design_stub(requirements: str) -> Dict[str, Any]:
    """STUB. Propose target molecules for the ТЗ from literature analogues.

    Args:
        requirements: the target product requirements, with the analogues and
            facts gathered from the literature.

    Returns:
        Candidate molecules: SMILES, a readable name and the properties that
        the ТЗ's quality criteria are checked against.
    """
    return {
        "stub": True,
        "requirements": requirements,
        "candidates": [
            {
                "name": "Додецилсульфат натрия (SDS)",
                "smiles": "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]",
                "properties": {
                    "ККМ, ммоль/л": 8.2,
                    "МПН, мН/м": 38.5,
                    "Солеустойчивость, г/л NaCl": 30,
                    "Термостабильность, °C": 60,
                },
            },
            {
                "name": "Додецилбензолсульфонат натрия (SDBS)",
                "smiles": "CCCCCCCCCCCCc1ccc(cc1)S(=O)(=O)[O-].[Na+]",
                "properties": {
                    "ККМ, ммоль/л": 1.2,
                    "МПН, мН/м": 31.0,
                    "Солеустойчивость, г/л NaCl": 80,
                    "Термостабильность, °C": 90,
                },
            },
            {
                "name": "Кокамидопропилбетаин (CAPB)",
                "smiles": "CCCCCCCCCCCC(=O)NCCC[N+](C)(C)CC(=O)[O-]",
                "properties": {
                    "ККМ, ммоль/л": 0.9,
                    "МПН, мН/м": 33.2,
                    "Солеустойчивость, г/л NaCl": 150,
                    "Термостабильность, °C": 120,
                },
            },
        ],
    }


def retrosynthesis_stub(smiles: str) -> Dict[str, Any]:
    """STUB. Plan a synthesis route to a target molecule.

    Args:
        smiles: SMILES of the target molecule.

    Returns:
        The route as ordered steps; each step carries the operation and the
        operating conditions the experiment planner (node 6) plans against.
    """
    return {
        "stub": True,
        "target_smiles": smiles,
        "confidence": 0.78,
        "steps": [
            {
                "num": 1,
                "operation": "Сульфатирование додеканола хлорсульфоновой кислотой",
                "reagents": ["додеканол-1", "хлорсульфоновая кислота"],
                "conditions": {
                    "Температура, °C": 25,
                    "Время, мин": 90,
                    "Мольное соотношение": "1 : 1.05",
                    "Среда": "безводный дихлорметан",
                },
            },
            {
                "num": 2,
                "operation": "Нейтрализация водным раствором NaOH",
                "reagents": ["NaOH (20 % водн.)"],
                "conditions": {
                    "Температура, °C": 30,
                    "Время, мин": 30,
                    "pH на выходе": 8.5,
                },
            },
            {
                "num": 3,
                "operation": "Отгонка растворителя и сушка продукта",
                "reagents": [],
                "conditions": {
                    "Температура, °C": 60,
                    "Давление, мбар": 40,
                    "Время, мин": 120,
                },
            },
        ],
    }


def cfd_mcp_stub(geometry: str, flow: str) -> Dict[str, Any]:
    """STUB. Simulate the flow in the microfluidic chip (CFD).

    Args:
        geometry: the channel geometry under test.
        flow: the flow conditions (rates, phases).

    Returns:
        The simulation result: pressure drop, mixing efficiency, residence
        time and whether the solver converged.
    """
    return {
        "stub": True,
        "geometry": geometry,
        "flow": flow,
        "converged": True,
        "pressure_drop_bar": 1.35,
        "mixing_efficiency": 0.92,
        "residence_time_s": 4.6,
        "reynolds": 118,
        "hotspots": ["Зона слияния T-образного узла: локальный перегрев +6 °C"],
    }


def rig_mcp_stub(command: str) -> Dict[str, Any]:
    """STUB. Send a command to the microfluidic rig and read its telemetry.

    Args:
        command: the rig command to execute.

    Returns:
        The command status and the telemetry sampled right after it.
    """
    return {
        "stub": True,
        "command": command,
        "status": "ok",
        "telemetry": {
            "Расход, мл/мин": 0.5,
            "Температура реактора, °C": 25.4,
            "Давление, бар": 1.4,
            "Конверсия (онлайн-ИК), %": 87.3,
        },
    }


def finish_optimization(reason: str, tool_context: ToolContext) -> Dict[str, Any]:
    """Finish the experiment optimization loop and move on to the report.

    Call this once the experiment plan no longer needs refining — the target
    metrics are met, or further iterations stopped helping.

    Args:
        reason: why the optimization is finished (goes into the report).

    Returns:
        Confirmation that the loop is closed.
    """
    # Escalating is what stops ADK's LoopAgent: without it nodes 7 and 8 keep
    # handing the plan back to each other until max_iterations runs out.
    tool_context.actions.escalate = True
    return {"finished": True, "reason": reason}
