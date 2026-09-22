"""after_model callback: reduce a model response to its first valid JSON payload.

Ported from VibePAV's ``llm._extract_json``. Agents constrained by an ADK
``output_schema`` hard-fail (``ValidationError: trailing characters``) when the
model emits ANYTHING besides the JSON object — markdown fences, prose around
it, duplicated objects, or trailing text. Not every provider honours
``response_format`` strictly, so this callback rewrites the response text to
exactly the extracted JSON before ADK's strict validation sees it.

Attach as ``after_model: [sanitize_json_output]`` on schema-constrained agents
(see CoScientist/agents/microfluidics.yaml).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import yaml

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _try_loads(text: str) -> Optional[Any]:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _extract_json(text: str) -> Optional[Any]:
    """First JSON object/array in the text: fenced block, whole text, or the
    first balanced ``{...}`` candidate that parses."""
    text = text.strip()

    match = _JSON_BLOCK_RE.search(text)
    if match:
        parsed = _try_loads(match.group(1).strip())
        if parsed is not None:
            return parsed

    parsed = _try_loads(text)
    if parsed is not None:
        return parsed

    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    parsed = _try_loads(text[start : i + 1])
                    if parsed is not None:
                        return parsed
                    break
        start = text.find("{", start + 1)
    return None


def _lift_route_selection_fields(payload: Any) -> Any:
    """Recover two root fields commonly indented into the last decision.

    Some models answer a JSON-schema request using YAML indentation.  In the
    usual failure shape the final ``selected_route_id`` and
    ``selection_reason`` wind up in the final member of ``decisions``.  YAML
    can parse that response, but the route-selection schema cannot.  The two
    fields are unambiguous root-only fields, so moving them back is lossless.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        return payload
    for field in ("selected_route_id", "selection_reason"):
        if field in payload:
            continue
        for decision in reversed(payload["decisions"]):
            if isinstance(decision, dict) and field in decision:
                payload[field] = decision.pop(field)
                break
    return payload


def _normalize_route_selection(payload: Any) -> Any:
    """Make a RouteSelection's duplicated choice fields internally coherent.

    ``selected_route_id`` and ``recommendation`` describe the same decision,
    but are generated independently by the model.  ADK validates the output
    immediately after this callback, so an otherwise useful answer used to
    abort the whole workflow before the human reviewer could see it.

    A known selected id is authoritative.  In the inverse, unambiguous case
    (one ``оставить`` and no id), derive the id from that decision.  If a model
    gives an unknown id or several kept routes without an id, there is no
    defensible automatic choice: publish a safe "none selected" proposal for
    HITL rather than inventing a route or crashing Module A.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
        return payload

    decisions = payload["decisions"]
    if not all(isinstance(item, dict) for item in decisions):
        return payload

    changed = False
    for item in decisions:
        route_id = item.get("route_id")
        if isinstance(route_id, str):
            normalized = route_id.strip()
            if normalized != route_id:
                item["route_id"] = normalized
                changed = True

    selected = payload.get("selected_route_id", "")
    if not isinstance(selected, str):
        return payload
    normalized_selected = selected.strip()
    if normalized_selected != selected:
        payload["selected_route_id"] = normalized_selected
        changed = True
    selected = normalized_selected

    ids = [item.get("route_id") for item in decisions]
    kept = [item for item in decisions if item.get("recommendation") == "оставить"]
    repair_note = ""
    if selected and selected in ids:
        for item in decisions:
            recommendation = "оставить" if item.get("route_id") == selected else "отсеять"
            if item.get("recommendation") != recommendation:
                item["recommendation"] = recommendation
                changed = True
        if changed:
            repair_note = "Рекомендации синхронизированы с selected_route_id."
    elif not selected and len(kept) == 1:
        payload["selected_route_id"] = kept[0]["route_id"]
        changed = True
        repair_note = "selected_route_id восстановлен из единственной рекомендации «оставить»."
    elif selected or len(kept) > 1:
        # Do not silently pick the first candidate: this is a scientific and
        # operational decision reserved for the reviewer.
        payload["selected_route_id"] = ""
        for item in decisions:
            if item.get("recommendation") == "оставить":
                item["recommendation"] = "отсеять"
        changed = True
        repair_note = (
            "Неоднозначный выбор модели сброшен: оператору нужно выбрать "
            "маршрут вручную."
        )

    if changed:
        if repair_note:
            previous_reason = str(payload.get("selection_reason") or "").strip()
            payload["selection_reason"] = (
                f"{repair_note} {previous_reason}".strip()
            )
        logger.warning("[RouteSelectionAgent] normalized inconsistent route selection")
    return payload


def _fallback_payload(agent_name: str, callback_context: Any) -> Optional[dict[str, Any]]:
    """Build a conservative schema-valid result when the model fails."""
    state = getattr(callback_context, "state", {}) or {}
    if agent_name in {"LiteratureSynthesisAgent", "EvidenceVerifierAgent"}:
        from CoScientist.microfluidics.models import LiteratureAnalysis
        if agent_name == "EvidenceVerifierAgent":
            candidate = state.get("literature_analysis_draft") or state.get("literature_analysis")
            try:
                return LiteratureAnalysis.model_validate(candidate or {}).model_dump()
            except Exception:  # noqa: BLE001
                pass
        return {
            "target_molecule": {}, "source_records": [], "analogues": [],
            "synthesis_routes": [], "facts": [],
            "gaps": [f"{agent_name}: ответ модели не удалось разобрать."],
        }
    if agent_name == "RouteSelectionAgent":
        from CoScientist.microfluidics.models import RouteSelection
        decisions = []
        analysis = state.get("literature_analysis") or {}
        routes = analysis.get("synthesis_routes") if isinstance(analysis, dict) else []
        for route in routes or []:
            if not isinstance(route, dict):
                continue
            product = route.get("product") or ""
            if isinstance(product, dict):
                product = product.get("name") or product.get("smiles") or ""
            decisions.append({
                "route_id": str(route.get("route_id") or "").strip(),
                "product": str(product), "recommendation": "отсеять",
                "reason": "Автоматическая рекомендация не сформирована; требуется решение оператора.",
            })
        try:
            return RouteSelection(decisions=decisions).model_dump()
        except Exception:  # noqa: BLE001
            return {"decisions": [], "selected_route_id": "", "selection_reason":
                    "Ответ модели не разобран; требуется ручная проверка."}
    if agent_name == "TZQueryGenAgent":
        return {"queries": []}
    if agent_name == "MolDesignAgent":
        return {"fixed_target": False, "candidates": [],
                "gaps": ["Ответ агента дизайна не удалось разобрать."]}
    return None


def _extract_structured_payload(
    text: str, agent_name: str = "", callback_context: Any = None,
) -> Optional[Any]:
    """Extract JSON, with a conservative YAML fallback for schema answers."""
    payload = _extract_json(text)
    if payload is None:
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError:
            payload = None
        if not isinstance(payload, (dict, list)):
            payload = None
    if payload is None and callback_context is not None and hasattr(callback_context, "state"):
        fallback = _fallback_payload(agent_name, callback_context)
        if fallback is not None:
            logger.warning("[%s] non-JSON response; using safe fallback", agent_name)
            return fallback
    if payload is None and agent_name == "LiteratureSynthesisAgent":
        # Backward-compatible helper behavior for callers that do not provide
        # an ADK callback context; real runs use the LiteratureAnalysis branch
        # above and never emit a selection-shaped payload.
        return {"selected_ids": [], "reason": "Ответ метаагента нельзя было разобрать.",
                "warnings": ["Ответ метаагента нельзя было разобрать."]}
    if payload is None:
        return None
    if agent_name == "RouteSelectionAgent":
        payload = _lift_route_selection_fields(payload)
        payload = _normalize_route_selection(payload)
    if callback_context is not None and hasattr(callback_context, "state") and agent_name in {
        "LiteratureSynthesisAgent", "EvidenceVerifierAgent", "RouteSelectionAgent",
        "TZQueryGenAgent", "MolDesignAgent",
    }:
        try:
            from CoScientist.microfluidics.models import (
                DesignCandidates, LiteratureAnalysis, LiteratureQueries, RouteSelection,
            )
            schema = {
                "RouteSelectionAgent": RouteSelection,
                "LiteratureSynthesisAgent": LiteratureAnalysis,
                "EvidenceVerifierAgent": LiteratureAnalysis,
                "TZQueryGenAgent": LiteratureQueries,
                "MolDesignAgent": DesignCandidates,
            }[agent_name]
            payload = schema.model_validate(payload).model_dump()
        except Exception:  # noqa: BLE001
            fallback = _fallback_payload(agent_name, callback_context)
            if fallback is not None:
                logger.warning("[%s] invalid JSON shape; using safe fallback", agent_name)
                payload = fallback
    return payload


def sanitize_json_output(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Rewrite the response to exactly its JSON payload (or pass through)."""
    content = getattr(llm_response, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    if not parts:
        return None
    # Function calls are not JSON answers — leave them alone.
    if any(getattr(p, "function_call", None) for p in parts):
        return None

    text = "".join(
        p.text for p in parts
        if getattr(p, "text", None) and not getattr(p, "thought", False)
    )
    if not text.strip():
        fallback = _fallback_payload(getattr(callback_context, "agent_name", ""), callback_context)
        if fallback is None:
            return None
        return LlmResponse(content=types.Content(
            role="model", parts=[types.Part(text=json.dumps(fallback, ensure_ascii=False))]
        ))

    extracted = _extract_structured_payload(
        text, getattr(callback_context, "agent_name", ""), callback_context
    )
    if extracted is None:
        # Last resort: for agents with an output_schema, returning None lets
        # the raw (non-JSON) text reach ADK's validate_schema, which crashes
        # with "Invalid JSON".  Build a safe fallback instead.
        agent_name = getattr(callback_context, "agent_name", "")
        fallback = _fallback_payload(agent_name, callback_context)
        if fallback is not None:
            logger.warning(
                "[%s] could not extract any JSON; using safe fallback", agent_name,
            )
            extracted = fallback
        else:
            return None  # unknown agent — nothing to fix

    clean = json.dumps(extracted, ensure_ascii=False)
    if clean == text.strip():
        return None

    logger.info(
        "[%s] sanitized JSON output (%d -> %d chars)",
        getattr(callback_context, "agent_name", "?"), len(text), len(clean),
    )
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=clean)])
    )
