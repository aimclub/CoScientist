"""Persistent, schema-validated store for the Research Context Graph.

One active research per user/session scope (one graph = one root question), held
in a NetworkX MultiDiGraph (parallel typed edges like E1-supports→H1 plus
E1-relates_to→H1 must coexist) and snapshotted atomically to JSON after every
write — the blackboard survives restarts, browser refresh and Web Stop. An
explicit reset or re-initialization archives the previous active graph first;
refuted branches remain available as negative results in that archive.

Writes go through ``commit`` — the transactional API from spec §5.3: ALL nodes,
edges and status changes of one agent step are validated together against the
schema (types, per-agent permissions, status transitions, edge endpoint pairs)
and either applied atomically or rejected with instructive per-item errors.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import networkx as nx

from CoScientist.graph.research import schema
from CoScientist.graph.research.models import CommitResult, ResearchEdge, ResearchNode
from CoScientist.graph.session_scope import (
    DEFAULT_SESSION_KEY,
    SessionKey,
    session_key,
    storage_dir,
)

logger = logging.getLogger(__name__)

_REF_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_ATTR_CHAR_CAP = 2000
_COMMIT_HINT = ("Fix the listed items and call research_commit again. "
                "NOTHING from this call was saved.")

# Attrs consulted (in order) when a short human-readable label is needed.
_LABEL_ATTRS = ("formulation", "content", "synthesis", "name", "title",
                "description", "rule", "threshold", "path")

# Priority words accepted in attrs.priority, most important first.
_PRIORITY_WORDS = {"critical": 0, "highest": 0, "high": 1, "primary": 0,
                   "medium": 2, "normal": 2, "moderate": 2, "low": 3, "lowest": 4}


def _is_truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "да", "selected",
                                         "primary")
    return bool(value)


def priority_rank(attrs: Dict[str, Any]) -> Tuple[float, float]:
    """Sort key for hypothesis selection: lower = more important.

    An explicit ``attrs.selected`` (the agent's own pick) always wins; otherwise
    ``attrs.priority`` is read both as a word (high/medium/low) and as a number
    (1 = most important, the spec's 1..5 scale). Unspecified sorts last but keeps
    the commit order among equals.
    """
    attrs = attrs or {}
    selected = 0 if _is_truthy(attrs.get("selected") or attrs.get("primary")) else 1
    raw = str(attrs.get("priority", "")).strip().lower()
    if raw in _PRIORITY_WORDS:
        return (selected, float(_PRIORITY_WORDS[raw]))
    try:
        return (selected, float(raw))
    except ValueError:
        return (selected, 99.0)


def _default_dir() -> str:
    """Snapshot directory from settings, tolerating a missing settings group
    (the store must stay importable/usable standalone, e.g. in unit tests)."""
    try:
        from CoScientist.config import get_settings
        return get_settings().research_graph.dir
    except Exception:  # noqa: BLE001
        return os.getenv("RESEARCH_GRAPH_DIR", "./graph_runs")


def _default_file() -> str:
    try:
        from CoScientist.config import get_settings
        return get_settings().research_graph.active_file
    except Exception:  # noqa: BLE001
        return "research_active.json"


def _short(value: Any, n: int = 200) -> str:
    if value is None:
        return ""
    s = value if isinstance(value, str) else str(value)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n] + "…"


class ResearchGraphStore:
    def __init__(self, directory: Optional[str] = None,
                 active_file: Optional[str] = None) -> None:
        self._dir = Path(directory or _default_dir())
        self._path = self._dir / (active_file or _default_file())
        self._lock = threading.RLock()
        self._g = nx.MultiDiGraph()
        self._research_id = "research"
        self._created_at: float = time.time()
        self._root_id: Optional[str] = None
        self._load()

    # ── public API ────────────────────────────────────────────────────────────

    def is_empty(self) -> bool:
        with self._lock:
            return self._g.number_of_nodes() == 0

    def root_id(self) -> Optional[str]:
        with self._lock:
            if self._root_id and self._g.has_node(self._root_id):
                return self._root_id
            # fallback: earliest ResearchQuestion
            questions = [(d.get("created_at", 0), n) for n, d in self._g.nodes(data=True)
                         if d.get("type") == "ResearchQuestion"]
            return min(questions)[1] if questions else None

    def init_research(self, source: str, question: str,
                      attrs: Optional[Dict[str, Any]] = None,
                      constraints: Optional[List[Dict[str, Any]]] = None,
                      tools: Optional[List[Dict[str, Any]]] = None,
                      resources: Optional[List[Dict[str, Any]]] = None,
                      empirical_bases: Optional[List[Dict[str, Any]]] = None,
                      confirmation_criteria: Optional[List[Dict[str, Any]]] = None,
                      cost_models: Optional[List[Dict[str, Any]]] = None,
                      question_source: Optional[str] = None) -> Dict[str, Any]:
        """Start a NEW research: root ResearchQuestion + the context star
        (Constraints —contextualizes→ Q, Q —defines_scope→ EmpiricalBases,
        CostModels —applies_to→ Q, standalone Tool/Resource/ConfirmationCriteria
        nodes). The previous graph, if any, is archived to a timestamped file —
        only after the new one validates.

        Each seed item may carry its own ``source`` (e.g. "human" for a field the
        operator set, "ContextInitAgent" for one the agent drafted) so the graph
        records the automation-vs-human split; items without it fall back to the
        top-level ``source``. ``question_source`` sets the root question's source.
        """
        if not (question or "").strip():
            return CommitResult(ok=False, errors=["question must be a non-empty string"],
                                hint=_COMMIT_HINT).model_dump()

        root: Dict[str, Any] = {
            "type": "ResearchQuestion", "ref": "q",
            "attrs": {"formulation": question.strip(), **(attrs or {})},
        }
        if question_source:
            root["source"] = question_source
        nodes: List[Dict[str, Any]] = [root]
        edges: List[Dict[str, Any]] = []

        def _star(items, node_type, ref_prefix):
            for i, item in enumerate(dict(it) for it in (items or []) if isinstance(it, dict)):
                status = item.pop("status", None)
                node_source = item.pop("source", None)
                a = item.pop("attrs", None) or item  # accept flat or {"attrs": …}
                draft = {"type": node_type, "ref": f"{ref_prefix}{i}", "attrs": a}
                if status:
                    draft["status"] = status
                if node_source:
                    draft["source"] = node_source
                nodes.append(draft)

        _star(constraints, "Constraint", "c")
        _star(tools, "Tool", "t")
        _star(resources, "Resource", "r")
        _star(empirical_bases, "EmpiricalBase", "eb")
        _star(confirmation_criteria, "ConfirmationCriteria", "cc")
        _star(cost_models, "CostModel", "cm")
        for draft in nodes:
            ref = draft["ref"]
            if draft["type"] == "Constraint":
                edges.append({"type": "contextualizes", "from": f"#{ref}", "to": "#q"})
            elif draft["type"] == "EmpiricalBase":
                edges.append({"type": "defines_scope", "from": "#q", "to": f"#{ref}"})
            elif draft["type"] == "CostModel":
                edges.append({"type": "applies_to", "from": f"#{ref}", "to": "#q"})

        with self._lock:
            old_graph, old_meta = self._g, (self._research_id, self._created_at, self._root_id)
            old_data = self._serialize() if old_graph.number_of_nodes() else None
            self._g = nx.MultiDiGraph()
            self._research_id = (
                "research-"
                + datetime.now().strftime("%Y%m%d-%H%M%S")
                + "-"
                + uuid4().hex[:8]
            )
            self._created_at = time.time()
            self._root_id = None
            # Privileged seeding: the context star (Question/Tool/Resource/
            # EmpiricalBase/Constraint) is created here regardless of the caller's
            # general create-set (schema.INIT_SEED_TYPES) — structural validation
            # still applies, only the per-agent ACL is skipped.
            result = self._commit_locked(source, nodes, edges, [],
                                         enforce_permissions=False)
            if not result.ok:
                # restore the previous research untouched
                self._g = old_graph
                self._research_id, self._created_at, self._root_id = old_meta
                return result.model_dump()
            self._root_id = next(n["id"] for n in result.committed["nodes"] if n.get("ref") == "q")
            archived = self._archive_data(old_data) if old_data else None
            self._save()
        out = result.model_dump()
        out["root_id"] = self._root_id
        if archived:
            out["archived"] = archived
            out["message"] += f" (previous research archived to {archived})"
        return out

    def commit(self, source: str,
               nodes: Optional[List[Dict[str, Any]]] = None,
               edges: Optional[List[Dict[str, Any]]] = None,
               status_updates: Optional[List[Dict[str, Any]]] = None,
               autolink_focus: Optional[str] = None,
               enforce_permissions: bool = True) -> CommitResult:
        """Transactional write: validate EVERYTHING, then apply all-or-nothing.

        `autolink_focus` (a Hypothesis id): any Evidence created in this commit
        that isn't already linked to a hypothesis is auto-linked to it with a
        `relates_to` edge — so evidence a worker records while focused on a
        hypothesis is never orphaned, and the background validator can pick it up
        and decide its polarity.

        `enforce_permissions=False` is the privileged code-path (same contract as
        ``init_research``): structural validation stays, only the per-agent ACL
        is skipped. Reserved for deterministic module hooks — never LLM tools."""
        with self._lock:
            result = self._commit_locked(source, list(nodes or []),
                                         list(edges or []), list(status_updates or []),
                                         enforce_permissions=enforce_permissions,
                                         autolink_focus=autolink_focus)
            if result.ok:
                self._save()
            return result

    # ── reads ─────────────────────────────────────────────────────────────────

    def get_context_slice(self, node_id: str, depth: int = 1,
                          char_budget: Optional[int] = None) -> Dict[str, Any]:
        """The subgraph a worker agent gets instead of the whole graph:
        the focus node + everything within `depth` edges (either direction)."""
        depth = max(1, min(int(depth or 1), self._max_depth()))
        with self._lock:
            if not self._g.has_node(node_id):
                return {"error": f"no node '{node_id}'. {self._ids_hint()}"}
            keep = {node_id}
            frontier = {node_id}
            for _ in range(depth):
                nxt = set()
                for n in frontier:
                    nxt.update(self._g.successors(n))
                    nxt.update(self._g.predecessors(n))
                frontier = nxt - keep
                keep |= nxt
            nodes = [self._node_public(n) for n in keep]
            edges = [{"type": k, "from": u, "to": v, **({"attrs": d["attrs"]} if d.get("attrs") else {})}
                     for u, v, k, d in self._g.edges(keys=True, data=True)
                     if u in keep and v in keep]
        nodes.sort(key=self._sort_key)
        focus = next(n for n in nodes if n["id"] == node_id)
        rendered = self._render_slice(focus, nodes, edges, char_budget or self._char_budget())
        return {"focus": node_id, "depth": depth, "nodes": nodes,
                "edges": edges, "rendered": rendered}

    def get_provenance(self, node_id: str) -> Dict[str, Any]:
        """Trace a node back to the root question (spec §5.5): the chain of
        typed nodes/edges plus who produced each step (automation vs human)."""
        with self._lock:
            if not self._g.has_node(node_id):
                return {"error": f"no node '{node_id}'. {self._ids_hint()}"}
            root = self.root_id()
            if root is None:
                return {"error": "the graph has no ResearchQuestion root yet."}
            if root == node_id:
                return {"root": root, "chain": [self._node_public(root)],
                        "rendered": f"{node_id} is the root question."}
            undirected = self._g.to_undirected(as_view=True)
            try:
                path = nx.shortest_path(undirected, source=node_id, target=root)
            except nx.NetworkXNoPath:
                return {"error": f"no path from '{node_id}' to the root '{root}'."}
            chain, lines = [], []
            for idx, n in enumerate(path):
                node = self._node_public(n)
                chain.append(node)
                lines.append(f"{n} [{node['type']}|{node['status']}] by {node['source']}")
                if idx + 1 < len(path):
                    lines.append(f"  {self._edge_between(n, path[idx + 1])}")
            return {"root": root, "chain": chain, "rendered": "\n".join(lines)}

    def overview(self) -> Dict[str, Any]:
        """Compact whole-graph index (ids/types/statuses/labels — no attrs):
        what the orchestrator consults; workers use it to find node ids."""
        with self._lock:
            counts: Dict[str, Dict[str, int]] = {}
            index = []
            for n, d in self._g.nodes(data=True):
                t, s = d.get("type", "?"), d.get("status", "?")
                counts.setdefault(t, {}).setdefault(s, 0)
                counts[t][s] += 1
                index.append({"id": n, "type": t, "status": s,
                              "label": self._label(d), "source": d.get("source", "")})
            root = self.root_id()
        index.sort(key=self._sort_key)
        lines = []
        if root:
            root_entry = next((e for e in index if e["id"] == root), None)
            if root_entry:
                lines.append(f"Root question {root}: {root_entry['label']}")
        for e in index:
            lines.append(f"- {e['id']} [{e['type']}|{e['status']}] {e['label']}")
        return {"root": root, "counts": counts, "nodes": index,
                "rendered": "\n".join(lines)}

    def full(self) -> Dict[str, Any]:
        with self._lock:
            return self._serialize()

    def full_graph(self) -> nx.MultiDiGraph:
        """Snapshot copy for the trigger queries. NetworkX ``copy()`` copies the
        structure and the attribute dicts one level deep — safe against this
        store's write patterns (we mutate/replace node data in place) and cheap
        at blackboard scale."""
        with self._lock:
            return self._g.copy()

    def to_view(self) -> Dict[str, Any]:
        """Project onto the shape web/templates/graph.html already renders
        (the execution-graph node/edge dicts)."""
        with self._lock:
            nodes = []
            for n, d in self._g.nodes(data=True):
                nodes.append({
                    "id": n,
                    "run_id": self._research_id,
                    "kind": d.get("type", "?").lower(),
                    "label": f"{n} · {self._label(d, 60)}",
                    "status": d.get("status", ""),
                    "executor_agent": d.get("source", ""),
                    "input": {k: _short(v, 300) for k, v in (d.get("attrs") or {}).items()},
                    "output": self._label(d, 300),
                    "t_start": d.get("created_at"),
                    "t_end": d.get("updated_at"),
                })
            edges = [{"src": u, "dst": v, "type": k}
                     for u, v, k in self._g.edges(keys=True)]
            # Cosmetic: tie orphan components (context nodes declared but not yet
            # referenced — a Tool no hypothesis requires, an unconsumed Resource,
            # an unlinked EmpiricalBase) to the root question with a faint
            # "context" edge, so nothing floats in the viewer (the spec's "star").
            root = self.root_id()
            if root and self._g.number_of_nodes() > 1:
                und = self._g.to_undirected(as_view=True)
                for comp in nx.connected_components(und):
                    if root in comp:
                        continue
                    rep = sorted(comp, key=self._sort_key_id)[0]
                    edges.append({"src": root, "dst": rep, "type": "context",
                                  "synthetic": True})
            return {"run_id": self._research_id, "nodes": nodes, "edges": edges}

    def reset(self, archive: bool = True) -> Optional[str]:
        """Start over with an empty graph. The old graph is archived (never
        silently destroyed) unless archive=False. Returns the archive path."""
        with self._lock:
            archived = None
            if archive and self._g.number_of_nodes():
                archived = self._archive_data(self._serialize())
            self._g = nx.MultiDiGraph()
            self._research_id = "research"
            self._created_at = time.time()
            self._root_id = None
            self._save()
            return archived

    # ── commit internals ──────────────────────────────────────────────────────

    def _commit_locked(self, source: str, node_drafts: List[Any],
                       edge_drafts: List[Any], status_drafts: List[Any],
                       enforce_permissions: bool = True,
                       autolink_focus: Optional[str] = None) -> CommitResult:
        if not (node_drafts or edge_drafts or status_drafts):
            return CommitResult(ok=False, errors=[
                "empty commit — provide nodes, edges and/or status_updates"],
                hint=_COMMIT_HINT)
        errors: List[str] = []
        warnings: List[str] = []
        creates: List[Dict[str, Any]] = []     # {ref, type, status, attrs}
        merges: List[Dict[str, Any]] = []      # {id, attrs}
        refs: Dict[str, int] = {}              # ref -> index into creates

        # -- nodes: creations and attrs-merges -------------------------------
        for i, d in enumerate(node_drafts):
            if not isinstance(d, dict):
                errors.append(f"nodes[{i}]: must be an object")
                continue
            if d.get("id") and not d.get("type"):
                errors.extend(self._stage_merge(source, i, d, merges))
                continue
            ntype = schema.normalize_node_type(d.get("type", ""))
            spec = schema.NODE_TYPES.get(ntype)
            status = schema.normalize_token(
                d.get("status") or (spec.statuses[0] if spec else ""))
            attrs = d.get("attrs")
            if attrs is None:
                attrs = {}
            if not isinstance(attrs, dict):
                errors.append(f"nodes[{i}]: attrs must be an object")
                attrs = {}
            if "subtype" in attrs:
                attrs["subtype"] = schema.normalize_token(str(attrs["subtype"]))
            errors.extend(f"nodes[{i}]: {e}" for e in
                          schema.validate_node_draft(source, ntype, status, attrs,
                                                     enforce_permissions=enforce_permissions))
            ref = d.get("ref")
            if ref is not None:
                ref = str(ref)
                if not _REF_RE.match(ref):
                    errors.append(f"nodes[{i}]: invalid ref '{ref}' "
                                  "(1-32 chars of A-Za-z0-9_-)")
                    ref = None
                elif any(r.lower() == ref.lower() for r in refs):
                    errors.append(f"nodes[{i}]: duplicate ref '{ref}' in this commit "
                                  "(refs are matched case-insensitively)")
                    ref = None
                else:
                    refs[ref] = len(creates)
            creates.append({"ref": ref, "type": ntype, "status": status,
                            "attrs": attrs, "source": d.get("source")})

        # -- one active hypothesis per commit --------------------------------
        self._normalize_hypothesis_selection(creates, warnings)

        # -- edges: resolve endpoints against existing nodes + this commit ---
        staged_edges: List[Dict[str, Any]] = []
        for j, d in enumerate(edge_drafts):
            if not isinstance(d, dict):
                errors.append(f"edges[{j}]: must be an object")
                continue
            etype = schema.normalize_token(d.get("type", ""))
            src, e1 = self._resolve_endpoint(d.get("from"), j, "from", refs, warnings)
            dst, e2 = self._resolve_endpoint(d.get("to"), j, "to", refs, warnings)
            errors.extend(e for e in (e1, e2) if e)
            if src is None or dst is None:
                continue
            ftype = creates[refs[src[1]]]["type"] if src[0] == "ref" else self._g.nodes[src[1]]["type"]
            ttype = creates[refs[dst[1]]]["type"] if dst[0] == "ref" else self._g.nodes[dst[1]]["type"]
            edge_errs = schema.validate_edge(source, etype, ftype, ttype,
                                             enforce_permissions=enforce_permissions)
            errors.extend(f"edges[{j}]: {e}" for e in edge_errs)
            if not edge_errs:
                staged_edges.append({"type": etype, "from": src, "to": dst,
                                     "attrs": d.get("attrs") or {}})

        # -- status updates: existing nodes only ------------------------------
        staged_status: List[Dict[str, Any]] = []
        for k, d in enumerate(status_drafts):
            if not isinstance(d, dict):
                errors.append(f"status_updates[{k}]: must be an object")
                continue
            new = schema.normalize_token(d.get("status") or "")
            nid = self._canon_node(d.get("id") or "")
            if nid is None:
                errors.append(f"status_updates[{k}]: no node "
                              f"'{str(d.get('id') or '').strip()}'. {self._ids_hint()}")
                continue
            node = self._g.nodes[nid]
            cur, ntype = node.get("status"), node.get("type")
            # Branch lock (spec §5.4): an under_verification hypothesis is busy —
            # a second attempt to start verification is a CONFLICT, not a no-op.
            if (ntype, cur, new) == ("Hypothesis", "under_verification",
                                     "under_verification"):
                owner, since = self._lock_owner(nid)
                errors.append(
                    f"status_updates[{k}]: {nid} is already under verification "
                    f"(locked by {owner} since {since}). Pick a different "
                    f"hypothesis or wait for the branch to close.")
                continue
            if cur == new:
                warnings.append(f"status_updates[{k}]: {nid} already has "
                                f"status '{new}' — skipped.")
                continue
            tr_errs = schema.validate_transition(source, ntype, cur, new,
                                                enforce_permissions=enforce_permissions)
            errors.extend(f"status_updates[{k}]: {e}" for e in tr_errs)
            if not tr_errs:
                staged_status.append({"id": nid, "type": ntype, "from": cur,
                                      "to": new, "reason": d.get("reason")})

        if errors:
            return CommitResult(ok=False, errors=errors, warnings=warnings,
                                hint=_COMMIT_HINT)

        # -- apply (all validation passed) ------------------------------------
        now = time.time()
        committed: Dict[str, List[Dict[str, Any]]] = {"nodes": [], "edges": [],
                                                      "status_updates": []}
        ref_ids: Dict[str, str] = {}
        for c in creates:
            nid = self._next_id(c["type"])
            attrs = self._truncate_attrs(c["attrs"], warnings)
            # A per-node source (e.g. "human" for an operator-set frame field)
            # overrides the commit's default source; edges/status keep the default.
            node_source = c.get("source") or source
            node = ResearchNode(
                id=nid, type=c["type"], attrs=attrs, status=c["status"],
                source=node_source, created_at=now, updated_at=now,
                status_history=[{"from": None, "to": c["status"],
                                 "source": node_source, "at": now}],
            )
            self._g.add_node(nid, **node.model_dump())
            if c["ref"]:
                ref_ids[c["ref"]] = nid
            echo = {"id": nid, "type": c["type"], "status": c["status"]}
            if c["ref"]:
                echo["ref"] = c["ref"]
            committed["nodes"].append(echo)
        for m in merges:
            node = self._g.nodes[m["id"]]
            node["attrs"] = {**(node.get("attrs") or {}),
                             **self._truncate_attrs(m["attrs"], warnings)}
            node["updated_at"] = now
            committed["nodes"].append({"id": m["id"], "type": node.get("type"),
                                       "updated_attrs": sorted(m["attrs"])})
        seen_edges = set()
        for e in staged_edges:
            u = ref_ids[e["from"][1]] if e["from"][0] == "ref" else e["from"][1]
            v = ref_ids[e["to"][1]] if e["to"][0] == "ref" else e["to"][1]
            if (u, v, e["type"]) in seen_edges or self._g.has_edge(u, v, key=e["type"]):
                warnings.append(f"edge {u} -{e['type']}→ {v} already exists — skipped.")
                continue
            seen_edges.add((u, v, e["type"]))
            edge = ResearchEdge(id=f"{e['type']}:{u}->{v}", type=e["type"],
                                **{"from": u, "to": v},
                                attrs=e["attrs"], source=source, created_at=now)
            data = edge.model_dump(by_alias=True)
            data.pop("from"), data.pop("to")
            self._g.add_edge(u, v, key=e["type"], **data)
            committed["edges"].append({"type": e["type"], "from": u, "to": v})
        for s in staged_status:
            node = self._g.nodes[s["id"]]
            node["status"] = s["to"]
            node["updated_at"] = now
            history = list(node.get("status_history") or [])
            history.append({"from": s["from"], "to": s["to"], "source": source,
                            "at": now, "reason": s.get("reason")})
            node["status_history"] = history
            committed["status_updates"].append({"id": s["id"], "from": s["from"],
                                                "to": s["to"]})
        # Focus auto-link (Option A): Evidence created here that isn't linked to
        # any hypothesis gets a `relates_to` edge to the focused hypothesis, so a
        # worker's finding is never orphaned. The background validator then decides
        # its polarity (supports/refutes). Deterministic; source graph-maintainer.
        self._autolink_focus(committed, autolink_focus, source, now)
        # Deterministic graph maintainer (no LLM): a `formulated` Hypothesis that
        # just received evidence (incl. an auto-linked relates_to) moves to
        # `under_verification` — work has started. Keeps the graph visibly live
        # (blue → amber) for free; the VERDICT is a judgment left to the validator.
        self._auto_maintain(committed, now)
        message = (f"committed {len(committed['nodes'])} node(s), "
                   f"{len(committed['edges'])} edge(s), "
                   f"{len(committed['status_updates'])} status change(s)")
        return CommitResult(
            ok=True, message=message, committed=committed, warnings=warnings,
            graph_stats={"nodes": self._g.number_of_nodes(),
                         "edges": self._g.number_of_edges()},
        )

    # Edge types that mean "this evidence bears on this hypothesis". relates_to is
    # included so focus-auto-linked (polarity-unknown) evidence also advances the
    # hypothesis to under_verification and reaches the validator.
    _EVIDENCE_EDGES = ("supports", "refutes", "refines", "relates_to")

    def _autolink_focus(self, committed: Dict[str, List[Dict[str, Any]]],
                        focus: Optional[str], source: str, now: float) -> None:
        if not focus or not self._g.has_node(focus):
            return
        if self._g.nodes[focus].get("type") != "Hypothesis":
            return
        # evidence ids already linked to SOME hypothesis in this commit
        linked = {e["from"] for e in committed["edges"]
                  if e["type"] in self._EVIDENCE_EDGES
                  and self._g.nodes.get(e["to"], {}).get("type") == "Hypothesis"}
        for n in committed["nodes"]:
            eid = n.get("id")
            if n.get("type") != "Evidence" or eid in linked:
                continue
            if self._g.has_edge(eid, focus, key="relates_to"):
                continue
            edge = ResearchEdge(id=f"relates_to:{eid}->{focus}", type="relates_to",
                                **{"from": eid, "to": focus}, attrs={},
                                source="graph-maintainer", created_at=now)
            data = edge.model_dump(by_alias=True)
            data.pop("from"), data.pop("to")
            self._g.add_edge(eid, focus, key="relates_to", **data)
            committed["edges"].append({"type": "relates_to", "from": eid,
                                       "to": focus, "auto": True})

    def _auto_maintain(self, committed: Dict[str, List[Dict[str, Any]]],
                       now: float) -> None:
        """Store invariant: a `formulated` Hypothesis that just received evidence
        moves to `under_verification` (work has started). Mechanical only — never
        decides a verdict. Runs inside the same locked commit."""
        targets = {e["to"] for e in committed.get("edges", [])
                   if e["type"] in self._EVIDENCE_EDGES}
        for hid in targets:
            if not self._g.has_node(hid):
                continue
            node = self._g.nodes[hid]
            if node.get("type") == "Hypothesis" and node.get("status") == "formulated":
                node["status"] = "under_verification"
                node["updated_at"] = now
                history = list(node.get("status_history") or [])
                history.append({"from": "formulated", "to": "under_verification",
                                "source": "graph-maintainer",
                                "at": now, "reason": "auto: evidence attached"})
                node["status_history"] = history
                committed["status_updates"].append(
                    {"id": hid, "from": "formulated", "to": "under_verification",
                     "auto": True})

    def _normalize_hypothesis_selection(self, creates: List[Dict[str, Any]],
                                        warnings: List[str]) -> None:
        """Store invariant: at most N hypotheses enter the run as active per commit.

        N = ``settings.web.max_active_hypotheses`` (default 1).

        A generator agent naturally proposes several hypotheses at once; if they
        all land as ``formulated``, every one of them shows up as READY and the
        orchestrator starts verifying them — which may not be desired. So
        exactly N (the agent's own picks: ``attrs.selected``, else the highest
        ``attrs.priority``, else the first N) stay ``formulated`` and the rest
        are created as ``postponed``: they remain in the graph as the ranked
        backlog, invisible to the READY trigger, and the orchestrator can revive
        one (postponed→formulated) once an active branch has a verdict.

        Deterministic and mechanical — it never drops or rewrites a hypothesis,
        only decides which ones are offered for verification next.
        """
        from CoScientist.config import get_settings
        max_active = max(1, min(5, get_settings().web.max_active_hypotheses))

        active = [c for c in creates
                  if c["type"] == "Hypothesis" and c["status"] == "formulated"]
        if len(active) <= max_active:
            return
        # Sort by priority_rank (lower = higher priority) and keep top N.
        ranked = sorted(active, key=lambda c: priority_rank(c["attrs"]))
        primary_set = set(id(c) for c in ranked[:max_active])
        for c in active:
            if id(c) in primary_set:
                continue
            c["status"] = "postponed"
            c["attrs"].setdefault(
                "postponed_reason",
                "alternative hypothesis — kept as backlog while the selected "
                "ones are verified")
        kept_labels = ", ".join(
            f'"{self._label(c, 60) or c.get("ref") or "?"}"'
            for c in ranked[:max_active])
        warnings.append(
            f"{len(active)} hypotheses were proposed as active at once; only "
            f"{max_active} may be verified at a time, so {kept_labels} "
            f"stay 'formulated' and the other "
            f"{len(active) - max_active} were created as 'postponed' (backlog). "
            f"To choose which ones are verified, mark them with "
            f"attrs.selected=true or a higher attrs.priority; the orchestrator "
            f"can revive a postponed one later.")

    def _stage_merge(self, source: str, i: int, draft: Dict[str, Any],
                     merges: List[Dict[str, Any]]) -> List[str]:
        """Validate an attrs-merge entry ({"id": …, "attrs": {…}}) — how e.g.
        the researcher enriches an existing EmpiricalBase (spec §2)."""
        nid = self._canon_node(draft["id"])
        if nid is None:
            return [f"nodes[{i}]: no node '{str(draft['id']).strip()}' to update. "
                    f"{self._ids_hint()}"]
        ntype = self._g.nodes[nid].get("type")
        perm = schema.AGENT_PERMISSIONS.get(source)
        if perm is None or (ntype not in perm.update_attrs
                            and ntype not in perm.create):
            allowed = ", ".join(sorted(perm.update_attrs | perm.create)) if perm else "none"
            return [f"nodes[{i}]: agent '{source}' may not update attrs of "
                    f"{ntype} nodes (yours: {allowed})."]
        attrs = draft.get("attrs")
        if not isinstance(attrs, dict) or not attrs:
            return [f"nodes[{i}]: an attrs object with the fields to merge is "
                    f"required to update '{nid}'."]
        if "subtype" in attrs:
            attrs = {**attrs, "subtype": schema.normalize_token(str(attrs["subtype"]))}
        merges.append({"id": nid, "attrs": attrs})
        return []

    def _resolve_endpoint(self, value: Any, j: int, side: str,
                          refs: Dict[str, int],
                          warnings: List[str]) -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
        v = str(value or "").strip()
        if not v:
            return None, f"edges[{j}]: missing '{side}'"

        # Ref/id matching is case-INSENSITIVE and returns the CANONICAL stored
        # key — LLMs routinely define ref "E4" then cite it as "#e4", and node
        # ids are all uppercase, so forgiving the casing removes a whole class of
        # avoidable retries. The returned key stays the stored one so downstream
        # lookups (refs[...] / ref_ids[...] / graph node) are unchanged.
        def _match_ref(name: str) -> Optional[str]:
            if name in refs:
                return name
            low = name.lower()
            return next((r for r in refs if r.lower() == low), None)

        def _match_node(name: str) -> Optional[str]:
            return self._canon_node(name)

        if v.startswith("#"):
            r = _match_ref(v[1:])
            if r is not None:
                return ("ref", r), None
            return None, (f"edges[{j}]: no ref '{v[1:]}' among the nodes created in "
                          f"this call (refs: {', '.join(sorted(refs)) or 'none'}).")
        node = _match_node(v)
        if node is not None:
            return ("id", node), None
        r = _match_ref(v)
        if r is not None:
            warnings.append(f"edges[{j}]: '{v}' treated as ref '#{r}' "
                            "(prefer the # prefix).")
            return ("ref", r), None
        return None, (f"edges[{j}]: no node '{v}'. {self._ids_hint()} To "
                      f"reference a node created in THIS call, use '#<ref>'.")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _canon_node(self, name: str) -> Optional[str]:
        """The stored node id matching `name` case-insensitively, or None.
        Node ids are uppercase-prefix + digits, so an uppercased probe is an
        unambiguous canonicalization (lets an LLM write 'h1' for 'H1')."""
        name = str(name or "").strip()
        if self._g.has_node(name):
            return name
        up = name.upper()
        return up if self._g.has_node(up) else None

    def _next_id(self, node_type: str) -> str:
        prefix = schema.NODE_TYPES[node_type].prefix
        pat = re.compile(rf"^{prefix}(\d+)$")
        highest = 0
        for n in self._g.nodes:
            m = pat.match(str(n))
            if m:
                highest = max(highest, int(m.group(1)))
        return f"{prefix}{highest + 1}"

    def _lock_owner(self, node_id: str) -> Tuple[str, str]:
        history = self._g.nodes[node_id].get("status_history") or []
        for entry in reversed(history):
            if entry.get("to") == "under_verification":
                at = entry.get("at")
                when = datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M") if at else "?"
                return entry.get("source", "?"), when
        return "?", "?"

    def _ids_hint(self) -> str:
        ids = sorted(self._g.nodes, key=self._sort_key_id)
        if not ids:
            return "The graph is empty."
        if len(ids) <= 40:
            return f"Existing ids: {', '.join(ids)}."
        return (f"The graph has {len(ids)} nodes — call research_overview() "
                "to list them.")

    def _truncate_attrs(self, attrs: Dict[str, Any],
                        warnings: List[str]) -> Dict[str, Any]:
        out = {}
        for k, v in (attrs or {}).items():
            if isinstance(v, str) and len(v) > _ATTR_CHAR_CAP:
                out[k] = v[:_ATTR_CHAR_CAP] + "…[truncated]"
                warnings.append(f"attr '{k}' exceeded {_ATTR_CHAR_CAP} chars "
                                "and was truncated.")
            else:
                out[k] = v
        return out

    def _label(self, data: Dict[str, Any], n: int = 100) -> str:
        attrs = data.get("attrs") or {}
        for key in _LABEL_ATTRS:
            if attrs.get(key):
                return _short(attrs[key], n)
        return _short(json.dumps(attrs, ensure_ascii=False, default=str), n) if attrs else ""

    def _node_public(self, node_id: str) -> Dict[str, Any]:
        d = self._g.nodes[node_id]
        return {
            "id": node_id,
            "type": d.get("type"),
            "status": d.get("status"),
            "source": d.get("source"),
            "attrs": {k: _short(v, 400) if isinstance(v, str) else v
                      for k, v in (d.get("attrs") or {}).items()},
        }

    @staticmethod
    def _sort_key(entry: Dict[str, Any]):
        return ResearchGraphStore._sort_key_id(entry["id"])

    @staticmethod
    def _sort_key_id(node_id: str):
        m = re.match(r"^([A-Z]+)(\d+)$", str(node_id))
        return (m.group(1), int(m.group(2))) if m else (str(node_id), 0)

    def _edge_between(self, a: str, b: str) -> str:
        for u, v in ((a, b), (b, a)):
            data = self._g.get_edge_data(u, v)
            if data:
                return f"{u} -{next(iter(data))}→ {v}"
        return f"{a} ~ {b}"

    def _render_slice(self, focus: Dict[str, Any], nodes: List[Dict[str, Any]],
                      edges: List[Dict[str, Any]], char_budget: int) -> str:
        lines = [f"CONTEXT SLICE for {focus['id']} "
                 f"({focus['type']}, status={focus['status']})", "Nodes:"]
        for n in nodes:
            attrs = json.dumps(n["attrs"], ensure_ascii=False, default=str)
            lines.append(f"- {n['id']} [{n['type']}|{n['status']}] {_short(attrs, 240)}")
        lines.append("Edges:")
        for e in edges:
            lines.append(f"- {e['from']} -{e['type']}→ {e['to']}")
        text = "\n".join(lines)
        if len(text) > char_budget:
            text = text[: char_budget] + ("\n…[slice truncated — call "
                                          "research_context_slice on specific nodes]")
        return text

    def _max_depth(self) -> int:
        try:
            from CoScientist.config import get_settings
            return get_settings().research_graph.slice_depth_max
        except Exception:  # noqa: BLE001
            return 2

    def _char_budget(self) -> int:
        try:
            from CoScientist.config import get_settings
            return get_settings().research_graph.slice_char_budget
        except Exception:  # noqa: BLE001
            return 4000

    # ── persistence ───────────────────────────────────────────────────────────

    def _serialize(self) -> Dict[str, Any]:
        return {
            "research_id": self._research_id,
            "created_at": self._created_at,
            "root_id": self._root_id,
            "nodes": [dict(self._g.nodes[n]) for n in self._g.nodes],
            "edges": [{"type": k, "from": u, "to": v, **d}
                      for u, v, k, d in self._g.edges(keys=True, data=True)],
        }

    def _save(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._serialize(), f, ensure_ascii=False, default=str)
            os.replace(tmp, self._path)
        except Exception as exc:  # noqa: BLE001 — persistence must never break writes
            logger.warning("Research graph snapshot failed: %s", exc)

    def _archive_data(self, data: Dict[str, Any]) -> Optional[str]:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            root = data.get("root_id") or "graph"
            path = self._dir / (
                f"research_{root}_{stamp}_{uuid4().hex[:8]}.json"
            )
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, default=str)
            return str(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Research graph archive failed: %s", exc)
            return None

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            g = nx.MultiDiGraph()
            for node in data.get("nodes", []):
                g.add_node(node["id"], **node)
            for edge in data.get("edges", []):
                e = dict(edge)
                u, v, k = e.pop("from"), e.pop("to"), e.get("type")
                g.add_edge(u, v, key=k, **e)
            self._g = g
            self._research_id = data.get("research_id", "research")
            self._created_at = data.get("created_at", time.time())
            self._root_id = data.get("root_id")
        except Exception as exc:  # noqa: BLE001 — a corrupt file must not kill startup
            logger.warning("Research graph load failed (%s); starting empty. "
                           "Keeping the file untouched at %s", exc, self._path)
            self._g = nx.MultiDiGraph()


# Legacy/default graph for standalone utilities and unit tests.
research_graph = ResearchGraphStore()
_research_graphs: Dict[SessionKey, ResearchGraphStore] = {
    DEFAULT_SESSION_KEY: research_graph,
}
_registry_lock = threading.RLock()


def get_research_graph(
    context: Any = None,
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> ResearchGraphStore:
    """Return the typed research blackboard for one ADK user/session."""
    key = session_key(context, user_id=user_id, session_id=session_id)
    with _registry_lock:
        graph = _research_graphs.get(key)
        if graph is None:
            directory = storage_dir(_default_dir(), key)
            graph = ResearchGraphStore(
                directory=str(directory),
                active_file=_default_file(),
            )
            _research_graphs[key] = graph
        return graph
