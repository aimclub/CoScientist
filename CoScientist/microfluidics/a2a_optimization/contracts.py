"""Validate CoScientist's hand-off, without inventing an external result schema."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from CoScientist.microfluidics.models import (
    OPERATOR_ROUTE_OVERRIDE_KEY,
    LiteratureAnalysis,
    OperatorRouteOverride,
    QualifiedRoutes,
    SynthesisRoutes,
)

INPUT_KEYS = (
    "structured_tz", "literature_analysis", "synthesis_routes", "qualified_routes",
    "economics", "economics_ranking",
)
TARGET_UNITS = ("g", "kg", "mol", "mmol")
RANK_BY = ("per_unit", "packs")
ROUTE_STATUSES = ("ok", "partial", "invalid", "unpriceable")


class EconomicsRankingError(ValueError):
    """Everything else in the production hand-off is valid; only a usable
    ``economics_ranking`` for ``route_ids`` is missing — the one gap an
    operator can close without redoing an earlier stage."""

    def __init__(self, message: str, route_ids: list[str]) -> None:
        super().__init__(message)
        self.route_ids = list(route_ids)


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


def prepare_inputs(state: Any, *, planning_only: bool = False) -> dict:
    """Prepare either a production hand-off or a non-executing screening plan.

    Production needs fully qualified routes and cost rankings.  Screening is
    intentionally narrower: it may carry real routes with open evidence/yield
    gaps so the external system can design the measurements that close them.
    """
    inputs = {key: state.get(key) for key in INPUT_KEYS}
    # economics_ranking is checked last (production only), after every other
    # input: its failure alone raises EconomicsRankingError.
    for key in ("structured_tz", "literature_analysis", "synthesis_routes", "qualified_routes"):
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
    if planning_only and not routes:
        routes = qualified.experimental_routes
    override = None
    if planning_only and not routes and qualified.status == "no_compliant_routes":
        # A human may ask the external system to design evidence-gathering for
        # a rejected proposal.  This does not alter qualification and cannot
        # enter the production branch below.
        override = OperatorRouteOverride.model_validate(
            state.get(OPERATOR_ROUTE_OVERRIDE_KEY)
        )
        proposal_by_id = {route.route_id: route for route in proposals}
        unknown = set(override.route_ids) - set(proposal_by_id)
        if unknown:
            raise ValueError(
                "operator_route_override.route_ids must be a subset of synthesis_routes: "
                f"{sorted(unknown)}"
            )
        routes = [proposal_by_id[route_id] for route_id in override.route_ids]
        inputs[OPERATOR_ROUTE_OVERRIDE_KEY] = override.model_dump()
    ids = [route.route_id for route in routes]
    if not routes or not set(ids).issubset(set(proposal_ids)):
        mode = "eligible or experimental" if planning_only else "eligible"
        raise ValueError(f"qualified_routes: nonempty {mode} subset of synthesis_routes required")
    if planning_only:
        inputs["handoff_mode"] = "screening"
        inputs["selected_route_ids"] = ids
        return json.loads(json.dumps(inputs, ensure_ascii=False, allow_nan=False))

    try:
        inputs["economics_ranking"] = validate_economics_ranking(inputs["economics_ranking"], ids)
    except ValueError as exc:
        raise EconomicsRankingError(str(exc), ids) from exc
    # Snapshot with no references to mutable session data. Reject NaN in inputs.
    return json.loads(json.dumps(inputs, ensure_ascii=False, allow_nan=False))


def validate_economics_ranking(value: Any, route_ids: list[str]) -> dict:
    """The ranking contract of the production hand-off; returns the ranking.

    One row per qualified route; ``ok`` / ``partial`` rows carry a unique
    positive rank and finite nonnegative costs in the preferred currency;
    ``invalid`` / ``unpriceable`` rows are kept unranked, with their reasons.
    """
    ranking = _object(value, "economics_ranking")
    ranked = ranking.get("routes")
    if not isinstance(ranked, dict) or set(ranked) != set(route_ids):
        raise ValueError(
            "economics_ranking.routes must match qualified_routes route_id values exactly: "
            f"expected {sorted(route_ids)}, got "
            f"{sorted(ranked) if isinstance(ranked, dict) else type(ranked).__name__}"
        )
    _number(ranking.get("target_qty"), "economics_ranking.target_qty", positive=True)
    if ranking.get("target_unit") not in TARGET_UNITS:
        raise ValueError("economics_ranking.target_unit must be g, kg, mol or mmol")
    if ranking.get("rank_by") not in RANK_BY:
        raise ValueError("economics_ranking.rank_by must be per_unit or packs")
    currency = ranking.get("preferred_currency")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("economics_ranking.preferred_currency required")
    usable_ranks = []
    for route_id, row in ranked.items():
        if not isinstance(row, dict) or row.get("stub"):
            raise ValueError(f"{route_id}: real economics result required")
        status = row.get("status")
        if status not in ROUTE_STATUSES:
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
        raise ValueError(
            "economics_ranking: at least one costed route (status ok/partial) and unique ranks required"
        )
    return ranking
