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

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from google.adk.plugins.base_plugin import BasePlugin

from CoScientist.graph.memory import ROOT_ID, get_knowledge_graph
from CoScientist.graph.session_scope import SessionKey, session_key
from CoScientist.utils.s3_refs import find_s3_uris

_agent_names_cache: Optional[set] = None
_composite_parents_cache: Optional[dict] = None

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


_system_root_cache: Optional[str] = None


def _system_root() -> str:
    """The system's true root agent (root: true in system.yaml). Only its
    top-level invocation opens a goal — sub-agents run in their own ADK
    invocations and must NOT each spawn a goal."""
    global _system_root_cache
    if _system_root_cache is None:
        try:
            from CoScientist.assembly.schema import get_config
            cfg = get_config()
            _system_root_cache = next(
                (n for n, a in cfg.agents.items() if getattr(a, "root", False)),
                "OrchestratorAgent",
            )
        except Exception:  # noqa: BLE001
            _system_root_cache = "OrchestratorAgent"
    return _system_root_cache


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


#: Room for an input and for an output on a node. Generous rather than
#: unbounded: the whole graph is rewritten to disk on every single write, so a
#: half-megabyte sandbox log on one node is paid for again on every node that
#: follows it. What is cut says so, and says how much was cut.
_INPUT_LIMIT, _OUTPUT_LIMIT = 4000, 20000


def _readable(value: Any) -> str:
    """A tool's arguments or result as prose, not as a JSON dump.

    The panel used to show `{"query": "aspirin mechanism", "max_results": 5}`,
    which is the wire format and not something anyone wants to read. A mapping
    becomes one `key: value` line each, a list becomes one item per line, and a
    string is already what it should be. Nested structures fall back to JSON,
    indented, because inventing prose for them would hide their shape.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list, tuple)):
                rendered = json.dumps(item, ensure_ascii=False, indent=2,
                                      default=str)
                lines.append(f"{key}:\n" + "\n".join(
                    "  " + line for line in rendered.splitlines()))
            else:
                lines.append(f"{key}: {item}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple)):
        return "\n".join(_readable(item) for item in value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _short(value: Any, limit: int = _INPUT_LIMIT) -> str:
    text = _readable(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [{len(text) - limit} more characters]"


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
        #: The request each session is currently serving. A delegated agent runs
        #: under its own ADK invocation id, so stamping nodes with the id of the
        #: invocation that made the call split one user request into several —
        #: the sub-agent's calls formed a request of their own, with no prompt.
        #: What a node belongs to is the prompt that is open, so that is kept
        #: per session and set when the user speaks.
        self._turn_of_session: dict[SessionKey, str] = {}

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

    def _turn(self, context) -> str:
        """The request being served, not the invocation that happens to be running."""
        return self._turn_of_session.get(session_key(context)) \
            or self._invocation_id(context)

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
        # ONE stable node per agent — its roster node `agent:{name}`. An agent is
        # never duplicated no matter how many times, or from how many ADK
        # invocations, it is called; its tool calls and delegations all attach to
        # this single node. add_node MERGES onto the seeded roster node (keeping
        # its system:root membership) and just marks it running.
        nid = f"agent:{agent}"
        if agent in state.agent_node:
            return nid
        _seen = _seen or set()
        _seen.add(agent)
        try:
            graph.add_node(
                id=nid, kind="agent", label=agent, executor_agent=agent,
                status="running", t_start=time.time(),
            )
            # preserve sequential/parallel hierarchy (child under its composite)
            parent_agent = _composite_parents().get(agent)
            if parent_agent and parent_agent not in _seen:
                parent_node = self._agent_node_for(graph, state, parent_agent, _seen)
                graph.add_edge(parent_node, nid, type="delegated_to")
        except Exception:  # noqa: BLE001
            pass
        state.agent_node[agent] = nid
        return nid

    async def on_user_message_callback(self, *, invocation_context, user_message) -> Optional[Any]:
        if not _enabled():
            return None
        # Only the TRUE system root opens a goal. Sub-agents run in their own ADK
        # invocations and would otherwise each spawn a separate goal + a floating
        # duplicate of themselves.
        name = self._ctx_agent(invocation_context)
        if name != _system_root():
            return None
        state = self._state(invocation_context)
        state.root_agent_name = name
        inv = getattr(invocation_context, "invocation_id", "x")
        state.goal_id = f"goal:{inv}"
        state.goal_text = _content_text(user_message)
        # Everything recorded until the next prompt belongs to this one.
        self._turn_of_session[session_key(invocation_context)] = inv
        state.agent_node = {}
        state.node_by_fcid = {}
        try:
            graph = get_knowledge_graph(invocation_context)
            graph.add_node(
                id=state.goal_id, kind="goal", turn_id=inv, label=_short(_content_text(user_message), 200),
                status="running", parent_ids=[ROOT_ID], t_start=time.time(),
            )
            graph.add_edge(ROOT_ID, state.goal_id, type="caused_by")
            # the goal flows into the orchestrator; the whole run tree hangs off it
            orch = self._agent_node_for(graph, state, name)
            graph.add_edge(state.goal_id, orch, type="caused_by")
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
            # A sub-agent invocation never ran on_user_message_callback, so its
            # goal_id is still the sentinel and no goal node exists. Returning on
            # that basis left every delegated agent and its tools at "running"
            # for good; only a goal that exists and is already closed means there
            # is nothing left to finalise.
            goal = nodes.get(state.goal_id)
            if goal is not None and goal.get("status") != "running":
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
        """Release per-run bookkeeping before Runner shutdown."""
        self._runs.clear()

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
                # Delegation: connect the caller to the called agent's ONE stable
                # node (agent:{name}); its own tool calls attach there too.
                nid = self._agent_node_for(graph, state, tool.name)
                # The arguments of the delegation ARE this node's input. They
                # used to be withheld because the node also carried the agent's
                # capability card from the seeded roster and writing over it
                # broke get_agents_info. The roster is no longer seeded into the
                # graph, so there is nothing left to protect and withholding
                # them only left every agent in the trace with a blank input.
                graph.add_node(
                    id=nid, kind="agent", label=tool.name, executor_agent=tool.name,
                    status="running", input=_short(tool_args, 1000),
                    t_start=time.time(),
                )
                graph.add_edge(parent, nid, type="delegated_to")
            else:
                nid = f"tool:{fcid}"
                graph.add_node(
                    id=nid, kind="tool_call", turn_id=self._turn(tool_context),
                    label=tool.name, executor_agent=agent, status="running",
                    parent_ids=[parent], input=_short(tool_args),
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
            fcid = getattr(tool_context, "function_call_id", None)
            nid = state.node_by_fcid.get(fcid)
            if nid is None and tool.name in _agent_names():
                # A delegation whose call id ADK did not supply: the node is the
                # callee's stable one, so it closes without the map.
                nid = f"agent:{tool.name}"
            if nid:
                graph.set_status(
                    nid, status="failed" if _is_error(result) else "success",
                    output=_short(result, _OUTPUT_LIMIT),
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
                    nid, status="failed", output=_short(str(error), _OUTPUT_LIMIT), t_end=time.time(),
                )
        except Exception:  # noqa: BLE001
            pass
        return None

    async def on_event_callback(self, *, invocation_context, event) -> Optional[Any]:
        if not _enabled():
            return None
        state = self._state(invocation_context)
        if not (getattr(event, "is_final_response", None) and event.is_final_response()):
            return None
        text = _content_text(getattr(event, "content", None))
        if not text:
            return None

        speaker = self._ctx_agent(invocation_context)
        if speaker != state.root_agent_name:
            # A delegated agent answering. Its node is created when it first
            # acts, which records nothing about the work, so without this every
            # agent in the trace showed a blank output and the panel had only a
            # status to offer. Agents reached by transfer rather than as a tool
            # are the ones this covers; a tool-style delegation is already
            # closed out by after_tool_callback.
            try:
                graph = get_knowledge_graph(invocation_context)
                graph.set_status(
                    self._agent_node_for(graph, state, speaker),
                    status="success", output=_short(text, _OUTPUT_LIMIT),
                    t_end=time.time(),
                )
            except Exception:  # noqa: BLE001
                pass
            return None
        try:
            graph = get_knowledge_graph(invocation_context)
            parent = self._agent_node_for(
                graph,
                state,
                self._root_name(state),
            )
            inv = getattr(invocation_context, "invocation_id", "x")
            rid = f"result:{inv}"
            graph.add_node(
                id=rid, kind="result", turn_id=inv, label=_short(text, 200),
                executor_agent=self._root_name(state), status="success",
                parent_ids=[parent], output=_short(text, 600),
                t_start=time.time(), t_end=time.time(),
            )
            graph.add_edge(parent, rid, type="produced")
            graph.set_status(parent, status="success", t_end=time.time())
            graph.set_status(state.goal_id, status="success", t_end=time.time())
        except Exception:  # noqa: BLE001
            pass

        return None
