import json
import os
import re
from difflib import SequenceMatcher, get_close_matches

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import logging
logger = logging.getLogger(__name__)

# ── Executor tool-match thresholds (the Coder↔Executor redirect mechanism) ───
# A retrieved tool counts as a real match only at/above _KEEP. When NOTHING
# clears _KEEP we look at the single best score:
#   * best >= _ABSTAIN  -> marginal salvage: take top-2 and proceed (cautious).
#   * best <  _ABSTAIN  -> ABSTAIN: leave the tool set empty and flag a no-match,
#                          so ExperimentAgent redirects to CoderAgent instead of
#                          "solving" the task with an unrelated tool (e.g. running
#                          a GAN trainer for a "train a transformer" task).


# State key carrying the executor's tool-match verdict for the redirect guard.
TOOL_MATCH_STATE_KEY = "executor_tool_match"

# Set after a successful fedot_tool capture so Fedot/Coder cannot re-enter.
FEDOT_DELIVERABLE_READY_KEY = "fedot_deliverable_ready"
FEDOT_DELIVERABLE_READY_TOKEN = "FEDOT_DELIVERABLE_READY"

RERANK_SCORED = "scored"                  # the model ranked the candidates
RERANK_RECOVERED = "recovered_local"      # ranked by the local cross-encoder instead
RERANK_PARSE_FAILED = "parse_failed"      # output_key payload unreadable
RERANK_EMPTY_RANKING = "empty_ranking"    # readable, but not one usable {index, score}
RERANK_NO_CANDIDATES = "no_candidates"    # retrieval accumulated nothing to rank

UNJUDGED_REASONS = frozenset({RERANK_PARSE_FAILED, RERANK_EMPTY_RANKING})


class RerankParseError(ValueError):
    """A reranker's ``output_key`` payload could not be read as a JSON object.

    Deliberately distinct from an empty ranking: see UNJUDGED_REASONS above.
    """


def _output_key_json(value: Any) -> Dict[str, Any]:
    """Coerce a reranker's ``output_key`` payload to a dict, or raise.

    With ``output_schema`` set, ADK validates the model's text and stores a dict.
    We deliberately drop the schema on the rerankers so ADK never sends OpenRouter
    a *strict* json_schema ``response_format`` (some providers stall on the
    grammar-constrained decode it implies), which leaves ``output_key`` holding
    raw text — already reduced to bare JSON by ``sanitize_json_output``.

    Raises:
        RerankParseError: the payload is missing, empty, not JSON, or not an object.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise RerankParseError(f"not valid JSON: {value[:300]!r}") from exc
        if isinstance(parsed, dict):
            return parsed
        raise RerankParseError(
            f"got a JSON {type(parsed).__name__}, expected an object"
        )
    raise RerankParseError(f"empty or missing payload ({type(value).__name__})")


def _score_map(entries: Any, *, cast: Callable[[Any], Any]) -> Dict[int, Any]:
    """Build ``{index: score}``, skipping anything malformed.

    Without ``output_schema`` nothing validates the model's shape any more, so a
    missing/!int ``index`` or a non-numeric ``score`` must degrade to "this tool
    went unscored" rather than raise inside an after_agent callback.
    """
    out: Dict[int, Any] = {}
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        try:
            out[index] = cast(entry.get("score"))
        except (TypeError, ValueError):
            continue
    return out

# ── ToolReranker shortlist (local cross-encoder pre-pass) ────────────────────
# Every entry in `accumulated_tools` carries the score of the retrieval query
# that FOUND it, and those queries differ per tool — so the scores share no
# scale. (Observed: a tool whose query happened to contain its own name scored
# 0.74 while the one the task actually needed scored 0.38 and sat 12th.)
# Truncating on them drops the right tool, so we re-score every candidate
# against ONE query — the task — with the local reranker service, and shortlist
# on that. Putting candidates on a common scale is exactly the job the LLM
# reranker does next; this just narrows what it has to read.
_RERANK_SHORTLIST_KEY = "reranker_candidates"
_RERANK_SHORTLIST_SIZE = int(os.getenv("RERANK_SHORTLIST_SIZE", "8"))
_SHORTLIST_SCORES_KEY = "shortlist_scores"


def _first_text(content) -> str:
    """First text part of a Content, or '' if there is none."""
    if content is None or not getattr(content, "parts", None):
        return ""
    for part in content.parts:
        if getattr(part, "text", None):
            return part.text
    return ""


async def shortlist_reranker_tools(callback_context: CallbackContext) -> None:
    """Narrow `accumulated_tools` to the top-K by local cross-encoder score.

    Also records every candidate's score in ``state['shortlist_scores']`` — the
    LLM reranker that runs next can come back unreadable, and those scores are
    then the cheapest way to still rank the candidates (see
    ``after_tool_reranker_agent``).

    Best-effort by construction: every early return leaves the full tool list in
    place, so an unreachable reranker service costs context, never correctness.
    """
    state = callback_context.state
    acc: List[Dict[str, Any]] = state.get('accumulated_tools') or []
    # Set first: the prompt reads this key, so it must be populated on every path.
    state[_RERANK_SHORTLIST_KEY] = acc
    state[_SHORTLIST_SCORES_KEY] = {}

    # Scored even when the list is short enough to need no truncation: the scores
    # themselves are the point now, not just the ordering. Costs one extra call
    # to the local cross-encoder on the common path, and buys a deterministic
    # recovery for every reranker failure below the shortlist threshold.
    if not acc:
        return None

    task = _first_text(getattr(callback_context, "user_content", None)).strip()
    if not task:
        logger.info(
            "shortlist: no task text on this invocation — passing all %d tools", len(acc)
        )
        return None

    documents = [
        f"{tool.get('tool', '')}: {tool.get('description', '')}" for tool in acc
    ]
    try:
        from rag_tools.retrieval import APIReranker

        ranked = await APIReranker().rerank_with_scores(
            task, documents, top_k=len(documents)
        )
    except Exception as exc:  # noqa: BLE001 — never fail the run over a shortlist
        logger.warning(
            "shortlist: reranker unavailable (%r) — passing all %d tools", exc, len(acc)
        )
        return None

    # APIReranker swallows its own HTTP errors and answers with all-zero scores.
    # That ordering is just the input order, so shortlisting on it would silently
    # cut arbitrary tools — treat it as "service down" instead.
    if not ranked or max(score for _, score in ranked) <= 0.0:
        logger.warning(
            "shortlist: no usable scores from the reranker — passing all %d tools", len(acc)
        )
        return None

    state[_SHORTLIST_SCORES_KEY] = {
        acc[i]["tool_index"]: float(score)
        for i, score in ranked
        if 0 <= i < len(acc) and isinstance(acc[i].get("tool_index"), int)
    }

    if len(acc) <= _RERANK_SHORTLIST_SIZE:
        return None

    shortlist = [acc[i] for i, _ in ranked[:_RERANK_SHORTLIST_SIZE] if 0 <= i < len(acc)]
    if not shortlist:
        return None

    logger.info(
        "shortlist: %d -> %d tools for the reranker (best=%s)",
        len(acc), len(shortlist), round(ranked[0][1], 3),
    )
    state[_RERANK_SHORTLIST_KEY] = shortlist
    return None


# Rendered into FedotAgent's prompt via `{fedot_candidates?}`.
_FEDOT_CANDIDATES_KEY = "fedot_candidates"


def inject_fedot_candidates(callback_context: CallbackContext) -> None:
    """before_agent for FedotAgent: show it the tools `fedot_tool` will get.

    Same expression the tool itself uses — the reranker's pick when there is one,
    the unfiltered candidate pool when the reranker's answer was unreadable — so
    the prompt and the actual MCP server set can never disagree about what is on
    the table.
    """
    state = callback_context.state
    state[_FEDOT_CANDIDATES_KEY] = (
        state.get('filtered_tools') or state.get('accumulated_tools') or []
    )
    return None


def before_tool_reranker_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    """Drop ToolRetriever/ToolReranker dumps from the next LLM request.

    ADK often prefixes sibling output as ``For context:[Agent] …`` (one part),
    so an exact ``== 'For context:'`` match never fired and the planner saw the
    full retrieve_tools novels — then invented tools absent from inventory.
    """
    kept: List[Any] = []
    for content in llm_request.contents or []:
        parts = list(getattr(content, "parts", None) or [])
        blob = "\n".join(str(getattr(p, "text", None) or "") for p in parts).lstrip()
        if blob.startswith("For context:"):
            continue
        if "[ToolRetrieverAgent]" in blob or "[ToolReranker]" in blob:
            continue
        kept.append(content)
    llm_request.contents = kept


# Set when ToolReranker scores were applied from after_model (skip after_agent).
_TOOL_RERANK_APPLIED_KEY = "_tool_rerank_applied"


def _score_items_from_reranked_state(raw: Any) -> List[Dict[str, Any]]:
    """Normalize ``reranked_tools`` state (dict / model / list) to score dicts."""
    if raw is None:
        return []
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if isinstance(raw, dict):
        tools = raw.get("tools") or []
    elif isinstance(raw, list):
        tools = raw
    else:
        return []
    out: List[Dict[str, Any]] = []
    for t in tools:
        if hasattr(t, "model_dump"):
            t = t.model_dump()
        if not isinstance(t, dict):
            continue
        try:
            out.append({"index": int(t["index"]), "score": float(t["score"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _llm_response_text(llm_response: LlmResponse, *, include_thoughts: bool) -> str:
    content = getattr(llm_response, "content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    if not parts:
        return ""
    chunks: List[str] = []
    for p in parts:
        text = getattr(p, "text", None)
        if not text:
            continue
        if not include_thoughts and getattr(p, "thought", False):
            continue
        chunks.append(text)
    return "".join(chunks)


def _score_items_from_llm_response(llm_response: LlmResponse) -> Optional[List[Dict[str, Any]]]:
    """Parse ToolRanking scores from the model response (not from output_key state).

    Prefer non-thought text (post-sanitize path); fall back to thoughts — GLM often
    parks the JSON ranking in a thought part while the logger shows the plain text empty.
    """
    from CoScientist.agents.callbacks.json_output import _extract_json, _normalize_ranking_payload

    for include_thoughts in (False, True):
        text = _llm_response_text(llm_response, include_thoughts=include_thoughts)
        if not text.strip():
            continue
        extracted = _extract_json(text)
        if extracted is None:
            continue
        items = _score_items_from_reranked_state(_normalize_ranking_payload(extracted))
        if items:
            return items
    return None


def _tool_rank_key(tool: Dict[str, Any]) -> int:
    # Prefer explicit tool_index; fall back to 1-based list position.
    raw = tool.get("tool_index", tool.get("index"))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def apply_tool_rerank_scores(
    state: Any,
    score_items: List[Dict[str, Any]],
    *,
    reason: str = RERANK_SCORED,
) -> None:
    """Filter ``accumulated_tools`` by rerank scores; set match verdict + filtered_tools.

    Records WHY the tool set came out as it did (see the RERANK_* constants), so
    the guards downstream can tell "judged, nothing relevant" (abstain to
    CoderAgent) apart from "we could not read the answer" (recover locally, or
    hand the unfiltered candidates to the FEDOT.MAS fallback).
    """
    from CoScientist.config import get_settings

    web_settings = get_settings().web
    keep_score = web_settings.executor_tool_keep_score
    abstain_score = web_settings.executor_tool_abstain_score
    rerank_map: Dict[int, float] = {int(t["index"]): float(t["score"]) for t in score_items}
    acc_tools: List[Dict[str, Any]] = list(state.get("accumulated_tools") or [])

    filtered_tools: List[Dict[str, Any]] = [
        tool for tool in acc_tools
        if rerank_map.get(_tool_rank_key(tool), 0) >= keep_score
    ]
    # Some models emit 0-based indices while tool_index is 1-based (or vice versa).
    if not filtered_tools and rerank_map and acc_tools:
        shifted = {
            tool for tool in acc_tools
            if rerank_map.get(_tool_rank_key(tool) - 1, 0) >= keep_score
            or rerank_map.get(_tool_rank_key(tool) + 1, 0) >= keep_score
        }
        if shifted:
            filtered_tools = list(shifted)

    best_score = max(rerank_map.values(), default=0.0)
    matched = bool(filtered_tools)

    if not filtered_tools and best_score >= abstain_score:
        # Marginal salvage: nothing cleared _KEEP but the best is not hopeless —
        # take top-2 and proceed cautiously (preserves the old behaviour here).
        top_ids = {
            idx for idx, _ in sorted(
                rerank_map.items(), key=lambda x: x[1], reverse=True
            )[:2]
        }
        filtered_tools = [t for t in acc_tools if _tool_rank_key(t) in top_ids]
        if not filtered_tools:
            filtered_tools = [
                t for t in acc_tools
                if (_tool_rank_key(t) - 1) in top_ids or (_tool_rank_key(t) + 1) in top_ids
            ]
        matched = bool(filtered_tools)
    # else (best < _ABSTAIN): ABSTAIN — leave filtered_tools empty so the
    # redirect guard on ExperimentAgent sends the task to CoderAgent instead of
    # running an unrelated tool. Only for a reason that actually judged them.

    # Record the verdict for the redirect guard / the orchestrator's critic /
    # the FEDOT hard-stop (a False "matched" here means a DIFFERENT capability
    # is being asked for, so fedot_artifact_handoff.should_hard_stop_fedot must
    # let this step through even if a prior deliverable is already captured).
    state[TOOL_MATCH_STATE_KEY] = {
        "matched": matched,
        "best_score": round(best_score, 3),
        "kept": len(filtered_tools),
        "reason": reason,
        "candidates": len(acc_tools),
    }
    state["filtered_tools"] = filtered_tools

    if reason in UNJUDGED_REASONS:
        # Keep the candidate pool: FedotAgent builds its MCP server set out of
        # `accumulated_tools`, and clearing it here is what would make an
        # unreadable reranker answer unrecoverable.
        logger.warning(
            "reranker verdict=%s — keeping %d candidate(s) for the FEDOT.MAS fallback",
            reason, len(acc_tools),
        )
        return

    state["accumulated_tools"] = []
    state[_RERANK_SHORTLIST_KEY] = []
    state[_SHORTLIST_SCORES_KEY] = {}
    state["retrieval_queries"] = []
    state[_TOOL_RERANK_APPLIED_KEY] = True
    # Drop process-global buffer so the next discovery pass starts clean.
    try:
        from CoScientist.tools.retrieval_tools import clear_session_accumulated_tools

        clear_session_accumulated_tools()
    except Exception:  # noqa: BLE001
        pass


def after_tool_reranker_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model: apply ToolReranker scores from the response body.

    ``output_key`` is often invisible in ``after_agent`` (ADK state-delta timing),
    which produced false ``best_score=0.0`` / empty ``filtered_tools``. Reading the
    ranking JSON here (after ``sanitize_json_output``) avoids that race.
    """
    if any(
        getattr(p, "function_call", None)
        for p in (getattr(getattr(llm_response, "content", None), "parts", None) or [])
    ):
        return None
    items = _score_items_from_llm_response(llm_response)
    if not items:
        logger.warning(
            "[%s] after_model tool rerank: no parseable scores in response",
            _agent_name(callback_context),
        )
        return None
    apply_tool_rerank_scores(callback_context.state, items, reason=RERANK_SCORED)
    return None


def after_tool_reranker_agent(
    callback_context: CallbackContext
) -> None:
    """Turn ToolReranker's output into ``filtered_tools`` + a reasoned verdict.

    Preferred path: ``sanitize_json_output`` / ``after_tool_reranker_model``
    apply ToolRanking scores when the JSON is parsed — avoids ADK output_key
    timing races. This after_agent hook is the upstream-compatible fallback
    and also recovers from an unreadable ranking via the local cross-encoder.
    """
    current_state = callback_context.state
    if current_state.get(_TOOL_RERANK_APPLIED_KEY):
        return None

    acc_tools: List[Dict[str, Any]] = current_state.get("accumulated_tools") or []
    rerank_map: Dict[int, float] = {}
    reason = RERANK_SCORED
    try:
        payload = _output_key_json(current_state.get("reranked_tools"))
    except RerankParseError as exc:
        logger.warning("reranker output unusable — %s", exc)
        reason = RERANK_PARSE_FAILED
    else:
        rerank_map = _score_map(payload.get("tools"), cast=float)
        if not rerank_map:
            # HEAD's looser parser (model_dump / list payloads).
            score_items = _score_items_from_reranked_state(current_state.get("reranked_tools"))
            if score_items:
                rerank_map = {int(t["index"]): float(t["score"]) for t in score_items}
            elif acc_tools:
                logger.warning(
                    "reranker returned no usable {index, score} pairs for %d candidate(s)",
                    len(acc_tools),
                )
                reason = RERANK_EMPTY_RANKING

    if not acc_tools:
        reason = RERANK_NO_CANDIDATES

    if reason in UNJUDGED_REASONS:
        recovered = {
            idx: score
            for idx, score in (current_state.get(_SHORTLIST_SCORES_KEY) or {}).items()
            if isinstance(idx, int) and isinstance(score, (int, float))
        }
        if recovered:
            rerank_map = {int(k): float(v) for k, v in recovered.items()}
            reason = RERANK_RECOVERED
            logger.info(
                "reranker unusable — ranked %d candidate(s) by local cross-encoder score",
                len(rerank_map),
            )

    score_items = [{"index": idx, "score": score} for idx, score in rerank_map.items()]
    apply_tool_rerank_scores(current_state, score_items, reason=reason)
    return None


def after_fullset_reranker_agent(
    callback_context: CallbackContext
) -> None:
    """Turn FullSetToolReranker's output into ``filtered_mcps``.

    Parsed the same defensive way as ToolReranker's: this used to lean on
    ``output_schema`` for its shape and index straight into the payload, so a
    string, a missing ``index`` or a non-list ``mcp_scores`` raised
    AttributeError/KeyError/TypeError out of an after_agent callback and killed
    the whole run. Deploying no web MCP is a fine outcome; crashing is not.
    """
    current_state = callback_context.state

    try:
        payload = _output_key_json(current_state.get('reranked_web_servers'))
        scores = payload.get('mcp_scores')
    except RerankParseError as exc:
        logger.warning("web-MCP reranker output unusable — %s; deploying none", exc)
        scores = None

    # Binary deploy score per MCP index — truthiness selects deploy. A model that
    # answers with the 0.0-1.0 floats the sibling reranker asks for still works:
    # bool() of a non-zero float is True.
    rerank_map: Dict[int, bool] = {
        idx: bool(score) for idx, score in _score_map(scores, cast=bool).items()
    }
    acc_mcps: List[Dict[str, Any]] = current_state.get('accumulated_web_mcps') or []

    filtered_mcps: List[Dict[str, Any]] = [
        mcp for mcp in acc_mcps
        if rerank_map.get(mcp.get('index', -1), False)
    ]

    callback_context.state['filtered_mcps'] = filtered_mcps
    callback_context.state['accumulated_web_mcps'] = []
    callback_context.state['retrieval_queries_mcp'] = []
    return

def before_get_task(callback_context: CallbackContext):
    """Ensure session has a task list and sanitize active_tasks for the target agent before it runs."""
    master = callback_context.state.get("_master_active_tasks")
    active = callback_context.state.get("active_tasks")

    if master is None and active is None:
        callback_context.state["active_tasks"] = []
        callback_context.state["_master_active_tasks"] = []
        return None

    if master is None:
        master = list(active) if isinstance(active, list) else []
        callback_context.state["_master_active_tasks"] = master

    current_agent = getattr(callback_context, "agent_name", None)
    from CoScientist.tools.task_tracker import clean_tasks_for_agent
    callback_context.state["active_tasks"] = clean_tasks_for_agent(master, current_agent)
    return None


def inject_graph_root(callback_context: CallbackContext):
    """Give the agent the session graph root and relevant global memory.

    state['graph_root'] (rendered via the {graph_root?} placeholder) gets:
      1. the system root — every agent + its capabilities + this session's trace;
      2. relevant facts accumulated by all completed local research sessions,
         retrieved for the current query so agents build on prior findings.
    Best-effort — the graph must never break a run. Yields nothing when the
    knowledge graph is switched off, so the placeholder stays empty instead of
    describing a feature the agent no longer has tools for.
    """
    try:
        from CoScientist.config import get_settings
        if not get_settings().web.knowledge_graph_enabled:
            callback_context.state['graph_root'] = ""
            return None
    except Exception:  # noqa: BLE001
        pass

    parts = []
    query = ""
    try:
        from CoScientist.graph.memory import get_knowledge_graph
        knowledge_graph = get_knowledge_graph(callback_context)
        parts.append(knowledge_graph.root_summary())
        goals = [h for h in knowledge_graph.history(limit=50) if h.get("kind") == "goal"]
        query = goals[-1]["label"] if goals else ""
    except Exception:  # noqa: BLE001
        pass
    try:
        from CoScientist.graph.memory_store import get_knowledge_memory
        knowledge_memory = get_knowledge_memory(callback_context)
        mem = knowledge_memory.relevant_summary(query)
        if mem:
            parts.append(mem)
    except Exception:  # noqa: BLE001
        pass
    callback_context.state['graph_root'] = "\n\n".join(p for p in parts if p)
    return None


# ── Dataset archive attached by the user in the web UI ────────────────────────
# The link is set on the session (web/app.py) and surfaces in the agent's
# instructions, so the agent KNOWS about the archive and passes it as
# `dataset_url` when the work it is doing actually needs that data. Nothing
# fills the argument in for it — sending the data is the agent's own decision.
DATASET_URL_STATE_KEY = "dataset_url"
DATASET_CONTEXT_STATE_KEY = "dataset_context"


def inject_dataset_context(callback_context: CallbackContext):
    """before_agent: render state['dataset_url'] into the prompt's dataset block.

    The instruction carries ``{dataset_context?}`` rather than the raw URL, so a
    session with no attached archive gets nothing at all instead of a heading
    describing data that does not exist.
    """
    url = str(callback_context.state.get(DATASET_URL_STATE_KEY) or "").strip()
    callback_context.state[DATASET_CONTEXT_STATE_KEY] = (
        "## Dataset attached to this session\n"
        f"The user attached a dataset archive (.zip): {url}\n"
        "When a step needs that data, send the link along as the `dataset_url`\n"
        "argument of the tool that fetches it (e.g. `run_sandbox_task`) — the\n"
        "sandbox is a separate machine and this is how the archive gets there.\n"
        "Judge for yourself whether a given call needs it, and never substitute\n"
        "a different dataset for the one the user attached.\n"
    ) if url else ""
    return None


# Recognisable token the orchestrator prompt / post-critic key off to re-route.
NO_MATCHING_TOOL_TOKEN = "NO_MATCHING_TOOL"


def rerank_fallback_active(state: Any) -> bool:
    """True when the executor's tool set must go to the FEDOT.MAS fallback.

    Three conditions, all required:
      * the reranker never JUDGED the candidates (see UNJUDGED_REASONS) — note
        this is already past the local cross-encoder recovery in
        ``after_tool_reranker_agent``, so it means both rankers came up empty;
      * retrieval did accumulate candidates, so there is something to hand over;
      * the fallback is switched on.

    Read by ``ExecutorSwitchAgent`` (which child runs) and by
    ``redirect_when_no_tools`` (abstain, or stand aside for the fallback), so the
    two can never disagree about what happens next.
    """
    verdict = (state.get(TOOL_MATCH_STATE_KEY) if state else None) or {}
    if verdict.get("reason") not in UNJUDGED_REASONS:
        return False
    if not (state.get("accumulated_tools") or []):
        return False
    try:
        from CoScientist.config import get_settings
        return bool(get_settings().web.fedot_fallback_enabled)
    except Exception:  # noqa: BLE001 — a settings failure must not switch it ON
        logger.warning("fedot fallback: settings unreadable — treating as disabled")
        return False


def redirect_when_no_tools(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """before_agent_callback for ExperimentAgent: abstain → redirect to CoderAgent.

    By the time ExperimentAgent runs, the tool-prep pipeline has set
    ``executor_tool_match``. If no retrieved tool matched the task (and no web
    MCP was deployed), running FEDOT would just pick the nearest-but-wrong tool
    (the "train a GAN for a transformer task" failure). Instead we short-circuit
    the agent and return a structured redirect: the message is the tool
    pipeline's final answer, so TaskExecutorAgent (the router that called it)
    re-issues the step to CoderAgent without it ever reaching the orchestrator.
    """
    state = callback_context.state
    verdict = state.get(TOOL_MATCH_STATE_KEY) or {}
    has_local = bool(state.get("filtered_tools"))
    has_web = bool(state.get("filtered_mcps"))

    # Only abstain on an explicit no-match verdict with nothing usable.
    if verdict.get("matched") or has_local or has_web:
        return None

    if rerank_fallback_active(state):
        logger.info(
            "[%s] no tools, but the reranker never judged them (%s) — the FEDOT.MAS "
            "fallback owns this task, not CoderAgent",
            _agent_name(callback_context), verdict.get("reason"),
        )
        return None

    best = verdict.get("best_score", 0.0)
    message = (
        f"{NO_MATCHING_TOOL_TOKEN}: No ready-made MCP tool matches this task "
        f"(best tool relevance was {best}, below the bar). This looks like custom "
        "engineering — a specific architecture, a named repository/example code, "
        "or writing and running code — which no existing tool covers. Do NOT "
        "treat a tool that shares only the verb (e.g. 'train a GAN' for a 'train a "
        "transformer' request) as a match. Re-issue this step to CoderAgent — do "
        "not run this tool pipeline again for it."
    )
    logger.info("[ExperimentAgent] abstaining (no matching tool, best=%s) → CoderAgent", best)
    state["fedot_results"] = message
    return types.Content(role="model", parts=[types.Part(text=message)])


def _artifact_urls(artifacts: Any) -> List[str]:
    urls: List[str] = []
    for art in artifacts or []:
        if isinstance(art, dict):
            for key in ("results_presigned_url", "url", "presigned_url"):
                val = art.get(key)
                if val:
                    urls.append(str(val))
                    break
        elif isinstance(art, str) and art.strip():
            urls.append(art.strip())
    return urls


def refuse_when_fedot_deliverable(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """before_agent: hard-stop route agents once the ask's deliverable is done.

    Soft prompt STOP alone does not prevent ADK re-entry after a successful
    compute/MCP capture. Uses ``should_hard_stop_fedot`` (conservative predicate
    shared with the FEDOT tool path): it does NOT fire when the current step's
    tool-match verdict abstained or names a new tool — e.g. gen→dock handoff or
    a distinct Coder step — so retries for *new* work still run.

    Also useful under Experiment Module retries: re-entering Fedot/Coder for the
    same already-captured tool set is refused; ``retry_task`` / new attempt with
    a different tool match still proceeds.
    """
    from CoScientist.tools.fedot_artifact_handoff import should_hard_stop_fedot

    state = callback_context.state
    if not should_hard_stop_fedot(state):
        return None
    urls = _artifact_urls(state.get("fedot_artifacts"))
    if not urls:
        # EM managed captures may live outside fedot_artifacts.
        manifest = state.get("experiment_artifacts_manifest") or []
        if isinstance(manifest, list):
            for item in manifest:
                if isinstance(item, dict):
                    for key in ("presigned_url", "url", "resolved_url"):
                        val = item.get(key)
                        if isinstance(val, str) and val.strip():
                            urls.append(val.strip())
    body = "\n".join(urls) if urls else "(see session artifact state)"
    message = (
        f"{FEDOT_DELIVERABLE_READY_TOKEN}: S3/artifacts already captured. "
        "Do NOT call fedot_tool, CoderAgent, or retrieve again. "
        "Hand these URLs to the orchestrator for Final Response:\n"
        f"{body}"
    )
    logger.info(
        "[%s] refusing re-entry — deliverable already ready (%s url(s))",
        _agent_name(callback_context),
        len(urls),
    )
    state["fedot_results"] = message
    return types.Content(role="model", parts=[types.Part(text=message)])



# ResearchAgent as AgentTool dies if we replace a function_call with model text:
# that text is the sub-agent's final answer. Rewrite known aliases in-place so
# the real tool runs and the agent gets another turn.
_SHELL_PROGRAMS = frozenset({
    "awk", "cat", "cd", "chmod", "cp", "echo", "find", "git", "grep", "head",
    "ls", "mkdir", "mv", "pwd", "rm", "sed", "tail", "touch", "wc",
})
_TOOL_ALIASES: Dict[str, Sequence[str]] = {
    "download_papers": ("download_papers_from_search",),
    "explore_literature": (
        "search_papers", "explore_chemistry_database", "tavily_search",
    ),
    "explore_papers": ("explore_my_papers", "search_papers"),
    "explore_scientific_database": (
        "search_papers", "explore_chemistry_database", "tavily_search",
    ),
    "pubmed_search": ("search_papers", "tavily_search"),
    "search_literature": ("search_papers", "tavily_search"),
    "search_scientific_database": ("search_papers", "tavily_search"),
    "search_scientific_papers": ("search_papers",),
}
_QUERY_KEYS = ("query", "question", "task", "request", "q")
_QUERY_TARGETS = frozenset({
    "download_papers_from_search", "search_papers", "tavily_search",
})
_QUESTION_TARGETS = frozenset({
    "explore_chemistry_database", "explore_my_papers",
})


def _function_call_args(fc: Any) -> Dict[str, Any]:
    raw = getattr(fc, "args", None) or {}
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    return dict(raw) if isinstance(raw, dict) else {}


def _remap_hallucinated_args(target: str, args: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(args)
    if target in _QUERY_TARGETS and "query" not in out:
        for key in _QUERY_KEYS:
            if key in out and key != "query":
                out["query"] = out.pop(key)
                break
    if target in _QUESTION_TARGETS and "question" not in out:
        for key in _QUERY_KEYS:
            if key in out and key != "question":
                out["question"] = out.pop(key)
                break
    return out


def resolve_hallucinated_tool(name: str, valid: Iterable[str]) -> Optional[str]:
    """Map a hallucinated tool name onto exactly one real tool, or None."""
    valid_set = {item for item in valid if item}
    if not name or name in valid_set:
        return None
    for candidate in _TOOL_ALIASES.get(name, ()):
        if candidate in valid_set:
            return candidate
    if name.lower() in _SHELL_PROGRAMS:
        return None
    close = get_close_matches(name, valid_set, n=2, cutoff=0.78)
    if len(close) == 1:
        return close[0]
    if len(close) >= 2:
        first = SequenceMatcher(None, name, close[0]).ratio()
        second = SequenceMatcher(None, name, close[1]).ratio()
        if first - second >= 0.08:
            return close[0]
    return None


def make_unknown_tool_guard(valid_names: Iterable[str]) -> Callable:
    """Build an after_model_callback that intercepts hallucinated tool calls.

    When the LLM emits a function call whose name is NOT a real tool of the
    agent, ADK raises and kills the whole run before any tool/agent callback can
    react (e.g. CoderAgent calling `find` directly instead of
    `execute_bash("find ...")`).

    Prefer rewriting a known alias (or a uniquely close name) into a real
    function_call so AgentTool sub-agents keep a turn. Only unmatched names
    become a corrective text reply.
    """
    valid = {name for name in valid_names if name}

    def guard(
        callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        content = getattr(llm_response, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            return None
        rewritten: List[Any] = []
        unresolved: List[str] = []
        changed = False
        for part in parts:
            fc = getattr(part, "function_call", None)
            name = getattr(fc, "name", None) if fc is not None else None
            if not name or name in valid:
                rewritten.append(part)
                continue
            alias = resolve_hallucinated_tool(name, valid)
            if alias:
                logger.warning(
                    "[%s] rewriting hallucinated tool %s → %s",
                    _agent_name(callback_context),
                    name,
                    alias,
                )
                rewritten.append(
                    types.Part.from_function_call(
                        name=alias,
                        args=_remap_hallucinated_args(alias, _function_call_args(fc)),
                    )
                )
                changed = True
            else:
                unresolved.append(name)
                rewritten.append(part)
        if unresolved:
            bad = ", ".join(sorted(set(unresolved)))
            allowed = ", ".join(sorted(valid))
            logger.warning(
                "[%s] hallucinated tool call(s): %s",
                _agent_name(callback_context),
                bad,
            )
            msg = (
                f"The tool(s) `{bad}` do not exist — they are not in your tool list. "
                f"Your only tools are: {allowed}. Shell programs (find, grep, ls, cat, "
                "wc, git, sed, awk, …) are NOT tools — run them INSIDE execute_bash, "
                "e.g. execute_bash(command=\"find . -name '*.py' | wc -l\"). "
                "Re-issue your request calling ONLY a tool from the list above."
            )
            return LlmResponse(
                content=types.Content(role="model", parts=[types.Part(text=msg)])
            )
        if changed:
            return LlmResponse(
                content=types.Content(role="model", parts=rewritten)
            )
        return None

    return guard


def make_plan_registration_guard() -> Callable:
    """Build an after_model_callback that ends the planner's turn once the plan
    is registered, instead of letting it re-register forever.

    `create_plan` NORMALISES what it is given: it renumbers ids, drops
    OrchestratorAgent tasks and MERGES consecutive tasks with the same executor
    assignee. The planner prompt tells the model to check the returned plan — so
    when the plan it gets back is not the one it sent, the model registers again
    to "fix" it, gets the same normalisation, and loops. It cannot win: the
    difference it is chasing is the tracker's own doing.

    That loop is reachable on its own, but the plan critic makes it likely: ask
    for "a separate analysis step" next to an existing executor step and the
    tracker merges the two back together on every attempt.

    A registered plan is exactly ``state['active_tasks']`` being non-empty —
    SessionAgent clears it before each planner run, so the flag is per-run and
    a retry after a REJECTED create_plan (which registers nothing) still works.
    """

    def guard(
        callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        tasks = callback_context.state.get("active_tasks")
        if not tasks:
            return None  # nothing registered yet — the first call must go through
        content = getattr(llm_response, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            return None
        if not any(
            getattr(getattr(p, "function_call", None), "name", None) == "create_plan"
            for p in parts
        ):
            return None

        logger.warning(
            "[%s] create_plan called again after %d task(s) were registered — "
            "ending the turn instead of re-registering",
            _agent_name(callback_context), len(tasks),
        )
        roster = "\n".join(
            f"{i}. {t.get('title')} → {t.get('assignee')}"
            for i, t in enumerate(tasks, 1)
        )
        return LlmResponse(
            content=types.Content(role="model", parts=[types.Part(
                text=f"The plan is registered and stands as follows:\n\n{roster}"
            )])
        )

    return guard


def _agent_name(callback_context: CallbackContext) -> str:
    return getattr(callback_context, "agent_name", None) or "agent"


def print_research_agent_tool_call(
    tool: BaseTool,
    args: Dict[str, Any],
    tool_context: ToolContext,
    tool_response: Any,
) -> None:
    """Print tool calls and persist downloaded S3 keys to session state."""
    try:
        logger.info(f"\n[ResearchAgent tool called] {tool.name}")
        logger.info(f"[ResearchAgent tool args] {args}")
    except Exception as e:
        logger.error(f"Error in print_research_agent_tool_call: {e}")

    if tool.name != "download_papers_from_search":
        return

    try:
        papers = (tool_response or {}).get("metadata", {}).get("papers", [])
        new_keys = [p["s3_key"] for p in papers if p.get("s3_key")]
        if not new_keys:
            return
        existing: List[str] = tool_context.state.get("downloaded_paper_s3_keys", [])
        merged_keys: List[str] = existing + [k for k in new_keys if k not in existing]
        tool_context.state["downloaded_paper_s3_keys"] = merged_keys
        logger.info(
            "Registered %d downloaded paper S3 key(s) in session state.",
            len(merged_keys),
        )
    except Exception as e:
        logger.error("Failed to persist downloaded paper S3 keys: %s", e)

def capture_mcp_artifacts(
    tool: BaseTool,
    args: Dict[str, Any],
    tool_context: ToolContext,
    tool_response: Any,
) -> None:
    """after_tool: stash figure/table artifact URLs a tool returned into
    ``state['mcp_artifacts']`` so the graph-first Result Aggregator's
    ``format_results`` downloads them into the report folder.

    Many MCP tools (e.g. the tox-antitargets suite) render a plot server-side and
    return a presigned URL to it (commonly ``metadata.figure.artifact``). That link
    only lives in the tool result; with the aggregator running ``include_contents:
    none`` it never reaches the report unless captured here — at the AGENT's own
    tool boundary, which fires for sub-agent (AgentTool) MCP calls where an
    App-level plugin does not.
    """
    try:
        from CoScientist.reporting.collect import find_artifact_urls
        urls = find_artifact_urls(tool_response)
    except Exception:  # noqa: BLE001 — capture must never break a tool call
        return
    if not urls:
        return
    try:
        existing = list(tool_context.state.get("mcp_artifacts") or [])
        seen = {a.get("url") for a in existing if isinstance(a, dict)}
        name = getattr(tool, "name", None)
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            existing.append({"url": u, "tool": name})
        tool_context.state["mcp_artifacts"] = existing
        logger.info("capture_mcp_artifacts: %s → +%d artifact URL(s) (%d total)",
                    name, len(urls), len(existing))
    except Exception as e:  # noqa: BLE001
        logger.error("capture_mcp_artifacts failed: %s", e)


class SearchLimiter:

    _STATE_KEY = "_search_limiter_count"

    def __init__(self, max_searches: int = 5):
        self.max_searches = max_searches

    def reset_search_budget(self, callback_context: CallbackContext) -> None:
        """before_agent: cap is per ResearchAgent invocation, not per session."""
        try:
            callback_context.state[self._STATE_KEY] = 0
        except Exception:
            return None
        return None

    @staticmethod
    def is_counted_search(name: str) -> bool:
        """Count OpenAlex / web search only — not downloads or research_*.

        Token ``search`` used to match ``download_papers_from_search`` and eat
        the whole ResearchAgent budget after one 429, so Tavily never ran.
        """
        tokens = [tok for tok in re.split(r"[^a-z]+", (name or "").lower()) if tok]
        if "search" not in tokens:
            return False
        if "download" in tokens:
            return False
        if tokens[:1] == ["research"]:
            return False
        return True

    @staticmethod
    def is_failed_search_response(tool_response: Any) -> bool:
        if tool_response is None:
            return True
        blob = tool_response
        if isinstance(tool_response, dict):
            if tool_response.get("isError") is True:
                return True
            blob = tool_response
        text = str(blob).lower()
        markers = (
            "error calling tool",
            "too many requests",
            "429",
            "sslerror",
            "max retries exceeded",
        )
        return any(marker in text for marker in markers)

    def limit_searches(self, tool, args: dict, tool_context: ToolContext) -> Optional[dict]:
        if not self.is_counted_search(getattr(tool, "name", "")):
            return None
        count = int(tool_context.state.get(self._STATE_KEY, 0) or 0)
        if count >= self.max_searches:
            return {
                "result": (
                    f"Search limit reached ({self.max_searches} searches allowed). "
                    "You MUST now synthesize your answer from the results you already have. "
                    "Do NOT attempt any more searches."
                )
            }
        return None

    def record_search_result(
        self,
        tool,
        args: dict,
        tool_context: ToolContext,
        tool_response: Any,
    ) -> None:
        if not self.is_counted_search(getattr(tool, "name", "")):
            return None
        if self.is_failed_search_response(tool_response):
            logger.info(
                "search failed, not counting toward limiter: %s",
                getattr(tool, "name", ""),
            )
            return None
        count = int(tool_context.state.get(self._STATE_KEY, 0) or 0) + 1
        tool_context.state[self._STATE_KEY] = count
        return None

def inject_original_query(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> None:
    """Replace the last message in llm_request.contents with the original query."""

    original = getattr(callback_context, "user_content", None)
    if original is None or not original.parts:
        return

    # Extract original text
    original_text = None
    for part in original.parts:
        if part.text:
            original_text = part.text
            break
    if not original_text:
        return

    # Replace the last user-role content in llm_request.contents
    for i, content in enumerate(llm_request.contents):
        if getattr(content, "role", "user") == "user" and getattr(content, "parts", None):
            llm_request.contents[i] = types.Content(
                role="user",
                parts=[types.Part(text=original_text)],
            )
            logger.info(
                "[OrchestratorAgent] Replaced planner messages with original user query"
            )
            return