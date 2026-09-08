"""Graph scope survives ADK AgentTool child sessions.

AgentTool executes a delegated agent in a short-lived child session.  ADK
copies the parent state into that session, so graph resolution must use the
scope pinned in state instead of the child's generated ``session.id``.
"""

from types import SimpleNamespace
from uuid import uuid4

from CoScientist.graph.memory import get_knowledge_graph
from CoScientist.graph.memory_store import get_knowledge_memory
from CoScientist.graph.research import store as research_store
from CoScientist.graph.session_scope import session_key


def _context(*, state: dict, user_id: str, session_id: str):
    session = SimpleNamespace(
        id=session_id,
        user_id=user_id,
        state=state,
    )
    return SimpleNamespace(
        state=state,
        session=session,
        _invocation_context=SimpleNamespace(session=session),
    )


def test_parent_scope_is_pinned_and_wins_over_agenttool_child_session_id():
    token = uuid4().hex
    user_id = f"user-{token}"
    parent_session_id = f"parent-{token}"
    parent_state = {}
    parent = _context(
        state=parent_state,
        user_id=user_id,
        session_id=parent_session_id,
    )

    assert session_key(parent) == (user_id, parent_session_id)
    assert parent_state, "the first parent resolution must pin its graph scope"

    child = _context(
        state=dict(parent_state),
        user_id=user_id,
        session_id=f"agent-tool-child-{uuid4().hex}",
    )

    assert session_key(child) == (user_id, parent_session_id)


def test_agenttool_child_resolves_parent_graphs_and_global_memory(
    tmp_path,
    monkeypatch,
):
    token = uuid4().hex
    user_id = f"user-{token}"
    parent_session_id = f"parent-{token}"
    parent_state = {}
    parent = _context(
        state=parent_state,
        user_id=user_id,
        session_id=parent_session_id,
    )

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

    parent_execution = get_knowledge_graph(parent)
    parent_research = research_store.get_research_graph(parent)
    parent_memory = get_knowledge_memory(parent)

    child = _context(
        state=dict(parent_state),
        user_id=user_id,
        session_id=f"agent-tool-child-{uuid4().hex}",
    )

    assert get_knowledge_graph(child) is parent_execution
    assert research_store.get_research_graph(child) is parent_research
    assert get_knowledge_memory(child) is parent_memory

    other_parent = _context(
        state={},
        user_id=user_id,
        session_id=f"other-parent-{token}",
    )

    assert get_knowledge_graph(other_parent) is not parent_execution
    assert research_store.get_research_graph(other_parent) is not parent_research
    assert get_knowledge_memory(other_parent) is parent_memory

    other_user = _context(
        state={},
        user_id=f"other-user-{token}",
        session_id=f"other-user-session-{token}",
    )
    assert get_knowledge_memory(other_user) is parent_memory
