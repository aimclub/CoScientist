import json
import os
import re

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from typing import Any, Callable, Dict, Iterable, List, Optional

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
    """Skips ToolRetriever context"""

    new_contents = []

    for content in llm_request.contents:
        # A content may have empty parts or a non-text first part (function
        # call/response) — guard before reading .text.
        first_text = content.parts[0].text if content.parts else None
        if first_text == 'For context:':
            continue
        new_contents.append(content)

    llm_request.contents = new_contents
    return


def after_tool_reranker_agent(
    callback_context: CallbackContext
) -> None:
    """Turn ToolReranker's output into ``filtered_tools`` + a reasoned verdict.

    Records WHY the tool set came out as it did (see the RERANK_* constants), so
    the guards downstream can tell "judged, nothing relevant" (abstain to
    CoderAgent) apart from "we could not read the answer" (recover locally, or
    hand the unfiltered candidates to the FEDOT.MAS fallback). Conflating the two
    is how a single malformed JSON reply silently throws away tools that
    retrieval found correctly.
    """
    from CoScientist.config import get_settings
    web_settings = get_settings().web
    keep_score = web_settings.executor_tool_keep_score
    abstain_score = web_settings.executor_tool_abstain_score

    current_state = callback_context.state
    acc_tools: List[Dict[str, Any]] = current_state.get('accumulated_tools') or []

    rerank_map: Dict[int, float] = {}
    reason = RERANK_SCORED
    try:
        payload = _output_key_json(current_state.get('reranked_tools'))
    except RerankParseError as exc:
        logger.warning("reranker output unusable — %s", exc)
        reason = RERANK_PARSE_FAILED
    else:
        rerank_map = _score_map(payload.get('tools'), cast=float)
        if not rerank_map and acc_tools:
            # Readable JSON, no usable pairs: a renamed key ("tool_index" for
            # "index" — the prompt names both), a stringified index, a score that
            # is not a number. Indistinguishable from "all irrelevant" by score
            # alone, which is exactly why it needs its own reason.
            logger.warning(
                "reranker returned no usable {index, score} pairs for %d candidate(s)",
                len(acc_tools),
            )
            reason = RERANK_EMPTY_RANKING

    if not acc_tools:
        reason = RERANK_NO_CANDIDATES

    if reason in UNJUDGED_REASONS:
        # Recovery layer 1 — free and deterministic: the cross-encoder already
        # scored every candidate against this same task in
        # `shortlist_reranker_tools`, on one scale. Prefer it over any further
        # LLM work. Only when it has nothing to say do we stay "unjudged" and let
        # the FEDOT.MAS fallback take the whole candidate set.
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

    filtered_tools: List[Dict[str, Any]] = [
        tool for tool in acc_tools
        if rerank_map.get(tool.get('tool_index', -1), 0) >= keep_score
    ]

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
        filtered_tools = [t for t in acc_tools if t.get('tool_index', -1) in top_ids]
        matched = bool(filtered_tools)
    # else (best < _ABSTAIN): ABSTAIN — leave filtered_tools empty so the
    # redirect guard on ExperimentAgent sends the task to CoderAgent instead of
    # running an unrelated tool. Only for a reason that actually judged them.

    # Record the verdict for the redirect guard / the orchestrator's critic.
    callback_context.state[TOOL_MATCH_STATE_KEY] = {
        "matched": matched,
        "best_score": round(best_score, 3),
        "kept": len(filtered_tools),
        "reason": reason,
        "candidates": len(acc_tools),
    }
    callback_context.state['filtered_tools'] = filtered_tools

    if reason in UNJUDGED_REASONS:
        # Keep the candidate pool: FedotAgent builds its MCP server set out of
        # `accumulated_tools`, and clearing it here is what would make an
        # unreadable reranker answer unrecoverable.
        logger.warning(
            "reranker verdict=%s — keeping %d candidate(s) for the FEDOT.MAS fallback",
            reason, len(acc_tools),
        )
        return

    callback_context.state['accumulated_tools'] = []
    callback_context.state[_RERANK_SHORTLIST_KEY] = []
    callback_context.state[_SHORTLIST_SCORES_KEY] = {}
    callback_context.state['retrieval_queries'] = []
    return


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
    """Give the agent the session graph root: every agent, its capabilities and
    this session's trace, rendered via the {graph_root?} placeholder.

    Best-effort — the graph must never break a run. Yields nothing when the
    execution graph is switched off, so the placeholder stays empty instead of
    describing a feature the agent no longer has tools for.

    What earlier sessions established is no longer injected here. It is served by
    the research graph's cross-run index, which a run consults deliberately
    rather than receiving as ambient context.
    """
    try:
        from CoScientist.config import get_settings
        if not get_settings().web.knowledge_graph_enabled:
            callback_context.state['graph_root'] = ""
            return None
    except Exception:  # noqa: BLE001
        pass

    summary = ""
    try:
        from CoScientist.graph.memory import get_knowledge_graph
        summary = get_knowledge_graph(callback_context).root_summary()
    except Exception:  # noqa: BLE001
        pass
    callback_context.state['graph_root'] = summary
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


def make_unknown_tool_guard(valid_names: Iterable[str]) -> Callable:
    """Build an after_model_callback that intercepts hallucinated tool calls.

    When the LLM emits a function call whose name is NOT a real tool of the
    agent, ADK raises and kills the whole run before any tool/agent callback can
    react (e.g. CoderAgent calling `find` directly instead of
    `execute_bash("find ...")`). This guard catches that in the model response
    and replaces it with a corrective message, so the agent re-plans on its next
    turn instead of crashing the orchestration.
    """
    valid = set(valid_names)

    def guard(
        callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        content = getattr(llm_response, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            return None
        unknown = []
        for p in parts:
            fc = getattr(p, "function_call", None)
            name = getattr(fc, "name", None) if fc is not None else None
            if name and name not in valid:
                unknown.append(name)
        if not unknown:
            return None
        bad = ", ".join(sorted(set(unknown)))
        allowed = ", ".join(sorted(valid))
        logger.warning("[%s] hallucinated tool call(s): %s", _agent_name(callback_context), bad)
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

    def limit_searches(self, tool, args: dict, tool_context: ToolContext) -> Optional[dict]:
        # Match "search" as a whole name token, NOT as a substring: otherwise
        # "re-search" tools (research_commit, research_context_slice, …) are
        # wrongly counted as searches and blocked once the cap is hit, which
        # stops agents recording anything in the research graph.
        tokens = re.split(r"[^a-z]+", tool.name.lower())
        if "search" not in tokens:
            return None

        count = tool_context.state.get(self._STATE_KEY, 0)
        count += 1
        tool_context.state[self._STATE_KEY] = count

        if count > self.max_searches:
            return {
                "result": (
                    f"Search limit reached ({self.max_searches} searches allowed). "
                    "You MUST now synthesize your answer from the results you already have. "
                    "Do NOT attempt any more searches."
                )
            }
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

# ── the plan, mirrored into the research graph ───────────────────────────────
# The middle layer of the story — what each hypothesis is actually checked BY —
# existed only if a model remembered to commit it. In a run whose agents all
# skipped research_commit the graph drew a question with nothing underneath, and
# no amount of work on the viewer can draw a method that was never recorded. A
# registered plan is already a deterministic, ordered list of steps: deriving
# one planned VerificationMethod per step costs no LLM call and cannot be
# forgotten. Written as "plan-mirror" rather than as an agent, so a reader can
# see at a glance that no model chose these.

#: normalized task title -> the PlanStep id created for it, under the study
#: generation it was written against.
_VM_BY_TASK_KEY = "_research_vm_by_task"
_PLAN_SOURCE = "plan-mirror"


def _task_key(task: Dict[str, Any]) -> str:
    return " ".join(str(task.get("title") or "").split()).lower()[:120]


#: Node types that can be what a plan step turned into.
_REALISING_TYPES = ("VerificationMethod", "Hypothesis", "Evidence", "Conclusion")

#: The tracker's status words, lowercased into the PlanStep vocabulary. Anything
#: unrecognised is a step nobody has started.
_STEP_STATUS = {"todo": "todo", "in_progress": "in_progress", "done": "done",
                "blocked": "blocked", "cancelled": "blocked", "failed": "blocked"}


def _step_status(task: Dict[str, Any]) -> str:
    return _STEP_STATUS.get(str(task.get("status") or "").strip().lower(), "todo")


def _step_attrs(task: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in {
        "title": task.get("title", ""),
        "description": task.get("description", ""),
        "plan_task_id": str(task.get("id") or ""),
        "assignee": task.get("assignee", ""),
        "notes": task.get("notes", ""),
        # What the plan already knows about the HOW. The planner can read the
        # tool list, so this is the one part of a method it can answer in
        # advance, and whoever writes the method starts from it instead of
        # guessing.
        "tools": ", ".join(str(t) for t in (task.get("tools") or []) if t),
    }.items() if v}


def _study_generation(graph: Any) -> str:
    """Identity of the LIVE study, so a memo cannot outlive its graph.

    `research_init` archives the study and replaces the graph with an empty one,
    and `_next_id` scans only the live graph — so ids restart at PS1. The memo
    of "which step did I mirror for which task" lives in ADK session state,
    which survives that reset, so after a switch the old ids matched the new
    study's fresh ones and the mirror both skipped tasks it had never mirrored
    HERE and wrote an edge to an id that now names somebody else's node.
    Checking that an id merely resolves cannot catch this; only identity can.
    """
    try:
        full = graph.full()
        # `research_id`, not the timestamp. `init_research` mints it with a
        # uuid, so two studies started in quick succession differ — whereas
        # `created_at` is a wall clock that ticks every ~15 ms on Windows, so a
        # fast re-init produced the SAME key, the memo was kept, and the mirror
        # decided the new study's steps had already been drawn. It surfaced as
        # an order-dependent test failure; in a run it would have silently left
        # the new study with no plan column at all.
        return f"{full.get('research_id')}:{full.get('root_id')}"
    except Exception:  # noqa: BLE001
        return ""


def _realises_edges(graph: Any) -> List[Dict[str, Any]]:
    """`realises` edges for work that names the plan step it carried out.

    A method, hypothesis or conclusion whose `plan_task_id` matches a step is
    what became of that step, and this edge is the one thing that lets a reader
    cross between the intention and the record. Derived from an attribute its
    writer set — not guessed from wording — and only ever added, because a step
    can be realised by several things and none of them stops being true.
    """
    try:
        full = graph.full()
        nodes = full.get("nodes") or []
        already = {(e.get("from"), e.get("to")) for e in (full.get("edges") or [])
                   if e.get("type") == "realises"}
    except Exception:  # noqa: BLE001
        return []
    # BOTH sides come from the graph, not from the task list. The work that
    # carries out a step is written turns after the plan was registered, and by
    # then the task list is empty — reading the mapping from it made the
    # linking unreachable exactly when it was needed.
    step_by_task = {str((n.get("attrs") or {}).get("plan_task_id") or ""): n.get("id")
                    for n in nodes if n.get("type") == "PlanStep"}
    step_by_task.pop("", None)
    if not step_by_task:
        return []
    out = []
    for n in nodes:
        if n.get("type") not in _REALISING_TYPES:
            continue
        task_id = str((n.get("attrs") or {}).get("plan_task_id") or "")
        step = step_by_task.get(task_id)
        if not step or (n.get("id"), step) in already:
            continue
        out.append({"type": "realises", "from": n.get("id"), "to": step})
    return out


def sync_plan_to_research_graph(tasks: Iterable[Dict[str, Any]], graph: Any,
                                state: Any, question: str = "") -> Optional[Any]:
    """Mirror the registered plan into the graph as one PlanStep per step.

    It used to write the plan as `VerificationMethod` nodes, and that was the
    most misleading thing in the graph a scientist reads. A step is an
    INTENTION — what to do, in what order, by whom. A method answers a
    different question: by what MEANS was this established, and against which
    bar. Conflated, the planner's task list appeared as "methods" hanging off
    the research question, carrying no instrument, indistinguishable from a
    method an agent had designed for a hypothesis — and the reader could not
    tell the plan from the record.

    They are separate nodes now, joined by `realises`, so the graph shows both
    the intention and what was made of it. Methods are written by the agents
    that own them; when a hypothesis has none, the graph says so through
    `queries.hypotheses_without_methods` instead of filling the gap with the
    plan.

    Idempotent: a task already mirrored is remembered in session state, keyed to
    the study generation, so a re-plan adds only what is new; a step whose
    tracker status has moved is advanced in place.
    """
    tasks = [t for t in (tasks or []) if isinstance(t, dict)]
    root = graph.root_id()
    if not root:
        seed = question or (tasks[0].get("title", "") if tasks else "")
        if not seed:
            return None
        root = (graph.ensure_root(seed) or {}).get("root_id")
    if not root:
        return None
    # Deliberately NOT `if not tasks: return None`. The `realises` links are a
    # fact about the GRAPH, not about the plan: the work that carries out a step
    # is written after the plan is registered, and by then the task list this is
    # called with can be empty. Gating on it made the linking unreachable.
    gen = _study_generation(graph)
    try:
        memo = dict(state.get(_VM_BY_TASK_KEY) or {})
    except Exception:  # noqa: BLE001 — a stateless caller still gets the mirror
        memo = {}
    seen = dict(memo.get("ids") or {}) if memo.get("gen") == gen else {}
    live = _live_statuses(graph)

    creates, keys, updates = [], [], []
    for i, task in enumerate(tasks):
        key = _task_key(task)
        if not key:
            continue
        if key in seen:
            step, want = seen[key], _step_status(task)
            if live.get(step) not in (None, want):
                updates.append({"id": step, "status": want,
                                "reason": "the plan moved this step to " + want})
            continue
        keys.append(key)
        creates.append({"type": "PlanStep", "ref": f"ps{i}",
                        "status": _step_status(task), "attrs": _step_attrs(task)})

    result = None
    if creates or updates:
        result = graph.commit(source=_PLAN_SOURCE, nodes=creates,
                              status_updates=updates, partial_edges=True)
        if not result.ok:
            logger.warning("plan -> research graph refused: %s", result.errors[:3])
            return result
        for key, echo in zip(keys, result.committed.get("nodes", [])):
            seen[key] = echo.get("id")
        try:
            state[_VM_BY_TASK_KEY] = {"gen": gen, "ids": seen}
        except Exception:  # noqa: BLE001
            pass

    # Read after the commit above, so a step created just now is linkable in
    # this same call rather than a turn later.
    edges = _realises_edges(graph)
    if edges:
        linked = graph.commit(source=_PLAN_SOURCE, edges=edges, partial_edges=True)
        if not linked.ok:
            logger.warning("plan links refused: %s", linked.errors[:3])
        result = linked if result is None else result
    return result


def _live_statuses(graph: Any) -> Dict[str, str]:
    """id -> status for the steps already in the graph."""
    try:
        return {n.get("id"): n.get("status") for n in (graph.full().get("nodes") or [])
                if n.get("type") == "PlanStep"}
    except Exception:  # noqa: BLE001
        return {}


def mirror_plan_after_create(tool: BaseTool, args: Dict[str, Any],
                             tool_context: ToolContext,
                             tool_response: Any) -> None:
    """after_tool on create_plan: the roadmap becomes the method column."""
    if getattr(tool, "name", "") != "create_plan" or not isinstance(tool_response, dict):
        return
    try:
        from CoScientist.graph.research.store import get_research_graph
        sync_plan_to_research_graph(
            tool_response.get("plan") or [], get_research_graph(tool_context),
            tool_context.state,
            str((tool_context.state or {}).get("user_query", "")),
        )
    except Exception as exc:  # noqa: BLE001 — mirroring must never break a tool
        logger.warning("plan mirror failed: %s", exc)


def mirror_plan_before_agent(callback_context: CallbackContext):
    """before_agent: mirror the plan even when `create_plan` never fired.

    `create_plan` belongs to PlannerAgent, which ships disabled, and an operator
    can register a roadmap straight into state from the web UI — so the after_tool
    hook alone would be dead code in the default configuration. This reads the
    same list the executors read (`_master_active_tasks`), which every one of
    those paths writes. Idempotent, so both hooks may fire for one plan.
    """
    try:
        from CoScientist.graph.research.store import get_research_graph
        sync_plan_to_research_graph(
            callback_context.state.get("_master_active_tasks") or [],
            get_research_graph(callback_context), callback_context.state,
            str(callback_context.state.get("user_query", "")),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan mirror failed: %s", exc)
    return None
