"""The papers a run found, kept as records instead of prose.

``search_papers`` hands back a title, a DOI, a year and — when a copy is
reachable — an address for the PDF; ``download_papers_from_search`` hands back an
S3 pair as well. Until now the only thing kept was the S3 key
(``tool_callbacks.print_research_agent_tool_call``), so a DOI reached the
research graph as a bare string and the file, when there was one, reached
nothing at all: the evidence said `10.1021/acs.jafc.2c05393` and offered no way
to open it.

One record per paper, holding the whole citation and wherever the bytes ended
up. Three readers depend on that: the callback that mirrors the file, the
research graph (an Evidence citing a DOI is given the stored copy), and the
bibliography — ``finalize._extract_references`` has carried a TODO asking for
exactly this list.

Records are matched on the **normalized** DOI. Two sources spell the same DOI
three ways (`10.1021/X`, `doi:10.1021/X`, `https://doi.org/10.1021/x`) and a DOI
is case-insensitive by specification, so matching the raw string silently
misses. The raw spelling is kept beside it, because that is what the agent
wrote and what the reader will search for.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from CoScientist.reporting import session_files as sf

logger = logging.getLogger(__name__)

#: Session-state key. A list, not a dict: ADK state is serialized to JSON and
#: round-trips a list unchanged, and order is the order they were found in.
STATE_KEY = "paper_library"

#: What a stored paper is filed under. Kept out of the report's Files section by
#: `collect._SOURCE_KINDS` — a paper is a source, not a deliverable.
SOURCE_KIND = "paper"

#: Papers mirrored per tool call. A `limit=50` search must not turn into fifty
#: downloads inside one tool callback; the artifact quotas in `mirror._blocked`
#: are a backstop, not a pace.
MAX_PER_CALL = 8

_DOI_PREFIXES = (
    "https://doi.org/", "http://doi.org/",
    "https://dx.doi.org/", "http://dx.doi.org/",
    "doi:", "doi ",
)
_DOI_RE = re.compile(r"(10\.\d{4,9}/\S+)", re.IGNORECASE)
_SLUG_SPLIT = re.compile(r"[^0-9A-Za-z]+")
_TRAILING = ".,;:)]}>'\"" + "«»"


def normalize_doi(value: Any) -> str:
    """A DOI reduced to the one spelling everything else matches on.

    Lowercased because the specification says a DOI is case-insensitive, and
    OpenAlex, Crossref and an agent's own prose disagree about case often
    enough that matching without this loses real hits.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix):]
            break
    match = _DOI_RE.search(text)
    if not match:
        return ""
    return match.group(1).rstrip(_TRAILING).lower()


def filename_for(record: Dict[str, Any]) -> str:
    """A readable name for the stored file: the title, else the DOI, else generic.

    The store slugs and de-duplicates whatever it is given, so this only has to
    be legible — it is what the reader sees in the download and in the panel.
    """
    words = [w for w in _SLUG_SPLIT.split(str(record.get("title") or "")) if w]
    if words:
        return "-".join(words[:10]).lower()[:80] + ".pdf"
    doi = str(record.get("doi") or "")
    if doi:
        return "-".join(w for w in _SLUG_SPLIT.split(doi) if w)[:80] + ".pdf"
    return "paper.pdf"


def _key(record: Dict[str, Any]) -> str:
    """What makes two records the same paper.

    The DOI when there is one. Failing that the address the bytes came from —
    two results without a DOI and without a common address are, as far as
    anything here can tell, two papers.
    """
    return (record.get("doi")
            or str(record.get("s3_key") or "")
            or str(record.get("pdf_url") or "")
            or str(record.get("title") or "").strip().lower())


def _clean(value: Any, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def records_from_tool(tool_name: str, tool_response: Any) -> List[Dict[str, Any]]:
    """The papers one tool result is telling us about.

    Two shapes, because the papers server has two tools and they do not agree on
    field names: ``search_papers`` says ``title`` and takes the address from
    ``primary_location.pdf_url``; ``download_papers_from_search`` says
    ``paper_title`` and has already put the file in S3.
    """
    try:
        papers = ((tool_response or {}).get("metadata") or {}).get("papers") or []
    except AttributeError:
        return []
    if not isinstance(papers, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in papers:
        if not isinstance(item, dict):
            continue
        raw_doi = item.get("doi") or ""
        record = {
            "doi": normalize_doi(raw_doi),
            "doi_raw": _clean(raw_doi, 200),
            "title": _clean(item.get("paper_title") or item.get("title"), 300),
            "year": item.get("publication_year") or None,
            # OpenAlex's own answer about the licence. We store the papers it
            # points at either way, but a reader — and anyone auditing later —
            # can see which copies were openly licensed and which were not.
            "is_oa": bool(item.get("is_oa")) if "is_oa" in item else None,
            "pdf_url": _clean(item.get("pdf_url"), 2000),
            # Kept apart from `pdf_url` on purpose. The presigned link is the
            # one that actually fetches — it points at the copy the papers
            # server already made — but it expires, so it is what we download
            # from and never what we record as the paper's address.
            "presigned_url": _clean(item.get("presigned_url"), 2000),
            "bucket": _clean(item.get("bucket"), 200) or None,
            "s3_key": _clean(item.get("s3_key"), 500) or None,
            "tool": tool_name,
        }
        if not (record["doi"] or record["pdf_url"] or record["s3_key"]):
            continue
        if not record["title"]:
            record["title"] = record["doi_raw"] or record["doi"]
        out.append(record)
    return out


def library(state: Any) -> List[Dict[str, Any]]:
    """Every paper recorded so far. Never raises: state may be anything."""
    try:
        found = state.get(STATE_KEY) or []
    except Exception:  # noqa: BLE001
        return []
    return [p for p in found if isinstance(p, dict)] if isinstance(found, list) else []


def merge(state: Any, records: List[Dict[str, Any]], *,
          agent: str = "") -> List[Dict[str, Any]]:
    """Fold new records into the library and return the ones worth fetching.

    A paper already stored is not returned: re-running a search must not
    re-download what the session already holds. A paper known only by its
    citation IS returned once an address for it turns up.
    """
    existing = library(state)
    by_key = {_key(p): p for p in existing if _key(p)}
    fetch: List[Dict[str, Any]] = []
    for record in records:
        key = _key(record)
        if not key:
            continue
        known = by_key.get(key)
        if known is None:
            record = dict(record, agent=agent, at=time.time(),
                          session_artifact_id="", artifact_state="")
            existing.append(record)
            by_key[key] = record
            known = record
        else:
            # Learn the address without forgetting what we already knew: the
            # search tool knows the title and the year, the download tool knows
            # where the bytes are, and they arrive in either order.
            for field in ("doi", "doi_raw", "title", "year", "is_oa",
                          "pdf_url", "presigned_url", "bucket", "s3_key"):
                if not known.get(field) and record.get(field):
                    known[field] = record[field]
        if known.get("session_artifact_id"):
            continue
        if (known.get("presigned_url") or known.get("pdf_url")
                or (known.get("bucket") and known.get("s3_key"))):
            fetch.append(known)
    try:
        state[STATE_KEY] = existing
    except Exception:  # noqa: BLE001 — the library must never break a tool call
        logger.debug("paper_library: could not write %s to state", STATE_KEY)
    return fetch


def note_stored(state: Any, record: Dict[str, Any],
                mirror_record: Dict[str, Any]) -> None:
    """Record where a paper's bytes ended up (or why they did not)."""
    key = _key(record)
    state_word = str(mirror_record.get("state") or "")
    for paper in library(state):
        if _key(paper) != key:
            continue
        paper["artifact_state"] = state_word
        # Only a STORED record names a file. `session_files.note` mints an id
        # for a failure too — derived from the name and the reason, so the
        # record still dedupes and still has somewhere to be listed — and
        # taking that id would record a paper we do not hold as held: never
        # retried, and stamped onto Evidence as an artifact that resolves to
        # nothing.
        if state_word == sf.STATE_STORED and mirror_record.get("artifact_id"):
            paper["session_artifact_id"] = mirror_record["artifact_id"]
        if mirror_record.get("reason"):
            paper["artifact_reason"] = mirror_record["reason"]
        break


def find(state: Any, doi: Any) -> Optional[Dict[str, Any]]:
    """The recorded paper a DOI refers to, in whatever spelling it was written."""
    wanted = normalize_doi(doi)
    if not wanted:
        return None
    for paper in library(state):
        if paper.get("doi") == wanted:
            return paper
    return None


def citation(record: Dict[str, Any]) -> str:
    """One paper as a bibliography line. Plain text: the caller decides links."""
    parts = [str(record.get("title") or "").strip()]
    year = record.get("year")
    if year:
        parts.append(f"({year})")
    doi = record.get("doi_raw") or record.get("doi")
    if doi:
        normalized = normalize_doi(doi)
        parts.append(f"https://doi.org/{normalized}" if normalized else str(doi))
    return " ".join(p for p in parts if p)


def references(state: Any) -> List[str]:
    """The run's bibliography, from what it actually read.

    `finalize._extract_references` has carried a TODO for this: paper research
    kept its results as free text, so there was no citation metadata to build a
    reference list from. There is now.
    """
    out, seen = [], set()
    for paper in library(state):
        line = citation(paper)
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


__all__ = [
    "STATE_KEY", "SOURCE_KIND", "MAX_PER_CALL",
    "normalize_doi", "filename_for", "records_from_tool", "library", "merge",
    "note_stored", "find", "citation", "references",
]
