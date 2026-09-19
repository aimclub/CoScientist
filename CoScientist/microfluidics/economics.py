"""Keep the economics server's numbers in the state, as the server gave them.

``collect_economics_result`` (after_tool, EconomicsAgent) reads the answers of
the two costing tools and writes them to the session state, so the report and
the later modules take costs from the server instead of from the agent's
retelling:

``economics_ranking``
    ``{target_qty, target_unit, preferred_currency, rank_by, routes: {route_id:
    {status, rank, currency, cost_per_unit, cost_packs, starting_materials,
    missing, warnings}}}`` —
    one entry per route; a later ranking of the same route replaces it (a
    corrected route is recalculated under its id).
``economics_estimates``
    the plain reagent estimates: ``[{reagents, total_by_currency, missing}]``.
``economics_raw``
    the full answer of the last ranking, breakdown included.

The answer shapes are the ones recorded from the live server in
``tests/fixtures/economics_mcp/``. A transport failure (``{"error": ...}``) or an
``isError`` answer changes nothing: there are no numbers to keep.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

RANKING_KEY = "economics_ranking"
ESTIMATES_KEY = "economics_estimates"
RAW_KEY = "economics_raw"

_MAX_WARNINGS = 5


def structured_result(response: Any) -> Optional[Dict[str, Any]]:
    """The structured answer of an MCP call, or None for an error / no data.

    ADK hands after_tool a dumped CallToolResult: ``structuredContent`` when the
    tool declares an output schema, else JSON inside the text ``content``.
    """
    if not isinstance(response, dict):
        return None
    if response.get("isError") or response.get("is_error"):
        return None
    if set(response) == {"error"}:
        return None
    structured = response.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in response.get("content") or []:
        text = block.get("text") if isinstance(block, dict) else None
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _route_summary(route: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": route.get("status"),
        "rank": route.get("rank"),
        "currency": route.get("currency"),
        "cost_per_unit": route.get("cost_per_unit"),
        "cost_packs": route.get("cost_packs"),
        # What to buy for the target amount — the recipe in the report.
        "starting_materials": [
            {"smiles": m.get("smiles"), "qty": m.get("qty"), "unit": m.get("unit")}
            for m in route.get("starting_materials") or [] if isinstance(m, dict)
        ],
        "missing": [
            {"smiles": m.get("smiles"), "reason": m.get("reason")}
            for m in route.get("missing") or [] if isinstance(m, dict)
        ],
        "warnings": list(route.get("warnings") or [])[:_MAX_WARNINGS],
    }


def _collect_ranking(state: Any, args: Dict[str, Any], result: Dict[str, Any]) -> None:
    qualified = state.get("qualified_routes") or {}
    allowed = {
        str(route.get("route_id")) for route in qualified.get("routes") or []
        if isinstance(route, dict) and route.get("route_id")
    }
    returned = {
        str(route.get("route_id")) for route in result.get("routes") or []
        if isinstance(route, dict) and route.get("route_id")
    }
    if not allowed or returned != allowed:
        raise ValueError(
            "economics result route_ids must match qualified_routes exactly: "
            f"allowed={sorted(allowed)}, returned={sorted(returned)}"
        )
    previous = state.get(RANKING_KEY) or {}
    routes = dict(previous.get("routes") or {})
    for route in result.get("routes") or []:
        if isinstance(route, dict) and route.get("route_id"):
            routes[str(route["route_id"])] = _route_summary(route)
    # Written whole: AgentTool forwards only whole-key deltas to the parent.
    state[RANKING_KEY] = {
        "target_qty": args.get("target_qty", previous.get("target_qty")),
        "target_unit": args.get("target_unit", previous.get("target_unit")),
        "preferred_currency": result.get("preferred_currency"),
        "rank_by": result.get("rank_by"),
        "routes": routes,
    }
    state[RAW_KEY] = result


def _collect_estimate(state: Any, args: Dict[str, Any], result: Dict[str, Any]) -> None:
    estimates = list(state.get(ESTIMATES_KEY) or [])
    estimates.append({
        "reagents": args.get("reagents") or [],
        "total_by_currency": result.get("total_by_currency") or {},
        "missing": result.get("missing") or [],
    })
    state[ESTIMATES_KEY] = estimates


_COLLECTORS = {
    "rank_routes_by_cost": _collect_ranking,
    "estimate_synthesis_cost": _collect_estimate,
}


def collect_economics_result(
    tool: Any = None, args: Any = None, tool_context: Any = None, tool_response: Any = None,
    **kwargs: Any,
) -> None:
    """after_tool: file the costing answers under their state keys."""
    name = str(getattr(tool, "name", "") or "")
    collector = _COLLECTORS.get(name)
    if collector is None or tool_context is None:
        return None
    result = structured_result(tool_response)
    if result is None:
        return None
    try:
        collector(tool_context.state, args if isinstance(args, dict) else {}, result)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must never break the call
        logger.warning("economics: could not record %s: %s", name, exc)
    return None


__all__ = [
    "ESTIMATES_KEY",
    "RANKING_KEY",
    "RAW_KEY",
    "collect_economics_result",
    "structured_result",
]
