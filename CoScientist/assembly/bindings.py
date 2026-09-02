"""Registers every concrete tool, callback, agent class, output schema and
planner in the assembly registry — the names ``system.yaml`` refers to.

This module is the ONE place that maps names to implementations and carries the
prompt documentation (ToolDoc) for every tool. The assembler renders each
agent's "available tools" prompt section from these docs, so the docs here and
the wiring can never diverge: a tool that is not attached is not documented,
and a documented tool is attached.

Tool factories import their modules lazily so that merely loading the registry
does not construct MCP sessions or read service settings.
"""
from __future__ import annotations

from CoScientist.assembly.registry import (
    REGISTRY,
    CallbackEntry,
    ToolDoc,
    ToolEntry,
)

# ── Tools ────────────────────────────────────────────────────────────────────

def _websearch():
    from CoScientist.tools import websearch_toolset_instance
    return websearch_toolset_instance


def _paper_analysis():
    from CoScientist.tools import paper_analysis_toolset_instance
    return paper_analysis_toolset_instance


def _papers_search():
    from CoScientist.tools import papers_search_toolset_instance
    return papers_search_toolset_instance


def _economics():
    from CoScientist.tools import economics_toolset_instance
    return economics_toolset_instance


def _retrieval():
    from CoScientist.tools import retrieval_toolset_instance
    return retrieval_toolset_instance


def _mcp_server_search():
    from CoScientist.tools import search_mcp_servers
    return [search_mcp_servers]


def _fedot():
    from CoScientist.tools import fedot_toolset_instance
    return fedot_toolset_instance


def _medical():
    from CoScientist.tools import med_toolset_instance
    return med_toolset_instance


def _coder():
    from CoScientist.tools import coder_toolset_instance
    return coder_toolset_instance

def _task_tracker():
    from CoScientist.tools import task_tracker_instance
    return task_tracker_instance

def _create_plan_tool():
    from CoScientist.tools.task_tracker import create_plan_tool
    return [create_plan_tool()]


def _microfluidics_stub(name: str):
    """Wrap one microfluidics STUB (stages 3–11) as an attachable function tool.

    The external services are not connected yet; only the function BODY in
    CoScientist/microfluidics/stubs.py changes when they are, so the names
    registered below — and the YAML that references them — stay put.
    """
    def factory():
        from google.adk.tools import FunctionTool
        from CoScientist.microfluidics import stubs

        return [FunctionTool(getattr(stubs, name))]

    return factory

REGISTRY.register_tool(ToolEntry(
    key="websearch",
    factory=_websearch,
    runtime_resolved=True,  # Tavily MCP — tool surface comes from the remote server
    docs=(
        ToolDoc(
            name="tavily_search",
            signature="tavily_search(query)",
            purpose="General web search.",
        ),
        ToolDoc(
            name="tavily_extract",
            signature="tavily_extract(urls)",
            purpose="Read the content of specific pages/URLs.",
        ),
        ToolDoc(
            name="tavily_crawl",
            signature="tavily_crawl(url)",
            purpose="Crawl a site starting from a URL when one page is not enough.",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="paper_analysis",
    factory=_paper_analysis,
    optional=True,  # built only when MCP__PAPER_ANALYSIS_URL is configured
    runtime_resolved=True,
    docs=(
        # Confirmed live 2026-08-31 (server v3.1.1) — renamed from
        # explore_chemistry_database; CoScientist/agents/callbacks/
        # research_callbacks.py's _SMILES_SOURCE_TOOLS carries both names.
        ToolDoc(
            name="explore_scientific_database",
            signature="explore_scientific_database(task)",
            purpose="RAG search over an internal scientific literature database.",
        ),
        ToolDoc(
            name="explore_my_papers",
            signature="explore_my_papers(task, s3_keys)",
            purpose="Answers questions using user-uploaded or previously downloaded papers.",
        ),
        ToolDoc(
            name="find_papers_in_db",
            signature="find_papers_in_db(task)",
            purpose="Finds relevant papers in the database for a task — metadata list, no answer synthesis.",
        ),
        ToolDoc(
            name="find_relevant_data_in_db",
            signature="find_relevant_data_in_db(task, search_images=False)",
            purpose=(
                "Retrieves relevant papers AND structured context (text chunks + figures) "
                "in one call, without synthesizing an answer."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="papers_search",
    factory=_papers_search,
    optional=True,  # built only when MCP__PAPERS_SEARCH_URL is configured
    runtime_resolved=True,
    docs=(
        ToolDoc(
            name="search_papers",
            signature="search_papers(keywords, filters)",
            purpose=(
                "Searches scientific papers in OpenAlex using metadata and "
                "search filters. Does NOT download full paper files."
            ),
        ),
        ToolDoc(
            name="download_papers_from_search",
            signature="download_papers_from_search(keywords, filters)",
            purpose="Searches and downloads papers for downstream analysis.",
        ),
        # Confirmed live 2026-08-31 (server v3.1.0) — not previously documented.
        ToolDoc(
            name="search_entity",
            signature="search_entity(entity_type, entity_name)",
            purpose="Looks up an OpenAlex entity (author/source/institution) ID for use in search_papers filters.",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="retrieval",
    factory=_retrieval,
    docs=(
        ToolDoc(
            name="retrieve_tools",
            signature="retrieve_tools(query)",
            purpose="Retrieves tools from MCP servers using RAG.",
        ),
        ToolDoc(
            name="get_server_info",
            signature="get_server_info(server_id)",
            purpose="Returns server metadata.",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="task_tracker",
    factory=_task_tracker,
    runtime_resolved=True,  # BaseToolset — tool surface comes from get_tools()
    docs=(
        ToolDoc(
            name="get_active_tasks",
            signature="get_active_tasks(query)",
            purpose="Get tasks from TaskTracker",
        ),
        ToolDoc(
            name="update_task_status",
            signature="update_task_status(task_id)",
            purpose="Set task status to DONE/FAILED/IN_PROGRESS",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="create_plan_tool",
    factory=_create_plan_tool,
    docs=(
        ToolDoc(
            name="create_plan",
            signature="create_plan(tasks)",
            purpose="Replace all tasks with a new plan. Each task needs title, description, and assignee.",
        ),
    ),
))

# ── Microfluidics stages 3–11 ────────────────────────────────────────────────
# Stubs for the services behind nodes 3, 4, 5, 9 and 10 (see the design in
# docs/superpowers/specs/2026-07-14-microfluidics-graph-modules-design.md), plus
# finish_optimization — the REAL tool that ends the 7⇄8 optimization loop.

REGISTRY.register_tool(ToolEntry(
    key="molecular_design_stub",
    factory=_microfluidics_stub("molecular_design_stub"),
    docs=(
        ToolDoc(
            name="molecular_design_stub",
            signature="molecular_design_stub(requirements)",
            purpose=(
                "(ЗАГЛУШКА) Predicts target molecules for the ТЗ from the "
                "literature analogues: SMILES + the properties the quality "
                "criteria are checked against."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="retrosynthesis_stub",
    factory=_microfluidics_stub("retrosynthesis_stub"),
    docs=(
        ToolDoc(
            name="retrosynthesis_stub",
            signature="retrosynthesis_stub(smiles)",
            purpose=(
                "(ЗАГЛУШКА) Plans a synthesis route to a target molecule: "
                "ordered steps with reagents and operating conditions."
            ),
        ),
    ),
))

# chemquote — real MCP service (not a stub): Russian chemical-supplier price
# lists, priced/matched by SMILES. Full tool reference: MCP_Economic_model.md.
REGISTRY.register_tool(ToolEntry(
    key="economics",
    factory=_economics,
    optional=True,  # built only when MCP__ECONOMICS_URL is configured
    runtime_resolved=True,
    docs=(
        ToolDoc(
            name="search_reagents_by_name",
            signature="search_reagents_by_name(query, limit=20)",
            purpose=(
                "Fuzzy search for a reagent by its Russian trade name (typo-"
                "tolerant). Returns reagents (folded offers), not raw price rows."
            ),
        ),
        ToolDoc(
            name="get_price",
            signature="get_price(name, pack_unit=None, purity_grade=None, limit=50)",
            purpose=(
                "All offers for a reagent name — every supplier/pack size/grade, "
                "sorted by unit price."
            ),
        ),
        ToolDoc(
            name="search_by_structure",
            signature="search_by_structure(smiles, mode='exact', limit=50)",
            purpose=(
                "Find offers by molecule SMILES instead of name — reliable "
                "regardless of how the price list names the substance. "
                "mode='substructure' finds molecules containing a fragment."
            ),
        ),
        ToolDoc(
            name="estimate_synthesis_cost",
            signature=(
                "estimate_synthesis_cost(reagents, strategy='cheapest', "
                "similarity='hard', preferred_currency='RUB')"
            ),
            purpose=(
                "Costs a list of reagents ({smiles, qty, unit}). similarity="
                "'hard' aborts on any unmatched reagent (no partial estimate); "
                "'soft' matches what it can and lists the rest in `missing`."
            ),
        ),
        ToolDoc(
            name="rank_routes_by_cost",
            signature=(
                "rank_routes_by_cost(routes, target_qty=1, target_unit='g', "
                "default_yield=1.0, similarity='soft', preferred_currency='RUB')"
            ),
            purpose=(
                "Compares synthesis routes (ordered reaction-SMILES steps, "
                "'reactants>agents>products') by the purchase cost of their "
                "starting materials for the same target quantity. Set "
                "default_yield to each route's real step yield — 1.0 (no "
                "losses modelled) makes long routes look artificially cheap."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="cfd_mcp_stub",
    factory=_microfluidics_stub("cfd_mcp_stub"),
    docs=(
        ToolDoc(
            name="cfd_mcp_stub",
            signature="cfd_mcp_stub(geometry, flow)",
            purpose=(
                "(ЗАГЛУШКА) Simulates the flow in the chip (CFD): pressure "
                "drop, mixing efficiency, residence time."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="rig_mcp_stub",
    factory=_microfluidics_stub("rig_mcp_stub"),
    docs=(
        ToolDoc(
            name="rig_mcp_stub",
            signature="rig_mcp_stub(command)",
            purpose=(
                "(ЗАГЛУШКА) Sends a command to the microfluidic rig and reads "
                "back its status and telemetry."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="finish_optimization",
    factory=_microfluidics_stub("finish_optimization"),
    docs=(
        ToolDoc(
            name="finish_optimization",
            signature="finish_optimization(reason)",
            purpose=(
                "Ends the experiment optimization loop and moves on to the "
                "report. Call it once the plan needs no further refining."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="mcp_server_search",
    factory=_mcp_server_search,
    docs=(
        ToolDoc(
            name="search_mcp_servers",
            signature="search_mcp_servers(query)",
            purpose=(
                "Searches public MCP registries and returns up to 15 matching "
                "servers with descriptions, metadata, and links."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="fedot",
    factory=_fedot,
    docs=(
        ToolDoc(
            name="fedot_tool",
            signature="fedot_tool(task_description)",
            purpose="Builds and executes a multi-agent pipeline to solve the task.",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="medical",
    factory=_medical,
    docs=(
        ToolDoc(
            name="search_pubmed",
            signature="search_pubmed(keyword, num_results)",
            purpose=(
                "Find peer-reviewed literature on a clinical topic, drug, "
                "condition, or intervention (10 results by default)."
            ),
        ),
        ToolDoc(
            name="get_pico",
            signature="get_pico(title, abstract)",
            purpose=(
                "Extract Population / Intervention / Comparison / Outcome "
                "structure from a paper abstract."
            ),
        ),
        ToolDoc(
            name="get_study_taxonomy",
            signature="get_study_taxonomy(title, abstract)",
            purpose=(
                "Classify a paper's study design (observational vs experimental "
                "vs literature review, with subtypes)."
            ),
        ),
        ToolDoc(
            name="analyze_medical_image",
            signature="analyze_medical_image(artifact_id, question)",
            purpose=(
                "Interpret an uploaded DICOM or image file; provides differential "
                "diagnosis and ICD-10 codes."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="coder",
    factory=_coder,
    docs=(
        ToolDoc(
            name="execute_bash",
            signature="execute_bash(command, timeout)",
            purpose=(
                "Run a shell command in the session sandbox and WAIT for it: "
                "stdout, stderr and exit_code come back in this single call for "
                "almost everything (git clone, pip install, scripts, data "
                "processing). Only a genuinely long job that outlives the inline "
                "wait returns status \"running\" with a `job_id` to check later."
            ),
            usage=(
                "Use it for scripts, building/testing code, git (clone, checkout, "
                "commit, push, pull, diff, log), and data processing.",
                "You can run several independent commands; each call returns when "
                "its command finishes (or hands back a job_id for a long job).",
            ),
        ),
        ToolDoc(
            name="check_job",
            signature="check_job(job_id)",
            purpose=(
                "Check a long job that execute_bash handed back as still "
                "\"running\". You normally do NOT need this — execute_bash "
                "already waits and returns the result directly."
            ),
            usage=(
                "If the job is still running, do other work and check once "
                "later — never poll in a tight loop.",
            ),
        ),
        ToolDoc(
            name="read_file",
            signature="read_file(file_path, start_line, end_line)",
            purpose="Read code, config, and data files (completes immediately).",
        ),
        ToolDoc(
            name="write_file",
            signature="write_file(file_path, content)",
            purpose="Author code, config, and data files (completes immediately).",
        ),
        ToolDoc(
            name="list_directory",
            signature="list_directory(path, recursive)",
            purpose="Inspect the workspace (completes immediately).",
        ),
        ToolDoc(
            name="install_package",
            signature="install_package(package_name, upgrade)",
            purpose=(
                "Pip-install Python dependencies; like execute_bash it waits "
                "inline and returns the result (a very slow install may hand "
                "back a `job_id` for check_job)."
            ),
        ),
    ),
))

# HITL tools are not a YAML-listed tool entry: the assembler attaches them via
# the per-agent `hitl: true` flag (when HITL is globally enabled) and appends
# these docs so the prompt always matches.
HITL_TOOL_DOCS = (
    ToolDoc(
        name="request_approval",
        signature="request_approval(agent_name, message, context)",
        purpose=(
            "(HITL) Ask the human to approve or reject a proposed action before "
            "proceeding. Returns 'approved' (bool) and optional 'feedback'."
        ),
    ),
    ToolDoc(
        name="request_selection",
        signature="request_selection(agent_name, message, options)",
        purpose=(
            "(HITL) Ask the human to choose one of several options you generated "
            "(e.g. hypotheses or plans). Returns 'selected' and 'approved'."
        ),
    ),
)


# ── Callbacks ────────────────────────────────────────────────────────────────

def _cb(key: str, kind: str, func=None, factory=None) -> None:
    REGISTRY.register_callback(CallbackEntry(key=key, kind=kind, func=func, factory=factory))


def _save_uploaded_artifacts():
    from CoScientist.agents.callbacks import before_model_modifier
    return before_model_modifier


def _seed_coder_workspace():
    from CoScientist.tools.coder_tools import seed_coder_workspace
    return seed_coder_workspace


def _inject_medical_artifacts():
    from CoScientist.agents.callbacks import med_agent_before_model
    return med_agent_before_model


def _inject_uploaded_papers():
    from CoScientist.agents.callbacks import papers_agent_before_model
    return papers_agent_before_model


def _log_research_tool_calls():
    from CoScientist.agents.callbacks import print_research_agent_tool_call
    return print_research_agent_tool_call


def _capture_literature_smiles():
    from CoScientist.agents.callbacks import capture_literature_smiles
    return capture_literature_smiles


def _capture_literature_reactions():
    from CoScientist.agents.callbacks import capture_literature_reactions
    return capture_literature_reactions


def _skip_retriever_context():
    from CoScientist.agents.callbacks import before_tool_reranker_model
    return before_tool_reranker_model


def _collect_reranked_tools():
    from CoScientist.agents.callbacks import after_tool_reranker_agent
    return after_tool_reranker_agent


def _collect_reranked_mcps():
    from CoScientist.agents.callbacks import after_fullset_reranker_agent
    return after_fullset_reranker_agent


def _redirect_when_no_tools():
    from CoScientist.agents.callbacks import redirect_when_no_tools
    return redirect_when_no_tools


def _before_get_task():
    from CoScientist.agents.callbacks import before_get_task
    return before_get_task


def _web_search_limiter():
    import os
    from CoScientist.agents.callbacks.tool_callbacks import SearchLimiter
    # Default 2 keeps a normal delegated LIT-xx task cheap; bump via env when a
    # domain's internal corpus (paper_analysis) doesn't cover the topic and
    # ResearchAgent genuinely needs more OpenAlex attempts to find anything.
    max_searches = int(os.getenv("RESEARCH_MAX_SEARCHES", "2"))
    return SearchLimiter(max_searches=max_searches).limit_searches


def _sanitize_json_output():
    from CoScientist.agents.callbacks import sanitize_json_output
    return sanitize_json_output


def _save_tz_document():
    from CoScientist.microfluidics.tz_agent import save_tz_document
    return save_tz_document


def _export_tz_and_queries():
    from CoScientist.microfluidics.export import export_tz_and_queries
    return export_tz_and_queries


def _guard_unknown_tools(ctx):
    """after_model guard capturing the agent's REAL tool names from its context,
    so a hallucinated tool call is corrected instead of crashing the run."""
    from CoScientist.agents.callbacks import make_unknown_tool_guard
    names = [d.name for e in ctx.tool_entries for d in e.docs]
    return make_unknown_tool_guard(names)


def _pre_action_critique(ctx):
    from CoScientist.agents.callbacks import make_pre_action_critique
    return make_pre_action_critique(REGISTRY.prompt("pre_action_critic")(ctx))


def _post_action_critique(ctx):
    from CoScientist.agents.callbacks import make_post_action_critique
    return make_post_action_critique(REGISTRY.prompt("post_action_critic")(ctx))


# Plain callbacks are registered through tiny lazy factories that ignore the
# context — so importing bindings never drags in S3/opik/etc. transitively.
_cb("save_uploaded_artifacts", "before_model", factory=lambda ctx: _save_uploaded_artifacts())
# Pin the coder sandbox to the ADK session (one workspace per session).
_cb("seed_coder_workspace", "before_model", factory=lambda ctx: _seed_coder_workspace())
_cb("inject_medical_artifacts", "before_model", factory=lambda ctx: _inject_medical_artifacts())
_cb("inject_uploaded_papers", "before_model", factory=lambda ctx: _inject_uploaded_papers())
_cb("log_research_tool_calls", "after_tool", factory=lambda ctx: _log_research_tool_calls())
# Pull SMILES out of RAG/paper-search tool results (raw response, before the
# LLM paraphrase) and stash them in state for the design stage to pick up.
_cb("capture_literature_smiles", "after_tool", factory=lambda ctx: _capture_literature_smiles())
# Same, for reaction SMILES (reactants>agents>products) — feeds the
# retrosynthesis stage instead of the molecular-design one.
_cb("capture_literature_reactions", "after_tool", factory=lambda ctx: _capture_literature_reactions())
_cb("skip_retriever_context", "before_model", factory=lambda ctx: _skip_retriever_context())
_cb("collect_reranked_tools", "after_agent", factory=lambda ctx: _collect_reranked_tools())
_cb("collect_reranked_mcps", "after_agent", factory=lambda ctx: _collect_reranked_mcps())
# Coder↔Executor redirect: abstain to CoderAgent when no tool matched the task.
_cb("redirect_when_no_tools", "before_agent", factory=lambda ctx: _redirect_when_no_tools())
# Load active tasks into agent state before the agent runs.
_cb("before_get_task", "before_agent", factory=lambda ctx: _before_get_task())
# Limit web search calls per agent turn.
_cb("WebSearchLimiter", "before_tool", factory=lambda ctx: _web_search_limiter())
# Catch hallucinated tool calls (e.g. `find`) and correct instead of crashing.
_cb("guard_unknown_tools", "after_model", factory=_guard_unknown_tools)
# Trim prose/fences/trailing text around a JSON answer BEFORE strict
# output_schema validation (providers don't always honour response_format).
_cb("sanitize_json_output", "after_model", factory=lambda ctx: _sanitize_json_output())
# Render the approved ТЗ into the reference Markdown document (state + file).
_cb("save_tz_document", "after_agent", factory=lambda ctx: _save_tz_document())
# Save the ТЗ + literature queries as shareable Markdown & HTML for hand-off.
_cb("export_tz_and_queries", "after_agent", factory=lambda ctx: _export_tz_and_queries())
# Critic callbacks: their LLM prompts embed the orchestrator's current roster.
_cb("pre_action_critique", "after_model", factory=_pre_action_critique)
_cb("post_action_critique", "after_tool", factory=_post_action_critique)


# ── Agent classes / output schemas / planners ────────────────────────────────

def _register_classes() -> None:
    from CoScientist.agents.custom_agents import WebToolsDeployerAgent
    from CoScientist.hitl.session_agent import SessionAgent
    from CoScientist.microfluidics.tz_agent import TZSessionAgent

    REGISTRY.register_agent_class("session", SessionAgent)
    REGISTRY.register_agent_class("web_tools_deployer", WebToolsDeployerAgent)
    # Microfluidics ТЗ stage: the review loop shows the RENDERED ТЗ document.
    REGISTRY.register_agent_class("tz_session", TZSessionAgent)


def _register_schemas() -> None:
    from CoScientist.storage import MCPRanking, ToolRanking
    from CoScientist.microfluidics.models import LiteratureQueries, StructuredTZ

    REGISTRY.register_output_schema("tool_ranking", ToolRanking)
    REGISTRY.register_output_schema("mcp_ranking", MCPRanking)
    # Microfluidics profile: structured ТЗ and the literature queries derived
    # from it (see CoScientist/agents/microfluidics.yaml).
    REGISTRY.register_output_schema("structured_tz", StructuredTZ)
    REGISTRY.register_output_schema("tz_literature_queries", LiteratureQueries)


def _register_planners() -> None:
    from google.adk.planners import PlanReActPlanner

    REGISTRY.register_planner("plan_react", PlanReActPlanner)


_register_classes()
_register_schemas()
_register_planners()
