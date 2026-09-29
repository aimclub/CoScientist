"""Short, grounded labels for research-graph cards and slides.

Agents may provide a purpose-written ``short_description`` when committing a
node. Older records get a bounded extract from their own fields; this fallback
does not call a model or invent facts while the graph is being polled.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


def short_description(kind: str, attrs: Mapping[str, Any], fallback: str = "",
                      limit: int = 170) -> str:
    authored = attrs.get("short_description")
    if isinstance(authored, str) and authored.strip():
        source = authored
    elif kind == "ResearchQuestion" and attrs.get("domain"):
        source = str(attrs["domain"]).replace(";", ",")
    else:
        source = fallback
    source = re.sub(r"\s+", " ", str(source or "")).strip()
    if not source:
        return ""
    # A user's long instruction often starts with process constraints; keep the
    # research topic when the question has no shorter structured field.
    if kind == "ResearchQuestion" and "Тема:" in source:
        source = source.split("Тема:", 1)[1].strip()
    if kind == "Hypothesis" and len(source) > limit:
        # For older records without an authored short_description, a numeric
        # target is usually followed by the baseline and caveats. The core
        # claim before that target is a complete, readable card description;
        # the exact thresholds remain intact in the detail panel.
        target = re.search(r"\b(?:минимум|не менее|относительно|at least|compared to)\b",
                           source, flags=re.IGNORECASE)
        if target and 80 <= target.start() <= limit:
            source = source[:target.start()].rstrip(" ,;:—-") + "."
    sentences = re.split(r"(?<=[.!?])\s+", source)
    source = " ".join(sentences[:2]).strip()
    if len(source) <= limit:
        return source
    # Prefer a finished thought over a mid-sentence ellipsis when the source
    # offers a usable first sentence or semicolon-delimited clause.
    first = sentences[0].strip()
    if 80 <= len(first) <= limit:
        return first
    clause = source.split(";", 1)[0].strip(" ,;:—-")
    if 80 <= len(clause) <= limit:
        return clause if clause.endswith((".", "!", "?")) else clause + "."
    prefix = source[:limit]
    boundary = max(prefix.rfind(", "), prefix.rfind("; "), prefix.rfind(" "))
    if boundary >= limit // 2:
        prefix = prefix[:boundary]
    return prefix.rstrip(" ,;:—-") + "…"
