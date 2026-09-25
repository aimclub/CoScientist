"""graph_bridge: approved plan → VM/tested_by; result → Evidence/GeneratedData."""
from __future__ import annotations

from types import SimpleNamespace

from CoScientist.graph.research.store import ResearchGraphStore

from .helpers import _approved_state, _plan, _task


def _seeded_store(
    tmp_path,
    extra: list[dict] | None = None,
) -> ResearchGraphStore:
    """A research graph with a root question and Hypothesis H1 (+ optional extras).

    Extra hypotheses are committed one-by-one so the store's max_active
    selection does not auto-postpone them before the bridge runs.
    """
    store = ResearchGraphStore(directory=str(tmp_path))
    store.init_research(source="ContextInitAgent", question="Root question?")
    root = store.root_id()
    store.commit(
        source="HypothesesAgent",
        nodes=[{"type": "Hypothesis", "ref": "h1",
                "attrs": {"formulation": "Compound X inhibits target Y."}}],
        edges=[{"type": "motivates", "from": root, "to": "#h1"}],
        enforce_permissions=False,
    )
    for index, item in enumerate(extra or [], start=2):
        ref = f"h{index}"
        draft = {"type": "Hypothesis", "ref": ref,
                 "attrs": {"formulation": item.get("formulation") or f"Claim {index}."}}
        if item.get("status"):
            draft["status"] = item["status"]
        store.commit(
            source="HypothesesAgent",
            nodes=[draft],
            edges=[{"type": "motivates", "from": root, "to": f"#{ref}"}],
            enforce_permissions=False,
        )
    return store


def _node_status(store: ResearchGraphStore) -> dict[str, str]:
    return {n["id"]: n["status"] for n in store.full()["nodes"]}


def _nodes_by_type(store: ResearchGraphStore) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for node in store.full()["nodes"]:
        out.setdefault(node["type"], []).append(node["id"])
    return out


def test_publish_plan_creates_vm_and_tested_by(tmp_path):
    from CoScientist.experiments.runtime.graph_bridge import publish_plan_to_graph

    store = _seeded_store(tmp_path)
    state = _approved_state(_plan(_task("EXP-1", hypothesis_ref="H1")))

    publish_plan_to_graph(store, state)

    by_type = _nodes_by_type(store)
    assert len(by_type.get("VerificationMethod", [])) == 1
    vm_id = by_type["VerificationMethod"][0]
    assert state["experiment_graph_vm_ids"]["EXP-1"] == vm_id
    edges = store.full()["edges"]
    assert any(e["type"] == "tested_by" and e["from"] == "H1" and e["to"] == vm_id
               for e in edges)
    # VerificationMethod node attrs must contain mcp_servers
    vm_node = next(n for n in store.full()["nodes"] if n["id"] == vm_id)
    assert "mcp_servers" in vm_node.get("attrs", {})
    mcp_servers = vm_node["attrs"]["mcp_servers"]
    assert len(mcp_servers) >= 1
    assert mcp_servers[0]["url"] == "http://127.0.0.1:8000/mcp"
    assert "estimate_property" in mcp_servers[0]["tools"]


def test_publish_plan_is_idempotent(tmp_path):
    from CoScientist.experiments.runtime.graph_bridge import publish_plan_to_graph

    store = _seeded_store(tmp_path)
    state = _approved_state(_plan(_task("EXP-1", hypothesis_ref="H1")))

    publish_plan_to_graph(store, state)
    first_vm = dict(state["experiment_graph_vm_ids"])
    publish_plan_to_graph(store, state)

    assert _nodes_by_type(store).get("VerificationMethod") == [first_vm["EXP-1"]]
    assert state["experiment_graph_vm_ids"] == first_vm


def test_publish_result_writes_evidence_and_vm_status(tmp_path):
    from CoScientist.experiments.runtime.graph_bridge import (
        publish_plan_to_graph,
        publish_result_to_graph,
    )

    store = _seeded_store(tmp_path)
    state = _approved_state(_plan(_task("EXP-1", hypothesis_ref="H1")))
    publish_plan_to_graph(store, state)
    vm_id = state["experiment_graph_vm_ids"]["EXP-1"]

    task_result = {
        "result_id": "RES-1",
        "status": "success",
        "summary": "EXP-1 produced a managed result.",
        "artifacts": [{"name": "metrics.json", "bucket": "b", "s3_key": "k/metrics.json"}],
    }
    publish_result_to_graph(store, state, "EXP-1", task_result)

    by_type = _nodes_by_type(store)
    assert len(by_type.get("Evidence", [])) == 1
    assert len(by_type.get("GeneratedData", [])) == 1
    evidence_id = by_type["Evidence"][0]
    gd_id = by_type["GeneratedData"][0]
    edges = store.full()["edges"]
    assert any(e["type"] == "produces" and e["from"] == vm_id and e["to"] == evidence_id
               for e in edges)
    assert any(e["type"] == "derived_from" and e["from"] == gd_id and e["to"] == evidence_id
               for e in edges)
    assert any(e["type"] == "relates_to" and e["from"] == evidence_id and e["to"] == "H1"
               for e in edges)
    statuses = _node_status(store)
    assert statuses[vm_id] == "done"
    assert statuses["H1"] == "under_verification"


def test_publish_result_failure_marks_vm_failed(tmp_path):
    from CoScientist.experiments.runtime.graph_bridge import (
        publish_plan_to_graph,
        publish_result_to_graph,
    )

    store = _seeded_store(tmp_path)
    state = _approved_state(_plan(_task("EXP-1", hypothesis_ref="H1")))
    publish_plan_to_graph(store, state)
    vm_id = state["experiment_graph_vm_ids"]["EXP-1"]

    publish_result_to_graph(store, state, "EXP-1",
                            {"result_id": "RES-2", "status": "failure", "summary": "boom"})

    by_type = _nodes_by_type(store)
    assert by_type.get("Evidence") is None
    vm_status = {n["id"]: n["status"] for n in store.full()["nodes"]}[vm_id]
    assert vm_status == "failed"


def test_publish_result_skips_when_no_vm(tmp_path):
    from CoScientist.experiments.runtime.graph_bridge import publish_result_to_graph

    store = _seeded_store(tmp_path)
    state: dict = {}
    publish_result_to_graph(store, state, "EXP-1",
                            {"result_id": "RES-3", "status": "success", "summary": "x"})
    assert _nodes_by_type(store).get("Evidence") is None


def test_publish_plan_swallows_store_errors():
    from CoScientist.experiments.runtime.graph_bridge import (
        publish_plan_to_graph,
        publish_result_to_graph,
    )

    class _Boom:
        def overview(self):
            raise RuntimeError("graph down")

        def commit(self, *a, **k):
            raise RuntimeError("graph down")

    state = _approved_state(_plan(_task("EXP-1", hypothesis_ref="H1")))
    # Must not raise — best-effort contract.
    publish_plan_to_graph(_Boom(), state)
    state["experiment_graph_vm_ids"] = {"EXP-1": "VM1"}
    publish_result_to_graph(_Boom(), state, "EXP-1",
                            {"result_id": "RES-4", "status": "success", "summary": "x"})


def test_publish_result_links_also_tests(tmp_path):
    from CoScientist.experiments.runtime.graph_bridge import (
        publish_plan_to_graph,
        publish_result_to_graph,
    )
    from .helpers import _design

    store = _seeded_store(
        tmp_path,
        extra=[{"formulation": "Secondary claim also tested by the same run."}],
    )
    design = _design("H1")
    design["also_tests"] = ["H2"]
    state = _approved_state(_plan(_task("EXP-1", design=design)))
    publish_plan_to_graph(store, state)

    publish_result_to_graph(store, state, "EXP-1", {
        "result_id": "RES-5",
        "status": "success",
        "summary": "Shared evidence.",
        "artifacts": [{"name": "out.csv", "bucket": "b", "s3_key": "k/out.csv"}],
    })

    evidence_id = _nodes_by_type(store)["Evidence"][0]
    edges = store.full()["edges"]
    linked = {e["to"] for e in edges
              if e["type"] == "relates_to" and e["from"] == evidence_id}
    assert linked == {"H1", "H2"}
    statuses = _node_status(store)
    assert statuses["H1"] == "under_verification"
    assert statuses["H2"] == "under_verification"


def test_publish_plan_postpones_uncovered_hypotheses(tmp_path):
    from CoScientist.experiments.runtime.graph_bridge import publish_plan_to_graph

    store = _seeded_store(
        tmp_path,
        extra=[{"formulation": "No task can test this alternative."}],
    )
    state = _approved_state(_plan(_task("EXP-1", hypothesis_ref="H1")))
    publish_plan_to_graph(store, state)

    statuses = _node_status(store)
    assert statuses["H1"] == "formulated"
    assert statuses["H2"] == "postponed"
    h2 = next(n for n in store.full()["nodes"] if n["id"] == "H2")
    reasons = " ".join(str(row.get("reason") or "") for row in (h2.get("status_history") or []))
    assert "no_method_this_stage" in reasons


def test_publish_plan_revives_postponed_when_task_covers(tmp_path):
    from CoScientist.experiments.runtime.graph_bridge import publish_plan_to_graph

    store = _seeded_store(
        tmp_path,
        extra=[{
            "formulation": "Parked alternative now assigned a task.",
            "status": "postponed",
        }],
    )
    assert _node_status(store)["H2"] == "postponed"
    state = _approved_state(_plan(_task("EXP-1", hypothesis_ref="H2")))
    publish_plan_to_graph(store, state)

    statuses = _node_status(store)
    assert statuses["H2"] == "formulated"
    assert statuses["H1"] == "postponed"


def test_publish_result_schedules_background_judgment(tmp_path, monkeypatch):
    from CoScientist.experiments.runtime import graph_bridge

    store = _seeded_store(tmp_path)
    state = _approved_state(_plan(_task("EXP-1", hypothesis_ref="H1")))
    graph_bridge.publish_plan_to_graph(store, state)
    called: list[object] = []
    monkeypatch.setattr(
        graph_bridge, "_schedule_hypothesis_judgments",
        lambda graph: called.append(graph) or 1,
    )
    graph_bridge.publish_result_to_graph(store, state, "EXP-1", {
        "result_id": "RES-6",
        "status": "success",
        "summary": "Ready to judge.",
        "artifacts": [{"name": "out.csv", "bucket": "b", "s3_key": "k/out.csv"}],
    })
    assert called == [store]
