"""Named trigger queries over the Research Context Graph (spec §3).

The orchestrator's decision logic works on statuses and edges, not on node
content — these functions are those decisions as code: pure, rule-based (no
LLM), each returning {"items": [...], "rendered": "..."} so the result can be
consumed programmatically or dropped into a prompt. ``trigger_report`` bundles
all of them into the digest the orchestrator sees before every turn.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from CoScientist.graph.research.store import (
    ResearchGraphStore,
    priority_rank,
    research_graph,
)

_EVIDENCE_EDGES = ("supports", "refutes", "refines")


def _graph(store: Optional[ResearchGraphStore]):
    return (store or research_graph)


def _nodes_of(g, node_type: str) -> List[str]:
    return [n for n, d in g.nodes(data=True) if d.get("type") == node_type]


def _out(g, node_id: str, edge_type: str) -> List[str]:
    """Targets of node's outgoing edges of the given type."""
    return [v for _, v, k in g.out_edges(node_id, keys=True) if k == edge_type]


def _in(g, node_id: str, edge_type: str) -> List[str]:
    """Sources of node's incoming edges of the given type."""
    return [u for u, _, k in g.in_edges(node_id, keys=True) if k == edge_type]


def _label(g, node_id: str, n: int = 80) -> str:
    attrs = g.nodes[node_id].get("attrs") or {}
    for key in ("formulation", "content", "synthesis", "name", "title", "description"):
        if attrs.get(key):
            value = str(attrs[key])
            value = " ".join(value.split())
            return value if len(value) <= n else value[:n] + "…"
    return ""


def _status(g, node_id: str) -> str:
    return g.nodes[node_id].get("status", "")


def _hypothesis_tools(g, hyp_id: str) -> List[str]:
    """All Tools a hypothesis depends on: requires(H→T) plus uses(VM→T) of the
    VerificationMethods the hypothesis is tested_by."""
    tools = set(_out(g, hyp_id, "requires"))
    for vm in _out(g, hyp_id, "tested_by"):
        tools.update(_out(g, vm, "uses"))
    return sorted(tools)


# ── individual triggers ──────────────────────────────────────────────────────

def _id_order(node_id: str) -> tuple:
    """H2 before H10 (numeric suffix), unknown shapes fall back to the string."""
    digits = "".join(c for c in str(node_id) if c.isdigit())
    return (int(digits) if digits else 0, str(node_id))


def ready_hypotheses(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """The ONE hypothesis to verify next.

    Every `formulated` hypothesis whose referenced Tools are available (vacuously
    ready when it references none) is a candidate, but only the most relevant one
    — the agent's pick (`attrs.selected`) / highest `attrs.priority`, ties broken
    by id order — is offered as actionable in `items`. The rest are reported as
    `queued` so the orchestrator sees the backlog without starting it: one branch
    at a time, otherwise a batch of hypotheses gets verified in parallel and the
    evidence of one contaminates the verdict of another.
    """
    g = _graph(store).full_graph()
    candidates = []
    for h in _nodes_of(g, "Hypothesis"):
        if _status(g, h) != "formulated":
            continue
        tools = _hypothesis_tools(g, h)
        if all(_status(g, t) == "available" for t in tools):
            candidates.append({"hypothesis": h, "label": _label(g, h),
                               "methods": _out(g, h, "tested_by"), "tools": tools})
    candidates.sort(key=lambda i: (priority_rank(g.nodes[i["hypothesis"]].get("attrs")),
                                   _id_order(i["hypothesis"])))
    items, queued = candidates[:1], candidates[1:]
    active = [h for h in _nodes_of(g, "Hypothesis")
              if _status(g, h) == "under_verification"]

    lines = [f"IN VERIFICATION: {h} \"{_label(g, h)}\" — this branch is active; "
             f"finish it (gather evidence → verdict) before starting another"
             for h in sorted(active, key=_id_order)]
    lines += [f"READY (verify this ONE next): {i['hypothesis']} \"{i['label']}\" — "
              f"{'tools available' if i['tools'] else 'no tools needed'} "
              f"→ research_set_focus({i['hypothesis']}) then delegate evidence "
              f"gathering for it" for i in items]
    if queued:
        lines.append(
            "QUEUED (do NOT verify in parallel): "
            + ", ".join(f"{i['hypothesis']} \"{i['label']}\"" for i in queued)
            + " → take the next one only after the active branch has a verdict")
    return {"items": items, "queued": queued, "in_verification": active,
            "rendered": "\n".join(lines)}


def postponed_hypotheses(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """The backlog: alternatives set aside while one hypothesis is verified.

    Rendered only when nothing is ready or under verification — i.e. exactly when
    reviving one (postponed→formulated) is the sensible next move; otherwise the
    backlog is noise the orchestrator must not act on."""
    g = _graph(store).full_graph()
    items = [{"hypothesis": h, "label": _label(g, h)}
             for h in sorted(_nodes_of(g, "Hypothesis"), key=_id_order)
             if _status(g, h) == "postponed"]
    idle = not ready_hypotheses(store)["items"] and not any(
        _status(g, h) == "under_verification" for h in _nodes_of(g, "Hypothesis"))
    rendered = ""
    if items and idle:
        rendered = ("BACKLOG: " + ", ".join(f"{i['hypothesis']} \"{i['label']}\""
                                            for i in items)
                    + " → no hypothesis is active; revive the most relevant one "
                      "(postponed→formulated) and verify it next")
    return {"items": items, "rendered": rendered}


def blocked_hypotheses(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """Formulated hypotheses blocked by a Tool that is not available."""
    g = _graph(store).full_graph()
    items = []
    for h in _nodes_of(g, "Hypothesis"):
        if _status(g, h) != "formulated":
            continue
        blocking = [{"id": t, "status": _status(g, t)}
                    for t in _hypothesis_tools(g, h)
                    if _status(g, t) != "available"]
        if blocking:
            items.append({"hypothesis": h, "label": _label(g, h),
                          "blocking_tools": blocking})
    lines = [f"BLOCKED: {i['hypothesis']} \"{i['label']}\" — waiting on "
             + ", ".join(f"{b['id']}({b['status']})" for b in i["blocking_tools"])
             for i in items]
    return {"items": items, "rendered": "\n".join(lines)}


def refuting_evidence(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """Evidence with a `refutes` edge to a hypothesis that has not been
    refuted/postponed yet → the branch needs review."""
    g = _graph(store).full_graph()
    items = []
    for h in _nodes_of(g, "Hypothesis"):
        if _status(g, h) in ("refuted", "postponed"):
            continue
        for e in _in(g, h, "refutes"):
            items.append({"evidence": e, "hypothesis": h,
                          "hypothesis_status": _status(g, h),
                          "label": _label(g, h)})
    lines = [f"REFUTE SIGNAL: {i['evidence']} refutes {i['hypothesis']} "
             f"({i['hypothesis_status']}) → review the branch" for i in items]
    return {"items": items, "rendered": "\n".join(lines)}


def closable_hypotheses(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """The spec's "path Hypothesis → Evidence → ConfirmationCriteria is closed"
    trigger: an under_verification hypothesis with evidence attached whose
    criteria (formulated_for) are all met → the validator can write a
    Conclusion. Sub-buckets: criteria exist but unmet (awaiting_criteria) and
    no criteria defined at all (missing_criteria)."""
    g = _graph(store).full_graph()
    closable, awaiting, missing = [], [], []
    for h in _nodes_of(g, "Hypothesis"):
        if _status(g, h) != "under_verification":
            continue
        evidence = sorted({e for et in _EVIDENCE_EDGES for e in _in(g, h, et)})
        if not evidence:
            continue
        criteria = _in(g, h, "formulated_for")
        entry = {"hypothesis": h, "label": _label(g, h), "evidence": evidence,
                 "criteria": sorted(criteria)}
        if not criteria:
            missing.append(entry)
        elif all(_status(g, c) == "met" for c in criteria):
            closable.append(entry)
        else:
            entry["unmet"] = [c for c in criteria if _status(g, c) != "met"]
            awaiting.append(entry)
    lines = [f"CLOSABLE: {i['hypothesis']} — evidence {','.join(i['evidence'])}; "
             f"{','.join(i['criteria'])} met → write a Conclusion (draft) with "
             f"based_on edges" for i in closable]
    lines += [f"AWAITING CRITERIA: {i['hypothesis']} — evidence collected but "
              f"{','.join(i['unmet'])} not met" for i in awaiting]
    lines += [f"MISSING CRITERIA: {i['hypothesis']} has evidence "
              f"{','.join(i['evidence'])} but no ConfirmationCriteria — define "
              f"them (HypothesesAgent) or judge sufficiency" for i in missing]
    return {"items": closable, "awaiting_criteria": awaiting,
            "missing_criteria": missing, "rendered": "\n".join(lines)}


def pending_conclusions(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    g = _graph(store).full_graph()
    items = [{"conclusion": c, "label": _label(g, c)}
             for c in _nodes_of(g, "Conclusion") if _status(g, c) == "draft"]
    lines = [f"PENDING CONCLUSION: {i['conclusion']} \"{i['label']}\" — "
             f"draft awaiting approval" for i in items]
    return {"items": items, "rendered": "\n".join(lines)}


def missing_tools(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """Tools that are not available, with who needs them."""
    g = _graph(store).full_graph()
    items = []
    for t in _nodes_of(g, "Tool"):
        status = _status(g, t)
        if status == "available":
            continue
        items.append({"tool": t, "label": _label(g, t), "status": status,
                      "required_by": _in(g, t, "requires"),
                      "used_by": _in(g, t, "uses")})
    lines = [f"TOOL NOT READY: {i['tool']} \"{i['label']}\" ({i['status']})"
             + (f" — required by {','.join(i['required_by'])}" if i["required_by"] else "")
             for i in items]
    return {"items": items, "rendered": "\n".join(lines)}


def resources_low(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """Exhausted resources, or numeric remainder below 10% of the limit —
    the spec's signal to wrap up / escalate."""
    g = _graph(store).full_graph()
    items = []
    for r in _nodes_of(g, "Resource"):
        attrs = g.nodes[r].get("attrs") or {}
        status = _status(g, r)
        remaining = _num(attrs.get("remaining", attrs.get("остаток")))
        limit = _num(attrs.get("limit", attrs.get("лимит")))
        low = status == "exhausted" or (remaining is not None and remaining <= 0) \
            or (remaining is not None and limit and remaining / limit < 0.1)
        if low:
            items.append({"resource": r, "label": _label(g, r), "status": status,
                          "remaining": remaining, "limit": limit})
    lines = [f"RESOURCES LOW: {i['resource']} \"{i['label']}\" "
             f"(remaining={i['remaining']}, limit={i['limit']}, "
             f"status={i['status']}) → consider wrapping up" for i in items]
    return {"items": items, "rendered": "\n".join(lines)}


def open_questions(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """Open/decomposed questions, annotated with how developed each branch is
    (no hypotheses yet → needs branching; no evidence yet → needs exploration)."""
    g = _graph(store).full_graph()
    items = []
    for q in _nodes_of(g, "ResearchQuestion"):
        status = _status(g, q)
        if status == "closed":
            continue
        hyps = _out(g, q, "motivates")
        evidence = _in(g, q, "relates_to")
        items.append({"question": q, "label": _label(g, q), "status": status,
                      "hypotheses": len(hyps), "evidence": len(evidence)})
    lines = []
    for i in items:
        need = []
        if i["evidence"] == 0:
            need.append("no evidence yet (explore literature)")
        if i["hypotheses"] == 0:
            need.append("no hypotheses yet (branch)")
        tail = " — " + "; ".join(need) if need else ""
        lines.append(f"QUESTION: {i['question']} \"{i['label']}\" "
                     f"[{i['status']}, {i['hypotheses']} hypotheses, "
                     f"{i['evidence']} evidence]{tail}")
    return {"items": items, "rendered": "\n".join(lines)}


def unresolved_hypotheses(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    """Hypotheses that already have evidence attached but still carry NO verdict
    (status not confirmed/refuted/postponed). This is the #1 reason a finished
    graph looks 'all formulated'. The orchestrator does NOT judge these itself —
    it delegates each to the ValidatorAgent, which weighs the evidence against the
    criteria and writes the verdict + Conclusion."""
    g = _graph(store).full_graph()
    items = []
    for h in _nodes_of(g, "Hypothesis"):
        st = _status(g, h)
        if st in ("confirmed", "refuted", "postponed"):
            continue
        supporting = _in(g, h, "supports")
        refuting = _in(g, h, "refutes")
        related = _in(g, h, "relates_to")   # polarity not yet assigned
        if not (supporting or refuting or related):
            continue
        items.append({"hypothesis": h, "label": _label(g, h), "status": st,
                      "supporting": sorted(supporting), "refuting": sorted(refuting),
                      "related": sorted(related)})
    lines = [f"NEEDS VERDICT: {i['hypothesis']} (still {i['status']}) has evidence "
             f"[support: {','.join(i['supporting']) or '—'} | refute: "
             f"{','.join(i['refuting']) or '—'} | unclassified: "
             f"{','.join(i['related']) or '—'}] → the background validator will "
             f"assign polarity and a verdict" for i in items]
    return {"items": items, "rendered": "\n".join(lines)}


def progress(store: Optional[ResearchGraphStore] = None) -> Dict[str, Any]:
    g = _graph(store).full_graph()
    counts: Dict[str, Dict[str, int]] = {}
    for _, d in g.nodes(data=True):
        t, s = d.get("type", "?"), d.get("status", "?")
        counts.setdefault(t, {}).setdefault(s, 0)
        counts[t][s] += 1
    parts = []
    for t in sorted(counts):
        inner = ", ".join(f"{s}:{n}" for s, n in sorted(counts[t].items()))
        parts.append(f"{t}({inner})")
    return {"items": counts, "rendered": "PROGRESS: " + "; ".join(parts) if parts else ""}


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── the digest the orchestrator consumes ─────────────────────────────────────

TRIGGERS = {
    "ready_hypotheses": ready_hypotheses,
    "blocked_hypotheses": blocked_hypotheses,
    "postponed_hypotheses": postponed_hypotheses,
    "refuting_evidence": refuting_evidence,
    "unresolved_hypotheses": unresolved_hypotheses,
    "closable_hypotheses": closable_hypotheses,
    "pending_conclusions": pending_conclusions,
    "missing_tools": missing_tools,
    "resources_low": resources_low,
    "open_questions": open_questions,
    "progress": progress,
}


def trigger_report(store: Optional[ResearchGraphStore] = None,
                   char_budget: int = 4000) -> Dict[str, Any]:
    """Run every named trigger and produce the compact digest injected into the
    orchestrator's prompt (and returned by the research_triggers tool)."""
    g = _graph(store)
    if g.is_empty():
        return {"triggers": {}, "rendered": "Research graph is EMPTY."}
    report: Dict[str, Any] = {}
    rendered_parts: List[str] = []
    for name, fn in TRIGGERS.items():
        result = fn(store)
        report[name] = result
        if result.get("rendered"):
            rendered_parts.append(result["rendered"])
    text = "\n".join(rendered_parts) or "No active triggers."
    if len(text) > char_budget:
        text = text[:char_budget] + "\n…[trigger digest truncated]"
    return {"triggers": report, "rendered": text}
