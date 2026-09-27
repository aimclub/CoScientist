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


def _unwrap_completion_state(obj: Any) -> Any:
    """Flatten GLM/OpenRouter ``completionState``/``entries`` envelopes.

    Some providers emit list items as JSON *strings* like
    ``{"completionState":"complete","entries":[["index",{"value":1}], ...],
    "type":"Object"}`` instead of a plain ``{"index": 1, ...}``. Schema
    validation (ToolRanking/MCPRanking, FEDOT MASConfig) then fails.
    """
    if isinstance(obj, str):
        parsed = _try_loads(obj)
        if parsed is None:
            return obj
        obj = parsed
    if not isinstance(obj, dict):
        return obj
    if obj.get("type") == "Object" and isinstance(obj.get("entries"), list):
        out: dict[str, Any] = {}
        for entry in obj["entries"]:
            if not (isinstance(entry, (list, tuple)) and len(entry) == 2):
                continue
            key, val = entry
            out[str(key)] = _unwrap_completion_state(
                val["value"] if isinstance(val, dict) and "value" in val else val
            )
        return out
    return {k: _unwrap_completion_state(v) for k, v in obj.items()}


def _normalize_ranking_payload(data: Any) -> Any:
    """Coerce ranking list items that arrived as completionState strings."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    for key in ("tools", "mcp_scores"):
        items = out.get(key)
        if isinstance(items, list):
            out[key] = [_unwrap_completion_state(item) for item in items]
    return out


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


def _maybe_apply_tool_rerank(callback_context: CallbackContext, payload: Any) -> None:
    """Fold ToolReranker score apply into sanitize (avoids a separate after_model cb).

    ``collect_reranked_tools`` (after_agent) remains the fallback when scores only
    land in ``output_key`` state. Lazy import avoids a cycle with tool_callbacks.
    """
    if not isinstance(payload, dict) or payload.get("tools") is None:
        return
    try:
        from CoScientist.agents.callbacks.tool_callbacks import (
            _TOOL_RERANK_APPLIED_KEY,
            _score_items_from_reranked_state,
            apply_tool_rerank_scores,
        )
    except Exception:  # noqa: BLE001
        return
    state = callback_context.state
    if state.get(_TOOL_RERANK_APPLIED_KEY):
        return
    items = _score_items_from_reranked_state(payload)
    if not items:
        return
    apply_tool_rerank_scores(state, items)
    logger.info(
        "[%s] applied tool rerank during sanitize (%d scores)",
        getattr(callback_context, "agent_name", "?"),
        len(items),
    )


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
    thought_text = "".join(
        p.text for p in parts
        if getattr(p, "text", None) and getattr(p, "thought", False)
    )

    extracted = _extract_json(text) if text.strip() else None
    if extracted is None and thought_text.strip():
        # GLM often parks ToolRanking JSON in a thought part.
        extracted = _extract_json(thought_text)
    if extracted is None:
        return None  # nothing to fix — let schema validation report it

    normalized = _normalize_ranking_payload(extracted)
    _maybe_apply_tool_rerank(callback_context, normalized)

    if not text.strip():
        return None

    clean = json.dumps(normalized, ensure_ascii=False)
    if clean == text.strip():
        return None

    logger.info(
        "[%s] sanitized JSON output (%d -> %d chars)",
        getattr(callback_context, "agent_name", "?"), len(text), len(clean),
    )
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=clean)])
    )
