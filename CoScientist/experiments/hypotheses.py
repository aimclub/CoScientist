"""Bridge system HypothesesAgent output into planner hypothesis_refs."""
from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from CoScientist.experiments.context.builder import extract_hypothesis_refs, _user_text
from CoScientist.experiments.runtime.shared import audit

logger = logging.getLogger(__name__)

_OUTPUT_KEYS = ("hypotheses", "experiment_hypotheses")
_PENDING_FC_KEY = "_em_hypotheses_from_fc"
_FORCE_COMMIT_KEY = "_em_hypotheses_commit_forced"
_MAX_H_PER_COMMIT = 3
# Numbered draft lines from model thinking / prose, e.g.
# "1. **ATP-competitive hypothesis**: Molecules with …"
_NUMBERED_HYP_RE = re.compile(
    r"(?:^|\n)\s*\d+[\.\)]\s+"
    r"(?:\*\*)?(?P<title>[^*\n:]{0,120})(?:\*\*)?\s*:\s*"
    r"(?P<body>.+?)"
    r"(?=(?:\n\s*\d+[\.\)]|\n\s*#{1,3}\s|\n\n|\Z))",
    re.IGNORECASE | re.DOTALL,
)
_NOISE_MARKERS = (
    "mcp_scores",
    "[FullSetToolReranker]",
    "[ToolReranker]",
    "[ToolRetrieverAgent]",
    "[WebToolsDeployerAgent]",
    "EXPERIMENT_RETRIEVAL_BUDGET",
)


def _is_tool_prep_noise(text: str) -> bool:
    blob = (text or "").strip()
    if not blob:
        return True
    if any(m in blob for m in _NOISE_MARKERS):
        return True
    if blob.startswith("{") and "mcp_scores" in blob:
        return True
    return False


def _resolve_em_ask(callback_context: CallbackContext) -> str:
    state = callback_context.state
    for key in ("experiment_source_request", "user_query", "query"):
        val = state.get(key)
        if isinstance(val, str) and val.strip() and not _is_tool_prep_noise(val):
            return val.strip()
    text = _user_text(callback_context)
    if text and not _is_tool_prep_noise(text):
        return text
    try:
        inv = getattr(callback_context, "_invocation_context", None) or getattr(
            callback_context, "invocation_context", None
        )
        session = getattr(inv, "session", None) if inv is not None else None
        events = list(getattr(session, "events", None) or [])
    except Exception:  # noqa: BLE001
        events = []
    candidates: list[str] = []
    for event in events:
        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None) == "ExperimentModuleAgent":
                args = dict(getattr(fc, "args", None) or {})
                req = args.get("request")
                if isinstance(req, str) and req.strip() and not _is_tool_prep_noise(req):
                    candidates.append(req.strip())
            text_part = getattr(part, "text", None)
            if isinstance(text_part, str) and text_part.strip() and not _is_tool_prep_noise(text_part):
                if getattr(content, "role", None) == "user":
                    candidates.append(text_part.strip())
    if candidates:
        return max(candidates, key=len)
    return ""


def bootstrap_research_question_if_empty(callback_context: CallbackContext) -> None:
    """before_agent on HypothesesAgent: seed the ResearchQuestion root if the
    graph is still empty when this stage starts.

    HypothesesAgent's seed prompt used to tell it to create a ResearchQuestion
    itself when the graph is empty — but its ACL
    (AGENT_PERMISSIONS["HypothesesAgent"] in graph/research/schema.py) forbids
    ResearchQuestion nodes, and it has no research_init tool (root-only,
    OrchestratorAgent). Relying on OrchestratorAgent to call research_init
    before delegating is best-effort per-turn LLM behavior and can miss —
    when it does, HypothesesAgent gets a permission error, burns turns on
    malformed retries, and every hypothesis source ends up empty. Bootstrap
    the root deterministically here instead of hoping the model catches it.
    """
    try:
        from CoScientist.config import get_settings
        if not get_settings().research_graph.enabled:
            return
    except Exception:  # noqa: BLE001
        pass
    try:
        from CoScientist.graph.research.store import get_research_graph

        research_graph = get_research_graph(callback_context)
        if not research_graph.is_empty():
            return
        ask = (
            _resolve_em_ask(callback_context)
            or str(callback_context.state.get("experiment_source_request") or "").strip()
            or "Computational experiment request."
        )
        out = research_graph.init_research(source="HypothesesAgent", question=ask)
    except Exception as exc:  # noqa: BLE001 — bootstrap must never break the run
        audit(
            logger, f"EXPERIMENT_RESEARCH_ROOT_BOOTSTRAP_FAILED error={exc}",
            level=logging.WARNING,
        )
        return
    audit(
        logger,
        f"EXPERIMENT_RESEARCH_ROOT_BOOTSTRAPPED ok={bool(out.get('ok'))} "
        f"root_id={out.get('root_id')}",
    )


def persist_experiment_em_request(callback_context: CallbackContext) -> None:
    """before_agent on ToolRetriever: capture the original ask once; do not
    overwrite it with hypothesis prose. A new orchestrator_root_goal clears leftover inventory."""
    state = callback_context.state
    root = str(state.get("orchestrator_root_goal") or "").strip()
    ask = root if root and not _is_tool_prep_noise(root) else _resolve_em_ask(callback_context)
    if not ask:
        return
    existing = str(state.get("experiment_source_request") or "").strip()
    if existing == ask:
        return
    if existing and not _is_tool_prep_noise(existing):
        # Keep the original ask unless the orchestrator root goal is a new request.
        if not (root and not _is_tool_prep_noise(root) and root != existing):
            return
        ask = root
    _clear_leftover_inventory(state)
    state["experiment_source_request"] = ask
    state["_em_hypotheses_seeded"] = False
    state[_FORCE_COMMIT_KEY] = False
    audit(logger, f"EXPERIMENT_EM_REQUEST_PERSISTED chars={len(ask)}")


def _clear_leftover_inventory(state: Any) -> None:
    """Drop retrieved tools from a prior ask so leftover MCP cannot fake cover."""
    from CoScientist.experiments.context.builder import (
        DISCOVERED_CAPABILITIES_KEY,
        RETRIEVED_CAPABILITIES_KEY,
    )

    state[DISCOVERED_CAPABILITIES_KEY] = None
    state[RETRIEVED_CAPABILITIES_KEY] = None
    state["accumulated_tools"] = []
    state["filtered_tools"] = []
    state["retrieval_queries"] = []
    try:
        from CoScientist.tools.retrieval_tools import clear_session_accumulated_tools

        clear_session_accumulated_tools()
    except Exception:  # noqa: BLE001
        pass


def seed_hypotheses_from_em_request(
    callback_context: CallbackContext, llm_request: LlmRequest,
) -> None:
    """before_model: on first turn only, replace ToolPreparer junk with EM ask.

    Must not re-run on later turns — rewriting contents would wipe tool results
    and trap HypothesesAgent in a research_overview loop.
    """
    state = callback_context.state
    if state.get("_em_hypotheses_seeded"):
        return
    ask = _resolve_em_ask(callback_context)
    if not ask:
        return
    if not str(state.get("experiment_source_request") or "").strip():
        state["experiment_source_request"] = ask
    ops = state.get("experiment_operations") or []
    if not (isinstance(ops, list) and ops):
        raw = state.get("research_frame")
        if raw:
            try:
                from CoScientist.context_init.agent import coerce_frame
                from CoScientist.context_init.commit import frame_operations
                ops = frame_operations(coerce_frame(raw))
            except Exception:  # noqa: BLE001
                ops = []
    op_block = ""
    if isinstance(ops, list) and ops:
        lines = []
        for item in ops:
            if isinstance(item, dict) and item.get("statement"):
                lines.append(
                    f"- {item.get('operation_id') or 'OP'}: {item['statement']}"
                )
            elif isinstance(item, str) and item.strip():
                lines.append(f"- {item.strip()}")
        if lines:
            op_block = (
                "AUTHORITATIVE operations (one hypothesis per slot; "
                "H1 matches OP-1, H2 matches OP-2, …). Do not invent extra "
                "endpoints and do not skip a slot:\n"
                + "\n".join(lines)
                + "\n"
            )
    prompt = (
        "Generate falsifiable scientific hypotheses for the computational experiment below.\n"
        f"{op_block}"
        "Prefer one distinct hypothesis per distinct operation the user asked to "
        "execute (numbered/separated steps in ASK, or AUTHORITATIVE operations "
        "above). Do not invent extra endpoints beyond those operations. Skip a "
        "narrative-only report step — that is ResultAggregator, not a hypothesis.\n"
        "CRITICAL — keep research_commit SMALL and reliable:\n"
        "- Commit Hypothesis nodes ONLY (no VerificationMethod / ConfirmationCriteria "
        "in the same call). Add VM/CC later in separate small commits if needed.\n"
        f"- At most {_MAX_H_PER_COMMIT} Hypothesis nodes per research_commit; "
        "make additional commits if you need more.\n"
        "- Prefer short formulation strings; avoid huge protocol_steps dumps.\n"
        "The research graph already has its ResearchQuestion root by the time you "
        "run. If you somehow still see an empty graph, do NOT try to create the "
        "ResearchQuestion yourself — you do not have that permission and have no "
        "research_init tool; just commit your Hypothesis nodes directly. Also state "
        "clear formulations in the final answer as 'Hypothesis 1 (…):' / "
        "'*Statement:* …' backup. Do not discuss tool inventory or MCP reranking.\n\n"
        f"ASK:\n{ask}"
    )
    llm_request.contents = [
        types.Content(role="user", parts=[types.Part(text=prompt)])
    ]
    state["_em_hypotheses_seeded"] = True
    audit(logger, f"EXPERIMENT_HYPOTHESES_SEEDED chars={len(ask)}")


def _parse_payload(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    if not isinstance(raw, str):
        return None
    from CoScientist.experiments.runtime.shared import parse_fenced_json

    try:
        return parse_fenced_json(raw, prefer_list=True)
    except json.JSONDecodeError:
        return None


def _as_ref_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("hypotheses", "hypothesis_refs", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
        if payload.get("hypothesis_id") or payload.get("statement") or payload.get("hypothesis"):
            return [payload]
    return []


def _refs_from_text(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    return extract_hypothesis_refs(raw)


def _merge_refs(
    existing: Any, new_refs: list[dict[str, str]], cap: int = 8,
) -> list[dict[str, str]]:
    """Merge by statement (keep order), renumber H1..Hn, trim to ``cap``."""
    merged = list(existing or [])
    seen = {r.get("statement") for r in merged if isinstance(r, dict)}
    for ref in new_refs:
        if ref["statement"] not in seen:
            merged.append(ref)
            seen.add(ref["statement"])
    for i, ref in enumerate(merged, start=1):
        ref["hypothesis_id"] = f"H{i}"
    return merged[:cap]


def _publish_refs(state: Any, refs: list[dict[str, str]]) -> None:
    """Write the authoritative hypothesis refs under every consumer key."""
    state["hypotheses"] = refs
    state["hypothesis_refs"] = refs
    state["experiment_hypotheses"] = refs


def _refs_from_research_graph(callback_context: CallbackContext) -> list[dict[str, str]]:
    try:
        from CoScientist.graph.research.store import get_research_graph

        store = get_research_graph(callback_context)
        g = store.full_graph()
    except Exception:  # noqa: BLE001
        return []
    # Missing status (unit-test fakes / legacy nodes) counts as still-active.
    active = frozenset({"formulated", "under_verification", ""})
    out: list[dict[str, str]] = []
    for node_id, data in g.nodes(data=True):
        if data.get("type") != "Hypothesis":
            continue
        if str(data.get("status") or "") not in active:
            continue
        attrs = data.get("attrs") or {}
        statement = str(attrs.get("formulation") or attrs.get("label") or "").strip()
        if not statement:
            continue
        hid = str(node_id).strip().upper()
        if not re.fullmatch(r"H\d+", hid):
            hid = f"H{len(out) + 1}"
        out.append({"hypothesis_id": hid, "statement": re.sub(r"\s+", " ", statement)[:800]})
        if len(out) >= 8:
            break
    return out


def _refs_from_hypothesis_nodes(payload: Any) -> list[dict[str, str]]:
    """Pull formulations from research_commit-style node lists."""
    nodes: list[Any] = []
    if isinstance(payload, list):
        nodes = payload
    elif isinstance(payload, dict):
        for key in ("nodes", "committed", "items"):
            val = payload.get(key)
            if isinstance(val, dict) and isinstance(val.get("nodes"), list):
                nodes = val["nodes"]
                break
            if isinstance(val, list):
                nodes = val
                break
    out: list[dict[str, str]] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or node.get("node_type") or "").strip()
        if ntype and ntype != "Hypothesis":
            continue
        attrs = node.get("attrs") or node.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        statement = str(
            attrs.get("formulation") or attrs.get("label") or node.get("formulation") or ""
        ).strip()
        if not statement:
            continue
        hid = str(node.get("id") or node.get("ref") or "").strip().upper()
        if not re.fullmatch(r"H\d+", hid):
            hid = f"H{len(out) + 1}"
        out.append({"hypothesis_id": hid, "statement": re.sub(r"\s+", " ", statement)[:800]})
        if len(out) >= 8:
            break
    return out


def _estimate_commit_chars(args: dict[str, Any]) -> int:
    try:
        return len(json.dumps(args, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return 10_000


def _response_has_function_call(llm_response: LlmResponse, name: str | None = None) -> bool:
    content = getattr(llm_response, "content", None)
    for part in list(getattr(content, "parts", None) or []):
        fc = getattr(part, "function_call", None)
        fc_name = getattr(fc, "name", None) if fc is not None else None
        if not fc_name:
            continue
        if name is None or fc_name == name:
            return True
    return False


def _response_text(llm_response: LlmResponse) -> str:
    """Collect visible + thought text from a model turn (for draft parsing)."""
    content = getattr(llm_response, "content", None)
    chunks: list[str] = []
    for part in list(getattr(content, "parts", None) or []):
        text = getattr(part, "text", None)
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n".join(chunks)


def _refs_from_numbered_drafts(text: str) -> list[dict[str, str]]:
    """Parse ``1. **Title**: statement`` drafts common in model thinking."""
    if not isinstance(text, str) or not text.strip():
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _NUMBERED_HYP_RE.finditer(text):
        title = re.sub(r"\s+", " ", (match.group("title") or "").strip(" *"))
        body = re.sub(r"\s+", " ", (match.group("body") or "").strip())
        # Prefer the body; if it is tiny, fall back to title+body.
        statement = body if len(body) >= 24 else f"{title}: {body}".strip(": ")
        statement = statement[:500]
        if len(statement) < 24 or statement in seen:
            continue
        seen.add(statement)
        out.append({"hypothesis_id": f"H{len(out) + 1}", "statement": statement})
        if len(out) >= _MAX_H_PER_COMMIT:
            break
    return out


def _refs_from_model_draft(text: str) -> list[dict[str, str]]:
    """Prefer explicit Hypothesis-N labels; else numbered thinking drafts."""
    refs = extract_hypothesis_refs(text or "")
    if refs:
        return refs[:_MAX_H_PER_COMMIT]
    return _refs_from_numbered_drafts(text)


def _root_question_id(callback_context: CallbackContext) -> str:
    try:
        from CoScientist.graph.research.store import get_research_graph

        rid = get_research_graph(callback_context).root_id()
        if rid:
            return str(rid)
    except Exception:  # noqa: BLE001
        pass
    return "Q1"


def _commit_args_from_refs(
    refs: list[dict[str, str]], *, root_id: str,
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for i, ref in enumerate(refs[:_MAX_H_PER_COMMIT], start=1):
        statement = re.sub(r"\s+", " ", str(ref.get("statement") or "").strip())[:500]
        if not statement:
            continue
        nodes.append({
            "type": "Hypothesis",
            "ref": f"h{i}",
            "attrs": {"formulation": statement, "status": "formulated"},
        })
    edges = [
        {"type": "motivates", "from": root_id, "to": f"#{n['ref']}"}
        for n in nodes
    ]
    return {"nodes": nodes, "edges": edges}


def _already_have_hypothesis_refs(callback_context: CallbackContext) -> bool:
    state = callback_context.state
    pending = state.get(_PENDING_FC_KEY) or []
    if any(isinstance(r, dict) and r.get("statement") for r in pending):
        return True
    return bool(_refs_from_research_graph(callback_context))


def enforce_hypothesis_research_commit(
    callback_context: CallbackContext, llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """after_model: if the model tries to finish without research_commit, force one.

    HypothesesAgent sometimes drafts hypotheses only in thinking/prose and exits
    without a tool call. Without a forced commit, after_agent falls through to a
    single H1 fallback. When drafts are recoverable from the turn text, rewrite
    the response into a Hypothesis-only research_commit (once per invocation).
    """
    state = callback_context.state
    if state.get(_FORCE_COMMIT_KEY):
        return None
    if _response_has_function_call(llm_response):
        # Still mid-loop (e.g. research_overview) or already committing — do not
        # interrupt tool-using turns.
        return None
    if _already_have_hypothesis_refs(callback_context):
        # If the model emits no visible non-thought text on its final exit turn,
        # furnish a clean summary from the committed refs so the caller (Orchestrator)
        # receives a substantive result instead of empty text.
        content = getattr(llm_response, "content", None)
        parts = list(getattr(content, "parts", None) or [])
        visible = "".join(
            getattr(p, "text", "") or ""
            for p in parts
            if not getattr(p, "thought", False)
        ).strip()
        if not visible:
            refs = (
                state.get(_PENDING_FC_KEY)
                or _refs_from_research_graph(callback_context)
            )
            if refs:
                lines = ["Formulated Hypotheses:"]
                for i, r in enumerate(refs, 1):
                    hid = r.get("hypothesis_id", f"H{i}")
                    stmt = r.get("statement", "")
                    lines.append(f"- {hid}: {stmt}")
                parts.append(types.Part.from_text(text="\n".join(lines)))
                return LlmResponse(
                    content=types.Content(
                        role=getattr(content, "role", None) or "model",
                        parts=parts,
                    )
                )
        return None
    draft = _response_text(llm_response)
    refs = _refs_from_model_draft(draft)
    if not refs:
        return None
    args = _commit_args_from_refs(refs, root_id=_root_question_id(callback_context))
    if not args.get("nodes"):
        return None
    state[_FORCE_COMMIT_KEY] = True
    # Stash early so after_agent is safe even if the tool path is odd.
    state[_PENDING_FC_KEY] = _merge_refs(state.get(_PENDING_FC_KEY), refs)
    ids = [r["hypothesis_id"] for r in state[_PENDING_FC_KEY]]
    audit(
        logger,
        f"EXPERIMENT_FORCE_HYPOTHESES_COMMIT count={len(args['nodes'])}",
        stdout=(
            f"EXPERIMENT_FORCE_HYPOTHESES_COMMIT count={len(args['nodes'])} ids={ids}"
        ),
    )
    return LlmResponse(
        content=types.Content(
            role=getattr(getattr(llm_response, "content", None), "role", None) or "model",
            parts=[types.Part.from_function_call(name="research_commit", args=args)],
        )
    )


def _shrink_commit_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]], bool]:
    """Keep Hypothesis-only (≤3) so the FC channel stays dispatchable."""
    nodes_raw = args.get("nodes")
    if isinstance(nodes_raw, str):
        nodes_raw = _parse_payload(nodes_raw)
    nodes = nodes_raw if isinstance(nodes_raw, list) else []
    hyp_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or node.get("node_type") or "").strip()
        if ntype and ntype != "Hypothesis":
            continue
        attrs = node.get("attrs") or node.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        formulation = str(
            attrs.get("formulation") or attrs.get("label") or node.get("formulation") or ""
        ).strip()
        if not formulation:
            continue
        ref = str(node.get("ref") or node.get("id") or f"h{len(hyp_nodes) + 1}").strip()
        compact_attrs = {
            "formulation": re.sub(r"\s+", " ", formulation)[:500],
            "status": str(attrs.get("status") or "formulated"),
        }
        if attrs.get("priority"):
            compact_attrs["priority"] = str(attrs["priority"])[:40]
        hyp_nodes.append({"type": "Hypothesis", "ref": ref, "attrs": compact_attrs})
        if len(hyp_nodes) >= _MAX_H_PER_COMMIT:
            break
    refs = _refs_from_hypothesis_nodes(hyp_nodes)
    if not hyp_nodes:
        return args, refs, False
    edges = [
        {"type": "motivates", "from": "Q1", "to": f"#{n['ref']}"}
        for n in hyp_nodes
    ]
    shrunk = {"nodes": hyp_nodes, "edges": edges}
    # Preserve optional root question if present and tiny.
    for key in ("question", "research_question"):
        if isinstance(args.get(key), str) and args[key].strip():
            shrunk[key] = args[key].strip()[:400]
    # Always emit the compact Hypothesis-only form when Hs were extracted.
    return shrunk, refs, True


def _coerce_commit_arg_lists(args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Force nodes/edges/status_updates to list type before the FC is dispatched.

    GLM occasionally emits ``research_commit`` with a JSON-encoded STRING for
    ``nodes`` (or edges/status_updates) instead of an array, or even serializes
    the JSON list directly as an argument key/value in args.
    """
    out = dict(args)
    changed = False

    # Check if a key in out is itself a JSON list/dict
    if "nodes" not in out:
        for k, v in list(out.items()):
            if isinstance(k, str) and (k.strip().startswith("[") or k.strip().startswith("{")):
                parsed = _parse_payload(k)
                if isinstance(parsed, list):
                    if parsed and isinstance(parsed[0], dict) and ("from" in parsed[0] or "to" in parsed[0]):
                        out["edges"] = out.get("edges") or parsed
                    else:
                        out["nodes"] = parsed
                    out.pop(k, None)
                    changed = True
                    break
                elif isinstance(parsed, dict):
                    out["nodes"] = out.get("nodes") or parsed.get("nodes")
                    out["edges"] = out.get("edges") or parsed.get("edges")
                    out["status_updates"] = out.get("status_updates") or parsed.get("status_updates")
                    out.pop(k, None)
                    changed = True
                    break
            if isinstance(v, str) and (v.strip().startswith("[") or v.strip().startswith("{")):
                parsed = _parse_payload(v)
                if isinstance(parsed, list):
                    if parsed and isinstance(parsed[0], dict) and ("from" in parsed[0] or "to" in parsed[0]):
                        out["edges"] = out.get("edges") or parsed
                    elif (k in ("nodes", "node_list", "hypotheses") or "nodes" not in out):
                        out["nodes"] = parsed
                    changed = True
                    break

    for key in ("nodes", "edges", "status_updates"):
        val = out.get(key)
        if not isinstance(val, str):
            continue
        parsed = _parse_payload(val)
        if isinstance(parsed, list):
            out[key] = parsed
        elif isinstance(parsed, dict):
            inner = parsed.get(key)
            out[key] = inner if isinstance(inner, list) else [parsed]
        else:
            # Unparseable string for a list field → drop it rather than ship a
            # malformed FC (empty/omitted is valid; a bare string is not).
            out.pop(key, None)
        changed = True
    return out, changed


def _extract_args_from_call_syntax(call_str: str) -> dict[str, Any]:
    """Parse python-syntax tool calls like research_commit(nodes=[...], edges=[...])."""
    try:
        clean = call_str.strip()
        if not clean.endswith(")"):
            clean += ")"
        tree = ast.parse(clean)
        if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Call):
            call_node = tree.body[0].value
            result: dict[str, Any] = {}
            for kw in call_node.keywords:
                try:
                    result[kw.arg] = ast.literal_eval(kw.value)
                except Exception:
                    pass
            return result
    except Exception:
        pass
    return {}


def normalize_em_hypothesis_commit(
    callback_context: CallbackContext, llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """after_model: stash H formulations; shrink fat research_commit to Hypothesis-only.

    Also coerces string-typed list args (nodes/edges/status_updates) so a
    research_commit FC is never dispatched with a JSON string where the tool
    expects an array.
    """
    content = getattr(llm_response, "content", None)
    parts = list(getattr(content, "parts", None) or [])
    if not parts:
        return None
    state = callback_context.state
    mutated = False
    new_parts: list[Any] = []
    for part in parts:
        fc = getattr(part, "function_call", None)
        name = getattr(fc, "name", None) if fc is not None else None
        if not name:
            new_parts.append(part)
            continue
        extracted_args = {}
        if name != "research_commit" and ("research_commit(" in name or name.startswith("research_commit")):
            extracted_args = _extract_args_from_call_syntax(name)
            name = "research_commit"
        if name != "research_commit":
            new_parts.append(part)
            continue
        args = dict(getattr(fc, "args", None) or {})
        if not args and extracted_args:
            args = extracted_args
            mutated = True
        args, coerced = _coerce_commit_arg_lists(args)
        shrunk, refs, changed = _shrink_commit_args(args)
        if refs:
            state[_PENDING_FC_KEY] = _merge_refs(state.get(_PENDING_FC_KEY), refs)
            ids = [r["hypothesis_id"] for r in state[_PENDING_FC_KEY]]
            audit(
                logger,
                f"EXPERIMENT_HYPOTHESES_FC_STASHED count={len(ids)}",
                stdout=f"EXPERIMENT_HYPOTHESES_FC_STASHED count={len(ids)} ids={ids}",
            )
        if (changed or extracted_args) and shrunk.get("nodes"):
            mutated = True
            new_parts.append(
                types.Part.from_function_call(name="research_commit", args=shrunk)
            )
            audit(
                logger,
                f"EXPERIMENT_HYPOTHESES_COMMIT_SHRUNK nodes={len(shrunk['nodes'])} "
                f"chars≈{_estimate_commit_chars(shrunk)}",
                stdout=f"EXPERIMENT_HYPOTHESES_COMMIT_SHRUNK nodes={len(shrunk['nodes'])}",
            )
        elif coerced or extracted_args:
            # Not shrunk (e.g. edges/status-only or non-Hypothesis nodes) but a
            # string list arg was repaired — ship the coerced, dispatchable form.
            mutated = True
            new_parts.append(
                types.Part.from_function_call(name="research_commit", args=args)
            )
            audit(
                logger,
                "EXPERIMENT_HYPOTHESES_COMMIT_ARGS_COERCED "
                f"keys={[k for k in ('nodes', 'edges', 'status_updates') if k in args]}",
            )
        else:
            new_parts.append(part)
    if not mutated:
        return None
    return LlmResponse(
        content=types.Content(role=getattr(content, "role", None) or "model", parts=new_parts)
    )


def capture_hypotheses_after_research_commit(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: Any,
) -> None:
    """after_tool: refresh pending refs from a successful research_commit."""
    if getattr(tool, "name", None) != "research_commit":
        return
    state = tool_context.state
    from_args = _refs_from_hypothesis_nodes(args if isinstance(args, dict) else {})
    from_resp = _refs_from_hypothesis_nodes(tool_response)
    # Prefer response committed nodes, then args.
    picked = from_resp or from_args
    if not picked:
        if isinstance(tool_response, dict) and tool_response.get("ok") is False:
            audit(
                logger,
                f"EXPERIMENT_HYPOTHESES_COMMIT_FAILED errors={tool_response.get('errors')}",
                level=logging.WARNING,
            )
        return
    state[_PENDING_FC_KEY] = _merge_refs(state.get(_PENDING_FC_KEY), picked)
    # Early authoritative write so Planner is safe even if after_agent is thin.
    _publish_refs(state, state[_PENDING_FC_KEY])
    ids = [r["hypothesis_id"] for r in state[_PENDING_FC_KEY]]
    audit(
        logger,
        f"EXPERIMENT_HYPOTHESES_AFTER_COMMIT count={len(ids)}",
        stdout=f"EXPERIMENT_HYPOTHESES_AFTER_COMMIT count={len(ids)} ids={ids}",
    )


def commit_experiment_hypotheses(callback_context: CallbackContext) -> None:
    """after_agent on HypothesesAgent: write authoritative hypothesis_refs for Planner."""
    state = callback_context.state
    raw = None
    for key in _OUTPUT_KEYS:
        if state.get(key) is not None:
            raw = state.get(key)
            break
    parsed = _parse_payload(raw)
    from_struct = extract_hypothesis_refs("", legacy_hypotheses=_as_ref_list(parsed))
    from_nodes = _refs_from_hypothesis_nodes(parsed)
    if not from_nodes and isinstance(raw, str):
        # Model sometimes dumps research_commit args into output_key text.
        from_nodes = _refs_from_hypothesis_nodes(_parse_payload(raw))
        if not from_nodes:
            # Brute-find a nodes=[...] / "nodes":[...] blob.
            m = re.search(r'"nodes"\s*:\s*(\[.*?\])\s*,\s*"edges"', raw, re.S)
            if m:
                from_nodes = _refs_from_hypothesis_nodes(_parse_payload(m.group(1)))
    from_text = _refs_from_text(raw)
    from_graph = _refs_from_research_graph(callback_context)
    from_fc = [
        r for r in (state.get(_PENDING_FC_KEY) or [])
        if isinstance(r, dict) and r.get("statement")
    ]
    # Fixed source order — first non-empty wins: graph nodes (authoritative,
    # written via research_commit) → stashed successful FC refs → structured
    # node payloads → prose extraction. No richest-wins length heuristic. When
    # every channel is empty, fall back to a single H1 built from the EM ask.
    refs = next(
        (c for c in (from_graph, from_fc, from_nodes, from_struct, from_text) if c),
        [],
    )
    if not refs:
        ask = (
            _resolve_em_ask(callback_context)
            or str(state.get("experiment_source_request") or "").strip()
            or "Computational experiment request."
        )
        ask = re.sub(r"\s+", " ", ask).strip()[:800]
        refs = [{"hypothesis_id": "H1", "statement": ask}]
        logger.info("EXPERIMENT_HYPOTHESES_FALLBACK count=1")
    # Normalize ids (unlike _merge_refs, keep pre-existing valid H\d+ ids).
    for i, ref in enumerate(refs, start=1):
        hid = str(ref.get("hypothesis_id") or "").strip().upper()
        if not re.fullmatch(r"H\d+", hid):
            ref["hypothesis_id"] = f"H{i}"
    _publish_refs(state, refs)
    ids = [r["hypothesis_id"] for r in refs]
    audit(
        logger,
        f"EXPERIMENT_HYPOTHESES_READY count={len(refs)}",
        stdout=f"EXPERIMENT_HYPOTHESES_READY count={len(refs)} ids={ids}",
    )


__all__ = [
    "bootstrap_research_question_if_empty",
    "capture_hypotheses_after_research_commit",
    "commit_experiment_hypotheses",
    "enforce_hypothesis_research_commit",
    "normalize_em_hypothesis_commit",
    "persist_experiment_em_request",
    "seed_hypotheses_from_em_request",
]
