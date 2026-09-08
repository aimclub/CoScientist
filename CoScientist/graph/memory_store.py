"""Global knowledge graph — persistent semantic *graph memory*.

While ``KnowledgeGraph`` (memory.py) records ONE session's execution trace, this
store accumulates the *semantic* layer ACROSS all users and sessions: the typed
domain entities and relations extracted from agent outputs (semantic.py). It is
what lets every later research session reuse facts established by prior runs.

Design notes addressing the obvious failure modes:
  * **Dedup** — entities are keyed by a CANONICAL id derived from the name
    (lowercased, punctuation-folded), independent of the LLM's chosen ``type:``
    prefix, so "molecule:paracetamol" and "drug:Paracetamol" collapse into ONE
    node. Aliases (the raw keys/names seen) are kept for lookup.
  * **Reuse** — facts are retrieved two ways: ``relevant(query)`` (ranked search,
    for the prompt injection) and ``neighbors(entity)`` (1-hop traversal, so an
    agent can search then walk the graph).

One data-driven template (Node/Edge shape), persisted to JSON so it survives
restarts and grows over time.
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import shutil
import threading
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from CoScientist.graph.semantic import Extraction

logger = logging.getLogger(__name__)


def _slug(s: str) -> str:
    normalized = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-_")


def _canon(name: str = "", key: str = "") -> str:
    """Canonical entity id from the name (preferred) or the key's tail."""
    base = name or (key.split(":", 1)[-1] if ":" in (key or "") else key)
    candidate = _slug(base) or _slug(key)
    if candidate:
        return candidate
    # Emoji/symbol-only names still need distinct, deterministic identities.
    raw = unicodedata.normalize("NFKC", base or key or "entity").casefold()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"entity-{digest}"


def _tokens(text: str) -> set:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return {
        word.strip("_")
        for word in re.findall(r"\w+", normalized, flags=re.UNICODE)
        if len(word.strip("_")) > 2
    }


class KnowledgeMemory:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path or os.getenv("KG_MEMORY_PATH", "graph_runs/knowledge_memory.json"))
        self.entities: Dict[str, Dict[str, Any]] = {}     # canon id -> entity record
        self.relations: Dict[str, Dict[str, Any]] = {}    # "src|type|dst" -> relation record
        self._migrated_sources: set[str] = set()
        self._migration_checked = False
        self._load_ok = True
        self._last_error: Optional[str] = None
        self._lock = threading.RLock()
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self.path.exists():
            self._load_ok = True
            self._last_error = None
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.entities = {e["id"]: e for e in data.get("entities", []) if e.get("id")}
            self.relations = {self._rkey(r["src"], r["type"], r["dst"]): r
                              for r in data.get("relations", []) if r.get("src") and r.get("dst")}
            meta = data.get("_meta") or {}
            self._migrated_sources = {
                str(source)
                for source in meta.get("migrated_user_memories", [])
                if source
            }
            self._load_ok = True
            self._last_error = None
        except Exception as exc:  # noqa: BLE001
            self.entities, self.relations = {}, {}
            self._migrated_sources = set()
            self._load_ok = False
            self._last_error = f"Could not load canonical knowledge memory: {exc}"

    def _save(self) -> bool:
        if not self._load_ok:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            payload = {
                "entities": list(self.entities.values()),
                "relations": list(self.relations.values()),
                "_meta": {
                    "migrated_user_memories": sorted(self._migrated_sources),
                },
            }
            tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            self._last_error = None
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"Could not persist canonical knowledge memory: {exc}"
            return False

    @staticmethod
    def _path_key(path: Path) -> str:
        """Stable source marker, including Windows case normalisation."""
        return os.path.normcase(str(path.resolve()))

    def _migration_key(self, path: Path) -> str:
        """Deployment-independent identity for one obsolete per-user file."""
        try:
            relative = path.resolve().relative_to(self.path.parent.resolve())
            value = relative.as_posix()
        except ValueError:
            value = path.name
        return f"v2:{os.path.normcase(value)}"

    def clear(self, archive: bool = True) -> Dict[str, Any]:
        """Drop every fact, keeping a copy of the old file by default.

        A memory whose file could not be read refuses to save, so that a
        transient read error never silently destroys facts (see ``_save``).
        Deleting is the deliberate exception: the operator asked for the file to
        go, so the guard is lifted here — the archive keeps the old bytes.
        """
        with self._lock:
            removed = {
                "entities": len(self.entities),
                "relations": len(self.relations),
            }
            archived = self._archive_file() if archive else None
            self.entities = {}
            self.relations = {}
            # Migration markers survive a wipe on purpose: re-importing the
            # obsolete per-user files would resurrect the deleted facts.
            self._load_ok = True
            self._last_error = None
            persisted = self._save()
            return {
                **removed,
                "archived": archived,
                "persisted": persisted,
                "error": self._last_error,
            }

    def _archive_file(self) -> Optional[str]:
        """Copy the current memory file aside, verbatim (best-effort).

        Copying bytes rather than re-serialising ``self`` keeps a file that
        failed to load recoverable by hand.
        """
        if not self.path.exists():
            return None
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.path.with_name(
                f"{self.path.stem}_{stamp}_{uuid4().hex[:8]}{self.path.suffix}"
            )
            shutil.copy2(self.path, target)
            return str(target)
        except Exception as exc:  # noqa: BLE001 — never block the deletion
            logger.warning("Knowledge memory archive failed: %s", exc)
            return None

    def _rebind(self, path: Path) -> None:
        """Point the singleton at a newly configured path.

        Production config is stable for the process lifetime. Rebinding keeps
        references imported through the legacy ``knowledge_memory`` symbol valid
        when a test temporarily changes ``KG_MEMORY_PATH``.
        """
        with self._lock:
            if self._path_key(self.path) == self._path_key(path):
                return
            self.path = path
            self.entities = {}
            self.relations = {}
            self._migrated_sources = set()
            self._migration_checked = False
            self._load_ok = True
            self._last_error = None
            self._load()

    @staticmethod
    def _rkey(src: str, type_: str, dst: str) -> str:
        return f"{src}|{type_}|{dst}"

    @staticmethod
    def _provenance_key(prov: Dict[str, Any]) -> tuple:
        """Identity of one producing event, preserving an optional scope.

        Invocation/result ids are not guaranteed to be globally unique. When
        user/session scope is present, it therefore participates in dedup.
        Legacy unscoped refs retain their result/goal based behaviour.
        """
        nested_scope = prov.get("_session") or prov.get("scope") or {}
        if not isinstance(nested_scope, dict):
            nested_scope = {}
        user_id = prov.get("user_id") or nested_scope.get("user_id")
        session_id = prov.get("session_id") or nested_scope.get("session_id")
        run = prov.get("run")
        for field in ("result_id", "goal_id", "goal"):
            value = prov.get(field)
            if value is not None:
                return user_id, session_id, run, field, str(value)
        try:
            fallback = json.dumps(
                prov,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        except Exception:  # noqa: BLE001
            fallback = str(prov)
        return user_id, session_id, run, "ref", fallback

    @classmethod
    def _add_prov(cls, rec: Dict[str, Any], prov: Dict[str, Any]) -> None:
        """Attach a provenance ref pointing into the knowledge graph (best-effort,
        deduped by the producing result node).

        Provenance is deliberately not capped: exact historical session views
        use it as their durable fact index, not merely as display metadata.
        """
        if not prov:
            return
        pl = rec.setdefault("provenance", [])
        key = cls._provenance_key(prov)
        if any(cls._provenance_key(p) == key for p in pl):
            return
        pl.append(deepcopy(prov))

    @staticmethod
    def _merge_unique(current: List[Any], incoming: List[Any]) -> List[Any]:
        merged = list(current)
        for value in incoming:
            if value not in merged:
                merged.append(value)
        return merged

    def _merge_entity(self, incoming: Dict[str, Any], legacy_user_id: str) -> None:
        cid = incoming.get("id")
        if not cid:
            return
        incoming = deepcopy(incoming)
        incoming_provenance = incoming.pop("provenance", []) or []
        cur = self.entities.get(cid)
        if cur is None:
            cur = incoming
            cur["id"] = cid
            cur["attrs"] = dict(cur.get("attrs") or {})
            cur["aliases"] = list(dict.fromkeys(cur.get("aliases") or []))
            cur["sources"] = list(dict.fromkeys(cur.get("sources") or []))
            cur["mentions"] = max(int(cur.get("mentions", 1) or 1), 1)
            cur["provenance"] = []
            self.entities[cid] = cur
        else:
            cur.setdefault("attrs", {}).update(incoming.get("attrs") or {})
            cur["mentions"] = (
                int(cur.get("mentions", 1) or 1)
                + max(int(incoming.get("mentions", 1) or 1), 1)
            )
            for field in ("name", "description"):
                candidate = incoming.get(field) or ""
                if len(candidate) > len(cur.get(field, "")):
                    cur[field] = candidate
            cur["aliases"] = self._merge_unique(
                cur.get("aliases", []), incoming.get("aliases", []),
            )
            cur["sources"] = self._merge_unique(
                cur.get("sources", []), incoming.get("sources", []),
            )
        for prov in incoming_provenance:
            if not isinstance(prov, dict):
                continue
            scoped_prov = dict(prov)
            scoped_prov.setdefault("user_id", legacy_user_id)
            scoped_prov.setdefault("entity", {
                "id": cid,
                "type": incoming.get("type"),
                "name": incoming.get("name") or cid,
                "description": incoming.get("description") or "",
                "attrs": deepcopy(incoming.get("attrs") or {}),
            })
            self._add_prov(cur, scoped_prov)

    def _merge_relation(self, incoming: Dict[str, Any], legacy_user_id: str) -> None:
        src, dst, type_ = (
            incoming.get("src"), incoming.get("dst"), incoming.get("type")
        )
        if not (src and dst and type_):
            return
        incoming = deepcopy(incoming)
        incoming_provenance = incoming.pop("provenance", []) or []
        key = self._rkey(src, type_, dst)
        cur = self.relations.get(key)
        if cur is None:
            cur = incoming
            cur["src"], cur["dst"], cur["type"] = src, dst, type_
            cur["attrs"] = dict(cur.get("attrs") or {})
            cur["sources"] = list(dict.fromkeys(cur.get("sources") or []))
            cur["count"] = max(int(cur.get("count", 1) or 1), 1)
            cur["provenance"] = []
            self.relations[key] = cur
        else:
            cur.setdefault("attrs", {}).update(incoming.get("attrs") or {})
            cur["count"] = (
                int(cur.get("count", 1) or 1)
                + max(int(incoming.get("count", 1) or 1), 1)
            )
            cur["sources"] = self._merge_unique(
                cur.get("sources", []), incoming.get("sources", []),
            )
        for prov in incoming_provenance:
            if not isinstance(prov, dict):
                continue
            scoped_prov = dict(prov)
            scoped_prov.setdefault("user_id", legacy_user_id)
            scoped_prov.setdefault("claim", {
                "src": src,
                "src_name": self.entities.get(src, {}).get("name", src),
                "dst": dst,
                "dst_name": self.entities.get(dst, {}).get("name", dst),
                "type": type_,
                "attrs": deepcopy(incoming.get("attrs") or {}),
            })
            self._add_prov(cur, scoped_prov)

    def _migrate_legacy_user_memories(self) -> int:
        """Merge obsolete ``users/*`` memories into the canonical store once.

        Source files are read-only and retained. Their paths relative to the
        canonical store are committed atomically with the merged graph, making
        repeated startup idempotent even if the deployment directory is moved.
        Invalid sources are skipped and remain eligible for retry on restart.
        """
        with self._lock:
            if self._migration_checked or not self._load_ok:
                return 0
            self._migration_checked = True
            users_dir = self.path.parent / "users"
            if not users_dir.is_dir():
                return 0

            before = (
                deepcopy(self.entities),
                deepcopy(self.relations),
                set(self._migrated_sources),
            )
            migrated = 0
            metadata_changed = False
            for source_path in sorted(users_dir.glob("*/knowledge_memory.json")):
                source_key = self._migration_key(source_path)
                if source_key in self._migrated_sources:
                    continue
                # Upgrade markers written by the short-lived absolute-path
                # migration implementation without importing the source twice.
                legacy_key = self._path_key(source_path)
                if legacy_key in self._migrated_sources:
                    self._migrated_sources.remove(legacy_key)
                    self._migrated_sources.add(source_key)
                    metadata_changed = True
                    continue
                try:
                    payload = json.loads(
                        source_path.read_text(encoding="utf-8")
                    )
                    entities = payload.get("entities", [])
                    relations = payload.get("relations", [])
                    if (
                        not isinstance(entities, list)
                        or not isinstance(relations, list)
                    ):
                        continue
                except Exception:  # noqa: BLE001
                    continue

                legacy_user_id = source_path.parent.name
                source_before = (
                    deepcopy(self.entities),
                    deepcopy(self.relations),
                )
                try:
                    for entity in entities:
                        if isinstance(entity, dict):
                            self._merge_entity(entity, legacy_user_id)
                    for relation in relations:
                        if isinstance(relation, dict):
                            self._merge_relation(relation, legacy_user_id)
                except Exception:  # noqa: BLE001 - malformed legacy file
                    self.entities, self.relations = source_before
                    continue
                self._migrated_sources.add(source_key)
                migrated += 1

            if not migrated and not metadata_changed:
                return 0
            self._prune_orphans()
            if not self._save():
                self.entities, self.relations, self._migrated_sources = before
                self._migration_checked = False
                return 0
            return migrated

    def _prune_orphans(self) -> None:
        """Drop entities not connected by any relation — the memory graph must
        have no disconnected nodes (a fact only counts if it links to something)."""
        connected = set()
        for r in self.relations.values():
            connected.add(r["src"])
            connected.add(r["dst"])
        self.entities = {k: e for k, e in self.entities.items() if k in connected}

    # ── ingest (accumulate + dedup across runs) ────────────────────────────────
    def ingest(self, extraction: Extraction, source: str = "",
               refs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        added: Dict[str, Any] = {
            "entities": 0,
            "relations": 0,
            "persisted": False,
        }
        # provenance ref into the knowledge graph (which run/goal/result produced it)
        prov = dict(refs or {})
        if source:
            prov.setdefault("goal", source)
        with self._lock:
            if not self._load_ok:
                added["error"] = self._last_error or "Knowledge memory is unavailable"
                return added
            before = deepcopy(self.entities), deepcopy(self.relations)
            keymap: Dict[str, str] = {}   # the extraction's raw key/name -> canonical id
            for e in extraction.entities:
                cid = _canon(e.name, e.key)
                keymap[e.key] = cid
                if e.name:
                    keymap[e.name] = cid
                cur = self.entities.get(cid)
                if cur is None:
                    cur = self.entities[cid] = {
                        "id": cid, "type": e.type, "name": e.name or cid,
                        "description": (e.description or "").strip(),
                        "attrs": dict(e.attrs or {}), "mentions": 1,
                        "aliases": sorted({a for a in (e.key, e.name) if a}),
                        "sources": [source] if source else [], "provenance": [],
                    }
                    added["entities"] += 1
                else:
                    cur["attrs"].update(e.attrs or {})
                    cur["mentions"] = cur.get("mentions", 1) + 1
                    if e.name and len(e.name) > len(cur.get("name", "")):
                        cur["name"] = e.name
                    if e.description and len(e.description) > len(cur.get("description", "")):
                        cur["description"] = e.description.strip()
                    cur["aliases"] = sorted(set(cur.get("aliases", [])) | {a for a in (e.key, e.name) if a})
                    if source and source not in cur["sources"]:
                        cur["sources"].append(source)
                entity_prov = dict(prov)
                entity_prov.setdefault("entity", {
                    "id": cid,
                    "type": e.type,
                    "name": e.name or cid,
                    "description": (e.description or "").strip(),
                    "attrs": dict(e.attrs or {}),
                })
                self._add_prov(cur, entity_prov)

            def resolve(ref: str) -> str:
                return keymap.get(ref) or _canon(key=ref)

            for r in extraction.relations:
                if not (r.src and r.dst):
                    continue
                src, dst = resolve(r.src), resolve(r.dst)
                if src == dst:
                    continue
                rk = self._rkey(src, r.type, dst)
                cur = self.relations.get(rk)
                if cur is None:
                    cur = self.relations[rk] = {"src": src, "dst": dst, "type": r.type,
                                                "attrs": dict(getattr(r, "attrs", {}) or {}),
                                                "count": 1, "sources": [source] if source else [],
                                                "provenance": []}
                    added["relations"] += 1
                else:
                    cur["attrs"].update(getattr(r, "attrs", {}) or {})
                    cur["count"] = cur.get("count", 1) + 1
                    if source and source not in cur["sources"]:
                        cur["sources"].append(source)
                relation_prov = dict(prov)
                relation_prov.setdefault("claim", {
                    "src": src,
                    "src_name": self.entities.get(src, {}).get("name", src),
                    "dst": dst,
                    "dst_name": self.entities.get(dst, {}).get("name", dst),
                    "type": r.type,
                    "attrs": dict(getattr(r, "attrs", {}) or {}),
                })
                self._add_prov(cur, relation_prov)

            self._prune_orphans()
            if self._save():
                added["persisted"] = True
            else:
                self.entities, self.relations = before
                added["error"] = self._last_error or "Knowledge memory was not saved"
        return added

    # ── reads ───────────────────────────────────────────────────────────────
    def snapshot(self) -> tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        """Return an immutable-by-convention semantic snapshot for projections."""
        with self._lock:
            return deepcopy(self.entities), deepcopy(list(self.relations.values()))

    def health(self) -> Dict[str, Any]:
        """Persistence health surfaced by the global Knowledge API."""
        with self._lock:
            return {
                "healthy": self._load_ok and self._last_error is None,
                "path": str(self.path),
                "error": self._last_error,
            }

    def full(self) -> Dict[str, Any]:
        """Node/Edge-shaped dict so the same viz renders the memory graph.
        Entity labels carry a salient attr so the graph reads at a glance."""
        with self._lock:
            entities = deepcopy(self.entities)
            relations = deepcopy(self.relations)
        nodes = []
        for e in entities.values():
            attrs = e.get("attrs") or {}
            salient = next(iter(attrs.items()), None)
            label = e.get("name") or e["id"]
            if salient:
                label = f"{label} · {salient[0]}={salient[1]}"
            # provenance: pointers into the KNOWLEDGE graph (which run/goal/result
            # produced this fact) — so a memory fact is verifiable against the log.
            prov = e.get("provenance", [])
            prov_str = "; ".join(
                " ".join(
                    f"{key}={p.get(key)}"
                    for key in (
                        "user_id",
                        "session_id",
                        "research_id",
                        "run",
                        "goal_id",
                        "result_id",
                    )
                    if p.get(key) is not None
                )
                for p in prov[-3:]
            ) or str(e.get("sources", []))
            desc = e.get("description") or ""
            nodes.append({
                "id": e["id"], "run_id": "memory", "kind": "entity",
                "label": label, "status": "success",
                "semantic": {"type": e.get("type"), "entity": e["id"]},
                "input": attrs,
                "mentions": e.get("mentions", 1),
                "sources": deepcopy(e.get("sources", [])),
                "provenance": deepcopy(prov),
                "output": ((f"{desc}\n" if desc else "")
                           + f"type={e.get('type')} · mentions={e.get('mentions', 1)} · "
                           f"source (knowledge graph): {prov_str} · aliases={e.get('aliases', [])}"),
            })
        edges = []
        for r in relations.values():
            if r["src"] in entities and r["dst"] in entities:
                lbl = r.get("type", "")
                val = (r.get("attrs") or {}).get("value")
                edges.append({
                    "src": r["src"],
                    "dst": r["dst"],
                    "type": f"{lbl} ({val})" if val is not None else lbl,
                    "relation_type": lbl,
                    "attrs": deepcopy(r.get("attrs", {})),
                    "count": r.get("count", 1),
                    "sources": deepcopy(r.get("sources", [])),
                    "provenance": deepcopy(r.get("provenance", [])),
                })
        return {
            "run_id": "memory",
            "view": "memory",
            "scope": "global",
            "storage": self.health(),
            "nodes": nodes,
            "edges": edges,
        }

    def _match(self, ref: str) -> Optional[Dict[str, Any]]:
        """Resolve a key/name/alias to an entity record."""
        with self._lock:
            cid = _canon(key=ref)
            if cid in self.entities:
                return deepcopy(self.entities[cid])
            cid2 = _canon(name=ref)
            if cid2 in self.entities:
                return deepcopy(self.entities[cid2])
            for e in self.entities.values():
                if ref in e.get("aliases", []) or ref.lower() == (e.get("name", "").lower()):
                    return deepcopy(e)
        return None

    def relevant(self, query: str, k: int = 8) -> List[Dict[str, Any]]:
        q = _tokens(query)
        with self._lock:
            entities = deepcopy(list(self.entities.values()))
        if not q:
            return sorted(entities, key=lambda e: -e.get("mentions", 1))[:k]
        scored = []
        for e in entities:
            blob = " ".join([e.get("name", ""), e.get("id", ""), e.get("type", ""),
                             " ".join(map(str, (e.get("attrs") or {}).values())),
                             " ".join(e.get("aliases", []))])
            score = len(q & _tokens(blob)) + 0.1 * e.get("mentions", 1)
            if score >= 1:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:k]]

    def neighbors(self, ref: str) -> Dict[str, Any]:
        """The entity plus its 1-hop facts — for an agent to walk the graph."""
        with self._lock:
            e = self._match(ref)
            if e is None:
                return {"found": False, "query": ref}
            cid = e["id"]
            facts = []
            for r in self.relations.values():
                if r["src"] == cid:
                    other = self.entities.get(r["dst"], {})
                    facts.append({"fact": f"{e['name']} {r['type']} {other.get('name', r['dst'])}",
                                  "direction": "out", "type": r["type"], "neighbor": r["dst"],
                                  "attrs": deepcopy(r.get("attrs", {}))})
                elif r["dst"] == cid:
                    other = self.entities.get(r["src"], {})
                    facts.append({"fact": f"{other.get('name', r['src'])} {r['type']} {e['name']}",
                                  "direction": "in", "type": r["type"], "neighbor": r["src"],
                                  "attrs": deepcopy(r.get("attrs", {}))})
        return {"found": True,
                "entity": {k: e.get(k) for k in
                           ("id", "type", "name", "attrs", "mentions", "sources", "provenance")},
                "facts": facts}

    def relevant_summary(self, query: str = "", k: int = 8) -> str:
        with self._lock:
            ents = self.relevant(query, k)
            if not ents:
                return ""
            keys = {e["id"] for e in ents}
            lines = ["GLOBAL KNOWLEDGE MEMORY — facts established in PRIOR runs (build on these, don't redo):"]
            for e in ents:
                attrs = ", ".join(f"{kk}={vv}" for kk, vv in (e.get("attrs") or {}).items())
                desc = e.get("description") or ""
                lines.append(f"- {e.get('name')} [{e.get('type')}]"
                             + (f": {desc}" if desc else "")
                             + (f" ({attrs})" if attrs else ""))
            for r in [r for r in self.relations.values() if r["src"] in keys and r["dst"] in keys][:k]:
                sn = self.entities.get(r["src"], {}).get("name", r["src"])
                dn = self.entities.get(r["dst"], {}).get("name", r["dst"])
                val = (r.get("attrs") or {}).get("value")
                lines.append(f"  · {sn} {r.get('type')} {dn}" + (f" ({val})" if val is not None else ""))
            return "\n".join(lines)

    def known_types(self):
        """(entity types, relation types) currently in the graph — fed back to
        the extractor so it reuses them instead of minting near-duplicates."""
        with self._lock:
            ent = {e.get("type") for e in self.entities.values() if e.get("type")}
            rel = {r.get("type") for r in self.relations.values() if r.get("type")}
            return ent, rel

    def stats(self) -> Dict[str, int]:
        with self._lock:
            entity_types, relation_types = self.known_types()
            return {
                "entities": len(self.entities),
                "relations": len(self.relations),
                "entity_types": len(entity_types),
                "relation_types": len(relation_types),
            }


# One canonical memory for every user/session. The exported symbol remains for
# standalone utilities and callers written before ``get_knowledge_memory``.
knowledge_memory = KnowledgeMemory()
_registry_lock = threading.RLock()


def get_global_knowledge_memory() -> KnowledgeMemory:
    """Return the one semantic memory configured by ``KG_MEMORY_PATH``."""
    configured = Path(
        os.getenv("KG_MEMORY_PATH", "graph_runs/knowledge_memory.json")
    )
    with _registry_lock:
        knowledge_memory._rebind(configured)
        knowledge_memory._migrate_legacy_user_memories()
        return knowledge_memory


def get_knowledge_memory(
    context: Any = None,
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> KnowledgeMemory:
    """Compatibility resolver for the global semantic Knowledge Memory.

    Context and explicit scope arguments remain accepted so existing tools and
    callbacks keep one resolver interface. They intentionally do not partition
    semantic knowledge; scope is stored as fact provenance instead.
    """
    del context, user_id, session_id
    return get_global_knowledge_memory()
