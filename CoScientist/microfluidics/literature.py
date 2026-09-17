"""Module A plumbing: keep every literature result and the target molecule.

Three callbacks close the gaps between the literature stage and the modules
that read it:

``collect_literature_finding`` (after_agent, ResearchAgent)
    ResearchAgent writes its answer to ``search_results`` on every call, so each
    LIT-xx task overwrote the one before and only the last survived. This
    callback appends every answer to ``literature_findings``. ResearchAgent runs
    as an AgentTool, and the AgentTool forwards the state delta to the parent
    session, so the list accumulates across calls.

``inject_target_molecule`` (before_agent)
    Reads the customer's target molecule out of the structured ТЗ into
    ``target_molecule``, so the prompts downstream see it as a field instead of
    digging through 16 blocks.

``pin_target_molecule`` (after_agent, LiteratureSynthesisAgent)
    When the ТЗ fixes the molecule, the ТЗ wins over whatever the LLM wrote into
    ``literature_analysis.target_molecule``.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext

from CoScientist.hitl.field_status import OPEN_STATUSES
from CoScientist.microfluidics.models import StructuredTZ, TargetMolecule

logger = logging.getLogger(__name__)

FINDINGS_KEY = "literature_findings"
TARGET_KEY = "target_molecule"
ANALYSIS_KEY = "literature_analysis"

_QUERY_ID = re.compile(r"\bLIT-\d+\b", re.IGNORECASE)
_EMPTY = {"", "-", "—", "не задано", "не задан", "не задана", "нет данных"}
_YES = ("да", "yes", "true")


# ── Target molecule ──────────────────────────────────────────────────────────

def _field(tz: StructuredTZ, block: str, *needles: str) -> str:
    """Value of the first set field of ``block`` whose name contains a needle.

    Field names are written by the LLM from a guide, not fixed, so they are
    matched by substring.
    """
    b = tz.block(block)
    if b is None:
        return ""
    for row in b.fields:
        name = row.name.lower()
        if any(n in name for n in needles):
            value = row.value.strip()
            if row.status not in OPEN_STATUSES and value.lower() not in _EMPTY:
                return value
    return ""


def extract_target_molecule(structured_tz: Any) -> TargetMolecule:
    """The customer's target molecule as the ТЗ states it."""
    try:
        tz = (
            structured_tz
            if isinstance(structured_tz, StructuredTZ)
            else StructuredTZ.model_validate(structured_tz or {})
        )
    except Exception as exc:  # noqa: BLE001 — a malformed ТЗ must not break the run
        logger.warning("target molecule: unreadable structured_tz: %s", exc)
        return TargetMolecule()

    name = _field(tz, "Целевой продукт", "целевое вещество", "целевая молекула")
    smiles = _field(tz, "Целевой продукт", "smiles")
    cas = _field(tz, "Целевой продукт", "cas")
    fixed_flag = _field(tz, "Тип задачи", "фиксированн").lower()
    fixed = fixed_flag.startswith(_YES) or (not fixed_flag and bool(smiles or cas))

    if not (name or smiles or cas):
        return TargetMolecule(fixed=False)
    return TargetMolecule(fixed=fixed, name=name, smiles=smiles, cas=cas, source="ТЗ")


def inject_target_molecule(callback_context: CallbackContext) -> None:
    """Refresh ``target_molecule`` from the current ТЗ (idempotent)."""
    tz = callback_context.state.get("structured_tz")
    if not tz:
        return None
    callback_context.state[TARGET_KEY] = extract_target_molecule(tz).model_dump()
    return None


def pin_target_molecule(callback_context: CallbackContext) -> None:
    """Make the ТЗ's fixed molecule win inside ``literature_analysis``."""
    state = callback_context.state
    analysis = state.get(ANALYSIS_KEY)
    tz = state.get("structured_tz")
    if not isinstance(analysis, dict) or not tz:
        return None
    target = extract_target_molecule(tz)
    if not target.fixed:
        return None
    state[ANALYSIS_KEY] = {**analysis, "target_molecule": target.model_dump()}
    return None


# ── Literature findings ──────────────────────────────────────────────────────

def _request_text(callback_context: CallbackContext) -> str:
    content = getattr(callback_context, "user_content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(getattr(p, "text", None) or "" for p in parts).strip()


def collect_literature_finding(callback_context: CallbackContext) -> None:
    """Append this ResearchAgent answer to ``literature_findings``."""
    state = callback_context.state
    result = state.get("search_results")
    if not result:
        return None
    request = _request_text(callback_context)
    match = _QUERY_ID.search(request) or _QUERY_ID.search(str(result)[:500])
    finding = {
        "query_id": match.group(0).upper() if match else "",
        "request": request,
        "result": result,
    }

    findings = list(state.get(FINDINGS_KEY) or [])
    # The AgentTool copies the parent state in, so a call that wrote nothing
    # still sees the previous task's search_results — do not record it twice.
    if any(f.get("result") == result for f in findings):
        return None
    # A retry of the same LIT-xx replaces the earlier answer instead of piling up.
    if finding["query_id"]:
        findings = [f for f in findings if f.get("query_id") != finding["query_id"]]
    findings.append(finding)
    state[FINDINGS_KEY] = findings
    return None


__all__ = [
    "ANALYSIS_KEY",
    "FINDINGS_KEY",
    "TARGET_KEY",
    "collect_literature_finding",
    "extract_target_molecule",
    "inject_target_molecule",
    "pin_target_molecule",
]
