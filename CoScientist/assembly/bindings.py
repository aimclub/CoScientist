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

from importlib import import_module

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

def _microfluidics():
    from CoScientist.tools import microfluidics_toolset_instance
    return microfluidics_toolset_instance

def _paper_analysis():
    from CoScientist.tools import paper_analysis_toolset_instance
    return paper_analysis_toolset_instance


def _papers_search():
    from CoScientist.tools import papers_search_toolset_instance
    return papers_search_toolset_instance


def _vault():
    from CoScientist.tools import vault_toolset_instance
    return vault_toolset_instance


def _retrieval():
    from CoScientist.tools import retrieval_toolset_instance
    return retrieval_toolset_instance


def _mcp_server_search():
    from CoScientist.tools import search_mcp_servers
    return [search_mcp_servers]


def _fedot():
    from CoScientist.tools import fedot_toolset_instance
    return fedot_toolset_instance


def _result_formatter():
    from CoScientist.tools import result_formatter_tool
    return result_formatter_tool


def _nir_report():
    """The GOST NIR report toolset, or None when the MCP is not configured.

    Returning None (rather than a toolset that fails on first call) lets the
    entry be `optional`, so NirReportAgent simply has nothing to offer and the
    run completes the way it does today.
    """
    from CoScientist.config import get_settings

    if not get_settings().mcp.normcontrol_url:
        return None
    from CoScientist.tools.nir_report_tool import nir_report_tools
    return nir_report_tools


def _dynamic_tools():
    from CoScientist.tools import dynamic_mcp_toolset_instance
    return dynamic_mcp_toolset_instance


def _medical():
    from CoScientist.tools import med_toolset_instance
    return med_toolset_instance


def _coder():
    """Local coder toolset — dropped when the web UI switches it off, leaving
    the coder family to work through the OpenHands `sandbox` tools only."""
    if not _is_local_coder():
        return None
    from CoScientist.tools import coder_toolset_instance
    return coder_toolset_instance


def _alembic():
    from CoScientist.tools.alembic_tools import ALEMBIC_TOOLS
    return ALEMBIC_TOOLS

def _verify():
    from CoScientist.verify.tools import verify_toolset
    return verify_toolset.get_tools(None)


def _sandbox():
    """OpenHands sandbox tools — absent when no sandbox URL is configured."""
    from CoScientist.tools.coder_tools.sandbox_tools import get_sandbox_tools
    return get_sandbox_tools() or None

def _task_tracker():
    from CoScientist.tools import task_tracker_instance
    return task_tracker_instance


def _experiment_control():
    from CoScientist.experiments.runtime import experiment_control_toolset
    return experiment_control_toolset


def _create_plan_tool():
    from CoScientist.tools.task_tracker import create_plan_tool
    return [create_plan_tool()]


def _microfluidic_economic():
    from CoScientist.tools import microfluidic_economic_toolset_instance
    return microfluidic_economic_toolset_instance


def _microfluidic_cfd():
    from CoScientist.tools import microfluidic_cfd_toolset_instance
    return microfluidic_cfd_toolset_instance


def _microfluidics_stub_unless(name: str, real_url_setting: str):
    """The stub, only while its real MCP server is not configured.

    The YAML lists both the real toolset and the stub; exactly one of them is
    attached, so the agent never sees a stub next to the service it replaces.
    """
    stub_factory = _microfluidics_stub(name)

    def factory():
        from CoScientist.config import get_settings

        if getattr(get_settings().mcp, real_url_setting):
            return None
        return stub_factory()

    return factory


def _retrosynthesis():
    from CoScientist.microfluidics.retrosynthesis import tools
    return tools()


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


def _tz_builder_tool(name: str):
    """Wrap one section tool of the microfluidics ТЗ (tz_builder.py)."""
    def factory():
        from google.adk.tools import FunctionTool
        from CoScientist.microfluidics import tz_builder

        return [FunctionTool(getattr(tz_builder, name))]

    return factory

def _sleep_tool():
    from google.adk.tools import FunctionTool
    from CoScientist.tools.sleep_tool import sleep_tool
    return [FunctionTool(sleep_tool)]

def _web_flag(field: str) -> bool:
    """Read a per-tool switch off ``settings.web`` (set from the web UI)."""
    try:
        from CoScientist.config import get_settings
        return bool(getattr(get_settings().web, field))
    except Exception:  # noqa: BLE001
        return True


def _is_local_coder() -> bool:
    try:
        from CoScientist.config import get_settings
        return get_settings().web.coder_mode == "local"
    except Exception:  # noqa: BLE001
        return True


def _graph():
    """Knowledge-graph reader toolset — dropped when the graph is switched off,
    which also stops GraphMemoryPlugin from recording (graph/plugin.py)."""
    if not _web_flag("knowledge_graph_enabled"):
        return None
    from CoScientist.graph.agent_tools import graph_reader_instance
    return graph_reader_instance


def _planner_retrieval():
    if not _web_flag("planner_retrieval_enabled"):
        return None
    return _retrieval()


def _planner_graph():
    if not _web_flag("planner_graph_enabled"):
        return None
    return _graph()


def _research_graph_enabled() -> bool:
    try:
        from CoScientist.config import get_settings
        return get_settings().research_graph.enabled
    except Exception:  # noqa: BLE001
        return False


def _research_graph():
    if not _research_graph_enabled():
        return None
    from CoScientist.graph.research.agent_tools import research_worker_toolset
    return research_worker_toolset


def _research_graph_orchestrator():
    if not _research_graph_enabled():
        return None
    from CoScientist.graph.research.agent_tools import research_orchestrator_toolset
    return research_orchestrator_toolset


def _research_graph_readonly():
    if not _research_graph_enabled():
        return None
    from CoScientist.graph.research.agent_tools import research_reporter_toolset
    return research_reporter_toolset

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
        ToolDoc(
            name="explore_scientific_database",
            signature="explore_scientific_database(task)",
            purpose=(
                "RAG over the internal scientific-literature corpus "
                "(deployed paper-analysis MCP)."
            ),
        ),
        ToolDoc(
            name="explore_chemistry_database",
            signature="explore_chemistry_database(task)",
            purpose="RAG search over an internal scientific literature database.",
        ),
        ToolDoc(
            name="explore_my_papers",
            signature="explore_my_papers(question, s3_keys)",
            purpose="Answers questions using user-uploaded or previously downloaded papers.",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="vault",
    factory=_vault,
    optional=True,  # built only when MCP__VAULT_URL is configured
    runtime_resolved=True,
    docs=(
        ToolDoc(
            name="get_upload_link",
            signature="get_upload_link(filename, feature=None)",
            purpose=(
                "Returns a one-hour upload_url for a new file, plus the bucket "
                "and s3_key that identify it for good. Upload with a plain HTTP "
                "PUT and no extra headers. Report the bucket and the s3_key, "
                "never the URL: the URL expires and the object does not."
            ),
        ),
        ToolDoc(
            name="get_download_link",
            signature="get_download_link(s3_key)",
            purpose=(
                "Turns an s3_key from an earlier step back into a one-hour "
                "download URL. Use it when a link you were given no longer works."
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
            signature="search_papers(keywords)",
            purpose=(
                "Searches scientific papers in OpenAlex using keywords. "
                "Does NOT download full paper files. Argument name is "
                "`keywords`, not `query`. Optional `email` / `api_key` overlay "
                "OpenAlex credentials from env/headers."
            ),
        ),
        ToolDoc(
            name="download_papers_from_search",
            signature="download_papers_from_search(keywords)",
            purpose=(
                "Searches and downloads papers for downstream analysis. "
                "Optional `email` / `api_key` overlay OpenAlex credentials."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="microfluidics",
    factory=_microfluidics,
    optional=True,  # built only when MCP__MICROFLUIDICS_URL is configured
    runtime_resolved=True,  # real MCP server — tool surface comes from it
    docs=(
        ToolDoc(
            name="<microfluidics MCP tools>",
            signature="(varies)",
            purpose=(
                "Tools exposed by the microfluidics MCP server (chip CFD / rig "
                "control) — call them directly."
            ),
        ),
    ),
))

_RETRIEVAL_DOCS = (
    ToolDoc(
        name="retrieve_tools",
        signature="retrieve_tools(query)",
        purpose=(
            "Searches the MCP registry by capability. Returns ranked tool "
            "records with tool name, server_id, full description, input_schema, "
            "and score; use the metadata to determine exact requirement coverage."
        ),
    ),
    ToolDoc(
        name="get_server_info",
        signature="get_server_info(server_id)",
        purpose="Returns server metadata.",
    ),
)

REGISTRY.register_tool(ToolEntry(
    key="retrieval",
    factory=_retrieval,
    docs=_RETRIEVAL_DOCS,
))

# Same toolset as "retrieval", gated on the web setting so the planner's MCP
# discovery can be switched off from the UI without touching any other agent.
REGISTRY.register_tool(ToolEntry(
    key="planner_retrieval",
    factory=_planner_retrieval,
    optional=True,  # dropped when WEB__PLANNER_RETRIEVAL_ENABLED is false
    docs=_RETRIEVAL_DOCS,
))

REGISTRY.register_tool(ToolEntry(
    key="task_tracker",
    factory=_task_tracker,
    runtime_resolved=True,  # BaseToolset — tool surface comes from get_tools()
    docs=(
        ToolDoc(
            name="get_active_tasks",
            signature="get_active_tasks()",
            purpose="Get tasks from the current ADK session",
        ),
        ToolDoc(
            name="update_task_status",
            signature="update_task_status(task_id, status, notes=None)",
            purpose="Set task status to DONE/FAILED/IN_PROGRESS",
        ),
    ),
))

_GRAPH_DOCS = (
    ToolDoc(
        name="read_research_graph",
        signature="read_research_graph()",
        purpose="Read the shared knowledge graph: roster + every step so far.",
    ),
    ToolDoc(
        name="get_graph_history",
        signature="get_graph_history(limit)",
        purpose="Chronological history of steps taken in this session.",
    ),
    ToolDoc(
        name="get_agents_info",
        signature="get_agents_info()",
        purpose="Structured info about all agents in the system.",
    ),
)

REGISTRY.register_tool(ToolEntry(
    key="experiment_control",
    factory=_experiment_control,
    runtime_resolved=True,
    docs=(
        ToolDoc(
            name="get_experiment_plan",
            signature="get_experiment_plan()",
            purpose="Read the approved experiment plan and task/attempt runtime.",
        ),
        ToolDoc(
            name="start_task",
            signature="start_task(task_id)",
            purpose="Create one fresh attempt and immutable scoped route envelope.",
        ),
        ToolDoc(
            name="record_result",
            signature="record_result(task_id, attempt_id, result)",
            purpose="Validate and persist the attempt's only terminal TaskResult.",
        ),
        ToolDoc(
            name="retry_task",
            signature="retry_task(task_id)",
            purpose="Authorize a retryable failure to use a new attempt.",
        ),
        ToolDoc(
            name="fallback_task",
            signature="fallback_task(task_id, reason)",
            purpose="Advance to the next route in the finite acyclic fallback chain.",
        ),
        ToolDoc(
            name="skip_task",
            signature="skip_task(task_id, reason)",
            purpose="Skip an optional task and persist a skipped TaskResult.",
        ),
        ToolDoc(
            name="amend_task",
            signature="amend_task(task_id, patch, reason)",
            purpose="Amend an unstarted runtime task; material changes return to review.",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="graph",
    factory=_graph,
    optional=True,  # dropped when WEB__KNOWLEDGE_GRAPH_ENABLED is false
    runtime_resolved=True,  # BaseToolset — tool surface comes from get_tools()
    docs=_GRAPH_DOCS,
))

# Same toolset as "graph", gated on the web setting (planner only).
REGISTRY.register_tool(ToolEntry(
    key="planner_graph",
    factory=_planner_graph,
    optional=True,  # dropped when WEB__PLANNER_GRAPH_ENABLED is false
    runtime_resolved=True,
    docs=_GRAPH_DOCS,
))

# ── Research Context Graph ────────────────────────────────────────────────────
# The typed blackboard (CoScientist/graph/research). Two surfaces: workers get
# read + research_commit; the orchestrator additionally gets init/triggers/focus.
# Both optional (drop out when RESEARCH_GRAPH__ENABLED is false) and
# runtime_resolved (BaseToolset — real tool names come from get_tools()).
_RESEARCH_COMMIT_DOC = ToolDoc(
    name="research_commit",
    signature="research_commit(nodes, edges, status_updates)",
    purpose=("Record your results in the shared research graph in ONE "
             "transaction (validated + applied all-or-nothing). You may only "
             "write types/edges/status changes your role allows."),
    usage=(
        'create a node: {"type": "Evidence", "attrs": {...}, "status"?: "...", "ref"?: "e1"}',
        'enrich an existing node: {"id": "EB1", "attrs": {...}} (no "type")',
        'edge: {"type": "supports", "from": "E4", "to": "H2"} — use "#e1" to point at a node created in this call',
        'status change: {"id": "H2", "status": "under_verification", "reason"?: "..."}',
        "on ok=false, read errors, fix the payload, and call it again (nothing was saved).",
    ),
)
_RESEARCH_SLICE_DOC = ToolDoc(
    name="research_context_slice",
    signature="research_context_slice(node_id, depth=1)",
    purpose="Get one node plus its 1–2 hop neighborhood (the focused view to work from).",
)
_RESEARCH_OVERVIEW_DOC = ToolDoc(
    name="research_overview",
    signature="research_overview()",
    purpose="Compact index of the whole research graph (ids, types, statuses, labels).",
)
_RESEARCH_PROVENANCE_DOC = ToolDoc(
    name="research_provenance",
    signature="research_provenance(node_id)",
    purpose="Trace a node back to the root question (chain of nodes/edges + sources).",
)
_RESEARCH_WORKER_DOCS = (_RESEARCH_COMMIT_DOC, _RESEARCH_SLICE_DOC,
                         _RESEARCH_OVERVIEW_DOC, _RESEARCH_PROVENANCE_DOC)
_RESEARCH_ORCH_DOCS = _RESEARCH_WORKER_DOCS + (
    ToolDoc(
        name="research_init",
        signature="research_init(question, attrs, constraints, tools, resources, empirical_bases)",
        purpose=("Start a NEW research: create the root ResearchQuestion + its "
                 "context star. Call once at the start; archives any active graph."),
    ),
    ToolDoc(
        name="research_prior",
        signature="research_prior(query, limit)",
        purpose=("Search PAST researches (previous runs) related to a question: "
                 "their hypotheses with verdicts, the methods/tools used and the "
                 "conclusions. Consult BEFORE planning so settled work is reused "
                 "instead of re-derived; each hit reports why it matched."),
    ),
    ToolDoc(
        name="research_triggers",
        signature="research_triggers()",
        purpose=("Evaluate the decision triggers (READY / BLOCKED / REFUTE / "
                 "CLOSABLE / PENDING / TOOLS / RESOURCES / QUESTIONS / PROGRESS)."),
    ),
    ToolDoc(
        name="research_set_focus",
        signature="research_set_focus(node_id)",
        purpose=("Set the node the NEXT delegated worker focuses on — it "
                 "receives that node's slice automatically. Call before delegating."),
    ),
)

REGISTRY.register_tool(ToolEntry(
    key="research_graph",
    factory=_research_graph,
    optional=True,
    runtime_resolved=True,
    docs=_RESEARCH_WORKER_DOCS,
))

REGISTRY.register_tool(ToolEntry(
    key="research_graph_orchestrator",
    factory=_research_graph_orchestrator,
    optional=True,
    runtime_resolved=True,
    docs=_RESEARCH_ORCH_DOCS,
))

# Read-only surface for the Result Aggregator: overview / slice / provenance,
# no research_commit (the reporter reads the finished graph, never mutates it).
REGISTRY.register_tool(ToolEntry(
    key="research_graph_readonly",
    factory=_research_graph_readonly,
    optional=True,
    runtime_resolved=True,
    docs=(_RESEARCH_OVERVIEW_DOC, _RESEARCH_SLICE_DOC, _RESEARCH_PROVENANCE_DOC),
))

REGISTRY.register_tool(ToolEntry(
    key="verify",
    factory=_verify,
    docs=(
        ToolDoc(
            name="validate_dataset",
            signature="validate_dataset(path)",
            purpose=(
                "Deterministically check that a dataset file holds REAL, diverse "
                "molecules (RDKit-valid SMILES + a fitness/SA column). Call it on "
                "your training dataset BEFORE training — training is BLOCKED until a "
                "real dataset validates; toy/placeholder data (integers, one "
                "repeated molecule, a synthetic fallback) is rejected."),
        ),
        ToolDoc(
            name="validate_training",
            signature="validate_training(checkpoint_path, loss_log)",
            purpose=(
                "Deterministically check a training result: a real saved checkpoint "
                "and a loss that actually decreased over >=1 epoch."),
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
            purpose=(
                "Replace all tasks with a new plan. Each task needs title, "
                "description and assignee, plus `id` and `parent_id` to state "
                "which task must run first. Tasks are stored in execution order."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="sleep",
    factory=_sleep_tool,
    docs=(
        ToolDoc(
            name="sleep_tool",
            signature="sleep_tool(minutes)",
            purpose=(
                "Pause before your next tool call instead of checking again "
                "immediately — use this to space out status/log checks on a "
                "long-running job (e.g. one that takes hours) instead of "
                "polling it every turn. Capped at 10 minutes per call; call it "
                "again afterwards if you need to wait longer."
            ),
        ),
    ),
))

# ── Microfluidics ТЗ (stage 1) ───────────────────────────────────────────────
# TZSpecAgent fills the ТЗ one section per call; both tools keep the ТЗ in
# state["structured_tz"] (see CoScientist/microfluidics/tz_builder.py).

REGISTRY.register_tool(ToolEntry(
    key="fill_tz_section",
    factory=_tz_builder_tool("fill_tz_section"),
    docs=(
        ToolDoc(
            name="fill_tz_section",
            signature="fill_tz_section(section, usage, fields)",
            purpose=(
                "Сохраняет ОДИН раздел ТЗ — следующий по порядку. Отвечает "
                "прогрессом (заполнено k из N) и называет раздел, который нужно "
                "заполнить следующим, с его рекомендуемыми полями."
            ),
            usage=(
                "fields — строки таблицы раздела: "
                '[{"name": ..., "value": ..., "status": ...}, ...]',
                'status "error" — раздел не сохранён; в errors указано, на каком '
                "шаге, в каком разделе и в каком поле (номер и имя) ошибка",
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="fill_agent_fields",
    factory=_tz_builder_tool("fill_agent_fields"),
    docs=(
        ToolDoc(
            name="fill_agent_fields",
            signature="fill_agent_fields(section, fields)",
            purpose=(
                "Заполняет поля, которые оператор оставил пустыми при проверке "
                "ТЗ, — по одному разделу за вызов, в указанном порядке. Статус "
                "«заполнено агентом» ставится автоматически."
            ),
            usage=(
                'fields — [{"name": ..., "value": ...}, ...]: ровно поля, '
                "названные в запросе, с конкретными значениями",
                "вызывай только после сообщения, что оператор оставил поля тебе",
            ),
        ),
    ),
))

# Registered for when an agent is allowed to edit an assembled ТЗ; NOT attached
# to any agent yet — a rewrite after review refills the ТЗ from section 1.
REGISTRY.register_tool(ToolEntry(
    key="edit_tz_section",
    factory=_tz_builder_tool("edit_tz_section"),
    docs=(
        ToolDoc(
            name="edit_tz_section",
            signature="edit_tz_section(section, fields, usage='')",
            purpose=(
                "Переписывает ОДИН раздел уже собранного ТЗ: fields полностью "
                "заменяют прежнюю таблицу раздела, остальные разделы не меняются."
            ),
            usage=(
                "usage можно не передавать — останется прежний",
            ),
        ),
    ),
))

# ── Microfluidics stages 3–11 ────────────────────────────────────────────────
# Stubs for the services behind nodes 3, 5, 9 and 10 (see the design in
# docs/superpowers/specs/2026-07-14-microfluidics-graph-modules-design.md), plus
# finish_optimization — the REAL tool that ends the 7⇄8 optimization loop.

def _molecular_design():
    from CoScientist.microfluidics.molecular_design import molecular_design
    return [molecular_design]


REGISTRY.register_tool(ToolEntry(
    key="molecular_design",
    factory=_molecular_design,
    docs=(
        ToolDoc(
            name="molecular_design",
            signature="molecular_design(requirements)",
            purpose=(
                "Screens literature analogues with RDKit descriptors and explicit TZ "
                "constraints, optionally enumerating BRICS hypotheses. Reads TZ and "
                "literature from session state; saves molecular_design_result. "
                "Returns candidates, criteria_checks, rejected structures and gaps; "
                "unknown properties are not predicted."
            ),
            usage=(
                'requirements is a JSON string: criteria [{name, minimum and/or maximum, '
                'unit, conditions}], required_smarts, forbidden_smarts, generate (bool), '
                'max_candidates (1..30). All fields are optional; {} is valid.',
                'Descriptor names/units: MolWt (g/mol), TPSA (angstrom^2); MolLogP, '
                'HBD, HBA, RotatableBonds, FormalCharge use unit="". Other properties '
                'require matching literature name, unit and measurement conditions.',
                'Use only explicit TZ bounds. status=error/no_candidates means no '
                'usable candidates; do not invent a fallback result.',
            ),
        ),
    ),
))

# The retrosynthesis service (ASKCOS proxy — the ГПН block "ретро / forward /
# классиф."), recorded in tests/fixtures/retrosynthesis/. Plain HTTP, not MCP:
# the tools are async wrappers in microfluidics/retrosynthesis.py.
REGISTRY.register_tool(ToolEntry(
    key="retrosynthesis",
    factory=_retrosynthesis,
    optional=True,  # built only when HOSTS_PORTS__RETROSYNTHESIS_SERVICES_HOST/PORT are set
    docs=(
        ToolDoc(
            name="retrosynthesis_routes",
            signature="retrosynthesis_routes(smiles, mode=\"balanced\", max_routes=5)",
            purpose=(
                "Routes to a target molecule from the retrosynthesis tree search. "
                "Returns status (ok | no_routes | error) and routes[]: route_id, "
                "depth (steps), precursor_cost, min_step_plausibility, "
                "all_starting_materials_purchasable, starting_materials, and steps "
                "in FORWARD order — reaction_smiles, plausibility, "
                "template_examples, reactants (smiles, purchasable, "
                "stoichiometry), products."
            ),
            usage=(
                "mode: \"balanced\" (about 30 s) first; \"deep\" only once, if "
                "balanced found nothing — it is much slower.",
                "Send ONE neutral molecule: a salt or a dotted SMILES often finds "
                "no route — use the parent acid or base.",
                "No conditions and no yields: take them from the literature.",
            ),
        ),
        ToolDoc(
            name="predict_reaction_products",
            signature="predict_reaction_products(reactants, reagents=\"\", solvent=\"\", top_n=5)",
            purpose=(
                "Forward prediction: predictions[] {smiles, score} for a set of "
                "reactant SMILES."
            ),
            usage=(
                "A cross-check, not a verdict: a confident prediction can be wrong "
                "(dodecanol + chlorosulfonic acid came back as dodecanal). A "
                "mismatch with the expected product is a bottleneck to name.",
            ),
        ),
        ToolDoc(
            name="classify_reactions",
            signature="classify_reactions(reaction_smiles)",
            purpose=(
                "Reaction class per reaction SMILES: classes[] {rank, "
                "reaction_name, reaction_classname, reaction_superclassname, "
                "certainty}."
            ),
            usage=("Use it to name a step's operation from its reaction SMILES.",),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="economics_mcp_stub",
    factory=_microfluidics_stub_unless("economics_mcp_stub", "microfluidic_economic_url"),
    optional=True,  # dropped once the real MCP server is configured
    docs=(
        ToolDoc(
            name="economics_mcp_stub",
            signature="economics_mcp_stub(route)",
            purpose=(
                "(ЗАГЛУШКА) Costs a synthesis route: price per kg, reagent "
                "availability in Russia, and supply risks."
            ),
        ),
    ),
))

# The economics server's contract, as recorded in
# tests/fixtures/economics_mcp/ (scripts/mcp_contract_dump.py). Real tool names,
# so a Work Order can check them; the answers arrive as structuredContent.
REGISTRY.register_tool(ToolEntry(
    key="economics_mcp",
    factory=_microfluidic_economic,
    optional=True,  # built only when MCP_MICROFLUIDIC_ECONOMIC is configured
    runtime_resolved=True,  # real MCP server — tool surface comes from it
    docs=(
        ToolDoc(
            name="resolve_chemicals",
            signature="resolve_chemicals(names, use_llm=false)",
            purpose=(
                "Names or SMILES -> structures. Up to 200 per call. Returns "
                "items[]: {input, canonical_smiles, inchikey, formula, molar_mass, "
                "method, confidence, error, hint}; error \"unresolved\" means no "
                "structure, and a route using that name cannot be costed."
            ),
            usage=(
                "Russian trivial names often do NOT resolve (\"додеканол-1\", "
                "\"хлорсульфоновая кислота\" fail); English names and SMILES do "
                "(\"1-dodecanol\", \"chlorosulfonic acid\"). Send English names or "
                "SMILES.",
                "A string that reads both as a name and as SMILES (CO, NO, Br) is "
                "refused: write it as a SMILES object or a full name.",
            ),
        ),
        ToolDoc(
            name="rank_routes_by_cost",
            signature=(
                "rank_routes_by_cost(routes, target_qty, target_unit, default_yield=1.0, "
                "strategy=\"cheapest\", similarity=\"soft\", preferred_currency=\"RUB\", "
                "rank_by=\"per_unit\", include_breakdown=true)"
            ),
            purpose=(
                "Costs synthesis routes for ONE target amount and ranks them "
                "cheapest first. Returns routes[]: {route_id, status (ok | partial | "
                "invalid | unpriceable), rank, currency, cost_per_unit, cost_packs, "
                "starting_materials[] (smiles, qty, unit, moles), intermediates, "
                "missing[] (smiles, reason), steps_smiles, resolved_inputs, warnings, "
                "estimate (per-reagent line_items with the chosen offer)}, plus "
                "assumptions."
            ),
            usage=(
                "Route: {route_id, steps, target_smiles?, target_name?, overrides?}. "
                "Step: {reactants: [...], agents: [...], products: [...], conditions, "
                "yield (0-1)} — substances as {\"smiles\": ...} or English names; "
                "\"@prev\" in reactants is the previous step's product (never in the "
                "first step). Or a reaction SMILES string.",
                "target_unit is g, kg, mol or mmol (not a volume). default_yield 1.0 "
                "means no losses — pass real yields.",
                "Only starting materials are bought; agents (solvents, catalysts) are "
                "NOT in the sum unless given an amount or an override.",
                "partial = a lower bound (missing items are not priced). invalid = a "
                "name did not resolve (see warnings) — fix the name, run again.",
                "cost_per_unit is the cost of the quantity used; cost_packs is the "
                "real bill for whole packs. Compare costs only within one currency.",
            ),
        ),
        ToolDoc(
            name="estimate_synthesis_cost",
            signature=(
                "estimate_synthesis_cost(reagents, strategy=\"cheapest\", "
                "similarity=\"hard\", preferred_currency=\"RUB\")"
            ),
            purpose=(
                "Costs a plain list of reagents {smiles | name, qty, unit, "
                "purity_min?}. Returns line_items[] (match_level, chosen {supplier, "
                "name_raw, pack_qty, pack_unit, price, price_currency, unit_price}, "
                "packs_needed, cost_packs, cost_per_unit), total_by_currency, "
                "resolved_inputs, missing[]."
            ),
            usage=(
                "Use it for a set of reagents without a route (a solvent, a "
                "catalyst, a recheck). With similarity=hard any miss is an error "
                "no_exact_match; soft allows the nearest structure.",
            ),
        ),
        ToolDoc(
            name="get_price",
            signature="get_price(name, pack_unit=null, purity_grade=null, limit=50)",
            purpose=(
                "All offers for a fuzzy-matched name, cheapest per unit first: "
                "result[] {name_raw, supplier, purity_grade, pack_qty, pack_unit, "
                "price, price_currency, unit_price, price_basis}."
            ),
            usage=(
                "Explains a missing or suspicious item: read name_raw — a match may "
                "be a solution (\"0,1Н\"), another grade or a neighbour by name "
                "(\"ацетон\" also matches \"ацетилацетон\").",
            ),
        ),
        ToolDoc(
            name="search_by_structure",
            signature="search_by_structure(smiles=null, name=null, mode=\"exact\", limit=50)",
            purpose=(
                "Offers by structure (give smiles OR name): per compound the cheapest "
                "offer, with match_level (точный, по_связности, подструктура)."
            ),
            usage=("mode=substructure finds molecules containing the fragment.",),
        ),
        ToolDoc(
            name="search_reagents_by_name",
            signature="search_reagents_by_name(query, limit=20)",
            purpose=(
                "Fuzzy search by Russian name, one row per reagent: result[] "
                "{name_norm, supplier, best_price, price_currency, unit_price, "
                "pack_qty, pack_unit, offer_count, similarity}."
            ),
            usage=("For finding how a reagent is listed in the price lists.",),
        ),
    ),
))

# The CFD service's contract, as recorded in tests/fixtures/cfd_mcp/
# (scripts/mcp_contract_dump.py). A run is asynchronous: it blocks up to
# wait_seconds, then the result is fetched by the caller-chosen request_id.
REGISTRY.register_tool(ToolEntry(
    key="cfd_mcp",
    factory=_microfluidic_cfd,
    optional=True,  # built only when MCP_MICROFLUIDIC_CFD_3_TOOLS is configured
    runtime_resolved=True,  # real MCP server — tool surface comes from it
    docs=(
        ToolDoc(
            name="cfd_list_reactors",
            signature="cfd_list_reactors()",
            purpose=(
                "The reactor geometries: reactors[] {reactor (the id to run), title, "
                "description, available, zones {inlets, outlets, inlet_count, "
                "supports_two_reactant_feed}}."
            ),
            usage=(
                "An A + B reaction needs supports_two_reactant_feed=true; "
                "available=false means the mesh is not on the host.",
            ),
        ),
        ToolDoc(
            name="cfd_run_reactor_experiment",
            signature=(
                "cfd_run_reactor_experiment(reactor, inlet_speed_m_per_s, "
                "concentration_a_mol_per_m3, concentration_b_mol_per_m3, "
                "rate_constant_m3_per_mol_s, temperature_k=298.15, turnovers=4, "
                "wait_seconds=600, request_id)"
            ),
            purpose=(
                "Runs flow -> mixing -> reaction on one reactor for A + B -> C and "
                "returns status (succeeded | failed | cancelled | pending), design "
                "(the parameters used), derived.operating_point (flow rate, "
                "residence_time_s_estimate), results (pressure_drop_pa, "
                "residence_time_s, damkohler, conversion_by_reactant, outlet "
                "concentrations, mixing index), trustworthy, blocking, stages[] "
                "(exit_code per stage) and error {code, message}."
            ),
            usage=(
                "Always pass your own request_id (e.g. \"exp1-cfd-1\"): reusing it "
                "returns the same run instead of starting another; a FAILED run "
                "reused starts afresh.",
                "Units: concentrations in mol/m3 (1 mol/L = 1000 mol/m3), rate "
                "constant in m3/(mol*s), temperature in K, inlet speed in m/s "
                "(flow rate = speed x inlet area).",
                "status pending: the call stopped waiting, the run goes on — fetch it "
                "with cfd_get_experiment_result. The service runs ONE experiment at a "
                "time: error capacity_exceeded means wait and retry the same request_id.",
                "A result is valid only with blocking empty; a run under 3 residence "
                "times reports near-zero conversion that means \"still filling\" — "
                "raise turnovers. Aim for damkohler 1-10; do not tune the diffusivity.",
            ),
        ),
        ToolDoc(
            name="cfd_get_experiment_result",
            signature="cfd_get_experiment_result(request_id)",
            purpose=(
                "The run by request_id, same payload as the run call. pending — "
                "still running; succeeded, failed, cancelled — final."
            ),
            usage=(
                "Between polls of a pending run wait with sleep_tool — do not poll "
                "in a tight loop.",
            ),
        ),
        ToolDoc(
            name="cfd_list_artifacts",
            signature="cfd_list_artifacts(request_id, offset=0, limit=50)",
            purpose=(
                "Files the run produced: keys[] are paths on the CFD host, not "
                "links — cite their count, not the paths."
            ),
        ),
        ToolDoc(
            name="cfd_cancel_run",
            signature="cfd_cancel_run(request_id)",
            purpose="Stops a run in progress (only your own, only if it is no longer needed).",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="cfd_mcp_stub",
    factory=_microfluidics_stub_unless("cfd_mcp_stub", "microfluidic_cfd_url"),
    optional=True,  # dropped once the real MCP server is configured
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

def _optimization_a2a():
    from CoScientist.microfluidics.a2a_optimization.adapter import (
        optimization_start, optimization_get_status,
        optimization_provide_input, optimization_approve,
    )
    return [optimization_start, optimization_get_status, optimization_provide_input, optimization_approve]


def _operator_screening_override():
    from CoScientist.microfluidics.operator_override import operator_authorize_screening_override
    return [operator_authorize_screening_override]


REGISTRY.register_tool(ToolEntry(
    key="optimization_a2a",
    factory=_optimization_a2a,
    docs=(
        ToolDoc(
            name="optimization_start",
            signature="optimization_start(planning_only=False)",
            purpose="Delegate the whole CFD/equipment/optimization workflow with validated TZ, literature, routes and ranking. Reuses the existing task even after completion. planning_only=True forbids execution.",
        ),
        ToolDoc(
            name="optimization_get_status",
            signature="optimization_get_status()",
            purpose="Poll the same A2A task and preserve all raw responses/artifacts. input_required is a request for clarification or approval, not completion.",
        ),
        ToolDoc(
            name="optimization_provide_input",
            signature="optimization_provide_input(details)",
            purpose="Reply to waiting_input with known facts or user clarification, preserving task/context/experiment IDs. Never invent parameters.",
        ),
        ToolDoc(
            name="optimization_approve",
            signature="optimization_approve()",
            purpose="Approve the external plan at input_required/approval within the authorized work order. May start remote equipment. Unavailable in planning-only mode.",
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="operator_screening_override",
    factory=_operator_screening_override,
    docs=(
        ToolDoc(
            name="operator_authorize_screening_override",
            signature="operator_authorize_screening_override(route_ids, rationale)",
            purpose=(
                "Ask the human operator to authorize a planning-only verification "
                "handoff for real routes rejected by automatic qualification. "
                "It cannot make a route eligible or authorize equipment execution."
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
    key="result_formatter",
    factory=_result_formatter,
    docs=(
        ToolDoc(
            name="format_results",
            signature="format_results()",
            purpose=(
                "Collect every figure and data table this run produced (from session "
                "artifacts and the sandbox workspace) into the per-run report folder and "
                "return ready-to-embed Markdown blocks (image embeds + tables). Call FIRST."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="nir_report",
    factory=_nir_report,
    optional=True,  # built only when MCP__NORMCONTROL_URL is configured
    docs=(
        ToolDoc(
            name="nir_report_outline",
            signature="nir_report_outline()",
            purpose=(
                "Show the planned GOST 7.32-2017 report: section ids, the evidence "
                "recorded for each, figures awaiting captions, and gaps. Call FIRST "
                "and write only from what it returns."
            ),
        ),
        ToolDoc(
            name="nir_report_draft",
            signature=(
                "nir_report_draft(research_title, report_title, abstract_text, keywords, "
                "introduction_paragraphs, conclusion_paragraphs, section_texts, "
                "figure_captions=None, terms=None, abbreviations=None)"
            ),
            purpose=(
                "Assemble your prose into the GOST document and check it locally — "
                "no network, so iterate freely. Returns unwritten sections, contract "
                "problems and style warnings."
            ),
        ),
        ToolDoc(
            name="nir_report_submit",
            signature="nir_report_submit()",
            purpose=(
                "Validate the draft on the normcontrol server, build the DOCX and "
                "return a permanent download link plus the server's warnings."
            ),
        ),
    ),
))

REGISTRY.register_tool(ToolEntry(
    key="dynamic_tools",
    factory=_dynamic_tools,
    runtime_resolved=True,  # tool surface is the task's MCP servers, resolved per turn from state
    docs=(
        ToolDoc(
            name="<dynamic MCP tools>",
            signature="(varies)",
            purpose=(
                "The MCP tools selected for THIS task by the tool-prep pipeline "
                "(filtered_tools/deployed_mcps). Call them directly to run the work."
            ),
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
    optional=True,  # dropped when WEB__CODER_LOCAL_TOOLS_ENABLED is false
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
            signature="list_directory(path)",
            purpose="List files in a directory.",
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

REGISTRY.register_tool(ToolEntry(
    key="alembic",
    factory=_alembic,
    docs=(
        ToolDoc(
            name="build_mcp_server",
            signature="build_mcp_server(repo_url, force_rebuild)",
            purpose=(
                "Start an Alembic build: turn a scientific GitHub repository into "
                "a served MCP tool server (clone -> env -> generated+validated "
                "tools -> FastMCP server in Docker)."
            ),
            usage=(
                "Returns immediately with a job_id; the build itself runs in the "
                "background and takes tens of minutes — report the job_id and "
                "do NOT poll it in a tight loop, check back later instead.",
                "Reuses an already running/done build for the same repo_url "
                "unless force_rebuild=true is passed.",
            ),
        ),
        ToolDoc(
            name="check_mcp_build",
            signature="check_mcp_build(job_id)",
            purpose=(
                "Check the status of a build started by build_mcp_server: "
                "\"running\" with the current pipeline stage and a log tail, "
                "\"done\" with the served mcp_url/image/container, or \"failed\" "
                "with the error tail of the build log."
            ),
        ),
        ToolDoc(
            name="list_mcp_builds",
            signature="list_mcp_builds()",
            purpose=(
                "List every Alembic build known to this process (running and "
                "finished) — use it to find a build from an earlier "
                "delegation/session (e.g. a lost job_id)."
            ),
        ),
    ),
))

_SANDBOX_TAIL_DOCS = (
    ToolDoc(
        name="check_sandbox_task",
        signature="check_sandbox_task()",
        purpose=(
            "Pick up the result of a sandbox task that came back "
            "\"running\". You normally do NOT need it — run_sandbox_task "
            "already waits and returns the result."
        ),
        usage=(
            "It waits inline; if the answer is still \"running\", do other "
            "work and check once later — never poll in a tight loop.",
        ),
    ),
    ToolDoc(
        name="list_sandbox_files",
        signature="list_sandbox_files(path)",
        purpose=(
            "List files in the sandbox workspace — use it to VERIFY that the "
            "artifacts the sandbox agent reported really exist before you "
            "rely on them."
        ),
    ),
)


def _sandbox_docs():
    """Sandbox docs, phrased for whether the local coder toolset is also there.

    With both, the sandbox is the escalation path for heavy jobs and the two
    workspaces must not be confused. Alone, it IS the way the agent runs
    anything, so the guidance must not point back at execute_bash.
    """
    if _is_local_coder():
        run_usage = (
            "The sandbox is a SEPARATE machine from your execute_bash "
            "workspace — files do NOT cross between them. Data goes in via "
            "`dataset_url`; results come back as the summary.",
            "It is bound to your session: the first call creates it, later "
            "calls continue in the SAME sandbox with its files and memory "
            "intact — so build one experiment up over several calls.",
            "Pass `new_sandbox=True` ONLY for an independent experiment on a "
            "clean machine; everything the previous one produced is lost.",
            "Say exactly what the deliverable is and where to write it — you "
            "cannot watch it work, you only get its report back.",
            "For ordinary code, shell and git work keep using execute_bash.",
        )
    else:
        run_usage = (
            "This is your ONLY way to run anything: you have no local shell, "
            "so every command, script, clone and install happens here. Data "
            "goes in via `dataset_url`; results come back as the summary.",
            "`task` is the task you were given, forwarded as it is — the agent "
            "on the other side plans and writes the code itself.",
            "It is bound to your session: the first call creates it, later "
            "calls continue in the SAME sandbox with its files and memory "
            "intact — so successive tasks build on each other.",
            "Pass `new_sandbox=True` ONLY for an independent experiment on a "
            "clean machine; everything the previous one produced is lost.",
            "Send the WHOLE task in one call — each call spins up a full "
            "coding agent; you cannot watch it work, you only get its report.",
        )
    return (
        ToolDoc(
            name="run_sandbox_task",
            signature="run_sandbox_task(task, dataset_url, new_sandbox)",
            purpose=(
                "Delegate a HEAVY / long-running / GPU-bound job (training runs, "
                "large data processing, long experiments) to an autonomous agent "
                "in the OpenHands sandbox. Waits inline and returns that agent's "
                "report; hands back status \"running\" only if the job outlives "
                "the wait."
            ),
            usage=run_usage,
        ),
    ) + _SANDBOX_TAIL_DOCS


REGISTRY.register_tool(ToolEntry(
    key="sandbox",
    factory=_sandbox,
    # Dropped silently in deployments where SANDBOX_URL is unset — the prompt
    # then never advertises a sandbox the agent does not have.
    optional=True,
    docs=_sandbox_docs,
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

# Attached the same way, by the per-agent `work_order: true` flag.
WORK_ORDER_TOOL_DOCS = (
    ToolDoc(
        name="declare_work_order",
        signature=(
            "declare_work_order(goal, done_criteria, assumptions, steps, planned_tools, "
            "expected_outcome, fallback)"
        ),
        purpose=(
            "(Work Order) Declare your contract BEFORE your first external action: "
            "goal, assumptions (a list of strings), "
            "steps, tools, expected outcome. "
            "Returns status approved / revise / rejected."
        ),
    ),
    ToolDoc(
        name="update_work_order",
        signature="update_work_order(reason, add_tools, add_steps)",
        purpose=(
            "(Work Order) Amend the approved contract when you need a tool or step "
            "it does not cover. The human reviews the diff."
        ),
    ),
    ToolDoc(
        name="update_work_step",
        signature="update_work_step(step_id, status, note)",
        purpose=(
            "(Work Order) Mark a step in_progress / done / skipped as you go, so the "
            "human can follow the plan live."
        ),
    ),
    ToolDoc(
        name="submit_work_report",
        signature=(
            "submit_work_report(summary, findings, done_verdict, done_evidence, "
            "actual_outcome, artifacts)"
        ),
        purpose=(
            "(Work Order) Before your final answer, report what you found (with "
            "evidence) and produced. The human accepts it, sends it back for rework "
            "or rejects it. Returns status accepted / revise / rejected."
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


def _capture_mcp_artifacts():
    from CoScientist.agents.callbacks import capture_mcp_artifacts
    return capture_mcp_artifacts


def _mirror_plan_after_create():
    from CoScientist.agents.callbacks import mirror_plan_after_create
    return mirror_plan_after_create


def _mirror_plan_before_agent():
    from CoScientist.agents.callbacks import mirror_plan_before_agent
    return mirror_plan_before_agent


def _skip_retriever_context():
    from CoScientist.agents.callbacks import before_tool_reranker_model
    return before_tool_reranker_model


def _shortlist_reranker_tools():
    from CoScientist.agents.callbacks import shortlist_reranker_tools
    return shortlist_reranker_tools


def _collect_reranked_tools():
    from CoScientist.agents.callbacks import after_tool_reranker_agent
    return after_tool_reranker_agent


def _collect_reranked_tools_from_model():
    from CoScientist.agents.callbacks import after_tool_reranker_model
    return after_tool_reranker_model


def _collect_reranked_mcps():
    from CoScientist.agents.callbacks import after_fullset_reranker_agent
    return after_fullset_reranker_agent


def _redirect_when_no_tools():
    from CoScientist.agents.callbacks import redirect_when_no_tools
    return redirect_when_no_tools


def _inject_fedot_candidates():
    from CoScientist.agents.callbacks import inject_fedot_candidates
    return inject_fedot_candidates


def _before_get_task():
    from CoScientist.agents.callbacks import before_get_task
    return before_get_task

def _inject_original_query():
    from CoScientist.agents.callbacks import inject_original_query
    return inject_original_query

def _inject_upstream_artifacts():
    # Kept for default system.yaml / non-EM profiles. EM uses
    # seed_upstream_from_resolved_inputs at start_task instead.
    from CoScientist.tools.fedot_artifact_handoff import inject_upstream_artifacts
    return inject_upstream_artifacts


def _inject_graph_root():
    from CoScientist.agents.callbacks import inject_graph_root
    return inject_graph_root


def _inject_dataset_context():
    from CoScientist.agents.callbacks import inject_dataset_context
    return inject_dataset_context


def _inject_report_language():
    from CoScientist.agents.callbacks import inject_report_language
    return inject_report_language


def _user_links():
    from CoScientist.agents.callbacks import user_links
    return user_links


def _resolve_link_refs():
    from CoScientist.agents.callbacks import resolve_link_refs
    return resolve_link_refs


def _register_tool_result_links():
    from CoScientist.agents.callbacks import register_tool_result_links
    return register_tool_result_links


def _expand_link_refs():
    from CoScientist.agents.callbacks import expand_link_refs
    return expand_link_refs


def _redact_link_urls():
    from CoScientist.agents.callbacks import redact_link_urls
    return redact_link_urls


def _inject_research_context(ctx):
    """before_agent callback seeding state['research_context']. The orchestrator
    (root) gets the overview + trigger digest; a worker gets its focus slice.
    Which branch is baked in at build time from the agent's role."""
    from CoScientist.graph.research.agent_tools import make_inject_research_context
    is_root = bool(getattr(ctx.config, "root", False))
    return make_inject_research_context(is_root=is_root)


def _web_search_limiter():
    from CoScientist.agents.callbacks.tool_callbacks import SearchLimiter
    from CoScientist.config import get_settings
    return SearchLimiter(max_searches=get_settings().web.max_searches).limit_searches


def _count_research_searches():
    from CoScientist.agents.callbacks.tool_callbacks import SearchLimiter
    from CoScientist.config import get_settings
    return SearchLimiter(max_searches=get_settings().web.max_searches).record_search_result


def _reset_research_searches():
    from CoScientist.agents.callbacks.tool_callbacks import SearchLimiter
    from CoScientist.config import get_settings
    return SearchLimiter(max_searches=get_settings().web.max_searches).reset_search_budget


def _tavily_search_limiter():
    from CoScientist.agents.callbacks.tool_callbacks import TavilySearchLimiter
    from CoScientist.config import get_settings
    return TavilySearchLimiter(max_searches=get_settings().web.max_searches).limit_searches


def _per_tool_call_limiter():
    from CoScientist.agents.callbacks.tool_callbacks import PerToolCallLimiter
    return PerToolCallLimiter(max_calls=2).limit_tool_calls


def _paper_search_guard():
    from CoScientist.agents.callbacks.tool_callbacks import PaperSearchGuard
    return PaperSearchGuard().guard_paper_search


def _forbid_explore_my_papers():
    from CoScientist.agents.callbacks.tool_callbacks import ForbidExploreMyPapersGuard
    return ForbidExploreMyPapersGuard().guard_tool


def _sanitize_json_output():
    from CoScientist.agents.callbacks import sanitize_json_output
    return sanitize_json_output


def _microfluidics_evidence(name: str):
    def factory(ctx):
        from CoScientist.microfluidics import evidence
        return getattr(evidence, name)
    return factory


def _save_tz_document():
    from CoScientist.microfluidics.tz_agent import save_tz_document
    return save_tz_document


def _microfluidics_literature(name: str):
    def factory(ctx):
        from CoScientist.microfluidics import literature
        return getattr(literature, name)
    return factory


def _use_fixed_target_molecule():
    from CoScientist.microfluidics.design import use_fixed_target_molecule
    return use_fixed_target_molecule


def _use_selected_route_product():
    from CoScientist.microfluidics.design import use_selected_route_product
    return use_selected_route_product


def _collect_cfd_result():
    from CoScientist.microfluidics.cfd import collect_cfd_result
    return collect_cfd_result


def _collect_economics_result():
    from CoScientist.microfluidics.economics import collect_economics_result
    return collect_economics_result


def _microfluidics_requirements():
    from CoScientist.microfluidics.requirements import compile_requirements_callback
    return compile_requirements_callback


def _microfluidics_research_record(name: str):
    def factory(ctx):
        from CoScientist.microfluidics import research_record
        return getattr(research_record, name)
    return factory


def _publish_literature_summary():
    from CoScientist.microfluidics.literature_report import publish_literature_summary
    return publish_literature_summary


def _microfluidics_route_compliance(name: str):
    from CoScientist.microfluidics import route_compliance
    return getattr(route_compliance, name)


def _normalize_literature_identities():
    from CoScientist.microfluidics.chemistry_identity import normalize_literature_identities
    return normalize_literature_identities


def _export_tz_and_queries():
    from CoScientist.microfluidics.export import export_tz_and_queries
    return export_tz_and_queries



def _guard_unknown_tools(ctx):
    """after_model guard capturing the agent's REAL tool names from its context,
    so a hallucinated tool call is corrected instead of crashing the run.

    The valid set must include BOTH the agent's function tools AND its
    subordinate AgentTools: sub-agents (e.g. CoderAgent, DatasetCollectorAgent)
    are legitimate call targets but are attached outside `tool_entries`, so
    leaving them out makes the guard false-block real delegations.

    Agents whose tool surface is resolved at runtime (dynamic MCP toolsets,
    e.g. ExperimentAgent) can't be guarded — their real tools aren't known at
    build time — so skip the guard for them to avoid blocking valid calls."""
    from CoScientist.agents.callbacks import make_unknown_tool_guard
    docs = [d for e in ctx.tool_entries for d in e.resolved_docs()]
    # A placeholder doc (name in <angle brackets>, e.g. "<dynamic MCP tools>")
    # marks a toolset whose real tool names are resolved per turn from state
    # (ExperimentAgent's dynamic MCP tools) — we can't enumerate them at build
    # time, so skip the guard rather than false-block valid calls. Fixed
    # BaseToolsets (graph, task_tracker) are runtime_resolved too but DO declare
    # their real tool names in docs, so they stay guarded.
    if any(d.name.startswith("<") for d in docs):
        return None
    names = [d.name for d in docs]
    names += [s.name for s in ctx.subordinates]  # subordinate AgentTools
    return make_unknown_tool_guard(names)


def _finish_after_plan_registered():
    from CoScientist.agents.callbacks import make_plan_registration_guard
    return make_plan_registration_guard()


def _pre_action_critique(ctx):
    from CoScientist.agents.callbacks import make_pre_action_critique
    return make_pre_action_critique(REGISTRY.prompt("pre_action_critic")(ctx))


def _post_action_critique(ctx):
    from CoScientist.agents.callbacks import make_post_action_critique
    return make_post_action_critique(REGISTRY.prompt("post_action_critic")(ctx))


def make_plan_critic(ctx):
    """The planner's plan critic, for agents declaring ``critic:`` in the YAML.

    Not an ADK callback (no callback can make the planner redo its roadmap):
    the assembler passes it to the session agent, which owns the review loop.
    Built here anyway so the assembler keeps looking things up instead of
    importing agent internals — and so the critic's prompt is rendered from the
    same PromptContext that wires the agents its plans may assign work to.
    """
    from CoScientist.agents.callbacks import make_plan_critique
    return make_plan_critique(REGISTRY.prompt("plan_critic")(ctx))


def _hitl_before_model():
    from CoScientist.agents.common import hitl_handler
    from CoScientist.hitl.callbacks import make_hitl_before_callback
    return make_hitl_before_callback(hitl_handler)


def _ask_pipeline_scope():
    from CoScientist.agents.common import hitl_handler
    from CoScientist.hitl.pipeline_scope import make_ask_pipeline_scope_callback
    return make_ask_pipeline_scope_callback(hitl_handler)


def _ask_nir_report():
    from CoScientist.agents.common import hitl_handler
    from CoScientist.reporting.nir.callback import make_ask_nir_report_callback
    return make_ask_nir_report_callback(hitl_handler)


def _enforce_pipeline_scope_hops():
    from CoScientist.hitl.pipeline_scope import enforce_pipeline_scope_hops
    return enforce_pipeline_scope_hops


def _mark_pipeline_scope_lane():
    from CoScientist.hitl.pipeline_scope import mark_pipeline_scope_lane
    return mark_pipeline_scope_lane
def _hitl_before_tool():
    from CoScientist.agents.common import hitl_handler
    from CoScientist.hitl.callbacks import make_hitl_before_tool_callback
    return make_hitl_before_tool_callback(hitl_handler, target_tools=("run_sandbox_task",))


# Plain callbacks are registered through tiny lazy factories that ignore the
# context — so importing bindings never drags in S3/opik/etc. transitively.
_cb("save_uploaded_artifacts", "before_model", factory=lambda ctx: _save_uploaded_artifacts())
# Pin the coder sandbox to the ADK session (one workspace per session).
_cb("seed_coder_workspace", "before_model", factory=lambda ctx: _seed_coder_workspace())
_cb("inject_medical_artifacts", "before_model", factory=lambda ctx: _inject_medical_artifacts())
_cb("inject_uploaded_papers", "before_model", factory=lambda ctx: _inject_uploaded_papers())
_cb("log_research_tool_calls", "after_tool", factory=lambda ctx: _log_research_tool_calls())
_cb("capture_mcp_artifacts", "after_tool", factory=lambda ctx: _capture_mcp_artifacts())
# The registered plan becomes the research graph's method column, deterministically.
# Two hooks because either path can be the one that fires: `create_plan` belongs to
# an agent that ships disabled, and an operator can register a roadmap from the web.
_cb("mirror_plan_after_create", "after_tool", factory=lambda ctx: _mirror_plan_after_create())
_cb("mirror_plan_before_agent", "before_agent", factory=lambda ctx: _mirror_plan_before_agent())
_cb("skip_retriever_context", "before_model", factory=lambda ctx: _skip_retriever_context())
# Cross-encoder pre-pass: hand the LLM reranker a short list, not everything.
_cb("shortlist_reranker_tools", "before_agent", factory=lambda ctx: _shortlist_reranker_tools())
_cb("collect_reranked_tools", "after_agent", factory=lambda ctx: _collect_reranked_tools())
_cb(
    "collect_reranked_tools_from_model",
    "after_model",
    factory=lambda ctx: _collect_reranked_tools_from_model(),
)
_cb("collect_reranked_mcps", "after_agent", factory=lambda ctx: _collect_reranked_mcps())
# Coder↔Executor redirect: abstain to CoderAgent when no tool matched the task.
_cb("redirect_when_no_tools", "before_agent", factory=lambda ctx: _redirect_when_no_tools())
# Reranker fallback: show FedotAgent the candidate pool fedot_tool will receive.
_cb("inject_fedot_candidates", "before_agent", factory=lambda ctx: _inject_fedot_candidates())
# Load active tasks into agent state before the agent runs.
_cb("before_get_task", "before_agent", factory=lambda ctx: _before_get_task())
# Project prior MCP CSV columns onto the current tools' input_schema arg names.
# EM profile omits this — start_task seeds via seed_upstream_from_resolved_inputs.
_cb(
    "inject_upstream_artifacts",
    "before_agent",
    factory=lambda ctx: _inject_upstream_artifacts(),
)
_cb("inject_original_query", "before_model", factory=lambda ctx: _inject_original_query())
# Give the orchestrator/planner the knowledge-graph root (agents + history) up front.
_cb("inject_graph_root", "before_agent", factory=lambda ctx: _inject_graph_root())
# Seed state['research_context'] from the research blackboard (role-dependent).
_cb("inject_research_context", "before_agent", factory=_inject_research_context)
# Tell the agent about the dataset archive the user attached in the web UI; it
# decides itself which calls need the link.
_cb("inject_dataset_context", "before_agent", factory=lambda ctx: _inject_dataset_context())
# Report language the user picked for this session: inject the whole block
# (headings, substitution rule, glossary), not a bare language name.
_cb("inject_report_language", "before_agent", factory=lambda ctx: _inject_report_language())
_cb("user_links", "before_agent", factory=lambda ctx: _user_links())
_cb("redact_link_urls", "before_model", factory=lambda ctx: _redact_link_urls())
_cb("resolve_link_refs", "before_tool", factory=lambda ctx: _resolve_link_refs())
_cb("register_tool_result_links", "after_tool", factory=lambda ctx: _register_tool_result_links())
_cb("expand_link_refs", "after_model", factory=lambda ctx: _expand_link_refs())
# Human-In-The-Loop approval callback before model/agent/tool execution.
_cb("hitl_before_model", "before_model", factory=lambda ctx: _hitl_before_model())
_cb("hitl_before_agent", "before_agent", factory=lambda ctx: _hitl_before_model())
_cb("ask_pipeline_scope", "before_agent", factory=lambda ctx: _ask_pipeline_scope())
# Asks, once per session, whether the run should also produce a GOST 7.32-2017
# NIR report, and collects the title-page requisites nothing else knows. Inert
# unless NIR__ENABLED, MCP__NORMCONTROL_URL and HITL are all on.
_cb("ask_nir_report", "before_agent", factory=lambda ctx: _ask_nir_report())
_cb(
    "enforce_pipeline_scope_hops",
    "after_model",
    factory=lambda ctx: _enforce_pipeline_scope_hops(),
)
_cb(
    "mark_pipeline_scope_lane",
    "after_tool",
    factory=lambda ctx: _mark_pipeline_scope_lane(),
)
_cb("hitl_before_tool", "before_tool", factory=lambda ctx: _hitl_before_tool())
# Limit web search calls per agent turn.
_cb("WebSearchLimiter", "before_tool", factory=lambda ctx: _web_search_limiter())
_cb("count_research_searches", "after_tool", factory=lambda ctx: _count_research_searches())
_cb("reset_research_searches", "before_agent", factory=lambda ctx: _reset_research_searches())
# A separate per-agent quota for EconomicsAgent / OptimizerAgent Tavily fallback.
_cb("TavilySearchLimiter", "before_tool", factory=lambda ctx: _tavily_search_limiter())
# Microfluidics ResearchAgent budget: two calls per concrete tool and per
# delegated agent branch, so parallel LIT-* tasks never share a counter.
_cb("PerToolCallLimiter", "before_tool", factory=lambda ctx: _per_tool_call_limiter())
# Clamp OpenAlex result sets before the request reaches the remote papers MCP.
_cb("PaperSearchGuard", "before_tool", factory=lambda ctx: _paper_search_guard())
# Forbid ResearchAgent from calling explore_my_papers (reserved for PaperRetriever).
_cb("ForbidExploreMyPapers", "before_tool", factory=lambda ctx: _forbid_explore_my_papers())
# Catch hallucinated tool calls (e.g. `find`) and correct instead of crashing.
_cb("guard_unknown_tools", "after_model", factory=_guard_unknown_tools)
# End the planner's turn once its plan is registered, so it cannot loop
# re-registering to undo create_plan's own normalisation.
_cb("finish_after_plan_registered", "after_model",
    factory=lambda ctx: _finish_after_plan_registered())
# Trim prose/fences/trailing text around a JSON answer BEFORE strict
# output_schema validation (providers don't always honour response_format).
_cb("sanitize_json_output", "after_model", factory=lambda ctx: _sanitize_json_output())
_cb("begin_evidence_verification", "before_agent",
    factory=_microfluidics_evidence("begin_evidence_verification"))
_cb("capture_evidence_verification", "after_tool",
    factory=_microfluidics_evidence("capture_evidence_verification"))
_cb("authenticate_evidence_verification", "after_agent",
    factory=_microfluidics_evidence("authenticate_evidence_verification"))
_cb("normalize_literature_identities", "after_agent",
    factory=lambda ctx: _normalize_literature_identities())
# Render the approved ТЗ into the reference Markdown document (state + file).
_cb("save_tz_document", "after_agent", factory=lambda ctx: _save_tz_document())
# Save the ТЗ + literature queries as shareable Markdown & HTML for hand-off.
_cb("export_tz_and_queries", "after_agent", factory=lambda ctx: _export_tz_and_queries())
# ── Experiment Module callbacks ──────────────────────────────────────────────
# Every EM callback is a plain (context-independent) function, so they are
# registered table-driven: (registry key, hook, "package:attr"), one lazy
# import per resolve. Keys and hooks must stay in sync with experiments.yaml.
_EM = "CoScientist.experiments"
_EM_CALLBACKS: tuple[tuple[str, str, str], ...] = (
    # Bounded planner context plus hard AgentTool route guard.
    ("build_experiment_context", "before_agent", f"{_EM}.context:build_experiment_context"),
    ("commit_experiment_hypotheses", "after_agent", f"{_EM}.hypotheses:commit_experiment_hypotheses"),
    ("persist_experiment_em_request", "before_agent", f"{_EM}.hypotheses:persist_experiment_em_request"),
    ("bootstrap_research_question_if_empty", "before_agent", f"{_EM}.hypotheses:bootstrap_research_question_if_empty"),
    ("seed_hypotheses_from_em_request", "before_model", f"{_EM}.hypotheses:seed_hypotheses_from_em_request"),
    ("enforce_hypothesis_research_commit", "after_model", f"{_EM}.hypotheses:enforce_hypothesis_research_commit"),
    ("normalize_em_hypothesis_commit", "after_model", f"{_EM}.hypotheses:normalize_em_hypothesis_commit"),
    ("capture_hypotheses_after_research_commit", "after_tool", f"{_EM}.hypotheses:capture_hypotheses_after_research_commit"),
    ("reset_experiment_retrieval_budget", "before_agent", f"{_EM}.context:reset_experiment_retrieval_budget"),
    ("enforce_experiment_retrieval_budget", "after_model", f"{_EM}.context:enforce_experiment_retrieval_budget"),
    ("snapshot_experiment_discovered_capabilities", "after_agent", f"{_EM}.context:snapshot_experiment_discovered_capabilities"),
    ("stash_experiment_retrieved_capabilities", "before_agent", f"{_EM}.context:stash_experiment_retrieved_capabilities"),
    # Same snapshot, after ToolRetriever finishes (reranker clears accumulated_tools).
    ("persist_experiment_retrieved_capabilities", "after_agent", f"{_EM}.context:stash_experiment_retrieved_capabilities"),
    ("skip_executor_without_runtime", "before_agent", f"{_EM}.context:skip_executor_without_runtime"),
    # After ToolPreparer: lit/knowledge asks with no compute signal → NO_MATCHING_TOOL
    # before Hypotheses/Plan/Coder burn budget on unrelated inventory.
    ("assess_experiment_inventory_feasibility", "after_agent", f"{_EM}.runtime:assess_experiment_inventory_feasibility"),
    ("skip_when_experiment_not_feasible", "before_agent", f"{_EM}.runtime:skip_when_experiment_not_feasible"),
    ("skip_when_experiment_stage_complete", "before_agent", f"{_EM}.runtime:skip_when_experiment_stage_complete"),
    ("guard_experiment_route", "before_tool", f"{_EM}.runtime:guard_route_agent_tool"),
    ("pin_alembic_build_args", "before_tool", f"{_EM}.runtime:pin_alembic_build_args"),
    ("pin_fedot_alembic_task", "before_tool", f"{_EM}.runtime:pin_fedot_alembic_task"),
    ("await_alembic_job_if_experiment", "after_tool", f"{_EM}.runtime:await_alembic_job_if_experiment"),
    ("force_schema_s3_upload", "before_tool", f"{_EM}.runtime:force_schema_s3_upload"),
    ("force_molecule_generator_s3_upload", "before_tool", f"{_EM}.runtime:force_molecule_generator_s3_upload"),
    ("mark_experiment_route_returned", "after_tool", f"{_EM}.runtime:on_route_agent_returned"),
    ("enforce_pending_record_result", "after_model", f"{_EM}.runtime:enforce_pending_record_result"),
    ("enforce_continue_until_reporting", "after_model", f"{_EM}.runtime:enforce_continue_until_reporting"),
    ("rewrite_mismatched_control_action", "after_model", f"{_EM}.runtime:rewrite_mismatched_control_action"),
    # Collapse parallel ExperimentModuleAgent fan-out into one merged request.
    ("coalesce_experiment_module_calls", "after_model", f"{_EM}.runtime:coalesce_experiment_module_calls"),
    ("suppress_experiment_module_after_completed", "after_model", f"{_EM}.runtime:suppress_experiment_module_after_completed"),
)


def _em_lazy_factory(path: str):
    module_name, attr = path.split(":", 1)
    return lambda ctx: getattr(import_module(module_name), attr)


for _key, _hook, _path in _EM_CALLBACKS:
    _cb(_key, _hook, factory=_em_lazy_factory(_path))

# Microfluidics module A: keep EVERY LIT-xx answer (search_results is
# overwritten per call), expose the ТЗ's target molecule as its own key, and
# let a fixed molecule from the ТЗ win in the literature analysis.
_cb("collect_literature_finding", "after_agent",
    factory=_microfluidics_literature("collect_literature_finding"))
_cb("inject_target_molecule", "before_agent",
    factory=_microfluidics_literature("inject_target_molecule"))
_cb("pin_target_molecule", "after_agent",
    factory=_microfluidics_literature("pin_target_molecule"))
_cb("assemble_selected_literature", "after_agent",
    factory=_microfluidics_literature("assemble_selected_literature"))
# Compile the approved human-readable TZ into the only requirements contract
# downstream chemistry stages may use.
_cb("compile_requirements", "before_agent", factory=lambda ctx: _microfluidics_requirements())
# Stage 4 proposals are assessed in code; stage 5 is skipped/guarded unless all
# hard constraints passed.
_cb("qualify_synthesis_routes", "after_agent",
    factory=lambda ctx: _microfluidics_route_compliance("qualify_synthesis_routes"))
_cb("gate_economics", "before_agent",
    factory=lambda ctx: _microfluidics_route_compliance("gate_economics"))
_cb("review_incomplete_economics_routes", "before_agent",
    factory=lambda ctx: _microfluidics_route_compliance("review_incomplete_economics_routes"))
_cb("review_preliminary_economics", "before_agent",
    factory=lambda ctx: _microfluidics_route_compliance("review_preliminary_economics"))
_cb("guard_economics_routes", "before_tool",
    factory=lambda ctx: _microfluidics_route_compliance("guard_economics_routes"))
# Microfluidics module B: keep the economics server's costing answers as given.
_cb("collect_economics_result", "after_tool", factory=lambda ctx: _collect_economics_result())
# Stage 3: a molecule fixed in the ТЗ is handed on as the only candidate — no design.
_cb("use_fixed_target_molecule", "before_agent", factory=lambda ctx: _use_fixed_target_molecule())
_cb("use_selected_route_product", "before_agent",
    factory=lambda ctx: _use_selected_route_product())
# Stage 9: keep the CFD service's run results as given, under their request ids.
_cb("collect_cfd_result", "after_tool", factory=lambda ctx: _collect_cfd_result())
# Microfluidics → research graph (the scientific-process record). Each stage
# writes its STRUCTURED result into the typed research graph from code
# (microfluidics/research_record.py): ТЗ → ResearchQuestion + Constraints +
# Tools + literature VerificationMethods; literature → Evidence; candidates →
# Hypotheses; routes → VerificationMethods; economics / optimisation →
# Evidence; report → Conclusion + Report. Best-effort, never breaks a run.
# They MUST precede any after_agent callback that returns chat Content
# (export_tz_and_queries, publish_literature_summary): ADK stops the chain at
# the first Content.
for _name in ("record_research_question", "record_literature_evidence",
              "record_design_hypotheses", "record_synthesis_routes",
              "record_economics_evidence", "record_experiment_evidence",
              "record_conclusion"):
    _cb(_name, "after_agent", factory=_microfluidics_research_record(_name))
# The literature agent's own deliverable for the report: summary + tables
# rendered from literature_analysis into state["literature_markdown"] and
# posted to the chat.
_cb("publish_literature_summary", "after_agent",
    factory=lambda ctx: _publish_literature_summary())
# Critic callbacks: their LLM prompts embed the orchestrator's current roster.
_cb("pre_action_critique", "after_model", factory=_pre_action_critique)
_cb("post_action_critique", "after_tool", factory=_post_action_critique)


# ── Agent classes / output schemas / planners ────────────────────────────────

def _register_classes() -> None:
    from CoScientist.agents.custom_agents import (
        ExecutorSwitchAgent,
        WebToolsDeployerAgent,
    )
    from CoScientist.hitl.session_agent import SessionAgent
    from CoScientist.microfluidics.tz_agent import TZSessionAgent
    from CoScientist.microfluidics.a2a_optimization.session_agent import OptimizationSessionAgent
    from CoScientist.microfluidics.route_selection import RouteSelectionSessionAgent
    from CoScientist.context_init.agent import ContextInitSessionAgent
    from CoScientist.experiments.review import ExperimentReviewSessionAgent

    REGISTRY.register_agent_class("session", SessionAgent)
    REGISTRY.register_agent_class("web_tools_deployer", WebToolsDeployerAgent)
    # Runs ONE of its children: the normal executor, or the reranker fallback.
    REGISTRY.register_agent_class("executor_switch", ExecutorSwitchAgent)
    # Microfluidics ТЗ stage: the review loop shows the RENDERED ТЗ document.
    REGISTRY.register_agent_class("tz_session", TZSessionAgent)
    REGISTRY.register_agent_class("optimization_session", OptimizationSessionAgent)
    REGISTRY.register_agent_class("route_selection_session", RouteSelectionSessionAgent)
    # Context-init pre-stage: the review shows a STRUCTURED FORM (research frame)
    # and seeds the confirmed frame into the research graph.
    REGISTRY.register_agent_class("context_init_session", ContextInitSessionAgent)
    REGISTRY.register_agent_class("experiment_review", ExperimentReviewSessionAgent)


def _register_schemas() -> None:
    from CoScientist.storage import MCPRanking, ToolRanking
    from CoScientist.microfluidics.models import (
        DesignCandidates,
        LiteratureAnalysis,
        LiteratureQueries,
        LiteratureSelection,
        RouteSelection,
        StructuredTZ,
        SynthesisRoutes,
    )
    from CoScientist.context_init.models import ResearchFrame
    from CoScientist.experiments.schemas import (
        ExperimentPlan,
        ExperimentTask,
        PlanCritique,
        TaskResult,
    )

    REGISTRY.register_output_schema("tool_ranking", ToolRanking)
    REGISTRY.register_output_schema("mcp_ranking", MCPRanking)
    # Microfluidics profile: structured ТЗ and the literature queries derived
    # from it (see CoScientist/agents/microfluidics.yaml).
    REGISTRY.register_output_schema("structured_tz", StructuredTZ)
    REGISTRY.register_output_schema("tz_literature_queries", LiteratureQueries)
    REGISTRY.register_output_schema("literature_analysis", LiteratureAnalysis)
    REGISTRY.register_output_schema("literature_selection", LiteratureSelection)
    REGISTRY.register_output_schema("route_selection", RouteSelection)
    # Module B hand-off: candidates and routes in the shape the economics server costs.
    REGISTRY.register_output_schema("design_candidates", DesignCandidates)
    REGISTRY.register_output_schema("synthesis_routes", SynthesisRoutes)
    # Framing entities of the meta-model, filled per run (context_init pre-stage).
    REGISTRY.register_output_schema("research_frame", ResearchFrame)
    REGISTRY.register_output_schema("experiment_plan", ExperimentPlan)
    REGISTRY.register_output_schema("experiment_task", ExperimentTask)
    REGISTRY.register_output_schema("task_result", TaskResult)
    REGISTRY.register_output_schema("plan_critique", PlanCritique)


def _register_planners() -> None:
    from google.adk.planners import PlanReActPlanner

    REGISTRY.register_planner("plan_react", PlanReActPlanner)


_register_classes()
_register_schemas()
_register_planners()
