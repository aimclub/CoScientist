import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from CoScientist.graph.memory import get_knowledge_graph
from CoScientist.graph.memory_store import (
    KnowledgeMemory,
    get_global_knowledge_memory,
    get_knowledge_memory,
    knowledge_memory,
)
from CoScientist.graph.knowledge import to_knowledge_graph
from CoScientist.graph.models import Edge, Node
from CoScientist.graph.research import store as research_store
from CoScientist.graph.semantic import Entity, Extraction, Relation
from CoScientist.graph.store import GraphStore


def _scope_ids():
    token = uuid4().hex
    return f"user_{token}", f"session_{token}_a", f"session_{token}_b"


def _create_user(client: TestClient, nickname: str) -> dict:
    response = client.post("/api/users", json={"nickname": nickname})
    assert response.status_code == 201
    return response.json()["user"]


def _create_session(client: TestClient, user_id: str, title: str) -> dict:
    response = client.post(
        f"/api/users/{user_id}/sessions",
        json={"title": title},
    )
    assert response.status_code == 201
    return response.json()["session"]


def test_graph_store_loads_snapshot_before_first_write(tmp_path):
    snapshot_dir = tmp_path / "execution"
    original = GraphStore(snapshot_dir=str(snapshot_dir))
    original.add_node(Node(
        id="old-goal",
        run_id="execution",
        kind="goal",
        label="persisted goal",
    ))
    original.add_node(Node(
        id="old-result",
        run_id="execution",
        kind="result",
        label="persisted result",
        status="success",
    ))
    original.add_edge(Edge(
        run_id="execution",
        src="old-goal",
        dst="old-result",
        type="produced",
    ))

    # The first operation on a new object is a write: it must merge with the
    # existing snapshot instead of replacing it with a one-node graph.
    restored = GraphStore(snapshot_dir=str(snapshot_dir))
    restored.add_node(Node(
        id="new-goal",
        run_id="execution",
        kind="goal",
        label="new goal",
    ))

    reloaded = GraphStore(snapshot_dir=str(snapshot_dir)).full("execution")
    assert {node["id"] for node in reloaded["nodes"]} == {
        "old-goal",
        "old-result",
        "new-goal",
    }
    assert {(
        edge["src"], edge["dst"], edge["type"]
    ) for edge in reloaded["edges"]} == {
        ("old-goal", "old-result", "produced")
    }


def test_graph_store_does_not_overwrite_unreadable_snapshot(tmp_path):
    snapshot_dir = tmp_path / "execution"
    snapshot_dir.mkdir()
    snapshot = snapshot_dir / "execution.json"
    damaged_contents = '{"nodes": ['
    snapshot.write_text(damaged_contents, encoding="utf-8")

    store = GraphStore(snapshot_dir=str(snapshot_dir))
    store.add_node(Node(
        id="new-goal",
        run_id="execution",
        kind="goal",
    ))

    assert snapshot.read_text(encoding="utf-8") == damaged_contents

    # An explicit reset remains available and replaces the broken snapshot.
    store.clear("execution")
    assert json.loads(snapshot.read_text(encoding="utf-8"))["nodes"] == []


def test_corrupt_global_memory_is_reported_and_never_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "memory" / "knowledge_memory.json"
    path.parent.mkdir()
    damaged_contents = '{"entities": ['
    path.write_text(damaged_contents, encoding="utf-8")
    monkeypatch.setenv("KG_MEMORY_PATH", str(path))

    memory = get_global_knowledge_memory()
    result = memory.ingest(
        Extraction(
            entities=[
                Entity(key="molecule:a", type="molecule", name="A"),
                Entity(key="target:b", type="target", name="B"),
            ],
            relations=[
                Relation(src="molecule:a", dst="target:b", type="inhibits")
            ],
        ),
        refs={"result_id": "result:must-not-persist"},
    )

    assert result["persisted"] is False
    assert result["error"]
    assert memory.health()["healthy"] is False
    assert path.read_text(encoding="utf-8") == damaged_contents

    from CoScientist.web.app import create_app
    with TestClient(create_app()) as client:
        response = client.get("/api/knowledge")
    assert response.status_code == 503
    assert response.json()["storage"]["healthy"] is False


def test_execution_graphs_are_isolated_by_session(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_SNAPSHOT_DIR", str(tmp_path / "execution"))
    user_id, first_session, second_session = _scope_ids()

    first = get_knowledge_graph(user_id=user_id, session_id=first_session)
    second = get_knowledge_graph(user_id=user_id, session_id=second_session)
    first.add_node(id="goal:first-session", kind="goal", label="first")
    second.add_node(id="goal:second-session", kind="goal", label="second")

    first_ids = {node["id"] for node in first.full()["nodes"]}
    second_ids = {node["id"] for node in second.full()["nodes"]}

    assert first is get_knowledge_graph(
        user_id=user_id,
        session_id=first_session,
    )
    assert first is not second
    assert "goal:first-session" in first_ids
    assert "goal:first-session" not in second_ids
    assert "goal:second-session" in second_ids
    assert "goal:second-session" not in first_ids


def test_research_graphs_are_isolated_by_session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        research_store,
        "_default_dir",
        lambda: str(tmp_path / "research"),
    )
    user_id, first_session, second_session = _scope_ids()

    first = research_store.get_research_graph(
        user_id=user_id,
        session_id=first_session,
    )
    second = research_store.get_research_graph(
        user_id=user_id,
        session_id=second_session,
    )
    first_result = first.init_research(
        source="OrchestratorAgent",
        question="Question visible only in the first session?",
    )
    second_result = second.init_research(
        source="OrchestratorAgent",
        question="Question visible only in the second session?",
    )

    assert first_result["ok"] and second_result["ok"]
    assert first is not second
    assert first.full_graph().nodes["Q1"]["attrs"]["formulation"].startswith(
        "Question visible only in the first"
    )
    assert second.full_graph().nodes["Q1"]["attrs"]["formulation"].startswith(
        "Question visible only in the second"
    )


def test_semantic_memory_is_global_across_users_and_sessions(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "KG_MEMORY_PATH",
        str(tmp_path / "memory" / "knowledge_memory.json"),
    )
    first_user, first_session, second_session = _scope_ids()
    second_user = f"user_{uuid4().hex}"

    first = get_knowledge_memory(
        user_id=first_user,
        session_id=first_session,
    )
    same_user_other_session = get_knowledge_memory(
        user_id=first_user,
        session_id=second_session,
    )
    other_user = get_knowledge_memory(
        user_id=second_user,
        session_id=first_session,
    )

    marker = uuid4().hex
    molecule_key = f"molecule:{marker}"
    target_key = f"target:{marker}"
    first.ingest(
        Extraction(
            entities=[
                Entity(key=molecule_key, type="molecule", name=molecule_key),
                Entity(key=target_key, type="target", name=target_key),
            ],
            relations=[
                Relation(src=molecule_key, dst=target_key, type="inhibits"),
            ],
        ),
        source="session-one",
    )

    assert first is same_user_other_session
    assert first is other_user
    assert first is knowledge_memory
    assert first is get_global_knowledge_memory()
    assert marker in str(same_user_other_session.full())
    assert marker in str(other_user.full())


def test_global_memory_provenance_dedup_preserves_user_session_scope(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "KG_MEMORY_PATH",
        str(tmp_path / "memory" / "knowledge_memory.json"),
    )
    memory = get_knowledge_memory(
        user_id="user-a",
        session_id="session-a",
    )
    marker = uuid4().hex
    molecule_key = f"molecule:{marker}"
    target_key = f"target:{marker}"
    extraction = Extraction(
        entities=[
            Entity(key=molecule_key, type="molecule", name=molecule_key),
            Entity(key=target_key, type="target", name=target_key),
        ],
        relations=[
            Relation(src=molecule_key, dst=target_key, type="inhibits"),
        ],
    )
    first_ref = {
        "user_id": "user-a",
        "session_id": "session-a",
        "run": "shared-run-id",
        "result_id": "result:shared-id",
    }
    second_ref = {
        "user_id": "user-b",
        "session_id": "session-b",
        "run": "shared-run-id",
        "result_id": "result:shared-id",
    }

    memory.ingest(extraction, source="same-source", refs=first_ref)
    memory.ingest(extraction, source="same-source", refs=second_ref)
    memory.ingest(extraction, source="same-source", refs=first_ref)

    entity = memory.entities[molecule_key.replace(":", "-")]
    relation = next(iter(memory.relations.values()))
    expected_scopes = [
        ("user-a", "session-a"),
        ("user-b", "session-b"),
    ]
    assert [
        (item["user_id"], item["session_id"])
        for item in entity["provenance"]
    ] == expected_scopes
    assert [
        (item["user_id"], item["session_id"])
        for item in relation["provenance"]
    ] == expected_scopes


def test_session_knowledge_projection_uses_exact_global_provenance(tmp_path):
    memory = KnowledgeMemory(str(tmp_path / "global.json"))
    extraction = Extraction(
        entities=[
            Entity(key="molecule:a", type="molecule", name="A"),
            Entity(key="target:b", type="target", name="B"),
        ],
        relations=[
            Relation(
                src="molecule:a",
                dst="target:b",
                type="score",
                attrs={"value": 1},
            ),
        ],
    )
    # Deliberately use the same question text. Text matching alone would leak
    # the fact into a different user's/session's knowledge projection.
    memory.ingest(
        extraction,
        source="Same research question",
        refs={
            "user_id": "user-a",
            "session_id": "session-a",
            "run": "inv-a",
            "goal_id": "goal:inv-a",
            "result_id": "result:inv-a",
        },
    )
    memory.ingest(
        Extraction(
            entities=extraction.entities,
            relations=[
                Relation(
                    src="molecule:a",
                    dst="target:b",
                    type="score",
                    attrs={"value": 2},
                )
            ],
        ),
        source="Same research question",
        refs={
            "user_id": "user-b",
            "session_id": "session-b",
            "run": "inv-b",
            "goal_id": "goal:inv-b",
            "result_id": "result:inv-b",
        },
    )
    execution = {
        "run_id": "execution",
        "nodes": [
            {
                "id": "goal:inv-a",
                "kind": "goal",
                "label": "Same research question",
            }
        ],
        "edges": [],
    }

    own = to_knowledge_graph(
        execution,
        memory=memory,
        user_id="user-a",
        session_id="session-a",
    )
    other_execution = {
        "run_id": "execution",
        "nodes": [
            {
                "id": "goal:inv-b",
                "kind": "goal",
                "label": "Same research question",
            }
        ],
        "edges": [],
    }
    other = to_knowledge_graph(
        other_execution,
        memory=memory,
        user_id="user-b",
        session_id="session-b",
    )

    own_facts = [node["label"] for node in own["nodes"] if node["kind"] == "fact"]
    other_facts = [
        node["label"] for node in other["nodes"] if node["kind"] == "fact"
    ]
    assert own_facts == ["A score B = 1"]
    assert other_facts == ["A score B = 2"]


def test_historical_session_projection_survives_many_global_confirmations(tmp_path):
    memory = KnowledgeMemory(str(tmp_path / "global.json"))
    extraction = Extraction(
        entities=[
            Entity(key="molecule:a", type="molecule", name="A"),
            Entity(key="target:b", type="target", name="B"),
        ],
        relations=[Relation(src="molecule:a", dst="target:b", type="inhibits")],
    )
    for index in range(25):
        memory.ingest(
            extraction,
            source=f"Question {index}",
            refs={
                "user_id": f"user-{index}",
                "session_id": f"session-{index}",
                "run": f"inv-{index}",
                "goal_id": f"goal:inv-{index}",
                "result_id": f"result:inv-{index}",
            },
        )

    projection = to_knowledge_graph(
        {
            "run_id": "execution",
            "nodes": [{
                "id": "goal:inv-0",
                "kind": "goal",
                "label": "Question 0",
            }],
            "edges": [],
        },
        memory=memory,
        user_id="user-0",
        session_id="session-0",
    )

    relation = next(iter(memory.relations.values()))
    assert len(relation["provenance"]) == 25
    assert any(node["kind"] == "fact" for node in projection["nodes"])


def test_global_memory_canonicalizes_unicode_entities_without_collision(tmp_path):
    memory = KnowledgeMemory(str(tmp_path / "global.json"))
    result = memory.ingest(
        Extraction(
            entities=[
                Entity(key="molecule:молекула", type="molecule", name="Молекула"),
                Entity(key="target:мишень", type="target", name="Мишень"),
            ],
            relations=[
                Relation(
                    src="molecule:молекула",
                    dst="target:мишень",
                    type="ингибирует",
                )
            ],
        ),
        source="Кириллический факт",
        refs={"result_id": "result:unicode"},
    )

    assert result["persisted"] is True
    assert set(memory.entities) == {"молекула", "мишень"}
    assert len(memory.relations) == 1
    assert memory.relevant("молекула")


def test_session_reset_never_clears_global_knowledge(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_SNAPSHOT_DIR", str(tmp_path / "execution"))
    monkeypatch.setenv(
        "KG_MEMORY_PATH",
        str(tmp_path / "memory" / "knowledge_memory.json"),
    )
    user_id, session_id, _other_session = _scope_ids()
    execution = get_knowledge_graph(user_id=user_id, session_id=session_id)
    execution.add_node(id="goal:to-reset", kind="goal", label="temporary")

    memory = get_knowledge_memory(user_id=user_id, session_id=session_id)
    marker = uuid4().hex
    memory.ingest(
        Extraction(
            entities=[
                Entity(key=f"molecule:{marker}", type="molecule", name=marker),
                Entity(key=f"target:{marker}", type="target", name=f"target-{marker}"),
            ],
            relations=[
                Relation(
                    src=f"molecule:{marker}",
                    dst=f"target:{marker}",
                    type="inhibits",
                )
            ],
        ),
        refs={
            "user_id": user_id,
            "session_id": session_id,
            "result_id": "result:to-reset",
        },
    )

    from CoScientist.main import reset_session_state
    reset_session_state(user_id, session_id, reset_research=False)

    assert "goal:to-reset" not in {
        node["id"] for node in execution.full()["nodes"]
    }
    assert marker in str(get_knowledge_memory().full())


def test_explicit_reset_archives_only_selected_research_session(
    tmp_path,
    monkeypatch,
):
    execution_dir = tmp_path / "execution"
    research_dir = tmp_path / "research"
    monkeypatch.setenv("GRAPH_SNAPSHOT_DIR", str(execution_dir))
    monkeypatch.setenv(
        "KG_MEMORY_PATH",
        str(tmp_path / "memory" / "knowledge_memory.json"),
    )
    monkeypatch.setattr(research_store, "_default_dir", lambda: str(research_dir))
    user_id, first_session, second_session = _scope_ids()

    first_execution = get_knowledge_graph(
        user_id=user_id,
        session_id=first_session,
    )
    second_execution = get_knowledge_graph(
        user_id=user_id,
        session_id=second_session,
    )
    first_execution.add_node(id="goal:first-reset", kind="goal")
    second_execution.add_node(id="goal:must-remain", kind="goal")

    first_research = research_store.get_research_graph(
        user_id=user_id,
        session_id=first_session,
    )
    second_research = research_store.get_research_graph(
        user_id=user_id,
        session_id=second_session,
    )
    assert first_research.init_research(
        source="OrchestratorAgent",
        question="Archive only this research",
    )["ok"]
    assert second_research.init_research(
        source="OrchestratorAgent",
        question="Keep this research active",
    )["ok"]

    from CoScientist.main import reset_session_state
    reset_session_state(user_id, first_session, reset_research=True)

    assert "goal:first-reset" not in {
        node["id"] for node in first_execution.full()["nodes"]
    }
    assert "goal:must-remain" in {
        node["id"] for node in second_execution.full()["nodes"]
    }
    assert first_research.full()["nodes"] == []
    assert second_research.full()["nodes"]

    first_session_dir = (
        research_dir / "sessions" / user_id / first_session
    )
    assert [
        path for path in first_session_dir.glob("research_*.json")
        if path.name != "research_active.json"
    ]
    assert not list(
        path
        for path in (
            research_dir / "sessions" / user_id / second_session
        ).glob("research_*.json")
        if path.name != "research_active.json"
    )


def test_per_user_memory_migration_is_idempotent_and_keeps_sources(
    tmp_path,
    monkeypatch,
):
    canonical_path = tmp_path / "memory" / "knowledge_memory.json"
    monkeypatch.setenv("KG_MEMORY_PATH", str(canonical_path))
    marker = uuid4().hex
    molecule_key = f"molecule:{marker}"
    target_key = f"target:{marker}"
    extraction = Extraction(
        entities=[
            Entity(key=molecule_key, type="molecule", name=molecule_key),
            Entity(key=target_key, type="target", name=target_key),
        ],
        relations=[
            Relation(src=molecule_key, dst=target_key, type="inhibits"),
        ],
    )

    source_contents = {}
    for user_id in ("user-a", "user-b"):
        source_path = (
            canonical_path.parent
            / "users"
            / user_id
            / "knowledge_memory.json"
        )
        legacy = KnowledgeMemory(str(source_path))
        legacy.ingest(
            extraction,
            source="legacy-source",
            refs={
                "run": "shared-run-id",
                "result_id": "result:shared-id",
            },
        )
        source_contents[source_path] = source_path.read_bytes()

    memory = get_knowledge_memory(
        user_id="new-user",
        session_id="new-session",
    )
    entity_id = molecule_key.replace(":", "-")
    provenance = memory.entities[entity_id]["provenance"]
    assert {item["user_id"] for item in provenance} == {"user-a", "user-b"}
    assert len(provenance) == 2
    assert all(path.read_bytes() == contents for path, contents in source_contents.items())

    # A fresh object simulates a process restart and reloads migration markers
    # from the canonical JSON. Re-running migration must not inflate counts or
    # duplicate provenance.
    before = canonical_path.read_bytes()
    reloaded = KnowledgeMemory(str(canonical_path))
    assert reloaded._migrate_legacy_user_memories() == 0
    assert canonical_path.read_bytes() == before
    assert len(reloaded.entities[entity_id]["provenance"]) == 2

    # Copying the whole deployment tree to a different absolute directory must
    # not make the same legacy sources look new.
    moved_canonical = tmp_path / "moved" / "memory" / "knowledge_memory.json"
    moved_canonical.parent.mkdir(parents=True)
    moved_canonical.write_bytes(canonical_path.read_bytes())
    for source_path, contents in source_contents.items():
        relative = source_path.relative_to(canonical_path.parent)
        moved_source = moved_canonical.parent / relative
        moved_source.parent.mkdir(parents=True, exist_ok=True)
        moved_source.write_bytes(contents)

    moved = KnowledgeMemory(str(moved_canonical))
    relation_count = next(iter(moved.relations.values()))["count"]
    assert moved._migrate_legacy_user_memories() == 0
    assert next(iter(moved.relations.values()))["count"] == relation_count


def test_web_graph_api_is_scoped_to_registered_session(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_SNAPSHOT_DIR", str(tmp_path / "execution"))
    monkeypatch.setenv(
        "KG_MEMORY_PATH",
        str(tmp_path / "memory" / "knowledge_memory.json"),
    )
    monkeypatch.setattr(
        research_store,
        "_default_dir",
        lambda: str(tmp_path / "research"),
    )

    # Imported after the temporary graph paths are configured.
    from CoScientist.web.app import create_app

    app = create_app()
    with TestClient(app) as client:
        global_marker = uuid4().hex
        global_memory = get_knowledge_memory()
        global_memory.ingest(
            Extraction(
                entities=[
                    Entity(
                        key=f"molecule:{global_marker}",
                        type="molecule",
                        name=f"molecule:{global_marker}",
                    ),
                    Entity(
                        key=f"target:{global_marker}",
                        type="target",
                        name=f"target:{global_marker}",
                    ),
                ],
                relations=[
                    Relation(
                        src=f"molecule:{global_marker}",
                        dst=f"target:{global_marker}",
                        type="inhibits",
                    )
                ],
            ),
            source="global-api-test",
            refs={
                "user_id": "producer",
                "session_id": "producer-session",
                "result_id": "result:global-api-test",
            },
        )
        global_response = client.get("/api/knowledge")
        assert global_response.status_code == 200
        assert global_response.json()["scope"] == "global"
        assert global_marker in str(global_response.json())
        assert global_response.json()["storage"]["healthy"] is True
        global_edge = global_response.json()["edges"][0]
        assert global_edge["relation_type"] == "inhibits"
        assert global_edge["provenance"][0]["user_id"] == "producer"

        user = _create_user(client, f"graph-user-{uuid4().hex}")
        first_session = _create_session(client, user["id"], "First")
        second_session = _create_session(client, user["id"], "Second")

        first_graph = get_knowledge_graph(
            user_id=user["id"],
            session_id=first_session["id"],
        )
        second_graph = get_knowledge_graph(
            user_id=user["id"],
            session_id=second_session["id"],
        )
        first_graph.add_node(id="goal:web-first", kind="goal", label="first")
        second_graph.add_node(id="goal:web-second", kind="goal", label="second")

        first_response = client.get(
            f"/api/users/{user['id']}/sessions/{first_session['id']}/graph",
            params={"view": "execution"},
        )
        second_response = client.get(
            f"/api/users/{user['id']}/sessions/{second_session['id']}/graph",
            params={"view": "execution"},
        )
        assert first_response.status_code == 200
        assert second_response.status_code == 200
        first_ids = {node["id"] for node in first_response.json()["nodes"]}
        second_ids = {node["id"] for node in second_response.json()["nodes"]}
        assert "goal:web-first" in first_ids
        assert "goal:web-first" not in second_ids
        assert "goal:web-second" in second_ids
        assert "goal:web-second" not in first_ids

        session_memory_response = client.get(
            f"/api/users/{user['id']}/sessions/{first_session['id']}/graph",
            params={"view": "memory"},
        )
        assert session_memory_response.status_code == 200
        assert session_memory_response.json()["scope"] == "global"
        assert global_marker in str(session_memory_response.json())

        assert client.get("/api/graph").status_code == 400
        compatibility_response = client.get(
            "/api/graph",
            params={
                "user_id": user["id"],
                "session_id": first_session["id"],
                "view": "execution",
            },
        )
        assert compatibility_response.status_code == 200
        assert "goal:web-first" in {
            node["id"] for node in compatibility_response.json()["nodes"]
        }

        other_user = _create_user(client, f"other-user-{uuid4().hex}")
        other_session = _create_session(client, other_user["id"], "Other")
        wrong_owner_response = client.get(
            f"/api/users/{user['id']}/sessions/{other_session['id']}/graph"
        )
        assert wrong_owner_response.status_code == 404


def test_web_graph_delete_wipes_only_the_requested_store(tmp_path, monkeypatch):
    memory_path = tmp_path / "memory" / "knowledge_memory.json"
    research_dir = tmp_path / "research"
    monkeypatch.setenv("GRAPH_SNAPSHOT_DIR", str(tmp_path / "execution"))
    monkeypatch.setenv("KG_MEMORY_PATH", str(memory_path))
    monkeypatch.setattr(research_store, "_default_dir", lambda: str(research_dir))

    from CoScientist.web.app import create_app

    app = create_app()
    with TestClient(app) as client:
        user = _create_user(client, f"delete-user-{uuid4().hex}")
        target = _create_session(client, user["id"], "Target")
        neighbour = _create_session(client, user["id"], "Neighbour")

        target_execution = get_knowledge_graph(
            user_id=user["id"],
            session_id=target["id"],
        )
        neighbour_execution = get_knowledge_graph(
            user_id=user["id"],
            session_id=neighbour["id"],
        )
        target_execution.add_node(id="goal:doomed", kind="goal", label="doomed")
        neighbour_execution.add_node(id="goal:kept", kind="goal", label="kept")

        target_research = research_store.get_research_graph(
            user_id=user["id"],
            session_id=target["id"],
        )
        assert target_research.init_research(
            source="OrchestratorAgent",
            question="Delete this research",
        )["ok"]

        marker = uuid4().hex
        memory = get_knowledge_memory()
        memory.ingest(
            Extraction(
                entities=[
                    Entity(key=f"molecule:{marker}", type="molecule", name=marker),
                    Entity(key=f"target:{marker}", type="target", name=f"t-{marker}"),
                ],
                relations=[
                    Relation(
                        src=f"molecule:{marker}",
                        dst=f"target:{marker}",
                        type="inhibits",
                    )
                ],
            ),
            source="delete-api-test",
            refs={"result_id": f"result:{marker}"},
        )

        execution_delete = client.delete(
            f"/api/users/{user['id']}/sessions/{target['id']}/graph",
            params={"view": "execution"},
        )
        assert execution_delete.status_code == 200
        assert execution_delete.json()["deleted"]["execution"]["cleared"] is True

        # Only the selected session's trace is gone; the roster is re-seeded so
        # the Graph view still renders, and nothing else was touched.
        assert "goal:doomed" not in {
            node["id"] for node in target_execution.full()["nodes"]
        }
        assert "goal:kept" in {
            node["id"] for node in neighbour_execution.full()["nodes"]
        }
        assert target_research.full()["nodes"]
        assert marker in str(get_knowledge_memory().full())

        research_delete = client.delete(
            f"/api/users/{user['id']}/sessions/{target['id']}/graph",
            params={"view": "research"},
        )
        assert research_delete.status_code == 200
        assert target_research.full()["nodes"] == []
        assert research_delete.json()["deleted"]["research"]["archived"]
        assert marker in str(get_knowledge_memory().full())

        memory_delete = client.delete(
            f"/api/users/{user['id']}/sessions/{target['id']}/graph",
            params={"view": "memory"},
        )
        assert memory_delete.status_code == 200
        deleted_memory = memory_delete.json()["deleted"]["memory"]
        assert deleted_memory["scope"] == "global"
        assert deleted_memory["entities"] == 2
        assert deleted_memory["relations"] == 1
        assert deleted_memory["cleared"] is True
        assert Path(deleted_memory["archived"]).is_file()
        assert marker not in str(get_knowledge_memory().full())
        # The wipe is persisted, not just held in the live singleton.
        assert KnowledgeMemory(str(memory_path)).entities == {}

        assert client.delete(
            f"/api/users/{user['id']}/sessions/{target['id']}/graph",
            params={"view": "knowledge"},
        ).status_code == 400

        other_user = _create_user(client, f"other-user-{uuid4().hex}")
        other_session = _create_session(client, other_user["id"], "Other")
        assert client.delete(
            f"/api/users/{user['id']}/sessions/{other_session['id']}/graph"
        ).status_code == 404


def test_web_graph_delete_all_clears_every_store(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_SNAPSHOT_DIR", str(tmp_path / "execution"))
    monkeypatch.setenv(
        "KG_MEMORY_PATH",
        str(tmp_path / "memory" / "knowledge_memory.json"),
    )
    monkeypatch.setattr(
        research_store,
        "_default_dir",
        lambda: str(tmp_path / "research"),
    )

    from CoScientist.web.app import create_app

    app = create_app()
    with TestClient(app) as client:
        user = _create_user(client, f"delete-all-{uuid4().hex}")
        session = _create_session(client, user["id"], "Everything")

        execution = get_knowledge_graph(user_id=user["id"], session_id=session["id"])
        execution.add_node(id="goal:all", kind="goal", label="all")
        research = research_store.get_research_graph(
            user_id=user["id"],
            session_id=session["id"],
        )
        assert research.init_research(
            source="OrchestratorAgent",
            question="Delete everything",
        )["ok"]
        marker = uuid4().hex
        get_knowledge_memory().ingest(
            Extraction(
                entities=[
                    Entity(key=f"molecule:{marker}", type="molecule", name=marker),
                ],
                relations=[],
            ),
            source="delete-all-test",
            refs={"result_id": f"result:{marker}"},
        )

        response = client.delete(
            f"/api/users/{user['id']}/sessions/{session['id']}/graph",
            params={"view": "all"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert set(response.json()["deleted"]) == {
            "execution",
            "research",
            "memory",
        }
        assert "goal:all" not in {node["id"] for node in execution.full()["nodes"]}
        assert research.full()["nodes"] == []
        assert marker not in str(get_knowledge_memory().full())


def test_settings_modal_exposes_a_graph_delete_button():
    from CoScientist.web.app import create_app

    app = create_app()
    with TestClient(app) as client:
        index_html = client.get("/").text

    assert 'id="graph-delete-btn"' in index_html
    assert 'id="graph-delete-target"' in index_html
    assert "async function deleteGraphData()" in index_html
    assert "method: 'DELETE'" in index_html


def test_graph_ui_uses_active_user_and_session_in_url():
    from CoScientist.web.app import create_app

    app = create_app()
    with TestClient(app) as client:
        index_html = client.get("/").text
        graph_html = client.get("/graph").text

    assert 'id="graph-link"' in index_html
    assert (
        "/graph?user_id=${encodeURIComponent(user.id)}"
        "&session_id=${encodeURIComponent(session.id)}"
    ) in index_html
    assert "new URLSearchParams(location.search)" in graph_html
    assert (
        "/api/users/${encodeURIComponent(userId)}"
        "/sessions/${encodeURIComponent(sessionId)}/graph"
    ) in graph_html
    assert 'fetch("/api/graph?view="' not in graph_html
