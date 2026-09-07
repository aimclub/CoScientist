"""Lifecycle coverage for the session-aware execution-graph plugin."""

import asyncio
from types import SimpleNamespace

from google.genai import types

from CoScientist.graph import plugin as plugin_module
from CoScientist.graph.plugin import GraphMemoryPlugin
from CoScientist.graph.semantic import Entity, Extraction, Relation
from CoScientist.graph.session_scope import session_key


class _RecordingGraph:
    def __init__(self):
        self.nodes = {}
        self.edges = []

    def add_node(self, **node):
        self.nodes[node["id"]] = dict(node)

    def add_edge(self, src, dst, type="caused_by"):
        self.edges.append((src, dst, type))

    def set_status(self, node_id, **updates):
        self.nodes[node_id].update(updates)

    def full(self):
        return {
            "nodes": [dict({"id": node_id}, **node) for node_id, node in self.nodes.items()],
            "edges": [
                {"src": src, "dst": dst, "type": edge_type}
                for src, dst, edge_type in self.edges
            ],
        }


def _contexts(*, user_id: str, session_id: str, invocation_id: str):
    state = {}
    session = SimpleNamespace(
        user_id=user_id,
        id=session_id,
        state=state,
    )
    invocation = SimpleNamespace(
        invocation_id=invocation_id,
        session=session,
        agent=SimpleNamespace(name="OrchestratorAgent"),
    )
    tool = SimpleNamespace(
        state=state,
        agent_name="OrchestratorAgent",
        function_call_id="call-1",
        _invocation_context=invocation,
    )
    return invocation, tool


def _final_event(text: str):
    return SimpleNamespace(
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        is_final_response=lambda: True,
    )


def _install_graph_resolver(monkeypatch):
    graphs = {}

    def resolve(context):
        return graphs.setdefault(session_key(context), _RecordingGraph())

    monkeypatch.setattr(plugin_module, "get_knowledge_graph", resolve)
    monkeypatch.setattr(plugin_module, "_agent_names", lambda: set())
    monkeypatch.setenv("KG_SEMANTIC_ENABLED", "0")
    return graphs


def test_run_state_survives_until_after_run_and_builds_one_goal_tree(monkeypatch):
    async def scenario():
        graphs = _install_graph_resolver(monkeypatch)
        plugin = GraphMemoryPlugin()
        invocation, tool_context = _contexts(
            user_id="user-a",
            session_id="session-a",
            invocation_id="inv-a",
        )
        tool = SimpleNamespace(name="search_tool")

        await plugin.on_user_message_callback(
            invocation_context=invocation,
            user_message=types.Content(
                role="user",
                parts=[types.Part(text="Find candidate molecules")],
            ),
        )
        run_key = plugin._run_key(invocation)
        assert run_key in plugin._runs

        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"query": "candidate molecules"},
            tool_context=tool_context,
        )
        await plugin.after_tool_callback(
            tool=tool,
            tool_args={"query": "candidate molecules"},
            tool_context=tool_context,
            result={"status": "success", "items": ["A"]},
        )
        await plugin.on_event_callback(
            invocation_context=invocation,
            event=_final_event("Candidate A is the best match."),
        )

        graph = graphs[("user-a", "session-a")]
        goal_id = "goal:inv-a"
        agent_id = f"{goal_id}::agent:OrchestratorAgent"
        tool_id = f"{goal_id}::tool:call-1"
        result_id = "result:inv-a"

        assert "goal:pending" not in graph.nodes
        assert set(graph.nodes) == {goal_id, agent_id, tool_id, result_id}
        assert graph.nodes[goal_id]["status"] == "success"
        assert graph.nodes[agent_id]["status"] == "success"
        assert graph.nodes[tool_id]["status"] == "success"
        assert (goal_id, agent_id, "caused_by") in graph.edges
        assert (agent_id, tool_id, "caused_by") in graph.edges
        assert (agent_id, result_id, "produced") in graph.edges
        assert run_key in plugin._runs

        await plugin.after_run_callback(invocation_context=invocation)
        assert run_key not in plugin._runs

    asyncio.run(scenario())


def test_parallel_invocations_keep_independent_state_until_each_run_ends(monkeypatch):
    async def scenario():
        graphs = _install_graph_resolver(monkeypatch)
        plugin = GraphMemoryPlugin()
        first_invocation, first_tool_context = _contexts(
            user_id="user-a",
            session_id="session-a",
            invocation_id="inv-a",
        )
        second_invocation, second_tool_context = _contexts(
            user_id="user-b",
            session_id="session-b",
            invocation_id="inv-b",
        )
        tool = SimpleNamespace(name="shared_tool")

        await asyncio.gather(
            plugin.on_user_message_callback(
                invocation_context=first_invocation,
                user_message=types.Content(
                    role="user",
                    parts=[types.Part(text="First research")],
                ),
            ),
            plugin.on_user_message_callback(
                invocation_context=second_invocation,
                user_message=types.Content(
                    role="user",
                    parts=[types.Part(text="Second research")],
                ),
            ),
        )
        await asyncio.gather(
            plugin.before_tool_callback(
                tool=tool,
                tool_args={"run": "first"},
                tool_context=first_tool_context,
            ),
            plugin.before_tool_callback(
                tool=tool,
                tool_args={"run": "second"},
                tool_context=second_tool_context,
            ),
        )

        first_key = plugin._run_key(first_invocation)
        second_key = plugin._run_key(second_invocation)
        assert first_key != second_key
        assert plugin._runs[first_key].goal_id == "goal:inv-a"
        assert plugin._runs[first_key].goal_text == "First research"
        assert plugin._runs[second_key].goal_id == "goal:inv-b"
        assert plugin._runs[second_key].goal_text == "Second research"

        await plugin.on_event_callback(
            invocation_context=first_invocation,
            event=_final_event("First result"),
        )
        await plugin.after_run_callback(invocation_context=first_invocation)
        assert first_key not in plugin._runs
        assert second_key in plugin._runs

        await plugin.on_event_callback(
            invocation_context=second_invocation,
            event=_final_event("Second result"),
        )
        await plugin.after_run_callback(invocation_context=second_invocation)
        assert plugin._runs == {}

        first_nodes = set(graphs[("user-a", "session-a")].nodes)
        second_nodes = set(graphs[("user-b", "session-b")].nodes)
        assert "goal:inv-a" in first_nodes
        assert "result:inv-a" in first_nodes
        assert not any("inv-b" in node_id for node_id in first_nodes)
        assert "goal:inv-b" in second_nodes
        assert "result:inv-b" in second_nodes
        assert not any("inv-a" in node_id for node_id in second_nodes)

    asyncio.run(scenario())


def test_run_without_final_response_is_marked_interrupted(monkeypatch):
    async def scenario():
        graphs = _install_graph_resolver(monkeypatch)
        plugin = GraphMemoryPlugin()
        invocation, tool_context = _contexts(
            user_id="user-stop",
            session_id="session-stop",
            invocation_id="inv-stop",
        )
        await plugin.on_user_message_callback(
            invocation_context=invocation,
            user_message=types.Content(
                role="user",
                parts=[types.Part(text="Long running research")],
            ),
        )
        await plugin.before_tool_callback(
            tool=SimpleNamespace(name="slow_tool"),
            tool_args={},
            tool_context=tool_context,
        )

        await plugin.after_run_callback(invocation_context=invocation)

        graph = graphs[("user-stop", "session-stop")]
        assert graph.nodes["goal:inv-stop"]["status"] == "interrupted"
        assert graph.nodes[
            "goal:inv-stop::agent:OrchestratorAgent"
        ]["status"] == "interrupted"
        assert graph.nodes["goal:inv-stop::tool:call-1"]["status"] == "interrupted"
        assert plugin._runs == {}

    asyncio.run(scenario())


def test_semantic_ingest_records_public_session_and_research_provenance(monkeypatch):
    class RecordingMemory:
        def __init__(self):
            self.ingests = []

        def known_types(self):
            return set(), set()

        def ingest(self, extraction, *, source, refs):
            self.ingests.append((extraction, source, refs))

    async def scenario():
        _install_graph_resolver(monkeypatch)
        monkeypatch.setenv("KG_SEMANTIC_ENABLED", "1")
        memory = RecordingMemory()
        monkeypatch.setattr(
            plugin_module,
            "get_knowledge_memory",
            lambda _context: memory,
        )

        pending = []
        monkeypatch.setattr(plugin_module, "_spawn_background", pending.append)

        from CoScientist.graph import semantic as semantic_module
        from CoScientist.graph.research import store as research_store

        async def fake_extract(_text, *, context, known_types):
            assert context == "Investigate scoped provenance"
            assert known_types == (set(), set())
            return Extraction(
                entities=[
                    Entity(key="molecule:a", type="molecule", name="A"),
                    Entity(key="target:b", type="target", name="B"),
                ],
                relations=[
                    Relation(src="molecule:a", dst="target:b", type="inhibits"),
                ],
            )

        monkeypatch.setattr(semantic_module, "extract", fake_extract)
        monkeypatch.setattr(
            research_store,
            "get_research_graph",
            lambda **_scope: SimpleNamespace(
                full=lambda: {"research_id": "research-42"}
            ),
        )

        plugin = GraphMemoryPlugin()
        invocation, _tool_context = _contexts(
            user_id="user-public",
            session_id="session-public",
            invocation_id="inv-public",
        )
        await plugin.on_user_message_callback(
            invocation_context=invocation,
            user_message=types.Content(
                role="user",
                parts=[types.Part(text="Investigate scoped provenance")],
            ),
        )
        await plugin.on_event_callback(
            invocation_context=invocation,
            event=_final_event("A inhibits B."),
        )
        assert len(pending) == 1
        await pending.pop()

        assert len(memory.ingests) == 1
        _extraction, source, refs = memory.ingests[0]
        assert source == "Investigate scoped provenance"
        assert refs["user_id"] == "user-public"
        assert refs["session_id"] == "session-public"
        assert refs["research_id"] == "research-42"
        assert refs["run"] == "inv-public"
        assert refs["goal_id"] == "goal:inv-public"
        assert refs["result_id"] == "result:inv-public"
        assert refs["agent"] == "OrchestratorAgent"
        assert refs["validation_status"] == "provisional"
        assert isinstance(refs["created_at"], float)

    asyncio.run(scenario())
