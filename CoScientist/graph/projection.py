"""Rule-based projections of the graph into agent context (Fact 2).

Deliberately rule-based (no LLM) so the same graph always yields the same
context — reproducibility is an evaluation metric. See docs/execution_graph.md.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_MAX_ITEMS = 12
_LABEL = 200


def _short(s: Optional[str], n: int = _LABEL) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + "…"


def _node_line(n: dict) -> str:
    who = n.get("executor_agent") or n.get("kind", "?")
    label = _short(n.get("label"))
    out = n.get("output")
    tail = f" → {_short(out, 160)}" if out else ""
    return f"- [{who}] {label}{tail}"


def orchestrator_summary(full: dict) -> str:
    """Planning view: what already succeeded vs failed/rejected, so the
    orchestrator builds on the former and does NOT repeat the latter."""
    nodes = full.get("nodes", [])
    # Only delegations/decisions matter for planning — skip low-level tool calls.
    plany = [n for n in nodes if n.get("kind") in ("agent_call", "decision", "goal")]
    completed = [n for n in plany if n.get("status") == "success"]
    failed = [
        n for n in plany
        if n.get("status") == "failed" or (n.get("verdict") in ("reject", "wrong"))
    ]
    running = [n for n in plany if n.get("status") == "running"]

    if not (completed or failed or running):
        return ""

    blocks: List[str] = [
        "EXECUTION GRAPH — what has already happened in THIS run. Build on "
        "completed steps; do NOT repeat failed/rejected ones."
    ]
    if completed:
        blocks.append("Completed:\n" + "\n".join(_node_line(n) for n in completed[-_MAX_ITEMS:]))
    if failed:
        blocks.append(
            "Failed / rejected (do not retry as-is):\n"
            + "\n".join(_node_line(n) for n in failed[-_MAX_ITEMS:])
        )
    if running:
        blocks.append("In progress:\n" + "\n".join(_node_line(n) for n in running[-_MAX_ITEMS:]))
    return "\n\n".join(blocks)


# Toolset bindings that decide which path an agent is on. Derived from the
# config rather than hardcoded agent names, so renaming or reshaping the agent
# tree cannot silently break the signal.
_MCP_TOOLSETS = frozenset({"dynamic_tools"})
_CODER_TOOLSETS = frozenset({"coder", "sandbox"})


def _agents_bound_to(toolsets: frozenset) -> set:
    from CoScientist.assembly.schema import get_config

    return {
        name
        for name, agent in get_config().agents.items()
        if toolsets & set(agent.tools or ())
    }


def tool_vs_coder(
    full: dict,
    *,
    mcp_agents: Optional[set] = None,
    coder_agents: Optional[set] = None,
) -> dict:
    """Was the work done by a tool from the catalogue, or written from scratch?

    The system is meant to look for an existing tool first and only fall back to
    writing code. Whether that actually happened is not otherwise recorded
    anywhere, so a catalogue that has quietly stopped being used looks exactly
    like one that is working.

    Read off the execution graph the plugin already emits. The two sides are not
    symmetric, deliberately: for the tool path only a ``tool_call`` counts,
    because delegating to the executor proves nothing — the catalogue lookup may
    have come up empty. For the coder, the delegation itself is the evidence
    that code was written.

    Returns ``{"path", "mcp_tool_calls", "coder_calls"}``, where ``path`` is
    ``"mcp" | "coder" | "mixed" | "none"``. Works on any run's ``full()`` dict,
    including a re-loaded snapshot. The agent sets can be passed in for callers
    that project a graph produced by a different configuration.

    .. note::

       Checked against the 29 recorded runs under ``graph_runs/sessions``: 25
       came out ``coder``, 2 ``mcp``, 2 ``none``. No run mixed the two, and no
       run reached the catalogue by way of a built tool, which is the signal
       this is here to expose.
    """
    mcp_agents = _agents_bound_to(_MCP_TOOLSETS) if mcp_agents is None else mcp_agents
    coder_agents = (
        _agents_bound_to(_CODER_TOOLSETS) if coder_agents is None else coder_agents
    )

    mcp_tool_calls: List[str] = []
    coder_calls: List[str] = []
    for n in full.get("nodes", []):
        kind, who = n.get("kind"), n.get("executor_agent")
        if kind == "tool_call" and who in mcp_agents:
            mcp_tool_calls.append(n.get("label") or "")
        elif kind in ("agent_call", "tool_call") and who in coder_agents:
            coder_calls.append(n.get("label") or "")

    if mcp_tool_calls and coder_calls:
        path = "mixed"
    elif mcp_tool_calls:
        path = "mcp"
    elif coder_calls:
        path = "coder"
    else:
        path = "none"
    return {
        "path": path,
        "mcp_tool_calls": mcp_tool_calls,
        "coder_calls": coder_calls,
    }


def _index(full: dict) -> Dict[str, dict]:
    return {n["id"]: n for n in full.get("nodes", []) if "id" in n}


def local_view(full: dict, node_id: str) -> str:
    """Sub-agent view: the ancestral path (why this step exists) plus validated
    findings in scope. Pushed into the delegation envelope."""
    idx = _index(full)
    if node_id not in idx:
        return ""
    # walk parents up to the root
    chain: List[dict] = []
    seen = set()
    cur: Optional[dict] = idx.get(node_id)
    while cur is not None and cur["id"] not in seen:
        seen.add(cur["id"])
        chain.append(cur)
        parents = cur.get("parent_ids") or []
        cur = idx.get(parents[0]) if parents else None
    chain.reverse()
    if len(chain) <= 1:
        return ""
    path = "\n".join(f"{'  ' * i}↳ {_node_line(n)}" for i, n in enumerate(chain))
    return "REASONING PATH that led to this task (top → here):\n" + path


def _turn_resolver(nodes: List[Dict[str, Any]]):
    """Answer "which request does this node belong to" for a whole graph.

    Shared by the trace list and the per-request graph so the two can never
    disagree about where a call belongs. `turn_id` is authoritative; snapshots
    written before it existed carry the request in the old namespaced id
    ``goal:{inv}::tool:{call}``; anything still unmarked belongs to the last
    request that started before it, because a request is a stretch of time.
    """
    def tagged(node: Dict[str, Any]) -> Optional[str]:
        if node.get("turn_id"):
            return node["turn_id"]
        nid = str(node.get("id", ""))
        for prefix in ("goal:", "result:"):
            if nid.startswith(prefix):
                return nid[len(prefix):].split("::", 1)[0]
        return None

    goals = sorted(((n.get("t_start") or 0.0, tagged(n) or n["id"])
                    for n in nodes if n.get("kind") == "goal"),
                   key=lambda pair: pair[0])

    known = {turn for _, turn in goals}

    def resolve(node: Dict[str, Any]) -> str:
        marked = tagged(node)
        # A mark naming no request is worse than no mark: a delegated agent used
        # to run under its own invocation id, and trusting it split one prompt
        # into several, one of them promptless. Fall through to the clock.
        if marked and marked in known:
            return marked
        started = node.get("t_start") or 0.0
        current = None
        for goal_start, goal_turn in goals:
            if goal_start <= started:
                current = goal_turn
            else:
                break
        return current or "untagged"

    return resolve


def turns(full: Dict[str, Any]) -> Dict[str, Any]:
    """The session's execution graph as a chronological list of turns.

    The call graph answers "what is connected to what". It cannot answer "what
    happened, in what order", because agent nodes are one per agent for the
    whole session, so every turn's calls hang off the same few nodes and the
    layout is force-directed with no time axis at all.

    This regroups the same records by the prompt that caused them and sorts each
    group by start time, which is the shape a trace viewer needs: one entry per
    user request, and under it every call with its agent, its arguments, its
    result and its duration.

    Turn membership comes from ``turn_id``. Snapshots recorded before that field
    existed are reconstructed two ways: ids of the old namespaced form
    ``goal:{inv}::tool:{call}`` carry the turn in their prefix, and anything left
    is assigned to the last request that started before it. Chronology is what a
    turn is, so recovering it from time is exact wherever the ids are silent.
    """
    nodes = {n["id"]: n for n in full.get("nodes", [])}
    order = {"goal": 0, "tool_call": 1, "result": 2}

    members = [n for n in nodes.values() if n.get("kind") in order]
    members.sort(key=lambda n: (n.get("t_start") or 0.0, order[n["kind"]]))
    turn_of = _turn_resolver(list(nodes.values()))

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for node in members:
        grouped.setdefault(turn_of(node), []).append(node)

    out = []
    for turn_id, members in grouped.items():
        members.sort(key=lambda n: (n.get("t_start") or 0.0, order[n["kind"]]))
        goal = next((m for m in members if m["kind"] == "goal"), None)
        result = next((m for m in members if m["kind"] == "result"), None)
        calls = [m for m in members if m["kind"] == "tool_call"]
        started = min((m.get("t_start") or 0.0) for m in members)
        ended = max((m.get("t_end") or m.get("t_start") or 0.0) for m in members)
        out.append({
            "turn_id": turn_id,
            "prompt": (goal or {}).get("label", ""),
            "answer": (result or {}).get("output", ""),
            "status": (goal or {}).get("status", ""),
            "t_start": started,
            "t_end": ended,
            "duration": round(ended - started, 3) if ended and started else None,
            "calls": [{
                "id": c["id"],
                "agent": c.get("executor_agent"),
                "tool": c.get("label"),
                "status": c.get("status"),
                "input": c.get("input"),
                "output": c.get("output"),
                "t_start": c.get("t_start"),
                "t_end": c.get("t_end"),
                "duration": (round(c["t_end"] - c["t_start"], 3)
                             if c.get("t_end") and c.get("t_start") else None),
            } for c in calls],
        })
    out.sort(key=lambda t: t["t_start"])
    return {"turns": out, "count": len(out)}


def execution_tree(full: Dict[str, Any],
                   turn: Optional[str] = None) -> Dict[str, Any]:
    """The call graph of ONE user request, ready to draw left to right.

    A session's worth of requests on one canvas was the wrong unit: lanes
    collided across requests, the canvas ran to thousands of pixels, and the
    thing a reader actually wants to follow — what this prompt caused — was
    buried. One request is drawn at a time; ``turn`` picks it, and the newest
    is used when nothing is asked for. Every request in the graph is listed
    back under ``turns`` so a caller can offer the choice.

    The stored graph is not shaped for reading. Older snapshots still carry the
    seeded roster — every configured agent wired to a hub by ``has_member``,
    whether or not it was ever called — and the hub itself adds a level above
    the request that carries no information. What a reader wants is the shape
    the run actually had:

        request -> agent -> its calls -> nested agent -> its calls -> answer

    So the roster and the hub are dropped, an agent survives only if something
    invoked it, and each node is given the depth it sits at in its own request.
    Depth is measured here rather than inferred by the viewer, because an agent
    node can be shared by several requests and inference would pin it to
    whichever one reached it first.
    """
    every = full.get("nodes", [])
    resolve = _turn_resolver(every)

    catalogue, seen = [], set()
    for node in sorted((n for n in every if n.get("kind") == "goal"),
                       key=lambda n: n.get("t_start") or 0.0):
        key = resolve(node)
        if key in seen:
            continue
        seen.add(key)
        catalogue.append({"turn_id": key, "prompt": node.get("label") or "",
                          "t_start": node.get("t_start")})

    chosen = turn or (catalogue[-1]["turn_id"] if catalogue else None)
    if chosen is not None:
        every = _scope_to_turn(every, full.get("edges", []), resolve, chosen)

    nodes = {n["id"]: dict(n) for n in every}
    edges = [e for e in full.get("edges", [])
             if e.get("type") != "has_member"
             and e.get("src") in nodes and e.get("dst") in nodes]

    roots = [n for n in nodes.values() if n.get("kind") == "system"]
    for root in roots:                       # the hub is a fixture, not an event
        nodes.pop(root["id"], None)
    edges = [e for e in edges
             if e.get("src") in nodes and e.get("dst") in nodes]

    # An agent that nothing called is roster, not history.
    called = {e["dst"] for e in edges}
    for node_id, node in list(nodes.items()):
        if node.get("kind") in ("agent", "agent_call") and node_id not in called:
            nodes.pop(node_id)
    edges = [e for e in edges if e["src"] in nodes and e["dst"] in nodes]

    children: Dict[str, List[str]] = {}
    for edge in edges:
        children.setdefault(edge["src"], []).append(edge["dst"])

    # Breadth-first from each request; a node keeps the shallowest depth found.
    level: Dict[str, int] = {}
    goals = sorted((n for n in nodes.values() if n.get("kind") == "goal"),
                   key=lambda n: n.get("t_start") or 0.0)
    frontier = [(g["id"], 0) for g in goals]
    while frontier:
        node_id, depth = frontier.pop(0)
        if node_id in level and level[node_id] <= depth:
            continue
        level[node_id] = depth
        for child in children.get(node_id, []):
            frontier.append((child, depth + 1))

    # Anything unreachable from a request still has to be placed somewhere.
    for node_id, node in nodes.items():
        level.setdefault(node_id, 0 if node.get("kind") == "goal" else 1)

    # The answer ends its request, so it belongs to the right of everything the
    # request did rather than beside the calls that produced it.
    deepest = max(level.values(), default=0)
    for node_id, node in nodes.items():
        if node.get("kind") == "result":
            level[node_id] = deepest + 1

    for node_id, node in nodes.items():
        node["level"] = level[node_id]

    ordered = sorted(nodes.values(),
                     key=lambda n: (n.get("t_start") or 0.0, n["level"]))
    _place_in_time(ordered, edges)
    return {"run_id": full.get("run_id"), "nodes": ordered, "edges": edges,
            "turns": catalogue, "turn_id": chosen}


_AGENTS = ("agent", "agent_call")


def _scope_to_turn(every, all_edges, resolve, chosen):
    """The nodes belonging to one request, agents included.

    A goal, a tool call and an answer each happen once, so they belong to the
    request that produced them. An agent node does not: it is written once and
    reused by every request it serves. Scoping it the same way hands it to one
    request and strands the rest — their calls keep the edges that named an
    agent no longer there, the edges are dropped as dangling, and the request
    is drawn as a row of cards joined by nothing.

    So an agent joins a request when it acted in it — when an edge ties it to
    that request's own goal, call or answer — and the agents above it in the
    delegation chain come with it, since a sub-agent drawn without its caller
    hangs off the picture unreached.
    """
    by_id = {n["id"]: n for n in every}
    scoped = [n for n in every
              if n.get("kind") == "system" or resolve(n) == chosen]
    inside = {n["id"] for n in scoped}
    # Only the request's own one-off nodes may vouch for an agent; letting one
    # shared agent vouch for another would pull in the whole roster.
    anchors = {n["id"] for n in scoped if n.get("kind") not in _AGENTS}

    edges = [e for e in all_edges if e.get("type") != "has_member"]
    extra = set()
    for edge in edges:
        for near, far in ((edge.get("src"), edge.get("dst")),
                          (edge.get("dst"), edge.get("src"))):
            if near in anchors and far not in inside:
                node = by_id.get(far)
                if node is not None and node.get("kind") in _AGENTS:
                    extra.add(far)

    # Walk up the delegation chain so a nested agent keeps its caller.
    delegations = [(e["src"], e["dst"]) for e in edges
                   if e.get("type") == "delegated_to"
                   and e.get("src") in by_id and e.get("dst") in by_id]
    growing = True
    while growing:
        growing = False
        for parent, child in delegations:
            if child in extra and parent not in extra and parent not in inside:
                extra.add(parent)
                growing = True

    return scoped + [by_id[node_id] for node_id in extra]


#: A card is this wide on screen, and two of them in one lane need this much
#: clear space between their left edges or they overlap. Getting this wrong is
#: what made consecutive calls sit on top of each other: time alone decided x,
#: and a busy second put several 190-pixel cards inside forty pixels.
_CARD_WIDTH, _CARD_GAP = 190, 26
_LANE_PITCH = _CARD_WIDTH + _CARD_GAP

#: How far the clock moves a node, and the most a single idle stretch may
#: occupy. A run waits forty minutes for a sandbox; drawn to scale that gap is
#: the whole picture and the calls either side of it are a smudge, so long
#: waits compress and the order is what survives.
_MAX_STEP, _PIXELS_PER_SECOND = 420, 8.0
_ROW_HEIGHT = 210
#: Distance between two sub-rows inside one agent's band.
_SUB_ROW_HEIGHT = 68


def _place_in_time(ordered: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    """Give every node an x from when it ran and a y from who ran it.

    Depth answers "what followed from what", which is why it stays on the node,
    but it is the wrong horizontal axis: laying calls out by depth puts thirty
    of them in one column and says nothing about the order they happened in.
    Here x advances with the clock, so the picture stretches as the run goes on
    and reading left to right is reading forward in time.

    Rows keep it legible. The request and its answer bookend row zero; every
    agent gets a row of its own in the order it first appears, and a call sits
    in the row of the agent that made it.
    """
    if not ordered:
        return

    owner = {e["dst"]: e["src"] for e in edges}

    def name_of(node: Dict[str, Any]) -> str:
        return str(node.get("executor_agent") or node.get("label")
                   or node["id"].split("::")[-1])

    def agent_of(node: Dict[str, Any]) -> Optional[str]:
        """The agent whose row this node belongs in, by walking up its callers.

        Keyed by name, not by node: the same agent called in three requests is
        three nodes, and giving each its own row would spread one participant
        across the page instead of showing it as one lane of activity.
        """
        if node.get("kind") in ("agent", "agent_call"):
            return name_of(node)
        seen, current = set(), owner.get(node["id"])
        while current and current not in seen:
            seen.add(current)
            parent = by_id.get(current)
            if parent is None:
                return None
            if parent.get("kind") in ("agent", "agent_call"):
                return name_of(parent)
            current = owner.get(current)
        return None

    by_id = {n["id"]: n for n in ordered}
    rows: Dict[str, int] = {}
    for node in ordered:                      # first appearance decides the row
        if node.get("kind") in ("goal", "result"):
            continue
        agent = agent_of(node)
        if agent is not None and agent not in rows:
            rows[agent] = len(rows) + 1

    # One pass, in time order. Each node starts at least a card's width to the
    # right of the one before it, and further when the clock says so. The floor
    # is global rather than per lane: packing lanes separately let a busy lane
    # push its cards past a quiet one, so x stopped agreeing with time. With the
    # floor applied to every step, reading left to right is reading forward in
    # time everywhere, and no two cards can overlap in any lane.
    # An agent with many calls gets a band of sub-rows rather than one long
    # line: twenty calls in a single row is a strip the reader has to scroll
    # sideways forever, and it wastes the vertical space beside it. Cards in
    # different sub-rows may sit closer horizontally, since only cards sharing
    # a sub-row can collide, so stacking also shortens the picture.
    per_agent: Dict[str, int] = {}
    for node in ordered:
        if node.get("kind") in ("goal", "result"):
            continue
        agent = agent_of(node) or ""
        per_agent[agent] = per_agent.get(agent, 0) + 1
    bands = {agent: (3 if count > 12 else 2 if count > 5 else 1)
             for agent, count in per_agent.items()}

    seen_in_lane: Dict[str, int] = {}
    previous_start, x = None, 0.0
    for node in ordered:
        started = node.get("t_start")
        is_bookend = node.get("kind") in ("goal", "result")
        agent = "" if is_bookend else (agent_of(node) or "")
        band = 1 if is_bookend else bands.get(agent, 1)

        if previous_start is not None:
            gap = (max(0.0, started - previous_start) * _PIXELS_PER_SECOND
                   if started is not None else 0.0)
            x += max(_LANE_PITCH / band, min(_MAX_STEP, gap))
        if started is not None:
            previous_start = started

        index = seen_in_lane.get(agent, 0)
        seen_in_lane[agent] = index + 1
        lane = 0 if is_bookend else rows.get(agent, 1)
        sub = 0 if is_bookend else index % band

        node["row"] = lane
        node["sub_row"] = sub
        node["x"] = round(x)
        node["y"] = round(lane * _ROW_HEIGHT + sub * _SUB_ROW_HEIGHT)
        node["card_width"] = _CARD_WIDTH

    # The answer closes the request, so it sits past everything the request did.
    # Its own timestamp cannot be trusted for this: older snapshots recorded it
    # without one, which left it drawn in the middle of the work it summarises.
    answers = [n for n in ordered if n.get("kind") == "result"]
    if answers:
        rightmost = max(n["x"] for n in ordered if n.get("kind") != "result")
        for offset, answer in enumerate(answers):
            answer["x"] = round(rightmost + _LANE_PITCH * (offset + 1))
