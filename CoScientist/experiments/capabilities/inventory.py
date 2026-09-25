"""Inventory indexing + capability-family cover (not leftover/RAG similarity).

Cover = this-run retrieve returned a **compute MCP of the needed family**.
Leftover tox / paper-demo / smiles2prop do not cover generate/dock.
Empty fedot/react binds from exact name in the task text, else family match.
Promote coder → MCP when THIS task's statement names a tool or its primary
family is covered. Leftover inventory for a different family does not steal
an unnamed coder slot (or alembic if a repo fits).

Research/medical families are declared route-agent capabilities (not RAG MCP).
They must not count as compute coverage for feasibility.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Mapping

_log = logging.getLogger(__name__)


FAMILY_MCP = "mcp"
FAMILY_RESEARCH = "research"
FAMILY_MEDICAL = "medical"

RESEARCH_SERVER_ID = "__research__"
MEDICAL_SERVER_ID = "__medical__"
_SYNTHETIC_SERVER_IDS = frozenset({RESEARCH_SERVER_ID, MEDICAL_SERVER_ID})

def declared_family_capabilities(*families: str) -> list[dict[str, Any]]:
    """Research/medical tool descriptors resolved from the assembly REGISTRY."""
    want = {str(item).strip() for item in families if str(item).strip()} or {
        FAMILY_RESEARCH, FAMILY_MEDICAL,
    }
    out: list[dict[str, Any]] = []

    try:
        from CoScientist.assembly.bindings import REGISTRY
        family_to_registry_keys = {
            FAMILY_RESEARCH: ("websearch", "paper_analysis", "papers_search"),
            FAMILY_MEDICAL: ("medical",),
        }
        for family, keys in family_to_registry_keys.items():
            if family not in want:
                continue
            server_id = RESEARCH_SERVER_ID if family == FAMILY_RESEARCH else MEDICAL_SERVER_ID
            for key in keys:
                entry = REGISTRY.get_tool(key)
                if not entry or not entry.docs:
                    continue
                for doc in entry.docs:
                    out.append({
                        "family": family,
                        "tool": doc.name,
                        "server_id": server_id,
                        "description": doc.purpose,
                        "input_schema": {},
                        "score": None,
                        "url": None,
                    })
    except Exception as exc:
        _log.warning("Failed to load declared family tools from REGISTRY: %s", exc)

    return out


def inventory_covers_capabilities(
    by_tool: Mapping[str, Mapping[str, Any]],
    needed: Iterable[str] = (),
) -> bool:
    """True when an inventory tool covers compute capabilities."""
    if not by_tool:
        return False
    return any(row_family(item) == FAMILY_MCP for item in by_tool.values())


def filter_inventory_to_needed(
    available_tools: Iterable[Mapping[str, Any]],
    needed: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Keep compute MCP rows."""
    out: list[dict[str, Any]] = []
    for item in available_tools:
        if not isinstance(item, Mapping):
            continue
        tool = str(item.get("tool") or item.get("name") or "").strip()
        if not tool:
            continue
        if row_family(item) != FAMILY_MCP:
            continue
        if str(item.get("server_id") or "") in _SYNTHETIC_SERVER_IDS:
            continue
        out.append(dict(item))
    return out


def row_family(item: Mapping[str, Any] | None) -> str:
    if not isinstance(item, Mapping):
        return FAMILY_MCP
    family = str(item.get("family") or "").strip()
    if family in {FAMILY_MCP, FAMILY_RESEARCH, FAMILY_MEDICAL}:
        return family
    server_id = str(item.get("server_id") or "").strip()
    if server_id == RESEARCH_SERVER_ID:
        return FAMILY_RESEARCH
    if server_id == MEDICAL_SERVER_ID:
        return FAMILY_MEDICAL
    return FAMILY_MCP


def index_inventory_tools(
    available_tools: Iterable[dict[str, Any]],
    *,
    families: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map tool name → inventory row (higher retrieval score wins).

    Default families={mcp}: RAG compute tools only. Pass research/medical to
    index declared route-agent capabilities.
    """
    allow = (
        {FAMILY_MCP}
        if families is None
        else {str(item).strip() for item in families if str(item).strip()}
    )
    out: dict[str, dict[str, Any]] = {}
    for item in available_tools:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or item.get("name") or "").strip()
        server_id = str(item.get("server_id") or "").strip()
        if not tool or not server_id:
            continue
        family = row_family(item)
        if family not in allow:
            continue
        if family == FAMILY_MCP and server_id in _SYNTHETIC_SERVER_IDS:
            continue
        row = {
            "family": family,
            "tool": tool,
            "server_id": server_id,
            "description": item.get("description") or "",
            "input_schema": item.get("input_schema"),
            "score": item.get("score"),
            "url": item.get("url"),
        }
        prior = out.get(tool)
        if prior is None or float(row.get("score") or 0) > float(prior.get("score") or 0):
            out[tool] = row
    return out


def inventory_pairs(inventory: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    """Exact (server_id, tool) pairs for registry feasibility checks (MCP only)."""
    return {
        (str(item["server_id"]), str(item.get("tool") or item.get("name")))
        for item in inventory
        if isinstance(item, dict)
        and item.get("server_id")
        and (item.get("tool") or item.get("name"))
        and row_family(item) == FAMILY_MCP
        and str(item.get("server_id") or "") not in _SYNTHETIC_SERVER_IDS
    }


def inventory_nonempty(available_tools: Iterable[dict[str, Any]] | Mapping[str, Any] | None) -> bool:
    """True when this-run retrieve left at least one compute MCP (server_id, tool)."""
    if not available_tools:
        return False
    if isinstance(available_tools, Mapping):
        first = next(iter(available_tools.values()), None)
        if isinstance(first, dict) and first.get("server_id") and row_family(first) == FAMILY_MCP:
            if str(first.get("server_id") or "") not in _SYNTHETIC_SERVER_IDS:
                return True
        if isinstance(first, dict):
            return bool(index_inventory_tools(list(available_tools.values())))
        return False
    return bool(index_inventory_tools(available_tools))


def _schema_literals(spec: Any) -> set[str]:
    """String enum/const literals from one JSON Schema node (incl. anyOf/items)."""
    if not isinstance(spec, dict):
        return set()
    out: set[str] = set()
    if isinstance(spec.get("enum"), list):
        out.update(str(v).strip() for v in spec["enum"] if isinstance(v, str) and v.strip())
    const = spec.get("const")
    if isinstance(const, str) and const.strip():
        out.add(const.strip())
    items = spec.get("items")
    if isinstance(items, dict):
        out.update(_schema_literals(items))
    for key in ("anyOf", "oneOf", "allOf"):
        alts = spec.get(key)
        if isinstance(alts, list):
            for alt in alts:
                out.update(_schema_literals(alt))
    return out


def schema_property_enums(schema: Any) -> dict[str, frozenset[str]]:
    """Map property name → allowed string literals from JSON Schema enum/const."""
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        return {}
    out: dict[str, frozenset[str]] = {}
    for name, spec in props.items():
        lits = _schema_literals(spec)
        if lits:
            out[str(name)] = frozenset(lits)
    return out


def schema_property_defaults(schema: Any) -> dict[str, Any]:
    """Map property name → JSON Schema default, when the schema declares one."""
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        return {}
    out: dict[str, Any] = {}
    for name, spec in props.items():
        if isinstance(spec, dict) and "default" in spec:
            out[str(name)] = spec["default"]
    return out


def _named_match(text: str, by_tool: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not text:
        return None
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text):
        if token in by_tool:
            return by_tool[token]
    low = text.lower().replace("-", "_")
    for tool, item in by_tool.items():
        pattern = rf"(?<![\w-]){re.escape(tool.lower())}(?![\w-])"
        if re.search(pattern, low):
            return item
    return None


def match_named_inventory_tool(
    blob: str, by_tool: dict[str, dict[str, Any]], *, source_request: str = "",
) -> dict[str, Any] | None:
    """Match an inventory tool by exact name against task text or source request."""
    if not by_tool:
        return None
    task_text = (blob or "").strip()
    if task_text:
        if hit := _named_match(task_text, by_tool):
            return hit
    request = (source_request or "").strip()
    if request:
        if hit := _named_match(request, by_tool):
            return hit
    return None


def match_named_family_capability(blob: str) -> dict[str, Any] | None:
    """First research/medical tool name appearing in *task* text.

    Does not consult source_request: mixed asks mention several families, and
    per-task routing must follow this task's text, not the whole brief.
    """
    rows = declared_family_capabilities(FAMILY_RESEARCH, FAMILY_MEDICAL)
    by_tool = index_inventory_tools(
        rows, families={FAMILY_RESEARCH, FAMILY_MEDICAL},
    )
    return match_named_inventory_tool(blob, by_tool)


def get_grouped_mcp_inventory(
    rows: Iterable[Mapping[str, Any] | dict[str, Any]]
) -> list[dict[str, Any]]:
    """Group flat retrieved tool rows by (server_id, url).

    Returns:
      [{name, server_id, url, tools: [{name, description, input_schema}]}]
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, (dict, Mapping)):
            continue
        server_id = str(item.get("server_id") or "").strip()
        url = str(item.get("url") or "").strip()
        if server_id in _SYNTHETIC_SERVER_IDS or row_family(item) != FAMILY_MCP:
            continue
        tool_name = str(item.get("tool") or item.get("name") or "").strip()
        if not tool_name:
            continue

        key = (server_id, url)
        if key not in groups:
            sname = str(item.get("server_name") or item.get("name") or "").strip()
            if not sname or sname == tool_name:
                sname = server_id
            groups[key] = {
                "name": sname,
                "server_id": server_id,
                "url": url,
                "tools": [],
            }

        tools_list = groups[key]["tools"]
        if not any(t.get("name") == tool_name for t in tools_list):
            tools_list.append({
                "name": tool_name,
                "description": str(item.get("description") or "").strip(),
                "input_schema": item.get("input_schema"),
            })

    return list(groups.values())


__all__ = [
    "FAMILY_MEDICAL",
    "FAMILY_RESEARCH",
    "declared_family_capabilities",
    "filter_inventory_to_needed",
    "get_grouped_mcp_inventory",
    "index_inventory_tools",
    "inventory_covers_capabilities",
    "inventory_nonempty",
    "inventory_pairs",
    "match_named_family_capability",
    "match_named_inventory_tool",
    "schema_property_defaults",
    "schema_property_enums",
]
