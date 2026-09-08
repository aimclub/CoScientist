"""Knowledge graph (interpretable): Question → Facts → their Sources.

Reads as "here are the facts this session established and, for each, the data source
(a tool/agent call, with its input and output) it came from" — NOT the mechanical
execution call-tree. Structural nodes (orchestrator/planner/agent nesting) are
intentionally dropped.

    Question
      ├─ Fact: "acetaldehyde is hepatotoxic"  ──from_source──▶ [tavily_extract] (in/out)
      ├─ Fact: "CYP2E1 → oxidative stress"     ──from_source──▶ [ResearchAgent] (in/out)
      └─ Fact: "fibrosis precedes cirrhosis"   ──from_source──▶ [tavily_search] (in/out)

Facts are claims extracted into global memory (relations between domain
entities) whose exact provenance points to THIS user/session/goal. Each fact is
attributed to the session data source whose output best matches it (content
overlap), so you can click the source to audit its exact input/output.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List


def _tokens(text: str) -> set:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return {
        word.strip("_")
        for word in re.findall(r"\w+", normalized, flags=re.UNICODE)
        if len(word.strip("_")) > 2
    }


def _norm(s: str) -> str:
    return (s or "").rstrip(" …")[:80]


def _from_run(
    relation: Dict[str, Any],
    gnorm: str,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    goal_id: str | None = None,
) -> bool:
    """Select facts produced by this execution scope.

    Global semantic memory may contain identical question text from different
    users. Web projections therefore use exact provenance rather than matching
    only the human-readable source string. The source fallback is retained for
    legacy/CLI snapshots where no explicit scope was supplied.
    """
    if user_id is not None or session_id is not None:
        return _matching_provenance(
            relation,
            user_id=user_id,
            session_id=session_id,
            goal_id=goal_id,
        ) is not None
    sources = relation.get("sources", [])
    return bool(gnorm) and any(
        gnorm.startswith(_norm(s)) or _norm(s).startswith(gnorm)
        for s in sources
    )


def _matching_provenance(
    relation: Dict[str, Any],
    *,
    user_id: str | None,
    session_id: str | None,
    goal_id: str | None,
) -> Dict[str, Any] | None:
    return next(
        (
            p
            for p in relation.get("provenance", [])
            if (user_id is None or str(p.get("user_id")) == str(user_id))
            and (session_id is None or str(p.get("session_id")) == str(session_id))
            and (goal_id is None or str(p.get("goal_id")) == str(goal_id))
        ),
        None,
    )


def to_knowledge_graph(
    full: Dict[str, Any],
    memory=None,
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    by_id = {n["id"]: n for n in full.get("nodes", [])}

    # Data sources = tool/agent calls that actually produced output (with I/O).
    sources = [n for n in full.get("nodes", [])
               if n.get("kind") in ("tool_call", "agent_call") and n.get("output")]
    src_tokens = {s["id"]: _tokens(f"{s.get('label', '')} {s.get('output', '')}") for s in sources}

    try:
        if memory is None:
            from CoScientist.graph.memory_store import get_global_knowledge_memory
            km = get_global_knowledge_memory()
        else:
            km = memory
        if hasattr(km, "snapshot"):
            ents, rels = km.snapshot()
        else:  # compatibility with lightweight test/custom memory objects
            ents, rels = km.entities, list(km.relations.values())
    except Exception:  # noqa: BLE001
        ents, rels = {}, []

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen: set = set()

    def node(nid: str, kind: str, label: str, **extra: Any) -> None:
        if nid in seen:
            return
        seen.add(nid)
        nodes.append({"id": nid, "kind": kind, "label": label or "", "status": "success", **extra})

    def edge(src: str, dst: str, etype: str) -> None:
        edges.append({"src": src, "dst": dst, "type": etype})

    for g in [n for n in full.get("nodes", []) if n.get("kind") == "goal"]:
        qid = "q:" + g["id"]
        query = g.get("label", "")
        node(qid, "question", "Q: " + query[:60], output=query)
        gnorm = _norm(query)

        # This run's facts = memory relations (claims) established for this query.
        for r in [
            r for r in rels
            if _from_run(
                r,
                gnorm,
                user_id=user_id,
                session_id=session_id,
                goal_id=g.get("id"),
            )
        ]:
            provenance = _matching_provenance(
                r,
                user_id=user_id,
                session_id=session_id,
                goal_id=g.get("id"),
            )
            assertion = (provenance or {}).get("claim") or {}
            sn = assertion.get("src_name") or ents.get(
                r["src"], {}
            ).get("name", r["src"])
            dn = assertion.get("dst_name") or ents.get(
                r["dst"], {}
            ).get("name", r["dst"])
            relation_type = assertion.get("type") or r.get("type", "")
            if "attrs" in assertion:
                relation_attrs = assertion.get("attrs") or {}
            else:
                relation_attrs = r.get("attrs") or {}
            val = relation_attrs.get("value")
            claim = f"{sn} {relation_type} {dn}" + (
                f" = {val}" if val is not None else ""
            )
            fid = f"fact:{r['src']}|{r.get('type', '')}|{r['dst']}"
            node(fid, "fact", claim, output=claim)
            edge(qid, fid, "has_finding")

            # Attribute the fact to the source whose output best matches it.
            ftok = _tokens(claim)
            best, best_score = None, 0
            for s in sources:
                score = len(ftok & src_tokens[s["id"]])
                if score > best_score:
                    best, best_score = s, score
            if best is not None and best_score >= 1:
                b = by_id[best["id"]]
                node(best["id"], b["kind"], b.get("label") or best["id"],
                     executor_agent=b.get("executor_agent"), input=b.get("input"),
                     output=b.get("output"), status=b.get("status", "success"))
                edge(fid, best["id"], "from_source")

    return {"run_id": full.get("run_id"), "view": "knowledge", "nodes": nodes, "edges": edges}
