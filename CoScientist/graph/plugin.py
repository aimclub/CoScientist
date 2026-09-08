"""ADK plugin that grows the in-process knowledge graph from agent activity.

Attached to the in-process Runner (web / cli) next to the event logger. Unlike
``GraphEmitterPlugin`` (which POSTs to the A2A graph service over HTTP), this
writes straight into the graph resolved for the public user/session scope, so
every in-process agent participating in that session can read it synchronously.

Shape of one query — a tree rooted at the orchestrator, with full agent
hierarchy (delegations AND sequential/parallel children):

    goal (the user query)
      └─ OrchestratorAgent
           ├─ tool_call: retrieve_tools          (a tool the orchestrator ran)
           ├─ agent_call: PlannerAgent           (a delegation)
           │     └─ tool_call: create_plan
           ├─ agent_call: TaskExecutorAgent      (the execution router)
           │     └─ agent_call: ToolPipelineAgent    (a sequential composite)
           │           └─ agent_call: ExperimentAgent  (its child — hierarchy kept)
           │                 └─ tool_call: fedot_tool
           └─ result                             (final answer — out of the orchestrator)

Node labels: tool_call shows the TOOL name, agent_call shows the AGENT name (who
called it is clear from the parent). Best-effort: a graph failure never breaks a
run. Toggle with LOG_AGENT_EVENTS=0 (shared with the event logger).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from google.adk.plugins.base_plugin import BasePlugin

from CoScientist.graph.memory import ROOT_ID, get_knowledge_graph
from CoScientist.graph.memory_store import get_knowledge_memory
from CoScientist.graph.session_scope import SessionKey, session_key
from CoScientist.utils.s3_refs import find_s3_uris

_agent_names_cache: Optional[set] = None
_composite_parents_cache: Optional[dict] = None

# Fire-and-forget background tasks (semantic extraction, etc.). Held at module
# level so they are not garbage-collected mid-flight; never awaited by the run
# loop (full asynchrony), but drained when the Runner closes.
_BG_TASKS: set = set()


def _spawn_background(coro) -> None:
    try:
        task = asyncio.create_task(coro)
        _BG_TASKS.add(task)
        task.add_done_callback(_BG_TASKS.discard)
    except Exception:  # noqa: BLE001 — no running loop / scheduling failure
        pass


def _agent_names() -> set:
    global _agent_names_cache
    if _agent_names_cache is None:
        try:
            from CoScientist.assembly.schema import get_config
            _agent_names_cache = get_config().delegatable_names()
        except Exception:  # noqa: BLE001
            _agent_names_cache = set()
    return _agent_names_cache


def _composite_parents() -> dict:
    """child agent -> parent composite (from sequential/parallel `children`)."""
    global _composite_parents_cache
    if _composite_parents_cache is None:
        m: dict = {}
        try:
            from CoScientist.assembly.schema import get_config
            for name, a in get_config().agents.items():
                for ch in (getattr(a, "children", None) or []):
                    m[ch] = name
        except Exception:  # noqa: BLE001
            pass
        _composite_parents_cache = m
    return _composite_parents_cache


def _enabled() -> bool:
    # The web UI switch wins: with the knowledge graph off nothing is recorded,
    # matching the `graph` reader toolset dropping out of every agent.
    try:
        from CoScientist.config import get_settings
        if not get_settings().web.knowledge_graph_enabled:
            return False
    except Exception:  # noqa: BLE001 — never let config break event recording
        pass
    value = os.getenv("LOG_AGENT_EVENTS") or os.getenv("A2A_LOG_EVENTS") or "1"
    return value not in ("0", "false", "False")


def _short(value: Any, limit: int = 800) -> str:
    """Trim a value for display on a node.

    The limit used to be 300, which cut a tool result before its file
    references. Those references now travel in ``input_files`` and
    ``output_files``, so this string only has to stay readable.

    Keep it short. GraphStore rewrites the whole graph JSON on every node, edge,
    and status change, so each character here is paid a few hundred times per
    run, inside the lock.
    """
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "…"


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    parts = getattr(content, "parts", None) or []
    return "\n".join(p.text for p in parts if getattr(p, "text", None)).strip()


def _is_error(result: Any) -> bool:
    if isinstance(result, dict):
        if result.get("status") in ("error", "failed", "timeout"):
            return True
        if result.get("error"):
            return True
    return False


@dataclass
class _RunState:
    root_agent_name: Optional[str] = None
    goal_id: str = "goal:pending"
    goal_text: str = ""
    agent_node: dict = field(default_factory=dict)
    node_by_fcid: dict = field(default_factory=dict)


class GraphMemoryPlugin(BasePlugin):
    """Record agent activity into the graph selected by the ADK session."""

    def __init__(self, name: str = "graph_memory") -> None:
        super().__init__(name=name)
        self._runs: dict[tuple[SessionKey, str], _RunState] = {}

    @staticmethod
    def _ctx_agent(invocation_context) -> Optional[str]:
        agent = getattr(invocation_context, "agent", None)
        return getattr(agent, "name", None)

    @staticmethod
    def _invocation_id(context) -> str:
        invocation = getattr(context, "_invocation_context", None)
        return str(
            getattr(context, "invocation_id", None)
            or getattr(invocation, "invocation_id", None)
            or "pending"
        )

    def _run_key(self, context) -> tuple[SessionKey, str]:
        return session_key(context), self._invocation_id(context)

    def _state(self, context) -> _RunState:
        return self._runs.setdefault(self._run_key(context), _RunState())

    @staticmethod
    def _root_name(state: _RunState) -> str:
        return state.root_agent_name or "OrchestratorAgent"

    def _agent_node_for(
        self,
        graph,
        state: _RunState,
        agent: str,
        _seen: Optional[set] = None,
    ) -> str:
        """The activity node for an agent, creating the whole ancestor chain.

        The root agent hangs under the goal; a sequential/parallel child hangs
        under its composite parent's node (recursively), so the hierarchy of
        composite agents is preserved even though their children are not invoked
        as AgentTool delegations.
        """
        cached = state.agent_node.get(agent)
        if cached is not None:
            return cached

        if agent == self._root_name(state):
            nid = f"{state.goal_id}::agent:{agent}"
            graph.add_node(
                id=nid, kind="agent_call", label=agent, executor_agent=agent,
                status="running", parent_ids=[state.goal_id], t_start=time.time(),
            )
            graph.add_edge(state.goal_id, nid, type="caused_by")
            state.agent_node[agent] = nid
            return nid

        _seen = _seen or set()
        parent_agent = _composite_parents().get(agent)
        if parent_agent and parent_agent not in _seen:
            _seen.add(parent_agent)
            parent_node = self._agent_node_for(graph, state, parent_agent, _seen)
        else:
            parent_node = self._agent_node_for(
                graph,
                state,
                self._root_name(state),
            )

        nid = f"{state.goal_id}::agent:{agent}"
        graph.add_node(
            id=nid, kind="agent_call", label=agent, executor_agent=agent,
            status="running", parent_ids=[parent_node], t_start=time.time(),
        )
        graph.add_edge(parent_node, nid, type="delegated_to")
        state.agent_node[agent] = nid
        return nid

    async def on_user_message_callback(self, *, invocation_context, user_message) -> Optional[Any]:
        if not _enabled():
            return None
        state = self._state(invocation_context)
        name = self._ctx_agent(invocation_context)
        if state.root_agent_name is None:
            state.root_agent_name = name
        if name != state.root_agent_name:
            return None
        inv = getattr(invocation_context, "invocation_id", "x")
        state.goal_id = f"goal:{inv}"
        state.goal_text = _content_text(user_message)
        state.agent_node = {}
        state.node_by_fcid = {}
        try:
            graph = get_knowledge_graph(invocation_context)
            graph.add_node(
                id=state.goal_id, kind="goal", label=_short(_content_text(user_message), 200),
                status="running", parent_ids=[ROOT_ID], t_start=time.time(),
            )
            graph.add_edge(ROOT_ID, state.goal_id, type="caused_by")
        except Exception:  # noqa: BLE001
            pass
        return None

    async def after_run_callback(self, *, invocation_context) -> None:
        """Finalize an interrupted tree and release transient bookkeeping.

        Tool and event callbacks run after ``on_user_message_callback`` and
        still need the goal id, root agent, and function-call mapping created
        there.  ADK invokes this hook after the run finishes, including runs
        that do not produce a normal final response, so it is the appropriate
        lifecycle boundary for cleanup.
        """
        state = self._runs.pop(self._run_key(invocation_context), None)
        if state is None:
            return
        try:
            graph = get_knowledge_graph(invocation_context)
            nodes = {node["id"]: node for node in graph.full().get("nodes", [])}
            goal = nodes.get(state.goal_id, {})
            if goal.get("status") != "running":
                return
            now = time.time()
            active_ids = {
                state.goal_id,
                *state.agent_node.values(),
                *state.node_by_fcid.values(),
            }
            for node_id in active_ids:
                if nodes.get(node_id, {}).get("status") == "running":
                    graph.set_status(
                        node_id,
                        status="interrupted",
                        output="Run ended before a final response.",
                        t_end=now,
                    )
        except Exception:  # noqa: BLE001 - cleanup must never mask run errors
            pass

    async def close(self) -> None:
        """Drain best-effort semantic extraction before Runner shutdown."""
        self._runs.clear()
        pending = [task for task in list(_BG_TASKS) if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> Optional[dict]:
        if not _enabled():
            return None
        try:
            graph = get_knowledge_graph(tool_context)
            state = self._state(tool_context)
            agent = (
                getattr(tool_context, "agent_name", None)
                or self._root_name(state)
            )
            parent = self._agent_node_for(graph, state, agent)
            fcid = getattr(tool_context, "function_call_id", None) or f"{tool.name}:{time.time()}"
            if tool.name in _agent_names():
                # Delegation: the called agent's activity node hangs under the
                # caller. Keep the request (the prompt the agent was called with)
                # as the node input so it shows on click.
                nid = f"{state.goal_id}::agent:{tool.name}"
                graph.add_node(
                    id=nid, kind="agent_call", label=tool.name, executor_agent=tool.name,
                    status="running", parent_ids=[parent], input=_short(tool_args, 1000),
                    t_start=time.time(),
                )
                graph.add_edge(parent, nid, type="delegated_to")
                state.agent_node[tool.name] = nid
            else:
                nid = f"{state.goal_id}::tool:{fcid}"
                graph.add_node(
                    id=nid, kind="tool_call", label=tool.name, executor_agent=agent,
                    status="running", parent_ids=[parent], input=_short(tool_args),
                    input_files=find_s3_uris(tool_args), t_start=time.time(),
                )
                graph.add_edge(parent, nid, type="caused_by")
            state.node_by_fcid[fcid] = nid
        except Exception:  # noqa: BLE001
            pass
        return None

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> Optional[dict]:
        if not _enabled():
            return None
        try:
            graph = get_knowledge_graph(tool_context)
            state = self._state(tool_context)
            nid = state.node_by_fcid.get(
                getattr(tool_context, "function_call_id", None)
            )
            if nid:
                graph.set_status(
                    nid, status="failed" if _is_error(result) else "success",
                    output=_short(result, 1500),
                    output_files=find_s3_uris(result),
                    t_end=time.time(),
                )
        except Exception:  # noqa: BLE001
            pass
        return None

    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error) -> Optional[dict]:
        if not _enabled():
            return None
        try:
            graph = get_knowledge_graph(tool_context)
            state = self._state(tool_context)
            nid = state.node_by_fcid.get(
                getattr(tool_context, "function_call_id", None)
            )
            if nid:
                graph.set_status(
                    nid, status="failed", output=_short(str(error), 300), t_end=time.time(),
                )
        except Exception:  # noqa: BLE001
            pass
        return None

    async def on_event_callback(self, *, invocation_context, event) -> Optional[Any]:
        if not _enabled():
            return None
        state = self._state(invocation_context)
        if self._ctx_agent(invocation_context) != state.root_agent_name:
            return None
        if not (getattr(event, "is_final_response", None) and event.is_final_response()):
            return None
        text = _content_text(getattr(event, "content", None))
        if not text:
            return None
        try:
            graph = get_knowledge_graph(invocation_context)
            parent = self._agent_node_for(
                graph,
                state,
                self._root_name(state),
            )
            rid = f"result:{getattr(invocation_context, 'invocation_id', 'x')}"
            graph.add_node(
                id=rid, kind="result", label=_short(text, 200),
                executor_agent=self._root_name(state), status="success",
                parent_ids=[parent], output=_short(text, 600),
                t_start=time.time(), t_end=time.time(),
            )
            graph.add_edge(parent, rid, type="produced")
            graph.set_status(parent, status="success", t_end=time.time())
            graph.set_status(state.goal_id, status="success", t_end=time.time())
        except Exception:  # noqa: BLE001
            pass

        # Semantic layer (Option B): extract domain entities/relations from the
        # answer and accumulate them in global cross-run knowledge memory. It is
        # enabled by default (KG_SEMANTIC_ENABLED=0 disables it); never fatal.
        # FULLY ASYNC: the extraction LLM call is fired as a background task and
        # NOT awaited here, so the run loop is never blocked waiting on it (on the
        # web's persistent loop it lands moments after the answer). Mirrors the
        # fire-and-forget pattern in graph/research/validator.py.
        try:
            from CoScientist.graph.semantic import semantic_enabled
            if semantic_enabled():
                inv = getattr(invocation_context, "invocation_id", "x")
                user_id, session_id = session_key(invocation_context)
                memory = get_knowledge_memory(invocation_context)
                refs = {
                    "run": inv,
                    "goal_id": state.goal_id,
                    "result_id": f"result:{inv}",
                    "user_id": user_id,
                    "session_id": session_id,
                    "agent": self._root_name(state),
                    "created_at": time.time(),
                    # Extraction is immediately reusable, but it is not the
                    # same thing as a validated Research Context Graph claim.
                    "validation_status": "provisional",
                }
                try:
                    from CoScientist.graph.research.store import get_research_graph
                    research_id = get_research_graph(
                        user_id=user_id,
                        session_id=session_id,
                    ).full().get("research_id")
                    if research_id and research_id != "research":
                        refs["research_id"] = research_id
                except Exception:  # noqa: BLE001 - provenance is best-effort
                    pass
                _spawn_background(
                    self._extract_semantic(
                        text,
                        state.goal_text,
                        memory,
                        refs,
                    )
                )
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _extract_semantic(
        self,
        text: str,
        goal_text: str,
        memory,
        refs: dict[str, Any],
    ) -> None:
        """Background: extract domain entities/relations from the final answer and
        accumulate them in the cross-run memory. Best-effort, never awaited by the
        run loop."""
        try:
            from CoScientist.graph.semantic import extract
            extraction = await extract(
                text,
                context=goal_text,
                known_types=memory.known_types(),
            )
            memory.ingest(
                extraction, source=_short(goal_text, 120),
                refs=refs,
            )
        except Exception:  # noqa: BLE001
            pass
