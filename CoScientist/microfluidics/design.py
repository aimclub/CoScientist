"""Module B, stage 3: a molecule the customer fixed is not designed again.

``use_fixed_target_molecule`` (before_agent, MolDesignAgent) checks the ТЗ.
When the customer named the substance (``target_molecule.fixed``), there is
nothing to design: the callback writes that molecule as the only candidate to
``design_candidates`` — with the properties module A found for it in the
literature — and answers for the agent, so no LLM call and no design stub runs.
The answer IS the DesignCandidates JSON: ADK treats a before_agent answer as the
agent's output and validates it against the agent's output_schema.
Otherwise the agent designs candidates as usual.

It reads the ТЗ itself (not the stored ``target_molecule``), so a ТЗ edited after
module A still decides.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from CoScientist.microfluidics.literature import extract_target_molecule
from CoScientist.microfluidics.models import (
    DesignCandidate,
    DesignCandidates,
    NamedValue,
    TargetMolecule,
)

logger = logging.getLogger(__name__)

CANDIDATES_KEY = "design_candidates"


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _matching_analogue(target: TargetMolecule, analysis: Any) -> Optional[Dict[str, Any]]:
    """The analogue from the literature that IS the target (by SMILES, then name)."""
    analogues = (analysis or {}).get("analogues") if isinstance(analysis, dict) else None
    for analogue in analogues or []:
        if not isinstance(analogue, dict):
            continue
        if target.smiles and analogue.get("smiles") and analogue["smiles"].strip() == target.smiles.strip():
            return analogue
    for analogue in analogues or []:
        if isinstance(analogue, dict) and target.name and _norm(analogue.get("name")) == _norm(target.name):
            return analogue
    return None


def fixed_target_candidates(structured_tz: Any, literature_analysis: Any) -> Optional[DesignCandidates]:
    """The candidates to hand on for a fixed molecule, or None when nothing is fixed."""
    target = extract_target_molecule(structured_tz)
    if not target.fixed:
        return None

    analogue = _matching_analogue(target, literature_analysis) or {}
    properties: List[NamedValue] = []
    for item in analogue.get("properties") or []:
        try:
            properties.append(NamedValue.model_validate(item))
        except Exception:  # noqa: BLE001 — a malformed property is skipped, not fatal
            continue

    name = target.name or analogue.get("name") or target.cas or target.smiles
    gaps: List[str] = []
    smiles = target.smiles or str(analogue.get("smiles") or "")
    if not smiles:
        gaps.append(
            "SMILES целевой молекулы не задан ни в ТЗ, ни в литературе — маршрут "
            "синтеза и стоимость придётся искать по названию"
        )
    if not properties:
        gaps.append("В литературе не найдено измеренных свойств целевой молекулы")

    candidate = DesignCandidate(
        name=name,
        smiles=smiles,
        compound_class=str(analogue.get("compound_class") or ""),
        properties=properties,
        tz_fit="Задана заказчиком в ТЗ — подбор кандидатов не выполнялся",
        risks="",
        source="ТЗ",
        stub=False,
    )
    return DesignCandidates(fixed_target=True, candidates=[candidate], gaps=gaps)


def use_fixed_target_molecule(callback_context: CallbackContext) -> Optional[types.Content]:
    """Skip design when the ТЗ fixes the molecule; hand the molecule on instead."""
    state = callback_context.state
    try:
        result = fixed_target_candidates(state.get("structured_tz"), state.get("literature_analysis"))
    except Exception as exc:  # noqa: BLE001 — fall back to designing
        logger.warning("fixed target molecule: could not build candidates: %s", exc)
        return None
    if result is None:
        return None

    state[CANDIDATES_KEY] = result.model_dump()
    logger.info("fixed target molecule %r handed on — design skipped", result.candidates[0].name)
    return types.Content(
        role="model", parts=[types.Part(text=result.model_dump_json(ensure_ascii=False))]
    )


def _selected_route(state: Any) -> Optional[Dict[str, Any]]:
    """The route whose product Module B takes: the one ``route_selection``
    selected, found among the active routes (``synthesis_routes``) or the
    literature routes; without a selection, the only route handed on."""
    selection = state.get("route_selection")
    if isinstance(selection, str):
        try:
            selection = json.loads(selection)
        except ValueError:
            selection = None
    selected_id = str(selection.get("selected_route_id") or "").strip() if isinstance(selection, dict) else ""
    synthesis = state.get("synthesis_routes")
    analysis = state.get("literature_analysis")
    for doc, key in ((synthesis, "routes"), (analysis, "synthesis_routes")):
        routes = [r for r in (doc.get(key) if isinstance(doc, dict) else None) or [] if isinstance(r, dict)]
        if selected_id:
            match = next((r for r in routes if str(r.get("route_id") or "").strip() == selected_id), None)
            if match is not None:
                return match
        elif len(routes) == 1:
            return routes[0]
    return None


def use_selected_route_product(callback_context: CallbackContext) -> Optional[types.Content]:
    """Hand the operator-selected literature product to Module B verbatim.

    A selected route is already a design decision.  Do not run BRICS or ask an
    LLM to invent another molecule at this point.  If the source did not give
    an explicit structure, leave the stage fail-soft with an actionable gap.
    """
    state = callback_context.state
    try:
        route = _selected_route(state)
        if route is None:
            return None
        product = (route.get("product") or {}) if isinstance(route, dict) else {}
        if isinstance(product, dict):
            name = str(product.get("name") or product.get("smiles") or "").strip()
            smiles = str(product.get("smiles") or "").strip()
        else:
            name = str(product).strip()
            smiles = str(route.get("product_smiles") or "").strip()
        name = name or str(route.get("route_id") or "").strip()
        if not name or not smiles:
            result = DesignCandidates(gaps=[
                "Выбранный маршрут не содержит явного product SMILES: "
                "структура не выдумывается и требует ручного уточнения."
            ])
        else:
            from rdkit import Chem
            molecule = Chem.MolFromSmiles(smiles)
            if molecule is None or not molecule.GetNumAtoms():
                result = DesignCandidates(gaps=[
                    f"Некорректный product SMILES выбранного маршрута {route.get('route_id', '')}."
                ])
            else:
                result = DesignCandidates(candidates=[DesignCandidate(
                    name=name,
                    smiles=Chem.MolToSmiles(molecule, isomericSmiles=True),
                    compound_class="продукт выбранного литературного маршрута",
                    source="литература",
                    derivation="Продукт выбранного литературного маршрута",
                    route_ids=[str(route.get("route_id") or "")],
                    tz_fit="Маршрут выбран оператором в Module A; повторный подбор не выполнялся",
                    risks="Целевые эксплуатационные свойства требуют экспериментальной проверки.",
                )])
        state[CANDIDATES_KEY] = result.model_dump()
        return types.Content(
            role="model", parts=[types.Part(text=result.model_dump_json(ensure_ascii=False))]
        )
    except Exception as exc:  # noqa: BLE001 - stage boundary must never crash the run
        logger.exception("selected route product hand-off failed: %s", exc)
        result = DesignCandidates(gaps=[
            f"Не удалось зафиксировать продукт выбранного маршрута ({type(exc).__name__})."
        ])
        state[CANDIDATES_KEY] = result.model_dump()
        return types.Content(
            role="model", parts=[types.Part(text=result.model_dump_json(ensure_ascii=False))]
        )


__all__ = [
    "CANDIDATES_KEY", "fixed_target_candidates", "use_fixed_target_molecule",
    "use_selected_route_product",
]
