"""Rule-based projections of the graph into agent context (Fact 2).

Deliberately rule-based (no LLM) so the same graph always yields the same
context — reproducibility is an evaluation metric. See docs/execution_graph.md.
"""
from __future__ import annotations

from typing import Dict, List, Optional

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
