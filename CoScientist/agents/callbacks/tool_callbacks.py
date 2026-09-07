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
    """Adds ToolReranker output to state"""
    from CoScientist.config import get_settings
    web_settings = get_settings().web
    keep_score = web_settings.executor_tool_keep_score
    abstain_score = web_settings.executor_tool_abstain_score


    current_state = callback_context.state
    reranked_tools: Dict[str, float] = (current_state.get('reranked_tools') or {}).get('tools', [])

    rerank_map: Dict[int, float] = {t['index']: t['score'] for t in reranked_tools}
    acc_tools: List[Dict[str, Any]] = current_state.get('accumulated_tools', [])

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
    # running an unrelated tool.

    # Record the verdict for the redirect guard / the orchestrator's critic.
    callback_context.state[TOOL_MATCH_STATE_KEY] = {
        "matched": matched,
        "best_score": round(best_score, 3),
        "kept": len(filtered_tools),
    }
    callback_context.state['filtered_tools'] = filtered_tools
    callback_context.state['accumulated_tools'] = []
    callback_context.state['retrieval_queries'] = []
    return


def after_fullset_reranker_agent(
    callback_context: CallbackContext
) -> None:
    """Adds ToolReranker output to state"""

    current_state = callback_context.state
    reranked_mcps: List[Dict[str, Any]] = (current_state.get('reranked_web_servers') or {}).get('mcp_scores', [])

    # Binary deploy score (0/1) per MCP index — truthiness selects deploy.
    rerank_map: Dict[int, bool] = {t['index']: t['score'] for t in reranked_mcps}
    acc_mcps: List[Dict[str, Any]] = current_state.get('accumulated_web_mcps', [])

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
        content = llm_request.contents[i]
        if content.role == "user" and content.parts:
            llm_request.contents[i] = types.Content(
                role="user",
                parts=[types.Part(text=original_text)],
            )
            logger.info(
                "[OrchestratorAgent] Replaced planner messages with original user query"
            )
            return