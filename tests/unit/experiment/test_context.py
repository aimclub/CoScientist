"""Planner context, stash, repo candidates, discovered capabilities."""
from __future__ import annotations

from types import SimpleNamespace

from CoScientist.config.settings import ExperimentsSettings
from CoScientist.experiments.critique import critique_plan
from CoScientist.experiments.runtime import (
    approve_plan,
    initialize_runtime,
)
from CoScientist.experiments.schemas import ExperimentPlan

from .helpers import (
    _plan,
    _task,
)

def test_discovered_capabilities_survive_filtered_tools_clear_and_revise():
    """Attempt clears must not erase critique inventory; revise keeps run id."""
    from CoScientist.experiments.context import (
        DISCOVERED_CAPABILITIES_KEY,
        RETRIEVED_CAPABILITIES_KEY,
        build_experiment_context,
        skip_executor_without_runtime,
        snapshot_experiment_discovered_capabilities,
        stash_experiment_retrieved_capabilities,
    )
    from CoScientist.experiments.critique import critique_plan

    tool = {
        "tool": "estimate_property",
        "server_id": "srv-chem",
        "description": "Compute a property.",
        "input_schema": {"type": "object"},
        "score": 0.9,
    }
    extra = {
        "tool": "calculate_docking",
        "server_id": "srv-dock",
        "description": "Dock a molecule.",
        "input_schema": {"type": "object"},
        "score": 0.4,
    }
    state: dict = {
        "accumulated_tools": [tool, extra],
        "filtered_tools": [tool],
        "experiment_source_request": "Estimate a chemical property with ready MCP tools.",
    }
    ctx = SimpleNamespace(state=state, user_content=None)
    stash_experiment_retrieved_capabilities(ctx)
    snapshot_experiment_discovered_capabilities(ctx)
    build_experiment_context(ctx)
    run_id = state["experiment_context"]["experiment_run_id"]
    assert state[RETRIEVED_CAPABILITIES_KEY][1]["tool"] == "calculate_docking"
    assert {c["tool"] for c in state["experiment_context"]["available_mcp_capabilities"]} == {
        "estimate_property",
        "calculate_docking",
    }
    assert {c["tool"] for c in state["experiment_context"]["critique_mcp_capabilities"]} >= {
        "estimate_property",
        "calculate_docking",
    }
    prompt_ctx = state["experiment_planner_context"]
    assert isinstance(prompt_ctx, str)
    assert "estimate_property" in prompt_ctx
    assert "calculate_docking" in prompt_ctx
    # Prompt projection must not triple-dump preferred/critique inventories.
    assert prompt_ctx.count("available_mcp_capabilities") == 1
    assert "critique_mcp_capabilities" not in prompt_ctx
    assert '"input_schema"' not in prompt_ctx

    # Simulate post-attempt clear used by the runtime.
    state["filtered_tools"] = []
    state["experiment_active_envelope"] = None
    state["experiment_plan_critique"] = {
        "verdict": "revise",
        "issues": [{"severity": "blocker", "message": "fix"}],
    }

    build_experiment_context(ctx)
    caps = state["experiment_context"]["critique_mcp_capabilities"]
    assert {c["server_id"] for c in caps} >= {"srv-chem", "srv-dock"}
    assert state["experiment_context"]["experiment_run_id"] == run_id
    assert state[DISCOVERED_CAPABILITIES_KEY]

    plan = ExperimentPlan.model_validate(_plan(_task("EXP-1")))
    approved = critique_plan(
        plan,
        settings=ExperimentsSettings(route_fedot=True),
        available_tools=caps,
    )
    assert approved.verdict == "approve"
    assert skip_executor_without_runtime(ctx) is not None
    state["experiment_plan_critique"] = approved.model_dump(mode="json")
    initialize_runtime(state, plan, critique=approved.model_dump(mode="json"))
    approve_plan(state)
    assert skip_executor_without_runtime(ctx) is None


def test_first_planner_entry_keeps_stashed_retrieval_without_prior_request():
    """ToolPreparer→Planner handoff: empty prev_request must not wipe RETRIEVED."""
    from CoScientist.experiments.context import (
        RETRIEVED_CAPABILITIES_KEY,
        build_experiment_context,
    )

    full = {
        "tool": "generate_case_mols",
        "server_id": "d36e3d994404e957",
        "description": "Generate case molecules.",
        "input_schema": {"type": "object", "properties": {"case": {}}},
        "score": 0.8,
    }
    kept = {
        "tool": "fetch_activity_data",
        "server_id": "bfd3f80438ba403b",
        "description": "Fetch activity.",
        "input_schema": {"type": "object"},
        "score": 0.9,
    }
    # After ToolRetriever+Reranker: full set stashed, accumulated cleared, keep-set in filtered.
    state: dict = {
        "accumulated_tools": [],
        "filtered_tools": [kept],
        RETRIEVED_CAPABILITIES_KEY: [full, kept],
        # No experiment_source_request yet — first planner entry.
    }
    user = SimpleNamespace(parts=[SimpleNamespace(text="Generate GSK-3beta inhibitors with high activit")])
    ctx = SimpleNamespace(state=state, user_content=user)
    build_experiment_context(ctx)
    tools = {c["tool"] for c in state["experiment_context"]["available_mcp_capabilities"]}
    assert tools == {"generate_case_mols", "fetch_activity_data"}
    assert state[RETRIEVED_CAPABILITIES_KEY][0]["tool"] == "generate_case_mols"
    assert "generate_case_mols" in state["experiment_planner_context"]


def test_stash_before_rerank_clear_preserves_full_retrieval():
    from CoScientist.experiments.context import (
        RETRIEVED_CAPABILITIES_KEY,
        stash_experiment_retrieved_capabilities,
    )

    tools = [
        {
            "tool": "generate_case_mols",
            "server_id": "d36e3d994404e957",
            "description": "gen",
            "input_schema": {},
        },
        {
            "tool": "calculate_docking",
            "server_id": "bfd3f80438ba403b",
            "description": "dock",
            "input_schema": {},
        },
    ]
    state: dict = {"accumulated_tools": tools}
    ctx = SimpleNamespace(state=state, user_content=None)
    stash_experiment_retrieved_capabilities(ctx)
    state["accumulated_tools"] = []  # rerank clear
    state["filtered_tools"] = [tools[0]]
    assert {c["tool"] for c in state[RETRIEVED_CAPABILITIES_KEY]} == {
        "generate_case_mols",
        "calculate_docking",
    }


def test_extract_repo_candidates_from_ask():
    from CoScientist.experiments.context import extract_repo_candidates

    refs = extract_repo_candidates(
        "Use https://github.com/whitead/synspace and also "
        "https://github.com/encode/httpx for nothing."
    )
    urls = [r["url"] for r in refs]
    assert "https://github.com/whitead/synspace" in urls
    assert "https://github.com/encode/httpx" in urls
    assert refs[0]["repo_name"] == "synspace"


def test_resolve_repo_candidates_skips_search_when_inventory_covers(monkeypatch):
    from CoScientist.experiments.context import resolve_repo_candidates

    called = {"n": 0}

    def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("search must not run when inventory covers")

    monkeypatch.setattr(
        "CoScientist.experiments.capabilities.repo_searcher.search_repos_sync",
        _boom,
    )
    caps = [{
        "server_id": "srv",
        "tool": "smiles2prop",
        "description": "molecular properties and SA score / synthesizability",
    }]
    out = resolve_repo_candidates(
        "Call smiles2prop to estimate synthetic accessibility SA score for SMILES",
        planner_caps=caps,
        route_alembic=True,
    )
    assert out == []
    assert called["n"] == 0


def test_resolve_repo_candidates_searches_when_inventory_empty(monkeypatch):
    from CoScientist.experiments.capabilities.repo_searcher import RepoCandidate, RepoSearchResult
    from CoScientist.experiments.context import resolve_repo_candidates

    def _fake_search(ask, **_kwargs):
        cand = RepoCandidate(
            url="https://github.com/whitead/synspace",
            owner="whitead",
            repo_name="synspace",
            source="github_search",
            fit_score=0.6,
            fit_reason="test",
            description="Synthesis generative model",
        )
        return RepoSearchResult(query=ask, search_queries=["q"], candidates=[cand])

    monkeypatch.setattr(
        "CoScientist.experiments.capabilities.repo_searcher.search_repos_sync",
        _fake_search,
    )
    out = resolve_repo_candidates(
        "Estimate synthetic accessibility SA score for SMILES",
        planner_caps=[],
        route_alembic=True,
    )
    assert any(c["url"] == "https://github.com/whitead/synspace" for c in out)
    assert out[0].get("source") == "github_search"


def test_planner_context_reads_numbered_frame_operations():
    from CoScientist.context_init.models import ResearchFrame
    from CoScientist.experiments.context.builder import build_experiment_context

    ask = (
        "Run the computational cycle. "
        "1. Review published methods for the endpoint. "
        "2. Curate a labeled dataset with inclusion criteria. "
        "3. Cluster the structures by similarity. "
        "4. Fit six predictive models for the endpoint. "
        "5. Quantify applicability domain for each prediction. "
        "6. Predict general toxicity for the densest cluster. "
        "7. Report. Conclusions and limitations."
    )
    frame = ResearchFrame.blank(ask)
    ctx = SimpleNamespace(
        user_content=SimpleNamespace(parts=[SimpleNamespace(text=ask)]),
        state={"research_frame": frame.model_dump(), "filtered_tools": []},
    )
    build_experiment_context(ctx)
    ops = ctx.state["experiment_context"]["operations"]
    ids = [row["operation_id"] for row in ops]
    assert ids == ["OP-1", "OP-2", "OP-3", "OP-4", "OP-5", "OP-6"]
    assert "Fit six predictive models" in ops[3]["statement"]
    assert not any("Conclusions and limitations" in row["statement"] for row in ops)


# ── research_graph_snapshot (Task: graph-first snapshot) ─────────────────────

class _FakeSnapshotGraph:
    """Minimal research store stand-in exposing full()/overview()/is_empty()."""

    def __init__(self, nodes, *, rendered="rendered overview"):
        self._nodes = nodes
        self._rendered = rendered

    def is_empty(self):
        return not self._nodes

    def full(self):
        return {"nodes": self._nodes}

    def overview(self):
        return {"rendered": self._rendered, "nodes": self._nodes}


def _snapshot_ctx(monkeypatch, store, *, enabled=True):
    import CoScientist.graph.research.store as research_store
    from CoScientist.config import get_settings
    from CoScientist.experiments.context import builder

    monkeypatch.setattr(get_settings().research_graph, "enabled", enabled, raising=False)
    monkeypatch.setattr(research_store, "get_research_graph", lambda ctx: store)
    # research_graph_snapshot requires an ADK session; fake a truthy one.
    monkeypatch.setattr(builder, "_invocation_session", lambda ctx: object())
    return SimpleNamespace(state={}, user_content=None)


def test_research_graph_snapshot_reads_typed_nodes(monkeypatch):
    from CoScientist.experiments.context.builder import research_graph_snapshot

    nodes = [
        {"id": "H1", "type": "Hypothesis", "status": "formulated",
         "attrs": {"formulation": "Compound X inhibits target Y."}},
        {"id": "H2", "type": "Hypothesis", "status": "refuted",
         "attrs": {"formulation": "Refuted idea should be skipped."}},
        {"id": "C1", "type": "Constraint", "status": "active",
         "attrs": {"subtype": "budget", "content": "Stay under 4 GPU-hours."}},
        {"id": "CC1", "type": "ConfirmationCriteria", "status": "not_met",
         "attrs": {"metric": "auc", "threshold": 0.8}},
        {"id": "EB1", "type": "EmpiricalBase", "status": "active",
         "attrs": {"base_type": "dataset", "source_ref": "s3://bucket/data.csv"}},
        {"id": "E1", "type": "Evidence", "status": "obtained",
         "attrs": {"subtype": "computational", "content": "Prior AUC 0.72.",
                   "source_ref": "s3://bucket/run1.json"}},
    ]
    ctx = _snapshot_ctx(monkeypatch, _FakeSnapshotGraph(nodes))
    snap = research_graph_snapshot(ctx)

    assert [h["hypothesis_id"] for h in snap["hypothesis_refs"]] == ["H1"]
    assert snap["hypothesis_refs"][0]["statement"] == "Compound X inhibits target Y."
    assert snap["constraints"][0]["content"] == "Stay under 4 GPU-hours."
    assert snap["confirmation_criteria"][0]["threshold"] == 0.8
    assert snap["data_refs"][0]["source_ref"] == "s3://bucket/data.csv"
    assert snap["prior_evidence"][0]["node_id"] == "E1"
    assert snap["rendered"] == "rendered overview"


def test_research_graph_snapshot_empty_when_disabled(monkeypatch):
    from CoScientist.experiments.context.builder import research_graph_snapshot

    nodes = [{"id": "H1", "type": "Hypothesis", "status": "formulated",
              "attrs": {"formulation": "Ignored while disabled."}}]
    ctx = _snapshot_ctx(monkeypatch, _FakeSnapshotGraph(nodes), enabled=False)
    assert research_graph_snapshot(ctx) == {}


def test_research_graph_snapshot_empty_graph(monkeypatch):
    from CoScientist.experiments.context.builder import research_graph_snapshot

    ctx = _snapshot_ctx(monkeypatch, _FakeSnapshotGraph([]))
    assert research_graph_snapshot(ctx) == {}


def test_research_graph_snapshot_swallows_store_errors(monkeypatch):
    from CoScientist.experiments.context.builder import research_graph_snapshot

    class _Boom:
        def is_empty(self):
            raise RuntimeError("graph unavailable")

    ctx = _snapshot_ctx(monkeypatch, _Boom())
    assert research_graph_snapshot(ctx) == {}


def test_build_experiment_context_prefers_graph_hypotheses(monkeypatch):
    from CoScientist.experiments.context.builder import build_experiment_context

    nodes = [
        {"id": "H1", "type": "Hypothesis", "status": "formulated",
         "attrs": {"formulation": "Graph hypothesis wins."}},
        {"id": "E1", "type": "Evidence", "status": "obtained",
         "attrs": {"subtype": "computational", "content": "Prior fact.",
                   "source_ref": "s3://b/e.json"}},
    ]
    ctx = _snapshot_ctx(monkeypatch, _FakeSnapshotGraph(nodes))
    ctx.state["filtered_tools"] = []
    # A rich prose ask that would otherwise dominate hypothesis extraction.
    ctx.state["experiment_source_request"] = (
        "Hypothesis 1: Prose one.\nHypothesis 2: Prose two.\nHypothesis 3: Prose three."
    )
    build_experiment_context(ctx)
    context = ctx.state["experiment_context"]
    assert [h["hypothesis_id"] for h in context["hypothesis_refs"]] == ["H1"]
    assert context["hypothesis_refs"][0]["statement"] == "Graph hypothesis wins."
    assert context["prior_evidence"][0]["content"] == "Prior fact."
    prompt = ctx.state["experiment_planner_context"]
    assert '"hypothesis_refs"' in prompt
    assert '"hypotheses"' not in prompt
    assert "rendered overview" not in prompt


def test_build_experiment_context_falls_back_without_graph(monkeypatch):
    from CoScientist.experiments.context.builder import build_experiment_context

    ctx = _snapshot_ctx(monkeypatch, _FakeSnapshotGraph([]))
    ask = "Hypothesis 1: Prose one works.\nHypothesis 2: Prose two works."
    ctx.state.update({"filtered_tools": [], "experiment_source_request": ask})
    ctx.user_content = SimpleNamespace(parts=[SimpleNamespace(text=ask)])
    build_experiment_context(ctx)
    refs = ctx.state["experiment_context"]["hypothesis_refs"]
    assert [r["hypothesis_id"] for r in refs] == ["H1", "H2"]
    assert refs[0]["statement"] == "Prose one works."
