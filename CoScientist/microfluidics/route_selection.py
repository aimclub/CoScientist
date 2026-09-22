"""Module-A route selection and its hand-off of the selected route downstream."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from CoScientist.microfluidics.models import (
    LiteratureAnalysis,
    LiteratureRoute,
    ProcessStep,
    QualifiedRoutes,
    RouteDecision,
    RouteSelection,
    Substance,
    SynthesisRoute,
    SynthesisRoutes,
)
from CoScientist.microfluidics.requirements import REQUIREMENTS_KEY, compile_requirements
from CoScientist.microfluidics.route_compliance import QUALIFIED_ROUTES_KEY, qualify_routes
from CoScientist.hitl.session_agent import SessionAgent

SELECTION_KEY = "route_selection"
SELECTION_AUDIT_KEY = "route_selection_audit"
ROUTE_CANDIDATES_AUDIT_KEY = "route_candidates_audit"
logger = logging.getLogger(__name__)

_PERCENT = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*%")


def _yield_fraction(value: str) -> float | None:
    match = _PERCENT.search(value or "")
    if not match:
        return None
    number = float(match.group(1).replace(",", ".")) / 100.0
    return number if 0 < number <= 1 else None


def _substances(values: list[str]) -> list[Substance]:
    return [Substance(name=str(value).strip()) for value in values if str(value).strip()]


def literature_route_to_synthesis(route: LiteratureRoute) -> SynthesisRoute:
    """Convert once in code, preserving every claim-level evidence reference."""
    steps: list[ProcessStep] = []
    for item in route.steps:
        fraction = _yield_fraction(item.yield_value)
        evidence_statuses = {
            ref.verification_status
            for ref in [*item.evidence, *(ref for condition in item.conditions for ref in condition.evidence)]
        }
        operating_status = (
            "reported" if evidence_statuses and evidence_statuses == {"verified"} else "unverified"
        )
        reactants = item.reactants or item.reagents
        steps.append(ProcessStep(
            operation=item.operation,
            reactants=_substances(reactants),
            agents=_substances(item.agents),
            products=_substances(item.products),
            conditions=item.conditions,
            conditions_status=operating_status if item.conditions else "missing",
            conditions_missing_reason="" if item.conditions else "Условия не указаны в литературном маршруте.",
            yield_fraction=fraction,
            yield_status=(operating_status if fraction is not None else "missing"),
            yield_missing_reason=("" if fraction is not None else
                                  f"Числовой выход не указан: {item.yield_value or 'нет данных'}."),
            evidence=item.evidence,
            flow_notes=route.flow_suitability,
        ))
    return SynthesisRoute(
        route_id=route.route_id,
        source_route_id=route.route_id,
        product=Substance(name=route.product, smiles=route.product_smiles),
        source="литература",
        variant_label=route.variant_label,
        selection_rationale=route.comparison_notes,
        steps=steps,
        flow_suitability=route.flow_suitability,
        sources=route.sources,
        evidence=route.evidence,
        stub=False,
    )


def _rejected_decisions(
    selection: RouteSelection, rejected: list[LiteratureRoute], selected_id: str,
) -> list[RouteDecision]:
    """Why each route left the hand-off, as the selection gave it."""
    by_id = {item.route_id: item for item in selection.decisions}
    decisions = []
    for route in rejected:
        item = by_id.get(route.route_id)
        reasons = [item.reason, *item.hard_violations] if item else [
            f"Не выбран в Module A: активный маршрут — {selected_id}."
        ]
        decisions.append(RouteDecision(
            route_id=route.route_id,
            product=route.product,
            overall_status="rejected",
            reasons=[reason for reason in reasons if reason.strip()],
        ))
    return decisions


def finalize_route_selection(callback_context: CallbackContext) -> types.Content:
    """Hand Module B the single selected route; keep the others as audit only.

    With a ``selected_route_id`` the selected literature route is the only
    active route downstream — ``synthesis_routes``, ``qualified_routes`` and
    ``literature_analysis.synthesis_routes`` carry it alone, so design,
    economics and the A2A hand-off never cost or ship the routes the selection
    dropped. Those stay in ``route_candidates_audit`` (full routes) and in
    ``qualified_routes.rejected`` (id, product, reasons) for the report.

    Without a usable selection (none selected, unparsable, or an id that is no
    literature route) every route is forwarded as before: a model decision or
    automatic TZ screening must never sever the Module-A -> Module-B hand-off.
    """
    state = callback_context.state
    try:
        selection = RouteSelection.model_validate(state.get(SELECTION_KEY) or {})
    except Exception as exc:  # noqa: BLE001 - malformed review must not kill the graph
        logger.warning("route selection was invalid; preserving all route candidates: %s", exc)
        selection = RouteSelection(
            selection_reason="Решение маршрута не удалось разобрать; все кандидаты переданы для выбора оператором.",
        )
        state[SELECTION_KEY] = selection.model_dump()
    try:
        analysis = LiteratureAnalysis.model_validate(state.get("literature_analysis") or {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("literature analysis at route hand-off was invalid: %s", exc)
        analysis = LiteratureAnalysis(gaps=[
            f"Структурированный литературный анализ недоступен ({type(exc).__name__})."
        ])
    by_id = {route.route_id: route for route in analysis.synthesis_routes}
    decision_ids = {item.route_id for item in selection.decisions}
    if decision_ids != set(by_id):
        logger.warning(
            "route selection decisions do not cover all routes: expected=%s actual=%s",
            sorted(by_id), sorted(decision_ids),
        )
    selected_id = selection.selected_route_id.strip()
    narrowed = bool(selected_id) and selected_id in by_id
    if narrowed:
        # ModuleA's selection is the only active route (the root never asks
        # for a second route decision), so it is also the transport filter.
        chosen = [by_id[selected_id]]
        dropped = [route for route in analysis.synthesis_routes if route.route_id != selected_id]
    else:
        if selected_id:
            logger.warning(
                "selected route %s is not a literature route %s; forwarding every candidate",
                selected_id, sorted(by_id),
            )
        chosen = list(analysis.synthesis_routes)
        dropped = []

    # Full routes that are not active (every candidate when none was
    # selected) — audit for the report, never an active route.
    state[ROUTE_CANDIDATES_AUDIT_KEY] = [
        route.model_dump() for route in (dropped if narrowed else analysis.synthesis_routes)
    ]
    if narrowed:
        analysis = analysis.model_copy(update={"synthesis_routes": chosen})
    from CoScientist.config import get_settings
    operator_confirmed = bool(get_settings().web.hitl_enabled)
    state[SELECTION_AUDIT_KEY] = {
        **selection.model_dump(),
        "approved_by_human": operator_confirmed,
        "review_mode": "human" if operator_confirmed else "headless",
    }
    state["literature_analysis"] = analysis.model_dump()

    routes = SynthesisRoutes(
        routes=[literature_route_to_synthesis(route) for route in chosen],
        gaps=list(analysis.gaps) + ([] if chosen else ["Литературные маршруты не найдены."]),
    )
    state["synthesis_routes"] = routes.model_dump()
    spec = state.get(REQUIREMENTS_KEY) or compile_requirements(state.get("structured_tz"))
    state[REQUIREMENTS_KEY] = spec if isinstance(spec, dict) else spec.model_dump()
    if routes.routes:
        # Qualification is informational at this stage.  Passing the route(s)
        # to economics/Module C must not depend on a later TZ gate.
        approved_routes = [route.model_copy(update={"overall_status": "eligible"}) for route in routes.routes]
        qualified = QualifiedRoutes(
            status="ok",
            routes=approved_routes,
            rejected=_rejected_decisions(selection, dropped, selected_id),
            gaps=list(routes.gaps),
        )
    else:
        qualified = qualify_routes(routes, spec, analysis.source_records)
    state[QUALIFIED_ROUTES_KEY] = qualified.model_dump()

    payload = {
        "status": ("selected_route_forwarded" if narrowed
                   else "candidates_forwarded" if chosen else "none_selected"),
        "selected_route_id": selection.selected_route_id,
        "active_route_ids": [route.route_id for route in chosen],
        "rejected_route_ids": [route.route_id for route in dropped],
        "qualified_status": qualified.status,
    }
    return types.Content(
        role="model",
        parts=[types.Part(text=json.dumps(payload, ensure_ascii=False))],
    )


def _commit_selection_output(state: dict[str, Any], output_text: Any) -> None:
    """Make the model's final selection available before post-final callbacks.

    ``SessionAgent`` emits its final event only after calling
    ``_post_final_events``.  With no HITL gate, its ``output_key`` state delta
    has therefore not yet been applied when route finalisation starts.
    """
    if state.get(SELECTION_KEY):
        return
    payload = output_text
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return
    if isinstance(payload, dict):
        state[SELECTION_KEY] = payload


class RouteSelectionSessionAgent(SessionAgent):
    """Finalize/filter the selected route and hand it to the next module."""

    def _post_final_events(self, ctx: InvocationContext, output_text):
        # Wrap the entire post-final sequence in a try/except so a failure here
        # never kills the pipeline — the next module must always run.
        try:
            _commit_selection_output(ctx.session.state, output_text)
            finalize_route_selection(type("Context", (), {"state": ctx.session.state})())
        except Exception as exc:  # noqa: BLE001
            logger.error("finalize_route_selection failed; continuing with safe defaults: %s", exc)
            # Ensure a minimal valid selection exists in state so downstream
            # stages do not crash either.
            if not ctx.session.state.get(SELECTION_KEY):
                safe = RouteSelection(
                    selection_reason="Финализация маршрута завершилась ошибкой; кандидаты требуют ручной проверки.",
                )
                ctx.session.state[SELECTION_KEY] = safe.model_dump()

        try:
            from CoScientist.microfluidics.research_record import record_synthesis_routes
            record_synthesis_routes(ctx)
        except Exception:  # noqa: BLE001
            # Graph recording is best-effort and must not block the hand-off.
            pass

        keys = (
            "literature_analysis", "synthesis_routes", QUALIFIED_ROUTES_KEY,
            REQUIREMENTS_KEY, SELECTION_AUDIT_KEY, ROUTE_CANDIDATES_AUDIT_KEY,
            "research_record",
        )
        delta = {key: ctx.session.state.get(key) for key in keys}

        # ── Build the human-readable markdown summary ────────────────────
        try:
            selection = RouteSelection.model_validate(
                ctx.session.state.get(SELECTION_KEY) or {}
            )
        except Exception:  # noqa: BLE001
            selection = RouteSelection(
                selection_reason="Ответ модели не удалось разобрать.",
            )
            ctx.session.state[SELECTION_KEY] = selection.model_dump()
            delta[SELECTION_KEY] = selection.model_dump()

        lines = ["## Решение по маршрутам", ""]
        for item in selection.decisions:
            lines.append(
                f"- {item.route_id}: **{item.recommendation}** — {item.reason}"
            )
        if selection.selected_route_id:
            lines.extend(["", f"Выбран маршрут: **{selection.selected_route_id}**."])
        else:
            lines.extend(["", "Маршрут не выбран."])

        # Yield the markdown event for human display in the chat.
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text="\n".join(lines))]),
            actions=EventActions(state_delta=delta),
        )

        # ── Yield a JSON event LAST so AgentTool.validate_schema sees it ─
        # ADK's AgentTool picks up `last_content` from the stream and, for
        # SequentialAgent children, recursively resolves the output_schema of
        # the last sub-agent (this agent).  Without a valid JSON event at the
        # end, validate_schema receives the markdown text above and crashes
        # with "Invalid JSON: expected value".
        try:
            json_text = json.dumps(selection.model_dump(), ensure_ascii=False)
        except Exception:  # noqa: BLE001
            json_text = json.dumps(
                {"decisions": [], "selected_route_id": "", "selection_reason":
                 "Ответ модели не разобран; требуется ручная проверка."},
                ensure_ascii=False,
            )
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part(text=json_text)]),
        )


__all__ = [
    "ROUTE_CANDIDATES_AUDIT_KEY",
    "SELECTION_AUDIT_KEY",
    "SELECTION_KEY",
    "finalize_route_selection",
    "literature_route_to_synthesis",
    "_commit_selection_output",
    "RouteSelectionSessionAgent",
]
