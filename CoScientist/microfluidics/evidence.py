"""Authenticate evidence claims at the tool boundary, not from LLM assertions."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext

from CoScientist.microfluidics.models import LiteratureAnalysis

TRACE_KEY = "_evidence_verifier_trace"
_URL = re.compile(r"https?://[^\s\"'<>]+", re.I)
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
_PATENT = re.compile(r"\b(?:WO|EP|US|RU)\s*[-/]?\s*\d{5,}[A-Z]\d?\b", re.I)
_STANDARD = re.compile(r"\b(?:ASTM|ISO|EN|GOST|ГОСТ)\s+[A-ZА-Я0-9][A-ZА-Я0-9.:-]*", re.I)
_FULL_TEXT_TOOL = re.compile(r"(?:extract|explore|analy[sz]|read|full.?text)", re.I)


def _serialized(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - audit must fail closed, never break a run
        return str(value)


def _identifiers(text: str) -> set[str]:
    found = {item.rstrip(".,);]") for item in _URL.findall(text)}
    found.update(item.rstrip(".,);]").casefold() for item in _DOI.findall(text))
    found.update(" ".join(item.split()).casefold() for item in _PATENT.findall(text))
    found.update(" ".join(item.split()).casefold() for item in _STANDARD.findall(text))
    return found


def _response_failed(response: Any) -> bool:
    if response is None:
        return True
    if isinstance(response, dict):
        if response.get("isError") is True or response.get("error"):
            return True
        content = response.get("content")
        if isinstance(content, list) and any(
            isinstance(item, dict) and item.get("isError") is True for item in content
        ):
            return True
    text = _serialized(response).strip().casefold()
    return len(text) < 20 or text.startswith(("error", "tool error"))


def begin_evidence_verification(callback_context: CallbackContext) -> None:
    callback_context.state[TRACE_KEY] = []
    return None


def capture_evidence_verification(
    tool: Any = None,
    args: Any = None,
    tool_context: Any = None,
    tool_response: Any = None,
    **kwargs: Any,
) -> None:
    """Record immutable hashes and identifiers from actual verifier tool results."""
    if tool_context is None:
        return None
    response = tool_response if tool_response is not None else kwargs.get("response")
    response_text = _serialized(response)
    args_text = _serialized(args)
    name = str(getattr(tool, "name", "") or "")
    trace = list(tool_context.state.get(TRACE_KEY) or [])
    trace.append({
        "tool": name,
        "full_text_capable": bool(_FULL_TEXT_TOOL.search(name)),
        "successful": not _response_failed(response),
        "requested_identifiers": sorted(_identifiers(args_text)),
        "returned_identifiers": sorted(_identifiers(response_text)),
        "content_hash": "sha256:" + hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
    })
    tool_context.state[TRACE_KEY] = trace
    return None


def authenticate_analysis(analysis: Any, trace: Any) -> LiteratureAnalysis:
    """Accept `verified` only when a full-text-capable tool observed the source."""
    model = analysis if isinstance(analysis, LiteratureAnalysis) else LiteratureAnalysis.model_validate(analysis or {})
    entries = [
        entry for entry in (trace or [])
        if isinstance(entry, dict)
        and entry.get("full_text_capable")
        and entry.get("successful", True)
    ]
    authenticated: dict[str, dict] = {}
    for source in model.source_records:
        candidates = {source.url.rstrip(".,);]").casefold()} if source.url else set()
        if source.doi:
            candidates.add(source.doi.casefold().removeprefix("https://doi.org/"))
        if source.external_id:
            candidates.add(" ".join(source.external_id.split()).casefold())
        match = next((entry for entry in entries if candidates.intersection({
            str(item).casefold()
            for key in ("returned_identifiers", "requested_identifiers", "identifiers")
            for item in (entry.get(key) or [])
        })), None)
        if match is None:
            source.full_text_available = False
            source.content_hash = ""
            source.verified_by = ""
            source.verification_tool = ""
            continue
        source.full_text_available = True
        source.content_hash = str(match.get("content_hash") or "")
        source.verified_by = "evidence_verifier"
        source.verification_tool = str(match.get("tool") or "")
        authenticated[source.source_id] = match

    def secure_refs(refs: list[Any]) -> None:
        for ref in refs:
            if ref.source_id not in authenticated or not ref.locator.strip():
                ref.verification_status = "unverified"

    for analogue in model.analogues:
        for prop in analogue.properties:
            secure_refs(prop.evidence)
    for route in model.synthesis_routes:
        secure_refs(route.evidence)
        for step in route.steps:
            secure_refs(step.evidence)
            for condition in step.conditions:
                secure_refs(condition.evidence)
    for fact in model.facts:
        secure_refs(fact.evidence)
    return model


def authenticate_evidence_verification(callback_context: CallbackContext) -> None:
    state = callback_context.state
    state["literature_analysis"] = authenticate_analysis(
        state.get("literature_analysis"), state.get(TRACE_KEY),
    ).model_dump()
    return None


__all__ = [
    "TRACE_KEY",
    "authenticate_analysis",
    "authenticate_evidence_verification",
    "begin_evidence_verification",
    "capture_evidence_verification",
]
