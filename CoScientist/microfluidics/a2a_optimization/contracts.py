"""Validate CoScientist's hand-off, without inventing an external result schema."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from CoScientist.microfluidics.models import LiteratureAnalysis, QualifiedRoutes, SynthesisRoutes

INPUT_KEYS = (
    "structured_tz", "literature_analysis", "synthesis_routes", "qualified_routes",
    "economics", "economics_ranking",
)


def _object(value: Any, name: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ValueError(f"{name}: expected a JSON object") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{name}: nonempty object required")
    return value


def _number(value: Any, name: str, *, positive: bool = False) -> None:
    try:
        if isinstance(value, bool):
            raise ValueError(name)
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or (positive and number == 0):
            raise ValueError(name)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name}: finite {'positive' if positive else 'nonnegative'} number required") from exc


def prepare_inputs(state: Any) -> dict:
    """Require real, linked route rankings; preserve service numbers verbatim."""
    inputs = {key: state.get(key) for key in INPUT_KEYS}
    for key in ("structured_tz", "literature_analysis", "synthesis_routes", "qualified_routes", "economics_ranking"):
        inputs[key] = _object(inputs[key], key)
    LiteratureAnalysis.model_validate(inputs["literature_analysis"])
    proposals = SynthesisRoutes.model_validate(inputs["synthesis_routes"]).routes
    proposal_ids = [route.route_id for route in proposals]
    if not proposals or any(not route_id.strip() for route_id in proposal_ids) or len(proposal_ids) != len(set(proposal_ids)):
        raise ValueError("synthesis_routes: nonempty unique route_id values required")
    if any(route.stub or not route.steps for route in proposals):
        raise ValueError("synthesis_routes: real routes with nonempty steps required")
    qualified = QualifiedRoutes.model_validate(inputs["qualified_routes"])
    routes = qualified.routes
    ids = [route.route_id for route in routes]
    if not routes or not set(ids).issubset(set(proposal_ids)):
        raise ValueError("qualified_routes: nonempty eligible subset of synthesis_routes required")
    ranking = inputs["economics_ranking"]
    ranked = ranking.get("routes")
    if not isinstance(ranked, dict) or set(ranked) != set(ids):
        raise ValueError("economics_ranking.routes must match qualified_routes route_id values exactly")
    _number(ranking.get("target_qty"), "economics_ranking.target_qty", positive=True)
    if ranking.get("target_unit") not in {"g", "kg", "mol", "mmol"}:
        raise ValueError("economics_ranking.target_unit must be g, kg, mol or mmol")
    if ranking.get("rank_by") not in {"per_unit", "packs"}:
        raise ValueError("economics_ranking.rank_by must be per_unit or packs")
    currency = ranking.get("preferred_currency")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("economics_ranking.preferred_currency required")
    usable_ranks = []
    for route_id, row in ranked.items():
        if not isinstance(row, dict) or row.get("stub"):
            raise ValueError(f"{route_id}: real economics result required")
        status = row.get("status")
        if status not in {"ok", "partial", "invalid", "unpriceable"}:
            raise ValueError(f"{route_id}: unsupported economics status {status!r}")
        if status in {"invalid", "unpriceable"}:
            continue  # Preserve excluded routes and their reasons for the remote system.
        rank = row.get("rank")
        if type(rank) is not int or rank < 1:
            raise ValueError(f"{route_id}: positive integer rank required")
        if row.get("currency") != currency:
            raise ValueError(f"{route_id}: ranking currencies must match")
        for key in ("cost_per_unit", "cost_packs"):
            _number(row.get(key), f"{route_id}.{key}")
        usable_ranks.append(rank)
    if not usable_ranks or len(usable_ranks) != len(set(usable_ranks)):
        raise ValueError("economics_ranking: at least one costed route and unique ranks required")
    # Snapshot with no references to mutable session data. Reject NaN in inputs.
    return json.loads(json.dumps(inputs, ensure_ascii=False, allow_nan=False))
