"""Unit tests for the Research Context Graph (CoScientist.graph.research).

Exercise the store/schema/queries directly with source= strings (no ADK
contexts needed) against a tmp_path store, plus a couple of assembly-level
checks that the tools are wired into the right agents' prompts.

Run from the repo root:  pytest tests/unit/test_research_graph.py -q
"""
import pytest
from dotenv import load_dotenv

load_dotenv()

from CoScientist.config import get_settings  # noqa: E402
from CoScientist.graph.research import queries, schema  # noqa: E402
from CoScientist.graph.research.store import ResearchGraphStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return ResearchGraphStore(directory=str(tmp_path))


def _init(store):
    return store.init_research(
        source="OrchestratorAgent",
        question="Does compound X inhibit target Y?",
        constraints=[{"subtype": "ethics", "content": "no animal testing"}],
        tools=[{"name": "AutoDock", "tool_type": "computational"}],
        resources=[{"resource_type": "GPU-hours", "remaining": 100, "limit": 100}],
        empirical_bases=[{"base_type": "dataset", "volume": "12k"}],
    )


# ── schema invariants ─────────────────────────────────────────────────────────

def test_edge_pairs_reference_known_types():
    for edge, pairs in schema.EDGE_TYPES.items():
        for f, t in pairs:
            assert f in schema.NODE_TYPES, f"{edge}: unknown from-type {f}"
            assert t in schema.NODE_TYPES, f"{edge}: unknown to-type {t}"


def test_transitions_reference_declared_statuses():
    for typ, pairs in schema.STATUS_TRANSITIONS.items():
        declared = set(schema.NODE_TYPES[typ].statuses)
        for f, t in pairs:
            assert f in declared and t in declared, f"{typ}: {f}->{t} not declared"


def test_node_prefixes_unique():
    prefixes = [s.prefix for s in schema.NODE_TYPES.values()]
    assert len(prefixes) == len(set(prefixes))


def test_permissions_reference_known_types_edges_transitions():
    for agent, perm in schema.AGENT_PERMISSIONS.items():
        for t in perm.create | perm.update_attrs:
            assert t in schema.NODE_TYPES, f"{agent}: unknown create type {t}"
        for edge, f, t in perm.edges:
            assert (f, t) in schema.EDGE_TYPES[edge], f"{agent}: bad edge {edge} {f}->{t}"
        for typ, f, t in perm.transitions:
            assert (f, t) in schema.STATUS_TRANSITIONS[typ], f"{agent}: bad transition {typ} {f}->{t}"


def test_permission_agents_exist_in_system(request):
    """Every AGENT_PERMISSIONS key must be a real agent in system.yaml, EXCEPT
    the virtual write-sources: 'human' (writes via HITL), 'ValidatorAgent'
    (writes via the fully-async background validator plugin, not a sub-agent)
    and 'plan-mirror' (deterministic code that mirrors the registered plan into
    planned methods — deliberately not attributed to a model)."""
    from CoScientist.assembly.schema import get_config
    agents = set(get_config().agents)
    virtual = {"human", "ValidatorAgent", "plan-mirror"}
    for name in schema.AGENT_PERMISSIONS:
        if name in virtual:
            continue
        assert name in agents, f"AGENT_PERMISSIONS has unknown agent {name!r}"


# ── init + happy-path commit ────────────────────────────────────────────────────

def test_init_creates_root_and_star(store):
    r = _init(store)
    assert r["ok"] and r["root_id"] == "Q1"
    types = {n["type"] for n in r["committed"]["nodes"]}
    assert {"ResearchQuestion", "Constraint", "Tool", "Resource", "EmpiricalBase"} <= types
    ov = store.overview()
    assert ov["root"] == "Q1"
    # context star edges exist
    full = store.full()
    edge_types = {e["type"] for e in full["edges"]}
    assert "contextualizes" in edge_types and "defines_scope" in edge_types


def test_commit_with_refs(store):
    _init(store)
    r = store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "X binds Y"}},
               {"type": "VerificationMethod", "ref": "vm", "attrs": {"method_type": "computational"}}],
        edges=[{"type": "motivates", "from": "Q1", "to": "#h"},
               {"type": "tested_by", "from": "#h", "to": "#vm"}],
    )
    assert r.ok, r.errors
    ids = {n["type"]: n["id"] for n in r.committed["nodes"]}
    assert ids["Hypothesis"] == "H1" and ids["VerificationMethod"] == "VM1"


# ── transactionality ────────────────────────────────────────────────────────────

def test_commit_is_atomic_on_any_error(store):
    _init(store)
    before = store.full()["nodes"]
    r = store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "ok"}},
               {"type": "Evidence", "attrs": {"subtype": "literature"}}],  # not allowed for Hypotheses
    )
    assert not r.ok
    assert any("may not create 'Evidence'" in e for e in r.errors)
    assert store.full()["nodes"] == before, "partial write on a failed commit"


# ── permission / transition / edge rejections ──────────────────────────────────

def test_orchestrator_cannot_create_context_star_mid_run(store):
    """The context-star types are seeded only via research_init. The orchestrator
    must NOT be able to invent them through a normal commit (selective-context:
    Tools come from Hypotheses/Coder, not the orchestrator mid-run)."""
    _init(store)
    for t in ("Tool", "Resource", "EmpiricalBase"):
        r = store.commit(source="OrchestratorAgent",
                         nodes=[{"type": t, "attrs": {"name": "x", "base_type": "d",
                                                      "resource_type": "gpu"}}])
        assert not r.ok, f"orchestrator should not create {t} mid-run"
        assert any("may not create" in e for e in r.errors)


def test_init_still_seeds_context_star_privileged(store):
    """research_init seeds Tool/Resource/EmpiricalBase/Constraint despite the
    orchestrator's narrowed general create-set (privileged path)."""
    r = _init(store)  # declares a Tool, Resource, EmpiricalBase, Constraint
    assert r["ok"], r.get("errors")
    types = {n["type"] for n in r["committed"]["nodes"]}
    assert {"Tool", "Resource", "EmpiricalBase", "Constraint"} <= types
    # but a structurally-invalid seed is still rejected even when privileged
    bad = store.init_research(source="OrchestratorAgent", question="Q?",
                              constraints=[{"content": "no subtype"}])  # Constraint needs subtype
    assert not bad["ok"] and any("subtype" in e for e in bad["errors"])


def test_orchestrator_can_wire_constraints(store):
    """regulates/constrains had no creator before; the orchestrator now wires
    seeded Constraints to the methods/hypotheses that appear later."""
    store.init_research(source="OrchestratorAgent", question="Q?",
                        constraints=[{"subtype": "ethics", "content": "no 3R breach"}])
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "x"}},
                        {"type": "VerificationMethod", "ref": "vm", "attrs": {"method_type": "lab"}}],
                 edges=[{"type": "tested_by", "from": "#h", "to": "#vm"}])
    r = store.commit(source="OrchestratorAgent",
                     edges=[{"type": "constrains", "from": "C1", "to": "H1"},
                            {"type": "regulates", "from": "C1", "to": "VM1"}])
    assert r.ok, r.errors


def test_permission_rejection_lists_allowed_types(store):
    _init(store)
    r = store.commit(source="ResearchAgent",
                     nodes=[{"type": "Tool", "attrs": {"name": "foo"}}])
    assert not r.ok
    assert any("ResearchAgent" in e and "Tool" in e for e in r.errors)


def test_bad_initial_status_rejected(store):
    _init(store)
    r = store.commit(source="HypothesesAgent",
                     nodes=[{"type": "Hypothesis", "status": "confirmed",
                             "attrs": {"formulation": "x"}}])
    assert not r.ok
    assert any("not a valid initial status" in e for e in r.errors)


def test_missing_subtype_rejected(store):
    _init(store)
    r = store.commit(source="ResearchAgent",
                     nodes=[{"type": "Evidence", "attrs": {"content": "no subtype"}}])
    assert not r.ok
    assert any("requires attrs.subtype" in e for e in r.errors)


def test_wrong_edge_pair_rejected(store):
    _init(store)
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "x"}}])
    # supports must go Evidence->Hypothesis; here Hypothesis->? is wrong direction
    r = store.commit(source="ResearchAgent",
                     nodes=[{"type": "Evidence", "ref": "e", "attrs": {"subtype": "literature"}}],
                     edges=[{"type": "supports", "from": "H1", "to": "#e"}])
    assert not r.ok
    assert any("must connect Evidence → Hypothesis" in e for e in r.errors)


def test_unknown_endpoint_lists_ids(store):
    _init(store)
    r = store.commit(source="ResearchAgent",
                     nodes=[{"type": "Evidence", "ref": "e", "attrs": {"subtype": "literature"}}],
                     edges=[{"type": "relates_to", "from": "#e", "to": "H99"}])
    assert not r.ok
    assert any("no node 'H99'" in e for e in r.errors)


def test_illegal_transition_rejected(store):
    _init(store)
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "x"}}])
    # refuted is not reachable from formulated in one step, and Hypotheses can't do it
    r = store.commit(source="OrchestratorAgent",
                     status_updates=[{"id": "H1", "status": "confirmed"}])
    assert not r.ok
    assert any("cannot go 'formulated' → 'confirmed'" in e for e in r.errors)


# ── RU aliases, enrichment, locking, persistence ────────────────────────────────

def test_russian_aliases_accepted(store):
    _init(store)
    r = store.commit(source="HypothesesAgent",
                     nodes=[{"type": "Гипотеза", "status": "сформулирована",
                             "attrs": {"formulation": "гипотеза"}}])
    assert r.ok, r.errors
    assert store.full()["nodes"][-1]["type"] == "Hypothesis"


def test_attrs_merge_enrichment(store):
    _init(store)
    r = store.commit(source="ResearchAgent",
                     nodes=[{"id": "EB1", "attrs": {"volume": "20k", "note": "cleaned"}}])
    assert r.ok, r.errors
    eb = next(n for n in store.full()["nodes"] if n["id"] == "EB1")
    assert eb["attrs"]["volume"] == "20k" and eb["attrs"]["note"] == "cleaned"


def test_hypothesis_branch_lock(store):
    _init(store)
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "x"}}])
    assert store.commit(source="OrchestratorAgent",
                        status_updates=[{"id": "H1", "status": "under_verification"}]).ok
    r = store.commit(source="OrchestratorAgent",
                     status_updates=[{"id": "H1", "status": "under_verification"}])
    assert not r.ok
    assert any("already under verification" in e for e in r.errors)


def test_ref_and_id_matching_is_case_insensitive(store):
    """LLMs define ref 'E4' then cite '#e4', and may write 'h1' for node 'H1'.
    Both must resolve (to the canonical stored key) instead of erroring."""
    _init(store)
    # ref defined uppercase ("Ev"), cited lowercase ("#ev"); bare id "q1" cited
    # lowercase. The node created here is assigned id E1 (ref is just a handle).
    r = store.commit(source="ResearchAgent",
                     nodes=[{"type": "Evidence", "ref": "Ev", "attrs": {"subtype": "literature"}}],
                     edges=[{"type": "relates_to", "from": "#ev", "to": "q1"}])
    assert r.ok, r.errors
    edges = store.full()["edges"]
    assert any(e["type"] == "relates_to" and e["from"] == "E1" and e["to"] == "Q1"
               for e in edges)
    # status update citing the node id in the wrong case ("e1" for "E1")
    assert store.commit(source="ResearchAgent",
                        status_updates=[{"id": "e1", "status": "validated"}]).ok
    # case-variant refs in one commit are a duplicate, not two nodes
    dup = store.commit(source="ResearchAgent",
                       nodes=[{"type": "Evidence", "ref": "x1", "attrs": {"subtype": "meta"}},
                              {"type": "Evidence", "ref": "X1", "attrs": {"subtype": "meta"}}])
    assert not dup.ok and any("duplicate ref" in e for e in dup.errors)


def test_duplicate_edge_is_idempotent(store):
    _init(store)
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "x"}}],
                 edges=[{"type": "motivates", "from": "Q1", "to": "#h"}])
    r = store.commit(source="HypothesesAgent",
                     edges=[{"type": "motivates", "from": "Q1", "to": "H1"}])
    assert r.ok
    assert any("already exists" in w for w in r.warnings)
    motivates = [e for e in store.full()["edges"] if e["type"] == "motivates"]
    assert len(motivates) == 1


def test_persistence_roundtrip_and_archive(tmp_path):
    s = ResearchGraphStore(directory=str(tmp_path))
    _init(s)
    s.commit(source="HypothesesAgent",
             nodes=[{"type": "Hypothesis", "attrs": {"formulation": "x"}}])
    before = s.full()
    s2 = ResearchGraphStore(directory=str(tmp_path))  # reload from disk
    after = s2.full()
    assert len(after["nodes"]) == len(before["nodes"])
    assert len(after["edges"]) == len(before["edges"])
    assert s2.root_id() == "Q1"
    # re-init archives the old graph and starts fresh
    r = s2.init_research(source="OrchestratorAgent", question="New question?")
    assert r["ok"] and "archived" in r
    assert list(tmp_path.glob("research_Q1_*.json")), "old graph not archived"


def test_research_generation_ids_are_unique_within_same_second(store, monkeypatch):
    import CoScientist.graph.research.store as store_module

    original_datetime = store_module.datetime

    class FixedDatetime:
        @staticmethod
        def now():
            return original_datetime(2024, 1, 1, 12, 0, 0)

    monkeypatch.setattr(store_module, "datetime", FixedDatetime)
    first = store.init_research(
        source="OrchestratorAgent",
        question="First question?",
    )
    first_id = store.full()["research_id"]
    second = store.init_research(
        source="OrchestratorAgent",
        question="Second question?",
    )
    second_id = store.full()["research_id"]

    assert first["ok"] and second["ok"]
    assert first_id != second_id


def test_no_delete_api():
    for attr in ("delete_node", "delete_edge", "remove_node", "remove_edge"):
        assert not hasattr(ResearchGraphStore, attr)


def test_search_limiter_ignores_research_tools():
    """Regression: the web-search limiter matched "search" as a SUBSTRING, so
    "re-search" tools (research_commit, …) were counted as searches and blocked
    once the cap was hit — which stopped agents recording anything in the graph.
    It must match "search" as a name token instead."""
    from CoScientist.agents.callbacks.tool_callbacks import SearchLimiter

    class _Tool:
        def __init__(self, name): self.name = name

    class _Ctx:
        def __init__(self): self.state = {}

    lim, ctx = SearchLimiter(max_searches=2), _Ctx()
    research_tools = ["research_commit", "research_context_slice", "research_overview",
                      "research_provenance", "research_init", "research_triggers",
                      "research_set_focus"]
    for _ in range(5):
        for name in research_tools:
            assert lim.limit_searches(_Tool(name), {}, ctx) is None
    assert ctx.state.get("_search_limiter_count", 0) == 0  # none counted as a search

    # Real search tools are still capped.
    lim2, ctx2 = SearchLimiter(max_searches=2), _Ctx()
    assert lim2.limit_searches(_Tool("tavily_search"), {}, ctx2) is None
    assert lim2.limit_searches(_Tool("download_papers_from_search"), {}, ctx2) is None
    blocked = lim2.limit_searches(_Tool("search_papers"), {}, ctx2)
    assert blocked is not None and "limit" in blocked["result"].lower()


# ── triggers ────────────────────────────────────────────────────────────────────

def _build_verifiable(store):
    _init(store)
    store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "X binds Y"}},
               {"type": "VerificationMethod", "ref": "vm", "attrs": {"method_type": "computational"}},
               {"type": "ConfirmationCriteria", "ref": "cc", "attrs": {"threshold": "<-8"}}],
        edges=[{"type": "motivates", "from": "Q1", "to": "#h"},
               {"type": "tested_by", "from": "#h", "to": "#vm"},
               {"type": "formulated_for", "from": "#cc", "to": "#h"},
               {"type": "requires", "from": "#h", "to": "T1"},
               {"type": "uses", "from": "#vm", "to": "T1"}],
    )


def test_ready_trigger(store):
    _build_verifiable(store)
    ready = queries.ready_hypotheses(store)["items"]
    assert [i["hypothesis"] for i in ready] == ["H1"]


def test_ready_trigger_offers_one_hypothesis_at_a_time(store):
    """Several verifiable hypotheses ⇒ exactly ONE is actionable; the rest are
    reported as queued so the orchestrator does not verify them in parallel."""
    _build_verifiable(store)
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "h2",
                         "attrs": {"formulation": "alt", "priority": "high"}}],
                 edges=[{"type": "motivates", "from": "Q1", "to": "#h2"}])
    ready = queries.ready_hypotheses(store)
    assert [i["hypothesis"] for i in ready["items"]] == ["H2"]   # higher priority wins
    assert [i["hypothesis"] for i in ready["queued"]] == ["H1"]
    assert "QUEUED" in ready["rendered"]


def test_commit_keeps_one_hypothesis_active_and_postpones_the_rest(store, monkeypatch):
    """A batch of hypotheses proposed in one commit: the selected one stays
    `formulated`, the alternatives are stored as `postponed` backlog."""
    # Pinned rather than relying on the code default: HYPOTHESES__MAX_ACTIVE in
    # .env overrides it for local runs, and this test's math (1 stays active,
    # 2 postponed) only holds for max_active == 1.
    monkeypatch.setattr(get_settings().web, "max_active_hypotheses", 1)
    _init(store)
    r = store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Hypothesis", "ref": "a", "attrs": {"formulation": "first"}},
               {"type": "Hypothesis", "ref": "b",
                "attrs": {"formulation": "the relevant one", "selected": "true"}},
               {"type": "Hypothesis", "ref": "c", "attrs": {"formulation": "third"}}],
        edges=[{"type": "motivates", "from": "Q1", "to": "#b"}])
    assert r.ok, r.errors
    statuses = {n["id"]: n["status"] for n in store.full()["nodes"]
                if n["type"] == "Hypothesis"}
    assert statuses == {"H1": "postponed", "H2": "formulated", "H3": "postponed"}
    # the warning names the cap and how to steer it, so the agent can act on it
    assert any("may be verified at a time" in w and "attrs.selected" in w
               for w in r.warnings), r.warnings
    # only the selected one is offered for verification; the backlog stays quiet
    assert [i["hypothesis"] for i in queries.ready_hypotheses(store)["items"]] == ["H2"]
    assert not queries.postponed_hypotheses(store)["rendered"]


def test_postponed_backlog_surfaces_only_when_nothing_is_active(store, monkeypatch):
    # Same pin as above: this test's second hypothesis must auto-postpone at
    # creation, which only happens when max_active == 1.
    monkeypatch.setattr(get_settings().web, "max_active_hypotheses", 1)
    _init(store)
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "a", "attrs": {"formulation": "one"}},
                        {"type": "Hypothesis", "ref": "b", "attrs": {"formulation": "two"}}])
    assert not queries.postponed_hypotheses(store)["rendered"]   # H1 is active
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "postponed"}])
    backlog = queries.postponed_hypotheses(store)
    assert [i["hypothesis"] for i in backlog["items"]] == ["H1", "H2"]
    assert "BACKLOG" in backlog["rendered"]


def test_blocked_trigger(store):
    _build_verifiable(store)
    # a hypothesis requiring a tool that is still being created is blocked, not ready
    store.commit(source="CoderAgent", nodes=[{"type": "Tool", "ref": "t2",
                 "status": "being_created", "attrs": {"name": "custom"}}])
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "h2", "attrs": {"formulation": "needs custom"}}],
                 edges=[{"type": "requires", "from": "#h2", "to": "T2"}])
    blocked = [i["hypothesis"] for i in queries.blocked_hypotheses(store)["items"]]
    assert "H2" in blocked
    assert "H1" not in blocked


def test_closable_and_missing_criteria(store):
    _build_verifiable(store)
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])
    store.commit(source="ExperimentAgent",
                 nodes=[{"type": "Evidence", "ref": "e", "attrs": {"subtype": "computational",
                         "content": "docking -9",
                         "measured_on": "AutoDock Vina 1.2.5, 5R84 receptor"}}],
                 edges=[{"type": "supports", "from": "#e", "to": "H1"}])
    # CC not met yet → awaiting, not closable
    res = queries.closable_hypotheses(store)
    assert not res["items"]
    assert [i["hypothesis"] for i in res["awaiting_criteria"]] == ["H1"]
    # meet CC → closable. Criteria transitions belong to the ValidatorAgent now,
    # not the orchestrator (verdict/criteria are the judge's job).
    assert not store.commit(source="OrchestratorAgent",
                            status_updates=[{"id": "CC1", "status": "met"}]).ok
    # ...and even the judge has to say what met it, or the bar and the claim
    # that it was cleared are the same unargued sentence.
    bare = store.commit(source="ValidatorAgent",
                        status_updates=[{"id": "CC1", "status": "met"}])
    assert not bare.ok and "reason" in bare.errors[0]
    store.commit(source="ValidatorAgent",
                 status_updates=[{"id": "CC1", "status": "met",
                                  "reason": "met by E1 (docking -9)"}])
    res2 = queries.closable_hypotheses(store)
    assert [i["hypothesis"] for i in res2["items"]] == ["H1"]


def test_refuting_evidence_trigger(store):
    _build_verifiable(store)
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])
    store.commit(source="ResearchAgent",
                 nodes=[{"type": "Evidence", "ref": "e", "attrs": {"subtype": "literature",
                         "content": "contradicts"}}],
                 edges=[{"type": "refutes", "from": "#e", "to": "H1"}])
    items = queries.refuting_evidence(store)["items"]
    assert items and items[0]["hypothesis"] == "H1"


def test_resources_low_trigger(store):
    _init(store)
    store.commit(source="OrchestratorAgent",
                 nodes=[{"id": "R1", "attrs": {"remaining": 5, "limit": 100}}])
    low = [i["resource"] for i in queries.resources_low(store)["items"]]
    assert "R1" in low


def test_provenance_to_root(store):
    _build_verifiable(store)
    prov = store.get_provenance("VM1")
    assert prov["root"] == "Q1"
    ids = [n["id"] for n in prov["chain"]]
    assert ids[0] == "VM1" and ids[-1] == "Q1"


# ── deterministic maintainer + async background validator ───────────────────────

def test_maintainer_auto_advances_hypothesis_on_evidence(store):
    """Store invariant (deterministic, no LLM): attaching supporting/refuting
    evidence to a `formulated` hypothesis auto-moves it to `under_verification`,
    attributed to the graph-maintainer — so the graph looks live for free."""
    _init(store)
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "x"}}])
    r = store.commit(source="ResearchAgent",
                     nodes=[{"type": "Evidence", "ref": "e", "attrs": {"subtype": "literature",
                             "content": "backs it"}}],
                     edges=[{"type": "supports", "from": "#e", "to": "H1"}])
    assert r.ok, r.errors
    h1 = next(n for n in store.full()["nodes"] if n["id"] == "H1")
    assert h1["status"] == "under_verification"
    assert any(u.get("auto") for u in r.committed["status_updates"])
    assert h1["status_history"][-1]["source"] == "graph-maintainer"


def test_background_validator_judges_hypothesis(store):
    """The async validator (with an injected fake LLM) turns an under_verification
    hypothesis with evidence into a verdict + Conclusion, committed as ValidatorAgent."""
    import asyncio
    import CoScientist.graph.research.validator as V

    _build_verifiable(store)
    store.commit(source="ResearchAgent",
                 nodes=[{"type": "Evidence", "ref": "e", "attrs": {"subtype": "literature",
                         "content": "strong support"}}],
                 edges=[{"type": "supports", "from": "#e", "to": "H1"}])
    assert next(n for n in store.full()["nodes"] if n["id"] == "H1")["status"] == "under_verification"

    async def fake_complete(system, user):
        return ('{"verdict":"confirmed","criteria":{"CC1":"met"},'
                '"conclusion":"X binds Y","validity_bounds":"in vitro","reason":"E1 meets CC1"}')

    orig = V.research_graph
    V.research_graph = store
    try:
        res = asyncio.run(V.judge_hypothesis("H1", complete=fake_complete))
    finally:
        V.research_graph = orig

    assert res and res["ok"], res
    nodes = {n["id"]: n for n in store.full()["nodes"]}
    assert nodes["H1"]["status"] == "confirmed"
    assert nodes["CC1"]["status"] == "met"
    assert any(n["type"] == "Conclusion" and n["source"] == "ValidatorAgent"
               for n in nodes.values())


def test_a_bar_can_still_be_written_after_evidence_starts_arriving(store):
    """Writing a bar and moving one are different acts, and the freeze must only
    refuse the second. A ConfirmationCriteria is legal with no attrs at all, so
    the generator can commit `{metric: "docking score"}` and fill in the
    threshold a turn later — and a literature finding recorded under the focus
    in between auto-links to the hypothesis. Keyed on the attribute NAME, that
    first write was refused as a move, and the hypothesis was left carrying a
    bar-less criterion that `_unmet_criteria` still counted and the judge was
    asked to weigh evidence against.
    """
    _init(store)
    root = store.root_id()
    store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "X binds Y"}},
        {"type": "ConfirmationCriteria", "ref": "cc",
         "attrs": {"metric": "docking score"}}],       # no threshold yet
        edges=[{"type": "motivates", "from": root, "to": "#h"},
               {"type": "formulated_for", "from": "#cc", "to": "#h"}])

    # Background reading lands under the focus, so the store auto-links it.
    store.commit(source="ResearchAgent",
                 nodes=[{"type": "Evidence", "attrs": {
                     "subtype": "literature", "content": "adjacent SDHI work"}}],
                 autolink_focus="H1")

    first = store.commit(source="HypothesesAgent", nodes=[
        {"id": "CC1", "attrs": {"threshold": "docking below -8.0 kcal/mol"}}])
    assert first.ok, first.errors
    cc1 = next(n for n in store.full()["nodes"] if n["id"] == "CC1")
    assert cc1["attrs"]["threshold"] == "docking below -8.0 kcal/mol"

    # Re-writing the SAME value is not a move either.
    assert store.commit(source="HypothesesAgent", nodes=[
        {"id": "CC1", "attrs": {"threshold": "docking below -8.0 kcal/mol"}}]).ok

    # But moving it now is exactly what the freeze is for.
    moved = store.commit(source="HypothesesAgent", nodes=[
        {"id": "CC1", "attrs": {"threshold": "docking below -6.0 kcal/mol"}}])
    assert not moved.ok
    assert "frozen" in moved.errors[0]


def test_the_bar_cannot_be_lowered_to_meet_the_result(store):
    """The author of a criterion also owns its attrs, so nothing stopped a run
    from editing `threshold` after the number came back. Before the measurement
    is aimed at it the bar is still being written; after, it is the record."""
    _build_verifiable(store)
    ok = store.commit(source="HypothesesAgent",
                      nodes=[{"id": "CC1", "attrs": {"threshold": "LD50 < 40 mg/kg"}}])
    assert ok.ok, ok.errors

    store.commit(source="ExperimentAgent",
                 nodes=[{"type": "Evidence", "ref": "e",
                         "attrs": {"subtype": "computational", "content": "LD50 58",
                                   "measured_on": "ADMETlab 3.0"}}],
                 edges=[{"type": "supports", "from": "#e", "to": "H1"}])

    moved = store.commit(source="HypothesesAgent",
                         nodes=[{"id": "CC1", "attrs": {"threshold": "LD50 < 60 mg/kg"}}])
    assert not moved.ok
    assert "frozen" in moved.errors[0]
    # The prose around the bar is still editable — only the bar is frozen.
    assert store.commit(source="HypothesesAgent",
                        nodes=[{"id": "CC1", "attrs": {
                            "description": "measured on the rat oral model"}}]).ok


def test_a_branch_the_judge_could_not_settle_can_be_reopened(store):
    """`inconclusive` was in the Hypothesis lifecycle with nothing holding the
    way out of it, so a branch parked there stayed parked. That was nearly
    unreachable until the background validator started WRITING that verdict
    whenever a confirmation is refused — which turned a theoretical dead end
    into the ordinary outcome of a claim that outran its evidence. Reopening one
    is scheduling, the same as reviving a postponed branch.
    """
    _build_verifiable(store)
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])
    assert store.commit(source="ValidatorAgent", status_updates=[
        {"id": "H1", "status": "inconclusive",
         "reason": "the docking run never produced a score"}]).ok

    # New evidence arrives, so the branch goes back under the judge.
    store.commit(source="ExperimentAgent",
                 nodes=[{"type": "Evidence", "ref": "e", "attrs": {
                     "subtype": "computational", "content": "docking -9.1 kcal/mol",
                     "measured_on": "AutoDock Vina 1.2.5"}}],
                 edges=[{"type": "supports", "from": "#e", "to": "H1"}])
    revived = store.commit(source="OrchestratorAgent",
                           status_updates=[{"id": "H1", "status": "under_verification"}])
    assert revived.ok, revived.errors
    h1 = next(n for n in store.full()["nodes"] if n["id"] == "H1")
    assert h1["status"] == "under_verification"

    # And it can now reach a verdict, which is the whole point of reopening it.
    assert store.commit(source="ValidatorAgent", status_updates=[
        {"id": "H1", "status": "confirmed", "reason": "the score clears the bar"},
        {"id": "CC1", "status": "met", "reason": "met by E2 at -9.1"}]).ok


def test_the_conclusion_carries_the_chain_and_not_only_the_answer(store):
    """The conclusion is the study's deliverable: the one card a reader opens
    to learn what came of the work, and what the NEXT study starts from. It
    used to hold a single paragraph, so the reader had to re-walk the whole
    graph to find out how the answer had been reached and a follow-up had
    nothing to begin with.
    """
    import asyncio
    import json

    import CoScientist.graph.research.validator as V

    _build_verifiable(store)
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])
    store.commit(source="ExperimentAgent",
                 nodes=[{"type": "Evidence", "ref": "e", "attrs": {
                     "subtype": "computational", "content": "медианная LD50 41 мг/кг",
                     "measured_on": "ADMETlab 3.0"}}],
                 edges=[{"type": "supports", "from": "#e", "to": "H1"}])

    async def judge(system, user):
        return json.dumps({
            "verdict": "confirmed",
            "criteria": {"CC1": "met"},
            "conclusion": "Кластер линейных фурокумаринов самый токсичный.",
            "how_established": "Литература дала 41 метаболит; прогон ADMETlab "
                               "3.0 вернул медианную LD50 41 мг/кг (E2).",
            "against_criteria": "CC1: измерено 41 мг/кг против порога 50 — "
                                "выполнен.",
            "validity_bounds": "in silico, мышь, внутривенно.",
            "open_questions": "Не измерен разброс между путями введения.",
            "reason": "порог пройден",
        }, ensure_ascii=False)

    orig = V.research_graph
    V.research_graph = store
    try:
        res = asyncio.run(V.judge_hypothesis("H1", complete=judge, language="ru"))
    finally:
        V.research_graph = orig
    assert res and res["ok"], res

    cl = next(n for n in store.full()["nodes"] if n["type"] == "Conclusion")
    attrs = cl["attrs"]
    # The answer stands alone, because it is the card's headline...
    assert attrs["synthesis"].startswith("Кластер линейных")
    # ...and the chain that produced it is stored beside it, not instead of it.
    assert "ADMETlab" in attrs["how_established"]
    assert "CC1" in attrs["against_criteria"]
    assert attrs["validity_bounds"]
    # What makes the study usable as the next one's starting point.
    assert "путями введения" in attrs["open_questions"]


def test_the_judge_is_told_which_language_the_study_is_written_in(store):
    """It is not an agent, so the `{report_language_block?}` substitution every
    agent receives never reached it: a Russian study got an English paragraph
    on the one card that answers its question."""
    import asyncio

    import CoScientist.graph.research.validator as V

    _build_verifiable(store)
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])
    store.commit(source="ResearchAgent",
                 nodes=[{"type": "Evidence", "ref": "e", "attrs": {
                     "subtype": "literature", "content": "подтверждающая работа"}}],
                 edges=[{"type": "supports", "from": "#e", "to": "H1"}])

    seen = {}

    async def capture(system, user):
        seen["system"] = system
        return ('{"verdict":"refuted","reason":"нет",'
                '"conclusion":"не подтверждено"}')

    orig = V.research_graph
    V.research_graph = store
    try:
        # One judgment only: it settles H1, so a second call would return at the
        # `under_verification` guard and re-read the first call's prompt.
        asyncio.run(V.judge_hypothesis("H1", complete=capture, language="ru"))
    finally:
        V.research_graph = orig

    ru = seen["system"]
    assert "RUSSIAN" in ru
    # And the instruction leaves the machine-readable parts alone.
    assert "node ids" in ru and "untranslated" in ru

    from CoScientist.agents.callbacks.report_language import graph_text_rule
    assert graph_text_rule("en") == "",         "an English study must not be told to write Russian"
    # A missing key is a Russian study, which is what every entrypoint that
    # does not set one has always produced.
    assert graph_text_rule(None) == graph_text_rule("ru")


def test_a_refused_confirmation_leaves_the_branch_open_for_the_missing_measurement(store):
    """A refusal is not a verdict, and the difference decides the study.

    The store refuses a confirmation whose criteria are still unmet, or which no
    Evidence supports. Both are "not yet": the runtime benchmark has not run
    yet, the docking score is still queued. An earlier version of this closed
    the branch as `inconclusive` on that refusal, which threw away the judge's
    own `met` findings along with the atomic commit and settled a hypothesis
    whose missing measurement was on its way.
    """
    import asyncio

    import CoScientist.graph.research.validator as V

    _build_verifiable(store)                       # H1 + CC1
    store.commit(source="HypothesesAgent", nodes=[
        {"type": "ConfirmationCriteria", "ref": "cc2",
         "attrs": {"threshold": "runtime under 1 s"}}],
        edges=[{"type": "formulated_for", "from": "#cc2", "to": "H1"}])
    store.commit(source="ResearchAgent",
                 nodes=[{"type": "Evidence", "ref": "e", "attrs": {
                     "subtype": "literature", "content": "affinity -9.4 kcal/mol"}}],
                 edges=[{"type": "supports", "from": "#e", "to": "H1"}])

    async def confident(system, user):
        # Honest: one bar cleared, the other not measured yet.
        return ('{"verdict":"confirmed","criteria":{"CC1":"met","CC2":"not_met"},'
                '"conclusion":"it binds","reason":"affinity clears the bar"}')

    orig = V.research_graph
    V.research_graph = store
    try:
        res = asyncio.run(V.judge_hypothesis("H1", complete=confident))
    finally:
        V.research_graph = orig

    assert res is not None and not res["ok"], res
    assert "CC2" in " ".join(res["errors"])
    h1 = next(n for n in store.full()["nodes"] if n["id"] == "H1")
    assert h1["status"] == "under_verification", \
        "a not-yet must not be recorded as a verdict"
    assert not any(n["type"] == "Conclusion" for n in store.full()["nodes"])

    # The missing measurement arrives, and now the same judgment lands.
    store.commit(source="ExperimentAgent",
                 nodes=[{"type": "Evidence", "ref": "e", "attrs": {
                     "subtype": "computational", "content": "runtime 0.4 s",
                     "measured_on": "one core, n=1000"}}],
                 edges=[{"type": "supports", "from": "#e", "to": "H1"}])

    async def complete_now(system, user):
        return ('{"verdict":"confirmed","criteria":{"CC1":"met","CC2":"met"},'
                '"conclusion":"it binds and it is fast","reason":"both bars clear"}')

    V.research_graph = store
    try:
        res2 = asyncio.run(V.judge_hypothesis("H1", complete=complete_now))
    finally:
        V.research_graph = orig
    assert res2 and res2["ok"], res2
    nodes = {n["id"]: n for n in store.full()["nodes"]}
    assert nodes["H1"]["status"] == "confirmed"
    assert nodes["CC1"]["status"] == "met" and nodes["CC2"]["status"] == "met"


def test_the_same_evidence_is_not_re_judged_after_a_refusal(store):
    """What bounds the cost of leaving the branch open. The plugin's dedupe key
    fingerprints the evidence set, and a refusal is deterministic in the slice
    it was made on — so keying only on SUCCESS meant a hypothesis the store
    would not let the judge confirm was re-judged on every later commit by
    anyone, for the rest of the run, at one LLM call each."""
    from CoScientist.graph.research.validator import BackgroundValidatorPlugin

    plugin = BackgroundValidatorPlugin()
    item = {"hypothesis": "H1", "supporting": ["E1"], "refuting": [], "related": []}
    key = plugin._key(store, "research", item)
    grown = plugin._key(store, "research",
                        {**item, "supporting": ["E1", "E2"]})
    assert key != grown, "new evidence must reopen the question"

    # A refusal settles this evidence set...
    plugin._completed.add(key)
    assert key in plugin._completed
    # ...and does not settle the next one.
    assert grown not in plugin._completed


def test_focus_autolink_relates_evidence_to_hypothesis(store):
    """Option A: Evidence committed with a focus hypothesis but no explicit link
    is auto-attached (relates_to) to that hypothesis, and the maintainer then
    advances the hypothesis to under_verification."""
    _build_verifiable(store)  # H1 formulated
    r = store.commit(source="ResearchAgent",
                     nodes=[{"type": "Evidence", "ref": "e",
                             "attrs": {"subtype": "literature", "content": "a finding"}}],
                     autolink_focus="H1")
    assert r.ok, r.errors
    edges = store.full()["edges"]
    assert any(e["type"] == "relates_to" and e["from"] == "E1" and e["to"] == "H1"
               for e in edges)
    h1 = next(n for n in store.full()["nodes"] if n["id"] == "H1")
    assert h1["status"] == "under_verification"


def test_autolink_resolves_focus_on_method_or_tool_to_hypothesis(store):
    """Broadened auto-link: evidence recorded while focused on a hypothesis'
    VerificationMethod (or Tool) still attaches to the HYPOTHESIS — the
    orchestrator often focuses on the method it is verifying, not the hypothesis."""
    _build_verifiable(store)  # H1 -tested_by-> VM1 ; H1 -requires-> T1
    # focus on the METHOD
    r = store.commit(source="ResearchAgent",
                     nodes=[{"type": "Evidence", "ref": "e",
                             "attrs": {"subtype": "literature", "content": "via method"}}],
                     autolink_focus="VM1")
    assert r.ok, r.errors
    assert any(e["type"] == "relates_to" and e["from"] == "E1" and e["to"] == "H1"
               for e in store.full()["edges"])
    assert next(n for n in store.full()["nodes"] if n["id"] == "H1")["status"] == "under_verification"
    # focus on the TOOL resolves to the same hypothesis
    r2 = store.commit(source="ResearchAgent",
                      nodes=[{"type": "Evidence", "ref": "e2",
                              "attrs": {"subtype": "literature", "content": "via tool"}}],
                      autolink_focus="T1")
    assert r2.ok, r2.errors
    assert any(e["type"] == "relates_to" and e["from"] == "E2" and e["to"] == "H1"
               for e in store.full()["edges"])


def test_validator_assigns_polarity_to_autolinked_evidence(store):
    """The validator turns an auto-linked (polarity-unknown) relates_to evidence
    into a supports/refutes edge as part of its verdict."""
    import asyncio
    import CoScientist.graph.research.validator as V

    _build_verifiable(store)
    store.commit(source="ResearchAgent",
                 nodes=[{"type": "Evidence", "ref": "e",
                         "attrs": {"subtype": "literature", "content": "supports it"}}],
                 autolink_focus="H1")

    async def fake(system, user):
        return ('{"evidence":{"E1":"supports"},"verdict":"confirmed",'
                '"criteria":{"CC1":"met"},"conclusion":"c","validity_bounds":"b","reason":"r"}')

    orig = V.research_graph
    V.research_graph = store
    try:
        res = asyncio.run(V.judge_hypothesis("H1", complete=fake))
    finally:
        V.research_graph = orig

    assert res and res["ok"], res
    full = store.full()
    assert any(e["type"] == "supports" and e["from"] == "E1" and e["to"] == "H1"
               for e in full["edges"])
    nodes = {n["id"]: n for n in full["nodes"]}
    assert nodes["H1"]["status"] == "confirmed" and nodes["CC1"]["status"] == "met"
    assert any(n["type"] == "Conclusion" for n in full["nodes"])


def test_background_validator_retries_after_failed_judgment(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import CoScientist.graph.research.validator as V

    class FakeGraph:
        def full(self):
            return {"research_id": "research-1"}

    graph = FakeGraph()
    item = {
        "hypothesis": "H1",
        "supporting": ["E1"],
        "refuting": [],
        "related": [],
    }
    outcomes = [None, {"ok": True}]
    calls = []

    async def fake_judge(hypothesis, *, graph, expected_research_id, language=None):
        calls.append((hypothesis, expected_research_id))
        return outcomes.pop(0)

    monkeypatch.setattr(V, "_enabled", lambda: True)
    monkeypatch.setattr(V, "get_research_graph", lambda context: graph)
    monkeypatch.setattr(
        V.queries,
        "unresolved_hypotheses",
        lambda selected_graph: {"items": [item]},
    )
    monkeypatch.setattr(V, "judge_hypothesis", fake_judge)
    plugin = V.BackgroundValidatorPlugin()
    tool = SimpleNamespace(name="research_commit")

    async def trigger():
        before = set(V._TASKS)
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={},
            tool_context=object(),
            result={},
        )
        scheduled = set(V._TASKS) - before
        if scheduled:
            await asyncio.gather(*scheduled)
        return len(scheduled)

    async def scenario():
        # The duplicate callback while the first task is still in flight must
        # not schedule another LLM call.
        before = set(V._TASKS)
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={},
            tool_context=object(),
            result={},
        )
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={},
            tool_context=object(),
            result={},
        )
        first_tasks = set(V._TASKS) - before
        assert len(first_tasks) == 1
        await asyncio.gather(*first_tasks)

        assert await trigger() == 1  # retry after the failed first result
        assert await trigger() == 0  # successful signature is now completed

    asyncio.run(scenario())
    assert calls == [("H1", "research-1"), ("H1", "research-1")]


def test_background_validator_dedup_tracks_related_evidence_and_research_id(
    monkeypatch,
):
    import asyncio
    from types import SimpleNamespace
    import CoScientist.graph.research.validator as V

    class FakeGraph:
        research_id = "research-1"

        def full(self):
            return {"research_id": self.research_id}

    graph = FakeGraph()
    item = {
        "hypothesis": "H1",
        "supporting": ["E1"],
        "refuting": [],
        "related": [],
    }
    calls = []

    async def fake_judge(hypothesis, *, graph, expected_research_id, language=None):
        calls.append((hypothesis, expected_research_id, tuple(item["related"])))
        return {"ok": True}

    monkeypatch.setattr(V, "_enabled", lambda: True)
    monkeypatch.setattr(V, "get_research_graph", lambda context: graph)
    monkeypatch.setattr(
        V.queries,
        "unresolved_hypotheses",
        lambda selected_graph: {"items": [item]},
    )
    monkeypatch.setattr(V, "judge_hypothesis", fake_judge)
    plugin = V.BackgroundValidatorPlugin()
    tool = SimpleNamespace(name="research_commit")

    async def trigger():
        before = set(V._TASKS)
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={},
            tool_context=object(),
            result={},
        )
        scheduled = set(V._TASKS) - before
        if scheduled:
            await asyncio.gather(*scheduled)

    async def scenario():
        await trigger()
        await trigger()
        item["related"] = ["E2"]
        await trigger()
        graph.research_id = "research-2"
        await trigger()

    asyncio.run(scenario())
    assert calls == [
        ("H1", "research-1", ()),
        ("H1", "research-1", ("E2",)),
        ("H1", "research-2", ("E2",)),
    ]


def test_validator_discards_result_if_research_changes_during_llm_call():
    import asyncio
    import CoScientist.graph.research.validator as V

    class FakeGraph:
        research_id = "research-1"
        committed = False

        def full(self):
            return {"research_id": self.research_id}

        def get_context_slice(self, hypothesis, depth):
            return {
                "nodes": [{
                    "id": "H1",
                    "type": "Hypothesis",
                    "status": "under_verification",
                    "attrs": {"formulation": "x"},
                }],
                "edges": [],
            }

        def commit(self, **kwargs):
            self.committed = True
            raise AssertionError("a stale verdict must not be committed")

    graph = FakeGraph()

    async def fake_complete(system, user):
        graph.research_id = "research-2"
        return '{"verdict":"postponed","reason":"insufficient evidence"}'

    result = asyncio.run(V.judge_hypothesis(
        "H1",
        complete=fake_complete,
        graph=graph,
        expected_research_id="research-1",
    ))

    assert result is None
    assert not graph.committed


def test_the_view_speaks_the_reader_s_language(tmp_path):
    """A scientist reads the graph, so it must not answer in storage format."""
    from CoScientist.graph.research.store import (
        ResearchGraphStore, _fields, _headline,
    )

    # A budget is a sentence, not the record it is stored as, and what the
    # sentence already says is not repeated underneath it.
    budget = {"resource_type": "GPU-hours", "remaining": "50", "limit": "50"}
    headline = _headline("Resource", budget)
    assert headline == "GPU-hours: 50 of 50 left"
    assert _fields(budget, headline, "Resource") == {}

    store = ResearchGraphStore(directory=str(tmp_path), active_file="v.json")
    store.commit(source="OrchestratorAgent", nodes=[
        {"type": "ResearchQuestion", "attrs": {"formulation": "Does it work?"}},
    ])
    store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "attrs": {"formulation": "It works", "priority": "high"}},
    ])

    view = {n["kind"]: n for n in store.to_view()["nodes"]}

    question = view["researchquestion"]
    assert question["type_word"] == "Вопрос", "the reader of this graph reads Russian"
    assert question["label"] == "Does it work?", "the id belongs in the panel"
    assert not question["label"].startswith("Q1")

    hypothesis = view["hypothesis"]
    assert hypothesis["type_word"] == "Гипотеза"
    assert hypothesis["status_word"] == "предложена", "`formulated` is not a word"
    # The projection sends the attribute CODE; the page captions it through
    # graph.field.priority, so one record reads correctly in either language.
    assert hypothesis["input"]["priority"] == "high"
    assert not any(k[:1].isupper() for k in hypothesis["input"]),         "a display word baked in here picks the reader's language for them"


def test_a_tested_branch_is_not_recorded_as_untried(tmp_path):
    """The verdict for "we tested it and it did not settle" must be its own."""
    from CoScientist.graph.research import queries
    from CoScientist.graph.research.store import ResearchGraphStore

    store = ResearchGraphStore(directory=str(tmp_path), active_file="v.json")
    store.commit(source="OrchestratorAgent",
                 nodes=[{"type": "ResearchQuestion", "attrs": {"formulation": "Q"}}])
    store.commit(source="HypothesesAgent",
                 nodes=[{"type": "Hypothesis",
                         "attrs": {"formulation": "H", "selected": "true"}}])
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification",
                                  "reason": "start"}])

    # While a branch is open the study is open, whatever answer is being drafted.
    assert "STUDY NOT FINISHED" in queries.study_open(store)["rendered"]

    # Only the validator may reach a verdict, and it has one for this outcome.
    denied = store.commit(source="OrchestratorAgent",
                          status_updates=[{"id": "H1", "status": "inconclusive",
                                           "reason": "no numbers"}])
    assert not denied.ok

    verdict = store.commit(source="ValidatorAgent",
                           status_updates=[{"id": "H1", "status": "inconclusive",
                                            "reason": "no quantitative results"}])
    assert verdict.ok

    node = next(n for n in store.to_view()["nodes"] if n["id"] == "H1")
    assert node["status_word"] == "проверена — без ответа"
    assert node["status"] != "postponed", "tested is not the same as never tried"


def test_a_claim_cannot_outrun_the_bar_set_for_it(tmp_path):
    """The three ways one recorded run reported a result its graph denied."""
    from CoScientist.graph.research import queries
    from CoScientist.graph.research.store import ResearchGraphStore

    store = ResearchGraphStore(directory=str(tmp_path), active_file="v.json")
    store.commit(source="OrchestratorAgent",
                 nodes=[{"type": "ResearchQuestion", "attrs": {"formulation": "Q"}}])
    store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "ref": "h",
         "attrs": {"formulation": "hierarchical beats flat", "selected": "true"}},
        {"type": "ConfirmationCriteria", "ref": "cc",
         "attrs": {"threshold": "p < 0.05 in at least 2 of 3 environments"}},
    ], edges=[{"type": "formulated_for", "from": "#cc", "to": "#h"}])
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])

    # 1. Work happening outside the record is visible while it is still fixable.
    assert "WORK NOT IN THE RECORD" in queries.verdict_without_evidence(store)["rendered"]

    # 2. Measured evidence must say what it was measured on. A run benchmarked a
    #    local stand-in for a repository that 404'd and reported it as the real
    #    comparison; the substitution appeared nowhere in the record.
    refused = store.commit(source="CoderAgent", nodes=[
        {"type": "Evidence", "attrs": {"subtype": "computational",
                                       "content": "hierarchical wins, p=0.0006"}}])
    assert not refused.ok
    assert "measured_on" in refused.errors[0]

    store.commit(source="CoderAgent", nodes=[
        {"type": "Evidence", "ref": "e",
         "attrs": {"subtype": "computational", "content": "hierarchical wins in 2 of 3",
                   "measured_on": "local reimplementation; upstream repo 404"}}],
        edges=[{"type": "supports", "from": "#e", "to": "H1"}])

    # 3. Confirmation cannot outrun the criteria written for the hypothesis.
    denied = store.commit(source="ValidatorAgent",
                          status_updates=[{"id": "H1", "status": "confirmed",
                                           "reason": "the benchmark says so"}])
    assert not denied.ok
    assert "CC1" in denied.errors[0]

    # Marking the criterion met in the SAME commit is the shape the schema asks
    # for, and the verdict may lead the list.
    allowed = store.commit(source="ValidatorAgent", status_updates=[
        {"id": "H1", "status": "confirmed", "reason": "criterion met"},
        {"id": "CC1", "status": "met", "reason": "met by E1, 2 of 3 datasets"},
    ])
    assert allowed.ok, allowed.errors


def test_a_verdict_needs_something_that_was_actually_measured(store):
    """A run confirmed a hypothesis nothing in the graph supported.

    The judge is an LLM reading a context slice, so "confirmed" costs it
    nothing. The graph is what makes the claim answerable later, so the
    transition is refused until some Evidence points at the hypothesis.
    """
    _build_verifiable(store)
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])

    empty = store.commit(source="ValidatorAgent", status_updates=[
        {"id": "H1", "status": "confirmed", "reason": "the literature agrees"},
        {"id": "CC1", "status": "met", "reason": "met by the review"},
    ])
    assert not empty.ok
    assert "Evidence" in empty.errors[0]

    # Refuting it needs no such support — a claim may die of an argument.
    assert store.commit(source="ValidatorAgent", status_updates=[
        {"id": "H1", "status": "refuted", "reason": "the assay never ran"}]).ok


def test_the_polarity_edge_may_arrive_with_the_verdict(store):
    """Evidence lands unattached and the judge decides which way it cuts, so
    the `supports` edge and the verdict are written in one commit. A gate
    reading only the saved graph would refuse the judge its own evidence."""
    _build_verifiable(store)
    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])
    store.commit(source="ExperimentAgent",
                 nodes=[{"type": "Evidence", "attrs": {
                     "subtype": "computational", "content": "LD50 41 mg/kg",
                     "measured_on": "ADMETlab 3.0"}}])
    res = store.commit(
        source="ValidatorAgent",
        edges=[{"type": "supports", "from": "E1", "to": "H1"}],
        status_updates=[
            {"id": "H1", "status": "confirmed", "reason": "below the bar"},
            {"id": "CC1", "status": "met", "reason": "met by E1"},
        ])
    assert res.ok, res.errors


def test_a_session_can_reach_every_study_it_holds(tmp_path):
    """research_init archives; only the live study used to be reachable."""
    from CoScientist.graph.research.store import ResearchGraphStore

    store = ResearchGraphStore(directory=str(tmp_path),
                               active_file="research_active.json")
    store.commit(source="OrchestratorAgent", nodes=[
        {"type": "ResearchQuestion", "attrs": {"formulation": "First question"}}])
    store.reset(archive=True)
    store.commit(source="OrchestratorAgent", nodes=[
        {"type": "ResearchQuestion", "attrs": {"formulation": "Second question"}}])

    studies = store.studies()
    assert [s["live"] for s in studies] == [True, False], "the live study comes first"
    assert studies[0]["label"] == "Second question"
    assert studies[1]["label"] == "First question", "a study is known by its question"

    # The default is the live study, and it lists the others beside it.
    live = store.view_of()
    assert live["study_id"] == "active"
    assert len(live["studies"]) == 2

    archived = store.view_of(studies[1]["study_id"])
    labels = [n["label"] for n in archived["nodes"] if not n.get("overlay")]
    assert labels == ["First question"]
    assert len(archived["studies"]) == 2, "the picker stays populated"
def test_tool_needs_adaptation_to_available_transition(store):
    _init(store)
    # T1 is available from _init; let's create a tool with needs_adaptation
    r = store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Tool", "status": "needs_adaptation", "attrs": {"name": "CVAE harness"}}],
    )
    assert r.ok, r.errors
    tool_id = r.committed["nodes"][0]["id"]

    # OrchestratorAgent can transition it to available
    r2 = store.commit(
        source="OrchestratorAgent",
        status_updates=[{"id": tool_id, "status": "available"}],
    )
    assert r2.ok, r2.errors
    tool_node = next(n for n in store.full()["nodes"] if n["id"] == tool_id)
    assert tool_node["status"] == "available"


def test_orchestrator_can_commit_evidence(store):
    _init(store)
    # HypothesesAgent creates hypothesis
    r = store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "CVAE models molecule properties"}}],
    )
    assert r.ok, r.errors

    # OrchestratorAgent commits Evidence and links to H1
    r2 = store.commit(
        source="OrchestratorAgent",
        # `measured_on` is required of computational evidence: what the number
        # was actually measured on is the difference between a result and a claim.
        nodes=[{"type": "Evidence", "ref": "e", "attrs": {
            "subtype": "computational", "content": "95% validity",
            "measured_on": "ZINC-250k held-out split",
        }}],
        edges=[{"type": "supports", "from": "#e", "to": "H1"}],
    )
    assert r2.ok, r2.errors
    ev_node = next(n for n in store.full()["nodes"] if n["type"] == "Evidence")
    assert ev_node["status"] == "obtained"
    assert any(e["type"] == "supports" and e["to"] == "H1" for e in store.full()["edges"])



def test_the_view_links_tool_calls_without_drawing_them(store):
    """Provenance rides on the node; it is not a node of its own.

    One Evidence can be the product of a dozen calls. Drawn as nodes they
    outnumber the findings and bury what the reader came for, so the graph
    shows the research record and the card carries the links into the log.
    """
    _init(store)
    r = store.commit(
        source="OrchestratorAgent",
        nodes=[{"type": "Evidence", "ref": "e", "attrs": {
            "subtype": "computational", "content": "95% validity",
            "measured_on": "ZINC-250k held-out split",
            "_provenance": [
                {"tool": "execute_bash", "exec_id": "tool:1", "result": "ok"},
                {"tool": "tavily_search", "exec_id": "tool:2", "result": "12 papers"},
            ],
        }}],
    )
    assert r.ok, r.errors

    view = store.to_view()
    assert not [n for n in view["nodes"] if n["kind"] == "toolcall"]
    assert not [e for e in view["edges"] if e["type"] == "via"]

    evidence = next(n for n in view["nodes"] if n["kind"] == "evidence")
    assert [p["tool"] for p in evidence["provenance"]] == ["execute_bash", "tavily_search"]
    # The panel needs the call id to link into the execution log.
    assert [p["exec_id"] for p in evidence["provenance"]] == ["tool:1", "tool:2"]
    # And the raw bookkeeping key never reaches the reader's field list.
    assert "_provenance" not in (evidence["input"] or {})


def test_the_graph_page_sends_a_tool_call_to_its_own_tab():
    """Following a result back to the call must not cost you the graph.

    The link also cannot name a node any more: calls are folded into the agent
    that made them, so the page has to find the request holding the call.
    """
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text

    assert 'window.open("/graph?"' in page and '"_blank"' in page
    assert "openTurnHolding" in page, "a deep link must locate the request itself"
    # What the canvas draws is the SERVER's call now. The client-side allow-list
    # dropped whole node kinds AND every edge that touched one, which in a real
    # session was every edge there was; the store folds them into the card that
    # carries them instead, so nothing loses its links.
    assert "RESEARCH_SHOWN" not in page
    for gone in ('id="legend"', 'id="tiles"', 'id="pbar"'):
        assert gone not in page, gone


def test_the_graph_page_only_wires_controls_it_still_has():
    """A handler left behind on a removed control takes the whole page down.

    `document.getElementById("prov").onchange = …` survived the removal of the
    tool-call toggle. It throws on load, so everything after it — honouring
    `?view=`, building the network, the first poll — never ran, and every link
    into the page landed on the default view with nothing drawn.
    """
    import re

    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text

    present = set(re.findall(r'id="([^"]+)"', page))
    wired = set(re.findall(r'getElementById\("([^"]+)"\)', page))
    assert not (wired - present), sorted(wired - present)


def test_a_headline_never_stands_in_for_the_thing_it_should_say(store):
    """The stock word won over content sitting under an unexpected key.

    Agents name the field whatever the prompt made natural. When none of the
    anticipated names matched, the card said "acceptance criteria" — which the
    type name already says — while the criteria themselves sat under details.
    """
    from CoScientist.graph.research.store import _headline

    invented = {"confirmation_criteria": "H1 подтверждается, если валидность ≥ 0.9"}
    assert _headline("ConfirmationCriteria", invented).startswith("H1 подтверждается")

    # Even a name nobody listed reaches the reader rather than a stock word.
    unheard_of = {"acceptance_rule_v2": "два независимых прогона сходятся"}
    said = _headline("ConfirmationCriteria", unheard_of)
    assert "два независимых прогона" in said

    # The same holds for the other types that had a stock word.
    assert _headline("Tool", {"purpose": "docking"}) != "tool"
    assert _headline("VerificationMethod", {"plan": "ретроспектива"}) != "method"
    assert _headline("Conclusion", {"verdict": "подтверждено"}) != "conclusion"


def test_what_the_headline_says_is_not_repeated_under_details(store):
    """One sentence, once: the panel used to print it twice."""
    from CoScientist.graph.research.store import _fields, _headline

    attrs = {"confirmation_criteria": "валидность ≥ 0.9", "reproducibility": "2 прогона"}
    headline = _headline("ConfirmationCriteria", attrs)
    assert "confirmation_criteria" not in _fields(attrs, headline, "ConfirmationCriteria")


def test_the_orchestrator_can_say_why_a_branch_was_left_untested(store):
    """The triggers tell it to; the store used to refuse.

    `study_open` ends with "commit attrs.not_tested_reason saying why the
    verdict already obtained makes testing it unnecessary" — and the
    orchestrator, the only agent that reads triggers, could not write that
    field on a Hypothesis. So the study stayed open, and the run learned to
    answer that closing it was somebody else's job and not critical anyway.
    """
    _init(store)
    r = store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "attrs": {"formulation": "H one"}},
        {"type": "Hypothesis", "attrs": {"formulation": "H two"}},
    ])
    assert r.ok, r.errors
    backlog = r.committed["nodes"][1]["id"]

    r2 = store.commit(
        source="OrchestratorAgent",
        nodes=[{"id": backlog, "attrs": {
            "not_tested_reason": "H1 подтверждена; проверять эту ветку незачем"}}],
    )
    assert r2.ok, r2.errors
    node = next(n for n in store.full()["nodes"] if n["id"] == backlog)
    assert node["attrs"]["not_tested_reason"].startswith("H1 подтверждена")


def test_that_grant_does_not_open_the_rest_of_the_hypothesis(store):
    """One field, not the node: the formulation stays with the agent that owns it."""
    _init(store)
    r = store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "attrs": {"formulation": "H one"}}])
    hid = r.committed["nodes"][0]["id"]

    denied = store.commit(
        source="OrchestratorAgent",
        nodes=[{"id": hid, "attrs": {"formulation": "rewritten"}}])
    assert not denied.ok
    assert "not_tested_reason" in " ".join(denied.errors), denied.errors

    # Nor smuggled in beside a field it may write.
    mixed = store.commit(
        source="OrchestratorAgent",
        nodes=[{"id": hid, "attrs": {"not_tested_reason": "ok", "priority": "high"}}])
    assert not mixed.ok


def test_the_prompt_tells_the_agent_about_the_field_it_may_write():
    """Prompt and enforcement come from one table, so neither can drift."""
    from CoScientist.graph.research import schema

    summary = schema.permitted_summary("OrchestratorAgent")
    assert any("not_tested_reason" in line for line in summary["update_attrs"]), summary
    validator = schema.permitted_summary("ValidatorAgent")
    assert any("inconclusive_reason" in line for line in validator["update_attrs"])


# ── the drawing: folding, connectedness, and the reason a step ended ──────────

def _drawn_components(view):
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(n["id"] for n in view["nodes"])
    g.add_edges_from((e["src"], e["dst"]) for e in view["edges"])
    return nx.number_connected_components(g)


def test_the_drawing_never_falls_apart_into_islands(store):
    """One picture, or the reader cannot follow the study through it.

    The viewer used to drop whole node kinds and, with them, every edge that
    touched one. In a real session the entire structure hung off GeneratedData,
    which was on that list — so the server sent five edges, the canvas drew
    none, and eleven findings sat unconnected. Folding has to preserve reach:
    whatever is not drawn is absorbed by the card that carries it, and its
    links come along.
    """
    _build_verifiable(store)
    r = store.commit(
        source="ExperimentAgent",
        nodes=[{"type": "Evidence", "ref": "e",
                "attrs": {"subtype": "computational", "measured_on": "docking",
                          "content": "score -9.1"}},
               {"type": "GeneratedData", "ref": "gd",
                "attrs": {"content": "poses", "path": "runs/poses.sdf"}}],
        edges=[{"type": "produces", "from": "VM1", "to": "#e"},
               {"type": "derived_from", "from": "#gd", "to": "#e"},
               {"type": "supports", "from": "#e", "to": "H1"}],
    )
    assert r.ok, r.errors
    view = store.to_view()
    assert _drawn_components(view) == 1, view["edges"]


@pytest.mark.parametrize("broken", ["orphan_tool", "orphan_artifact", "loose_evidence"])
def test_nothing_floats_however_the_agents_left_it(store, broken):
    """Whatever an agent forgot to link still reaches the question."""
    _build_verifiable(store)
    if broken == "orphan_tool":
        store.commit(source="CoderAgent",
                     nodes=[{"type": "Tool", "attrs": {"name": "lonely"}}])
    elif broken == "orphan_artifact":
        store.commit(source="CoderAgent",
                     nodes=[{"type": "CodeArtifact", "attrs": {"path": "x.py"}}])
    else:
        store.commit(source="ExperimentAgent",
                     nodes=[{"type": "Evidence",
                             "attrs": {"subtype": "literature", "content": "loose"}}])
    assert _drawn_components(store.to_view()) == 1


def test_a_folded_artifact_keeps_the_link_it_carried(store):
    """A dataset is not a card, and is not a hole either.

    It travels on the finding it produced — with the path it lives at, so the
    reader can open it — and the method that produced that finding keeps its
    arrow.
    """
    _build_verifiable(store)
    store.commit(
        source="ExperimentAgent",
        nodes=[{"type": "Evidence", "ref": "e",
                "attrs": {"subtype": "computational", "measured_on": "docking",
                          "content": "score -9.1"}},
               {"type": "GeneratedData", "ref": "gd",
                "attrs": {"content": "225 SMILES", "path": "data/smiles.csv"}}],
        edges=[{"type": "produces", "from": "VM1", "to": "#e"},
               {"type": "derived_from", "from": "#gd", "to": "#e"}],
    )
    view = store.to_view()
    drawn = {n["id"]: n for n in view["nodes"]}
    assert "GD1" not in drawn, "an engineering product is not a card"
    assert ("VM1", "E1") in {(e["src"], e["dst"]) for e in view["edges"]}
    attached = {a["id"]: a for a in drawn["E1"]["attachments"]}
    assert "GD1" in attached
    assert attached["GD1"]["href"] == "data/smiles.csv", "openable, or it is lost"


def test_a_tool_rides_on_the_method_that_uses_it(store):
    """The instrument is a chip on the method, and the bar a line under it."""
    _build_verifiable(store)
    drawn = {n["id"]: n for n in store.to_view()["nodes"]}
    assert "T1" not in drawn
    assert [c["id"] for c in drawn["VM1"]["chips"]] == ["T1"]
    assert drawn["VM1"]["criterion"] == "<-8"


def test_a_folded_node_never_invents_a_link_between_its_hosts(store):
    """One dataset feeding two findings does not make one derive from the other.

    Re-pointing that edge at the hosts would read as ancestry between siblings —
    a relation the record never claimed.
    """
    _build_verifiable(store)
    store.commit(
        source="ExperimentAgent",
        nodes=[{"type": "Evidence", "ref": "e1",
                "attrs": {"subtype": "computational", "measured_on": "a", "content": "A"}},
               {"type": "Evidence", "ref": "e2",
                "attrs": {"subtype": "computational", "measured_on": "b", "content": "B"}},
               {"type": "GeneratedData", "ref": "gd", "attrs": {"content": "shared"}}],
        edges=[{"type": "produces", "from": "VM1", "to": "#e1"},
               {"type": "produces", "from": "VM1", "to": "#e2"},
               {"type": "derived_from", "from": "#gd", "to": "#e1"},
               {"type": "derived_from", "from": "#gd", "to": "#e2"}],
    )
    view = store.to_view()
    pairs = {(e["src"], e["dst"], e["type"]) for e in view["edges"]}
    assert ("E1", "E2", "derived_from") not in pairs
    assert ("E2", "E1", "derived_from") not in pairs
    drawn = {n["id"]: n for n in view["nodes"]}
    for eid in ("E1", "E2"):
        assert "GD1" in {a["id"] for a in drawn[eid]["attachments"]}


def test_the_frame_is_one_card_beside_the_question(store):
    """The setup a study starts from is a card, not five scattered boxes."""
    _init(store)
    view = store.to_view()
    drawn = {n["id"]: n for n in view["nodes"]}
    assert "FRAME" in drawn, "the framing must be readable somewhere"
    for folded in ("C1", "T1", "R1", "EB1"):
        assert folded not in drawn, f"{folded} belongs on the frame card"
    assert {a["id"] for a in drawn["FRAME"]["attachments"]} >= {"C1", "R1", "EB1"}
    assert ("FRAME", "Q1", "frames") in {
        (e["src"], e["dst"], e["type"]) for e in view["edges"]}


def test_an_unseeded_frame_is_a_gap_and_not_an_empty_box(store):
    """With the pre-stage off nothing seeds the framing. Say so, don't draw it."""
    store.ensure_root("Does compound X inhibit target Y?")
    view = store.to_view()
    assert "FRAME" not in {n["id"] for n in view["nodes"]}
    assert "no_frame" in {g["code"] for g in view["gaps"]}


# ── ensure_root: a question, without wiping the study ─────────────────────────

def test_ensure_root_is_idempotent_and_keeps_the_generation(store):
    """Called on every message, so it must be free the second time.

    And it must not rotate `_research_id`: the background validator keys its
    dedup and its discard-stale-verdict check on that id, so a new generation
    mid-run makes every in-flight judgment throw itself away.
    """
    first = store.ensure_root("Does compound X inhibit target Y?")
    generation = store._research_id
    assert first == {"ok": True, "created": True, "root_id": "Q1"}

    second = store.ensure_root("Some entirely different question")
    assert second == {"ok": True, "created": False, "root_id": "Q1"}
    assert store._research_id == generation, "a re-seed is not a new research"

    store.commit(source="ResearchAgent",
                 nodes=[{"type": "Evidence",
                         "attrs": {"subtype": "literature", "content": "c"}}])
    assert store.ensure_root("x")["created"] is False
    assert store.ensure_root("   ")["ok"] is False, "an empty question is not a root"


def test_ensure_root_does_not_archive_the_study_in_progress(store, tmp_path):
    """init_research wipes and archives; seeding a root must do neither."""
    _build_verifiable(store)
    before = len(store.full()["nodes"])

    store.ensure_root("A different question entirely")

    assert len(store.full()["nodes"]) == before, "nothing was thrown away"
    archives = [p for p in tmp_path.glob("research_*.json")
                if p.name != "research_active.json"]
    assert not archives, "nothing was archived"
    assert store.root_id() == "Q1"


def test_a_root_written_by_a_plain_commit_still_names_its_archive(store, tmp_path):
    """`_root_id` is set by init_research and by loading — not by commit.

    A question written straight through commit left it unset, and the archive
    was then filed as `research_graph_*` instead of under the question's id.
    """
    store.commit(source="OrchestratorAgent",
                 nodes=[{"type": "ResearchQuestion",
                         "attrs": {"formulation": "First question"}}])
    assert store.full()["root_id"] is None

    store.ensure_root("First question")
    assert store.full()["root_id"] == "Q1"

    store.reset(archive=True)
    assert list(tmp_path.glob("research_Q1_*.json"))


# ── why a step ended where it did ────────────────────────────────────────────

def test_why_a_step_failed_reaches_the_reader(store):
    """The reason was always recorded, and never left the store.

    A failed method drew as its status word and stopped there, which is the one
    question a reader of a failed step actually has.
    """
    _build_verifiable(store)
    store.commit(source="ExperimentAgent",
                 status_updates=[{"id": "VM1", "status": "running"}])
    r = store.commit(source="ExperimentAgent",
                     status_updates=[{"id": "VM1", "status": "failed",
                                      "reason": "sandbox ran out of memory"}])
    assert r.ok, r.errors

    vm = next(n for n in store.to_view()["nodes"] if n["id"] == "VM1")
    assert vm["why"] == "sandbox ran out of memory"
    assert vm["why_missing"] is False
    assert vm["status_history"][-1]["reason"] == "sandbox ran out of memory"
    assert vm["status_history"][-1]["to_word"] == "не удался"


def test_a_failure_can_also_explain_itself_in_its_attrs(store):
    """The executor that hit the error may name it on the node itself."""
    _build_verifiable(store)
    store.commit(source="ExperimentAgent",
                 status_updates=[{"id": "VM1", "status": "running"}])
    store.commit(source="ExperimentAgent",
                 status_updates=[{"id": "VM1", "status": "failed"}],
                 nodes=[{"id": "VM1", "attrs": {"failure_reason": "no CUDA device"}}])
    vm = next(n for n in store.to_view()["nodes"] if n["id"] == "VM1")
    assert vm["why"] == "no CUDA device"


def test_a_postponed_branch_says_why_it_was_postponed(store, monkeypatch):
    """The store writes the backlog reason itself — and used to hide it."""
    monkeypatch.setattr(get_settings().web, "max_active_hypotheses", 1)
    _init(store)
    r = store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Hypothesis", "ref": "a",
                "attrs": {"formulation": "first", "priority": "high"}},
               {"type": "Hypothesis", "ref": "b",
                "attrs": {"formulation": "second", "priority": "low"}}],
    )
    assert r.ok, r.errors
    parked = next(n for n in store.to_view()["nodes"]
                  if n["status"] == "postponed")
    assert parked["why"], "a card saying only 'postponed' explains nothing"


def test_a_failure_with_no_reason_is_reported_as_a_gap(store):
    """A hole in the record is named, not quietly rendered as a colour."""
    _build_verifiable(store)
    store.commit(source="ExperimentAgent",
                 status_updates=[{"id": "VM1", "status": "failed"}])
    view = store.to_view()
    gaps = {g["code"]: g for g in view["gaps"]}
    assert "unreasoned_failures" in gaps
    assert "VM1" in gaps["unreasoned_failures"]["ids"]
    vm = next(n for n in view["nodes"] if n["id"] == "VM1")
    assert vm["why_missing"] is True


def test_the_view_counts_the_writes_it_refused(store):
    """A refused commit saves nothing, and used to say so to nobody."""
    _init(store)
    bad = store.commit(source="HypothesesAgent",
                       nodes=[{"type": "Evidence",
                               "attrs": {"subtype": "literature", "content": "x"}}])
    assert not bad.ok
    counted = {g["code"]: g["count"] for g in store.to_view()["gaps"]}
    assert counted.get("rejected_commits") == 1

    good = store.commit(source="ResearchAgent",
                        nodes=[{"type": "Evidence",
                                "attrs": {"subtype": "literature", "content": "x"}}])
    assert good.ok, good.errors
    assert "rejected_commits" not in {g["code"] for g in store.to_view()["gaps"]}


# ── how the study moved: iteration and outcome ───────────────────────────────

def test_supersedes_carries_its_verdict_to_the_view(store):
    """An unlabelled arrow between two look-alike cards explains nothing."""
    _build_verifiable(store)
    r = store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Hypothesis", "ref": "h2",
                "attrs": {"formulation": "X binds Y only above 35% anchors"}}],
        edges=[{"type": "supersedes", "from": "H1", "to": "#h2",
                "attrs": {"verdict": "refuted", "reason": "anchor fraction added"}},
               {"type": "motivates", "from": "Q1", "to": "#h2"}],
    )
    assert r.ok, r.errors
    view = store.to_view()
    edge = next(e for e in view["edges"] if e["type"] == "supersedes")
    assert edge["attrs"]["verdict"] == "refuted"
    assert edge["attrs"]["reason"] == "anchor fraction added"
    h2 = next(n for n in view["nodes"] if n["id"] == "H2")
    assert h2["origin"]["code"] == "modified", "a card says where it came from"


def test_the_outcome_is_the_story_of_the_verdicts(store):
    """What it all added up to — assembled from the record, with no model call."""
    _build_verifiable(store)
    store.commit(source="ExperimentAgent",
                 nodes=[{"type": "Evidence", "ref": "e",
                         "attrs": {"subtype": "computational", "measured_on": "d",
                                   "content": "score -9.1"}}],
                 edges=[{"type": "refutes", "from": "#e", "to": "H1"}])
    store.commit(source="ValidatorAgent",
                 status_updates=[{"id": "H1", "status": "refuted",
                                  "reason": "the bar was never cleared"}])
    view = store.to_view()
    outcome = next(n for n in view["nodes"] if n["id"] == "OUTCOME")
    assert "X binds Y" in outcome["label"]
    assert "опровергнута" in outcome["label"]
    assert "the bar was never cleared" in outcome["label"]
    assert _drawn_components(view) == 1


# ── the deterministic middle layer ───────────────────────────────────────────

_PLAN = [{"id": "TASK-1", "title": "Collect the metabolites", "assignee": "ResearchAgent"},
         {"id": "TASK-2", "title": "Cluster by Tanimoto", "description": "Butina t=0.6",
          "assignee": "ExperimentAgent"},
         {"id": "TASK-3", "title": "Estimate LD50 per cluster", "assignee": "ExperimentAgent"}]









_PLAN_STEPS = [
    {"id": "TASK-1", "title": "Write a testable hypothesis", "description": "one claim",
     "assignee": "HypothesesAgent", "status": "DONE"},
    {"id": "TASK-2", "title": "Collect the metabolite SMILES", "description": "from papers",
     "assignee": "TaskExecutorAgent", "status": "IN_PROGRESS",
     "tools": ["explore_chemistry_database", "name2smiles"]},
    {"id": "TASK-3", "title": "Predict LD50 per cluster", "description": "and the AD",
     "assignee": "TaskExecutorAgent", "status": "TODO",
     "tools": ["predict_general_toxicity"]},
]


def test_the_plan_becomes_one_step_per_task_not_one_method(store):
    """The mirror wrote the planner's task list as `VerificationMethod`, and
    that was the most misleading thing in the graph. A step is an INTENTION —
    what to do, in what order, by whom. A method answers a different question:
    by what MEANS was this established, and against which bar. Conflated, the
    task list appeared as "methods" hanging off the research QUESTION, carrying
    no instrument, indistinguishable from a method an agent had designed.
    """
    from CoScientist.agents.callbacks.tool_callbacks import sync_plan_to_research_graph

    state = {}
    r = sync_plan_to_research_graph(_PLAN_STEPS, store, state,
                                    question="How toxic is it?")
    assert r.ok, r.errors
    nodes = {n["id"]: n for n in store.full()["nodes"]}
    steps = sorted(n for n, v in nodes.items() if v["type"] == "PlanStep")
    assert len(steps) == 3, steps
    assert not [n for n, v in nodes.items() if v["type"] == "VerificationMethod"], \
        "the plan is not a set of methods"
    # The tracker's own status, so the column shows what has actually run.
    assert [nodes[s]["status"] for s in steps] == ["done", "in_progress", "todo"]
    assert all(nodes[s]["source"] == "plan-mirror" for s in steps), \
        "a reader must see that no model chose these"
    # The one part of the method the PLAN can already answer: the planner reads
    # the tool list, so the instruments come across with the step.
    assert (nodes[steps[1]]["attrs"] or {})["tools"] == \
        "explore_chemistry_database, name2smiles"
    assert "tools" not in (nodes[steps[0]]["attrs"] or {}), "a step that runs none"

    # A re-plan of the same steps says nothing new.
    assert sync_plan_to_research_graph(_PLAN_STEPS, store, state) is None


def test_the_plan_step_and_the_work_that_carried_it_out_are_linked(store):
    """`realises` is what lets a reader cross between the intention and the
    record. It runs from the RECORD to the INTENTION, so following the research
    forward never walks into the plan by accident, and a step with nothing
    pointing at it is visibly unrealised.

    Note which node realises which step: "write a testable hypothesis" is
    carried out by the HYPOTHESIS itself. That step used to be drawn as a
    verification method — a card in the literature band that verified nothing.
    """
    from CoScientist.agents.callbacks.tool_callbacks import sync_plan_to_research_graph

    state = {}
    sync_plan_to_research_graph(_PLAN_STEPS, store, state, question="How toxic is it?")
    store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "ref": "h", "attrs": {
            "formulation": "the coumarin cluster is the toxic one",
            "plan_task_id": "TASK-1"}},
        {"type": "VerificationMethod", "ref": "vm", "attrs": {
            "description": "Predict LD50 with ADMETlab",
            "procedure": "run predict_general_toxicity per cluster",
            "plan_task_id": "TASK-3"}}],
        edges=[{"type": "motivates", "from": store.root_id(), "to": "#h"},
               {"type": "tested_by", "from": "#h", "to": "#vm"}])

    # The task list is EMPTY now — the plan was registered turns ago. Gating the
    # linking on "are there tasks to mirror" made it unreachable in practice.
    linked = sync_plan_to_research_graph([], store, state)
    assert linked is not None and linked.ok, linked
    realises = {(e["from"], e["to"]) for e in store.full()["edges"]
                if e["type"] == "realises"}
    steps = sorted(n["id"] for n in store.full()["nodes"] if n["type"] == "PlanStep")
    assert ("H1", steps[0]) in realises, realises
    assert ("VM1", steps[2]) in realises, realises
    # Idempotent: a link that is already there is not written twice.
    assert sync_plan_to_research_graph([], store, state) is None


def test_a_step_the_plan_advances_is_advanced_in_the_graph(store):
    """The column is only worth reading if it says what has actually run."""
    from CoScientist.agents.callbacks.tool_callbacks import sync_plan_to_research_graph

    state = {}
    sync_plan_to_research_graph(_PLAN_STEPS, store, state, question="How toxic?")
    moved = [dict(t, status="DONE") for t in _PLAN_STEPS]
    r = sync_plan_to_research_graph(moved, store, state)
    assert r is not None and r.ok, r
    steps = {n["id"]: n["status"] for n in store.full()["nodes"]
             if n["type"] == "PlanStep"}
    assert set(steps.values()) == {"done"}, steps
    assert sync_plan_to_research_graph(moved, store, state) is None


def test_the_mirror_memo_does_not_outlive_the_study_it_was_written_for(store):
    """`research_init` archives the study and starts an empty graph, so ids
    restart at PS1 — but the memo lives in ADK session state, which survives.
    Checking that a remembered id still RESOLVES cannot catch that: it resolves
    to a different node. The mirror both skipped tasks it had never mirrored in
    the new study and wrote an edge to an id that now named somebody else's.
    """
    from CoScientist.agents.callbacks.tool_callbacks import sync_plan_to_research_graph

    state = {}
    assert sync_plan_to_research_graph(_PLAN_STEPS, store, state,
                                       question="How toxic is it?").ok
    first = sorted(n["id"] for n in store.full()["nodes"] if n["type"] == "PlanStep")

    store.init_research(source="OrchestratorAgent", question="Which ligand binds 6LU7?")
    again = sync_plan_to_research_graph(_PLAN_STEPS, store, state)
    assert again is not None and again.ok, "the same plan is new work here"
    fresh = sorted(n["id"] for n in store.full()["nodes"] if n["type"] == "PlanStep")
    assert len(fresh) == len(_PLAN_STEPS), fresh
    assert fresh == first, "ids restart, which is exactly why the memo cannot"


def test_two_methods_carrying_out_one_plan_step_both_point_at_it(store):
    """The operator's complaint was that «метод проверки 3 и 4» were
    indistinguishable cards. The cause was the mirror duplicating one plan step
    into two look-alike "methods"; with the plan as its own node that cause is
    gone, and two methods genuinely carrying out one step is legitimate — a
    step can be realised by several pieces of work. What matters is that the
    reader can SEE it, which the step on each card and the `realises` edges do.
    """
    _init(store)
    root = store.root_id()
    store.commit(source="plan-mirror", nodes=[
        {"type": "PlanStep", "attrs": {
            "title": "Toxicity profiling for the cluster", "plan_task_id": "TASK-3"}}])
    r = store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "ref": "h", "attrs": {"formulation": "E is the toxic one"}},
        {"type": "VerificationMethod", "ref": "a", "attrs": {
            "description": "Acute toxicity: LD50 per route",
            "procedure": "predict_general_toxicity over the cluster",
            "plan_task_id": "TASK-3"}},
        {"type": "VerificationMethod", "ref": "b", "attrs": {
            "description": "Organ toxicity: DILI and hERG",
            "procedure": "predict_molecule_profile over the cluster",
            "plan_task_id": "TASK-3"}}],
        edges=[{"type": "motivates", "from": root, "to": "#h"},
               {"type": "tested_by", "from": "#h", "to": "#a"},
               {"type": "tested_by", "from": "#h", "to": "#b"}])
    assert r.ok, r.errors

    view = store.view_of(None)
    steps = {n["id"]: n.get("plan_step") for n in view["nodes"]
             if n["kind"] == "verificationmethod"}
    assert set(steps.values()) == {"TASK-3"}, steps
    # And it is NOT reported as a fault of the record.
    assert "duplicate_plan_step" not in {g["code"] for g in view["gaps"]}


def test_a_method_card_names_the_hypothesis_it_tests_and_not_the_question(store):
    """Four method cards read identically on a real graph: every one of them
    said what it did and none said what it was for. The card names the claim
    the method is aimed at — and the HYPOTHESIS, never the question, because
    the question is already the page's own heading."""
    _init(store)
    root = store.root_id()
    store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "ref": "h", "attrs": {
            "formulation": "Cluster E is the most toxic of the five"}},
        {"type": "VerificationMethod", "ref": "vm", "attrs": {
            "description": "Predict LD50 per cluster",
            "procedure": "predict_general_toxicity, mouse, all routes"}}],
        edges=[{"type": "motivates", "from": root, "to": "#h"},
               {"type": "tested_by", "from": "#h", "to": "#vm"}])

    cards = {n["id"]: n for n in store.view_of(None)["nodes"]}
    assert cards["VM1"].get("tests", "").startswith("Cluster E is the most toxic")
    # A method serving the question directly — a literature sweep before any
    # hypothesis exists — has nothing to claim, and says nothing rather than
    # repeating the heading.
    store.commit(source="ResearchAgent", nodes=[
        {"type": "VerificationMethod", "ref": "lit", "attrs": {
            "method_type": "literature_review",
            "procedure": "Collect the published metabolite list"}}],
        edges=[{"type": "tested_by", "from": root, "to": "#lit"}])
    cards = {n["id"]: n for n in store.view_of(None)["nodes"]}
    assert not cards["VM2"].get("tests"), cards["VM2"].get("tests")


def test_experiment_agent_can_open_the_method_it_runs(store):
    """It owned the whole lifecycle of a method and could not create one."""
    _init(store)
    r = store.commit(source="ExperimentAgent",
                     nodes=[{"type": "VerificationMethod",
                             "attrs": {"method_type": "computational"}}])
    assert r.ok, r.errors

    # Creating a type carries the right to enrich it, so the executor that ran
    # the method can also say why it failed — no separate grant needed.
    ok = store.commit(source="ExperimentAgent",
                      nodes=[{"id": "VM1", "attrs": {"failure_reason": "OOM"}}])
    assert ok.ok, ok.errors
    # A role that does not own methods still may not touch one. Not the
    # ResearchAgent any more — a literature review IS a verification method, so
    # it owns the type now (see the test below); the collector does not.
    nope = store.commit(source="DatasetCollectorAgent",
                        nodes=[{"id": "VM1", "attrs": {"failure_reason": "mine now"}}])
    assert not nope.ok, "ownership is per type, not per field name"


def test_the_literature_agent_can_open_the_search_it_ran(store):
    """Evidence from a paper belongs to the search that found it.

    The ResearchAgent could create Evidence but neither open a
    VerificationMethod nor write `produces`, so a literature finding could only
    hang off the question by `relates_to` — and before the first hypothesis
    exists, that was its ONLY legal attachment. Meanwhile the "collect the
    literature" method the plan mirror had written stayed `planned` forever,
    with the evidence it produced floating unattached beside it.
    """
    _init(store)
    root = store.root_id()
    r = store.commit(
        source="ResearchAgent",
        nodes=[{"type": "VerificationMethod", "ref": "vm",
                "attrs": {"method_type": "literature_review",
                          "procedure": "Collect the metabolite list from the literature"}},
               {"type": "Evidence", "ref": "e",
                "attrs": {"subtype": "literature", "content": "225 metabolites",
                          "source_ref": "DOI 10.3390/plants14213253"}}],
        edges=[{"type": "tested_by", "from": root, "to": "#vm"},
               {"type": "produces", "from": "#vm", "to": "#e"}],
    )
    assert r.ok, r.errors

    view = store.view_of(None)
    links = {(e["src"], e["type"], e["dst"]) for e in view["edges"]}
    assert ("VM1", "produces", "E1") in links, \
        "the finding must point at the search that produced it"

    # And both land in the reading band, not among the experiments.
    stages = {n["id"]: n.get("stage") for n in view["nodes"]}
    assert stages["VM1"] == "literature"
    assert stages["E1"] == "literature"


def test_a_card_carries_the_stage_its_band_is_drawn_from(store):
    """The viewer bands a study by stage, and a stage is not an epistemic level.

    The same Evidence type belongs to the reading band when it came out of a
    paper and to the experiment band when a run produced it, so the projection
    has to say which — the type alone cannot.
    """
    _init(store)
    root = store.root_id()
    store.commit(source="ResearchAgent",
                 nodes=[{"type": "Evidence", "ref": "lit",
                         "attrs": {"subtype": "literature", "content": "from a paper"}}],
                 edges=[{"type": "relates_to", "from": "#lit", "to": root}])
    store.commit(source="ExperimentAgent",
                 nodes=[{"type": "VerificationMethod", "ref": "vm",
                         "attrs": {"method_type": "computational"}},
                        {"type": "Evidence", "ref": "run",
                         "attrs": {"subtype": "computational", "content": "AUC=0.91",
                                   "measured_on": "repo@abc123, dataset v2"}}],
                 edges=[{"type": "tested_by", "from": root, "to": "#vm"},
                        {"type": "produces", "from": "#vm", "to": "#run"}])

    stages = {n["id"]: n.get("stage") for n in store.view_of(None)["nodes"]}
    assert stages[root] == "framing"
    assert stages["E1"] == "literature", "a finding read out of a paper"
    assert stages["E2"] == "experiment", "the same type, produced by a run"
    assert stages["VM1"] == "experiment", "placed by what it produced"
    # The derived cards are banded too. The outcome card is only projected once
    # the study has something to sum up, so it is checked where it appears.
    assert stages.get("FRAME") == "framing"
    assert stages.get("OUTCOME", "report") == "report"




def test_a_metabolomics_method_is_not_mistaken_for_a_meta_analysis(store):
    """`meta` is a legal Evidence subtype and `metabolomics` is this domain's
    bread and butter, so the reading test matches whole tokens, never
    substrings."""
    from CoScientist.graph.research.store import _is_reading, _reads_like_review

    assert _is_reading("literature") and _is_reading("meta")
    assert not _is_reading("metabolomics")
    assert not _is_reading("computational")
    # Free text: the plan mirror writes its step as prose, and "dataset
    # overview" must not read as a literature review.
    assert _reads_like_review({"procedure": "По литературе собрать метаболиты"})
    assert not _reads_like_review(
        {"procedure": "dataset_overview and chemical_space_clustering, как в статье"})


# ── getting a hypothesis written at all ──────────────────────────────────────
# The graph almost never closed its arc: across both study runs and 27 of the
# operator's 29 archived studies there were zero hypotheses, so there was
# nothing for the methods to test or the validator to judge. Nothing was
# broken — every route to the generator was worded for uncertainty, and a
# procedural request ("automate X") is the opposite of uncertain. These tests
# pin the three independent places that had to change. They check the mechanism,
# not the model: whether an agent then writes a GOOD hypothesis is not
# something a unit test can answer.


def test_a_study_with_no_hypothesis_says_so_as_an_instruction(store):
    """`open_questions` already computed this and rendered it as the aside
    "no hypotheses yet (branch)", which no line of the orchestrator's action
    table consumed. An unconsumed observation changed nothing."""
    _init(store)
    from CoScientist.graph.research import queries as q

    fired = q.study_without_hypothesis(store)
    assert fired["items"], "a study with a question and no hypothesis"
    assert "NO HYPOTHESIS" in fired["rendered"]
    assert "HypothesesAgent" in fired["rendered"]
    # It has to be in the digest the orchestrator actually reads.
    assert "study_without_hypothesis" in q.TRIGGERS
    assert q.trigger_report(store)["rendered"].startswith("NO HYPOTHESIS")

    # Methods already standing under the question is the aggravating case and is
    # named — with their STATUS. The mirror creates them `planned`, the only
    # creatable status, so calling them "running" was false on every graph that
    # had just been planned and contradicted the PROGRESS line of the same
    # digest.
    store.commit(source="ResearchAgent", nodes=[
        {"type": "VerificationMethod", "ref": "vm", "attrs": {
            "method_type": "literature_review", "procedure": "run it"}}],
        edges=[{"type": "tested_by", "from": store.root_id(), "to": "#vm"}])
    rendered = q.study_without_hypothesis(store)["rendered"]
    assert "nothing to test" in rendered
    assert "VM1 (planned)" in rendered
    assert "are already running" not in rendered,         "do not assert a status the graph itself contradicts"


def test_the_trigger_speaks_again_when_every_branch_is_settled(store):
    """The prompt promises "more come later, and only if the first ones fail",
    and nothing delivered it. Keyed on whether any Hypothesis EXISTS, the
    trigger went silent the moment the first one was written and never spoke
    again — so a study whose sole hypothesis was refuted, with no backlog to
    revive, sat on an open question with every branch dead and nothing
    re-invoking the generator.
    """
    from CoScientist.graph.research import queries as q

    _build_verifiable(store)                       # H1 formulated
    assert not q.study_without_hypothesis(store)["items"], "H1 is live"

    store.commit(source="OrchestratorAgent",
                 status_updates=[{"id": "H1", "status": "under_verification"}])
    assert not q.study_without_hypothesis(store)["items"], "still live"

    store.commit(source="ValidatorAgent",
                 status_updates=[{"id": "H1", "status": "refuted",
                                  "reason": "the assay came back clean"}])
    fired = q.study_without_hypothesis(store)
    assert fired["items"], "nothing live is left under an open question"
    assert "NO LIVE HYPOTHESIS" in fired["rendered"]
    assert "H1 (refuted)" in fired["rendered"]
    assert "HypothesesAgent" in fired["rendered"]

    # A backlog IS something to revive, so the generator is not needed.
    store.commit(source="HypothesesAgent", nodes=[
        {"type": "Hypothesis", "ref": "h2", "status": "postponed",
         "attrs": {"formulation": "the other cluster is the toxic one"}}],
        edges=[{"type": "motivates", "from": store.root_id(), "to": "#h2"}])
    assert not q.study_without_hypothesis(store)["items"], \
        "a postponed branch is work in hand, not a gap"


def test_the_trigger_goes_quiet_once_a_hypothesis_exists(store):
    """A trigger that keeps firing after it has been acted on is noise, and the
    digest is char-budgeted — noise pushes the actionable lines out of it."""
    from CoScientist.graph.research import queries as q

    _build_verifiable(store)          # has H1, formulated
    assert not q.study_without_hypothesis(store)["items"]
    assert not q.study_without_hypothesis(store)["rendered"]


def test_the_orchestrator_is_told_to_get_a_hypothesis_before_running_methods():
    from CoScientist.assembly import load_config
    from CoScientist.assembly.prompting import PromptContext, ToolEntry
    from CoScientist.assembly.registry import REGISTRY

    cfg = load_config()
    ctx = PromptContext(config=cfg.agent("OrchestratorAgent"), system=cfg,
                        tool_entries=[ToolEntry(key="research_graph_orchestrator",
                                                factory=lambda: None)])
    prompt = REGISTRY.prompt("orchestrator")(ctx)
    assert "NO HYPOTHESIS" in prompt, "the trigger needs a line that consumes it"
    # The escape hatch read as an exemption for exactly the tasks that need the
    # graph most: "for a simple one-shot computation or question you may skip
    # the graph" is how a procedural request looks from the inside.
    assert "For a simple one-shot computation" not in prompt
    assert "Anything that gets a" in prompt and "PLAN goes in the graph" in prompt


def test_the_generator_is_asked_for_one_or_two_hypotheses_that_could_be_wrong():
    """It asked for "a small set (2–5)". Five hypotheses on one question buy
    five verification branches and finish none, and the surplus are usually
    the same claim reworded. The ceiling is two, and the two rules underneath
    are what stop a restated request or a method from being filed as one.

    The ceiling has to FOLLOW `web.max_active_hypotheses`, not ignore it: the
    selection scaffolding further down the prompt is generated from that
    setting, so a hardcoded "propose one or two, not five" told the model to
    write two hypotheses and then handed it five SELECTED HYPOTHESIS slots to
    fill. Raising the active limit is the operator asking for more branches.
    """
    from CoScientist.assembly import load_config
    from CoScientist.assembly.prompting import PromptContext
    from CoScientist.assembly.registry import REGISTRY
    from CoScientist.config import get_settings

    cfg = load_config()
    settings = get_settings()
    original = settings.web.max_active_hypotheses
    try:
        rendered = {}
        for limit in (1, 2, 5):
            settings.web.max_active_hypotheses = limit
            rendered[limit] = REGISTRY.prompt("hypotheses")(
                PromptContext(config=cfg.agent("HypothesesAgent"), system=cfg))
    finally:
        settings.web.max_active_hypotheses = original

    for limit, prompt in rendered.items():
        assert "(2–5)" not in prompt, limit
        assert "ONE or TWO" in prompt, f"the preference survives at limit {limit}"
        # The one combination that used to contradict itself.
        if limit > 2:
            assert "Not five" not in prompt, (
                f"limit {limit} offers {limit} selection slots, so the prompt "
                f"must not also forbid five")
            assert f"at most {limit} hypotheses" in prompt
        else:
            assert "Propose ONE or TWO hypotheses" in prompt

    prompt = rendered[2]                      # the configured default
    assert "threshold test" in prompt and "restatement test" in prompt
    # A known route still needs a claim about its outcome — this is the whole
    # reason the generator was never reached on a procedural task.
    assert "A known route still needs one" in prompt
    # And the human's own hypothesis is used rather than competed with.
    assert "If the human already stated one, use theirs" in prompt
    # The paragraph telling it to propose a VerificationMethod plus criteria was
    # in there twice, which is how a prompt starts contradicting itself on edit.
    assert prompt.count("propose HOW each would be verified") == 1


# ── the page ─────────────────────────────────────────────────────────────────

def test_a_card_label_can_never_take_the_page_down():
    """vis compiles a multi:"html" label as a regexp the moment it sees '&'.

    One unbalanced bracket left by the length cut then threw out of the render
    loop, and the canvas stayed blank until a reload. Agents write plain '&'
    themselves, so escaping is not the fix — the character must not reach the
    label at all.
    """
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text

    assert "function visSafe" in page
    assert "replace(/&/g" in page
    assert 'multi: "html"' in page, "the card keeps its bold head and italic foot"
    # The first fix deleted the brackets, so a criterion reading "SA <= 3.5" was
    # drawn as "SA  = 3.5" — a different threshold. The full-width forms are
    # inert to the tokenizer for the same reason the full-width ampersand is.
    assert 'replace(/<=/g, "≤")' in page
    assert 'replace(/</g, "＜")' in page


def test_the_server_and_the_page_agree_on_what_the_stages_are():
    """Five tables have to name the same five bands: the server's STAGES and
    _STAGE_BY_TYPE, and the page's STAGE_ORDER, STAGE_TINT and STAGE_BY_KIND.

    None of the ways they can diverge fails visibly. A band missing from
    STAGE_TINT does not disappear — `stageOf` sends its cards into another band
    instead — and a stage the page does not list is dropped from the layout, so
    a whole phase of the study goes quietly missing. ELK now reads STAGE_ORDER
    as its partition index too, so a divergence also puts cards in the wrong
    layer rather than merely the wrong colour.
    """
    import re

    from starlette.testclient import TestClient

    from CoScientist.graph.research.store import STAGES, _STAGE_BY_TYPE
    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text

    order = re.search(r"const STAGE_ORDER = \[(.*?)\];", page, re.S)
    assert order, "the page must still declare STAGE_ORDER"
    assert re.findall(r'"([a-z]+)"', order.group(1)) == list(STAGES)

    tint = re.search(r"const STAGE_TINT = \{(.*?)\n    \};", page, re.S)
    assert tint, "the page must still declare STAGE_TINT"
    for stage in STAGES:
        assert re.search(r"\b" + stage + r":\s*\{", tint.group(1)), \
            f"{stage} has no tint, so stageOf silently rehomes its cards"

    # And every band the projection can name has somewhere to land.
    assert set(_STAGE_BY_TYPE.values()) <= set(STAGES)
    by_kind = re.search(r"const STAGE_BY_KIND = \{(.*?)\};", page, re.S)
    assert by_kind, "the fallback for studies archived before the server sent a stage"
    for kind, stage in re.findall(r'([a-z]+):\s*"([a-z]+)"', by_kind.group(1)):
        assert stage in STAGES, f"STAGE_BY_KIND sends {kind} to unknown band {stage}"


def test_the_page_computes_its_layout_with_a_layout_engine():
    """Cards were flowed row by row, which got every card into the right band
    but ordered them arbitrarily inside it: the evidence a method produced sat
    six cards away with three unrelated methods in between. Ordering is ELK's
    now — and only the ordering. vis-network is still the renderer, so the
    label-safety and multi:"html" guarantees above still hold."""
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text
        assert client.get("/static/elk.bundled.js").status_code == 200

    assert "/static/elk.bundled.js" in page
    assert '"elk.algorithm": "layered"' in page
    # The bands ARE the partitions — without this ELK is free to lift a
    # conclusion into the framing row because it has fewer crossings there.
    assert '"elk.partitioning.activate": "true"' in page
    assert "elk.partitioning.partition" in page
    # A 1.6MB script that fails to load must cost the study its ordering, not
    # its drawing.
    assert "function flowSeats" in page
    assert "new vis.Network" in page


def test_the_page_stopped_offering_a_view_it_no_longer_draws():
    """One graph, one canvas. The slide renderer stays, for reports."""
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text

    assert 'value="slide"' not in page
    assert "pollSlide" not in page


def test_a_step_is_placed_by_what_it_does_not_by_what_it_mentions(store):
    """Every plan step of one real study landed under the wrong stage heading.

    The classifier read the whole of a step — title, description and notes — so
    a step was filed under any stage its prose happened to name. A Tanimoto
    clustering run went to the literature band because its description said
    "merge with the literature SMILES from TASK-2"; a QSAR LD50 prediction went
    to the report band because its description said the table then goes to the
    final report. The operator read it exactly as it was drawn: "the step
    «collect the literature» is at the framing stage, the step «predict ld50» is
    in the report".

    What a step IS is in its title. What it TOUCHES is in its description.
    """
    _init(store)
    steps = [
        # The two that were misfiled, verbatim from the study.
        {"title": "Кластеризация литературных SMILES по структурному сходству",
         "description": "Провести кластеризацию на литературных SMILES из TASK-2",
         "assignee": "TaskExecutorAgent", "plan_task_id": "TASK-5"},
        {"title": "QSAR-предсказания: LD50 по путям введения и домен применимости",
         "description": "Передать таблицу к финальному отчёту исследования",
         "assignee": "TaskExecutorAgent", "plan_task_id": "TASK-4"},
        # A step that really is gathering, and says so in its title.
        {"title": "Собрать литературные данные о метаболитах и их SMILES",
         "description": "PubMed, PubChem, ChEMBL",
         "assignee": "TaskExecutorAgent", "plan_task_id": "TASK-2"},
    ]
    store.commit(source="plan-mirror",
                 nodes=[{"type": "PlanStep", "attrs": a} for a in steps])

    stage = {n["id"]: n["stage"] for n in store.view_of(None)["nodes"]
             if n["kind"] == "planstep"}
    assert stage["PS1"] == "experiment", "clustering is a run, whatever it clusters"
    assert stage["PS2"] == "experiment", "a prediction is not a write-up"
    assert stage["PS3"] == "literature", "this one really is gathering sources"


def test_an_agent_with_one_job_places_the_step_its_title_cannot(store):
    """The assignee is the only part of a step the planner picks off a fixed
    roster instead of writing as prose, so where it means something it decides.

    Where it does not: TaskExecutorAgent describes itself as routing each task
    to whatever can deliver it, and the planner hands it literature collection
    as readily as a QSAR run — in one study four of five steps were its, across
    three stages. A generic executor says nothing about the stage, so the
    wording has to.
    """
    _init(store)
    store.commit(source="plan-mirror", nodes=[
        # Titled as a run, assigned to the agent whose whole job is reading.
        {"type": "PlanStep", "attrs": {
            "title": "Кластеризация по структурному сходству",
            "assignee": "ResearchAgent", "plan_task_id": "TASK-1"}},
        # Titled as gathering, assigned to the aggregator that writes the report.
        {"type": "PlanStep", "attrs": {
            "title": "Собрать литературу по фуранокумаринам",
            "assignee": "ResultAggregatorAgent", "plan_task_id": "TASK-2"}},
        # Nobody assigned it, so the title is all there is.
        {"type": "PlanStep", "attrs": {
            "title": "Обзор публикаций по фуранокумаринам",
            "assignee": "unassigned", "plan_task_id": "TASK-3"}},
    ])

    stage = {n["id"]: n["stage"] for n in store.view_of(None)["nodes"]
             if n["kind"] == "planstep"}
    assert stage["PS1"] == "literature"
    assert stage["PS2"] == "report"
    assert stage["PS3"] == "literature"


def test_a_band_is_sized_for_both_tracks_so_no_step_leaves_its_stage():
    """The plan column used to be centred in whatever height the RECORD needed,
    and allowed to overflow. Every study spends its first minutes as four plan
    steps and two cards, and at that size the steps were pushed clean out of
    their own band: one landed under the heading of the stage above, and two
    from different stages landed on top of each other. Measured on the
    operator's own study: 307x104 pixels of one card covered by another, and a
    literature step 135 pixels inside the framing band.

    A step drawn outside its band is worse than a step drawn small: the column's
    only job is to say which stage the plan asked for, and outside its band it
    says a different one. So the plan's height is measured BEFORE the bands are
    sized, and the band is made tall enough to hold whichever track needs more.
    """
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text

    assert "function planBlocks(place)" in page, \
        "the plan's height has to be measurable before the bands are sized"
    # Both stackers ask for it, and both take the larger of the two tracks.
    assert page.count("planBlocks(place)") == 3, \
        "ELK's stacker and the ELK-less fallback must both size for the plan"
    assert page.count("Math.max(BAND_MIN_HEIGHT, recordH, planH)") == 2, \
        "a band that ignores one of its two tracks lets that track overflow"
    # And the column may no longer compute its own centring from the record's
    # bands alone, which is what allowed the overflow.
    assert "function planColumn(bands, leftEdge, blocks)" in page


def test_the_stage_names_are_drawn_where_no_card_can_reach():
    """The names used to be painted inside each band, at its top-left corner —
    which is exactly where the plan column then put its first card. Three of the
    five names were unreadable on the operator's study, including the two whose
    bands had a step in them.

    The names go in a rail of their own, left of every card in either track.
    Nothing is ever seated there, so no rearrangement can bring this back.
    """
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text

    assert "function railWidth()" in page
    # Right-aligned OUTSIDE the band's left edge, not inset from it.
    assert "const railX = b.left - RAIL_GAP" in page
    assert "b.left + 16, b.top + 12" not in page, \
        "a name inside the band is a name a card can cover"
    # Every band carries the rail's edge, and the camera opens wide enough to
    # show it — a name the reader has to pan to find is no better than a hidden
    # one.
    assert "function addRail(bands)" in page
    assert page.count("addRail(bands);") == 2, \
        "both stackers have to set it, or one of them draws names over cards"
    assert "b.railLeft != null ? b.railLeft : b.left" in page


def test_an_undrawn_card_is_not_treated_as_a_card_of_no_size():
    """vis reports {0,0,0,0} for a node it has not drawn yet rather than
    reporting nothing, so the truthiness test accepted it as a measurement. A
    column of zero-height cards stacks every one of them at the same point.
    """
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/graph").text

    assert "box.right - box.left > 1 && box.bottom - box.top > 1" in page
