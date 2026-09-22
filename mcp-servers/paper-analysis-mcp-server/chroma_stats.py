"""Paper-level statistics over the ChromaDB collection of paper chunks.

The collection holds one row per chunk, not per paper. A single paper
contributes body chunks, image-description chunks and (from an older pipeline)
summary chunks. Every row carries ``article_id``, ``paper_title``, ``domain``
and ``field`` in its metadata, so paper-level statistics are an aggregation
over chunk metadata: unique ``article_id`` values, each counted once.

Summary chunks are outdated and are excluded. A paper that has nothing but
summary chunks is therefore not counted at all, which is the intended
behaviour - it is not part of the current index.

Reading every chunk's metadata takes time that grows with the collection, so
the MCP tool never scans on request. ``PaperStatisticsCache`` keeps the result
in memory and refreshes it from a background thread: a full scan at startup,
then a cheap ``count()`` every few minutes, with a rescan only when the count
changes or the result gets old. The tool answers from memory, instantly.

Nothing here opens a connection. The caller passes the server's own
``ChromaVectorStore`` - the one the retrieval tools already use - and this
module only reads from it, through ``iter_metadata`` and ``collection.count()``.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, Iterator, Sequence

if TYPE_CHECKING:
    from CoScientist.papers_processing_refactoring.storage.vector import ChromaVectorStore

logger = logging.getLogger(__name__)

# Chunk roles that carry no current paper content (see ChunkRole in
# CoScientist/papers_processing_refactoring/domain/entities.py).
EXCLUDED_ROLES: tuple[str, ...] = ("summary",)

# Rows per request during a scan. Metadata only, so a page stays a few MB.
DEFAULT_PAGE_SIZE = 5000
# Until a first result exists, a failed scan is retried sooner than the
# regular check, so a database that is briefly down at startup costs a minute.
RETRY_WITHOUT_RESULT_SECONDS = 60
UNKNOWN = "unknown"


@dataclass(frozen=True)
class PaperStatistics:
    """Aggregated state of the paper collection."""

    collection: str
    location: str
    total_papers: int
    domains: Counter
    fields: Counter
    # Keyed by (domain, field), for the per-domain breakdown.
    domain_fields: Counter
    total_chunks: int
    counted_chunks: int
    skipped_chunks: int


def aggregate_paper_statistics(
    metadatas: Iterable[dict],
    collection: str = "",
    location: str = "",
    excluded_roles: Sequence[str] = EXCLUDED_ROLES,
) -> PaperStatistics:
    """Aggregate chunk metadata into paper statistics.

    Roles are filtered here rather than through a Chroma ``where`` clause: a
    ``$nin`` filter also drops rows that carry no ``role`` key at all, which
    would silently undercount papers written by an older pipeline version.
    """
    excluded = {role.casefold() for role in excluded_roles}

    # A paper's chunks should all agree on domain and field; counting per paper
    # and taking the majority keeps one mislabelled chunk from moving a paper.
    domains_per_paper: dict[str, Counter] = {}
    fields_per_paper: dict[str, Counter] = {}

    total_chunks = 0
    counted_chunks = 0

    for metadata in metadatas:
        total_chunks += 1
        metadata = metadata or {}

        if str(metadata.get("role", "")).casefold() in excluded:
            continue

        article_id = metadata.get("article_id")
        if not article_id:
            continue

        article_id = str(article_id)
        counted_chunks += 1
        domains_per_paper.setdefault(article_id, Counter())[
            str(metadata.get("domain") or UNKNOWN)
        ] += 1
        fields_per_paper.setdefault(article_id, Counter())[
            str(metadata.get("field") or UNKNOWN)
        ] += 1

    # One resolved (domain, field) pair per paper - every distribution below is
    # a view over these pairs, so all of them share the same denominator.
    paper_pairs = [
        (
            domains_per_paper[article_id].most_common(1)[0][0],
            fields_per_paper[article_id].most_common(1)[0][0],
        )
        for article_id in domains_per_paper
    ]

    return PaperStatistics(
        collection=collection,
        location=location,
        total_papers=len(paper_pairs),
        domains=Counter(domain for domain, _ in paper_pairs),
        fields=Counter(field for _, field in paper_pairs),
        domain_fields=Counter(paper_pairs),
        total_chunks=total_chunks,
        counted_chunks=counted_chunks,
        skipped_chunks=total_chunks - counted_chunks,
    )


class _ScanStopped(Exception):
    """Raised inside a scan when the cache is shutting down."""


class PaperStatisticsCache:
    """Paper statistics kept current by one background thread.

    ``start()`` launches the thread (idempotent). The thread scans the whole
    collection once, then every ``check_interval_minutes`` compares
    ``collection.count()`` with the chunk count of the last scan and rescans
    when they differ - or when the last result is older than ``max_age_hours``,
    which catches changes that keep the count, such as a paper re-ingested
    with a different field. ``report()`` never touches the database; it
    formats whatever the thread produced last.
    """

    def __init__(
        self,
        store: "ChromaVectorStore",
        location: str = "",
        check_interval_minutes: float = 10,
        max_age_hours: float = 24,
        page_size: int = DEFAULT_PAGE_SIZE,
        excluded_roles: Sequence[str] = EXCLUDED_ROLES,
    ):
        if check_interval_minutes <= 0 or max_age_hours <= 0:
            raise ValueError("check_interval_minutes and max_age_hours must be positive")
        self._store = store
        self._location = location
        self._check_interval = check_interval_minutes * 60
        self._max_age = max_age_hours * 3600
        self._page_size = page_size
        self._excluded_roles = tuple(excluded_roles)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopped = False

        # Guarded by _lock, except _scan_rows: only the thread writes it, and
        # a slightly stale value in a progress message is harmless.
        self._stats: PaperStatistics | None = None
        self._computed_at: datetime | None = None
        self._computed_mono = 0.0
        self._scan_started_at: datetime | None = None  # None: no scan running
        self._scan_started_mono = 0.0
        self._scan_total: int | None = None
        self._scan_rows = 0
        self._error: str | None = None
        self._error_at: datetime | None = None

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background thread, once. A stopped cache stays stopped."""
        with self._lock:
            if self._stopped or self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run, name="paper-statistics", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Ask the thread to stop and wait briefly.

        A request already sent to Chroma cannot be interrupted, so this does
        not wait for it; the thread is a daemon and cannot keep the process
        alive.
        """
        with self._lock:
            self._stopped = True
            thread = self._thread
        self._stop_event.set()
        if thread is not None:
            thread.join(timeout)

    # ── background thread ───────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._needs_scan():
                    self._scan()  # clears the error when it succeeds
                else:
                    # The check reached the database and found nothing new, so
                    # an earlier failure is over.
                    with self._lock:
                        self._error = None
                        self._error_at = None
            except _ScanStopped:
                return
            except Exception as e:
                logger.exception("Paper statistics refresh failed")
                with self._lock:
                    self._error = f"{type(e).__name__}: {e}"
                    self._error_at = _now()
                    self._scan_started_at = None
            with self._lock:
                has_result = self._stats is not None
            delay = self._check_interval
            if not has_result:
                delay = min(delay, RETRY_WITHOUT_RESULT_SECONDS)
            self._stop_event.wait(delay)

    def _needs_scan(self) -> bool:
        with self._lock:
            stats, computed_mono = self._stats, self._computed_mono
        if stats is None:
            return True
        if time.monotonic() - computed_mono >= self._max_age:
            return True
        return self._store.collection.count() != stats.total_chunks

    def _scan(self) -> None:
        total = self._store.collection.count()
        with self._lock:
            self._scan_started_at = _now()
            self._scan_started_mono = time.monotonic()
            self._scan_total = total
            self._scan_rows = 0
        logger.info("Paper statistics: scanning %d chunks", total)

        stats = aggregate_paper_statistics(
            self._counted(self._store.iter_metadata(self._page_size)),
            collection=self._store.collection.name,
            location=self._location,
            excluded_roles=self._excluded_roles,
        )

        with self._lock:
            took = time.monotonic() - self._scan_started_mono
            self._stats = stats
            self._computed_at = _now()
            self._computed_mono = time.monotonic()
            self._scan_started_at = None
            self._error = None
            self._error_at = None
        logger.info(
            "Paper statistics: %d papers from %d chunks, scanned in %.1fs",
            stats.total_papers,
            stats.total_chunks,
            took,
        )

    def _counted(self, metadatas: Iterable[dict]) -> Iterator[dict]:
        for metadata in metadatas:
            if self._stop_event.is_set():
                raise _ScanStopped
            self._scan_rows += 1
            yield metadata

    # ── reading ─────────────────────────────────────────────────────────────

    def report(self) -> str:
        """The current statistics as the tool's plain-text answer. Instant."""
        self.start()  # normally already running, started with the server
        with self._lock:
            stats = self._stats
            computed_at, computed_mono = self._computed_at, self._computed_mono
            scan_started_at = self._scan_started_at
            scan_mono, scan_total = self._scan_started_mono, self._scan_total
            error, error_at = self._error, self._error_at
        scan_rows = self._scan_rows
        now_mono = time.monotonic()

        progress = None
        if scan_started_at is not None:
            progress = _progress(
                scan_started_at, now_mono - scan_mono, scan_rows, scan_total
            )

        if stats is None:
            if progress:
                return (
                    "The paper database statistics are still being computed "
                    f"({progress}). Try again in a few minutes."
                )
            if error:
                return (
                    "Could not compute the paper database statistics. The last "
                    f"attempt at {_clock(error_at)} failed: {error}. "
                    "Retrying automatically."
                )
            return (
                "The paper database statistics are being prepared. "
                "Try again in a few minutes."
            )

        notes = [
            f"Computed {_clock(computed_at)} ({_ago(now_mono - computed_mono)}); "
            "refreshed automatically when the collection changes."
        ]
        if progress:
            notes.append(
                f"A refresh is running ({progress}); "
                "these numbers are from the previous scan."
            )
        if error:
            notes.append(
                f"The last refresh failed at {_clock(error_at)} ({error}); "
                "these numbers are from the previous scan."
            )
        return format_paper_statistics(stats, notes)


# ── formatting ───────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now().astimezone()


def _clock(moment: datetime | None) -> str:
    return moment.strftime("%Y-%m-%d %H:%M %Z") if moment else "an unknown time"


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute ago"
    if minutes < 60:
        return f"{minutes} min ago"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min ago"


def _progress(started_at: datetime, elapsed: float, rows: int, total: int | None) -> str:
    parts = [f"started {_clock(started_at)}"]
    parts.append(f"{rows:,} of {total:,} chunks read" if total else f"{rows:,} chunks read")
    if rows and total and rows < total:
        left = (total - rows) * elapsed / rows
        parts.append(
            "less than a minute left" if left < 60 else f"about {math.ceil(left / 60)} min left"
        )
    return ", ".join(parts)


def _papers(count: int) -> str:
    return f"{count:,} paper" if count == 1 else f"{count:,} papers"


def _format_distribution(
    counter: Counter, total: int, width: int | None = None
) -> list[str]:
    width = width or max(len(name) for name in counter)
    rows = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [
        f"  {name:<{width}}  {count:>5}  {count / total * 100:5.1f}%"
        for name, count in rows
    ]


def _format_fields_by_domain(stats: PaperStatistics) -> list[str]:
    """One block per domain, listing its fields as a share of that domain."""
    fields_of: dict[str, Counter] = {}
    for (domain, field), count in stats.domain_fields.items():
        fields_of.setdefault(domain, Counter())[field] = count

    # One width across every block, so the field columns line up throughout.
    width = max(len(field) for _, field in stats.domain_fields)

    lines: list[str] = []
    for domain, domain_total in stats.domains.most_common():
        lines.append(f"  {domain} - {_papers(domain_total)}")
        lines += [
            f"  {row}"
            for row in _format_distribution(fields_of[domain], domain_total, width)
        ]
    return lines


def format_paper_statistics(stats: PaperStatistics, notes: Sequence[str] = ()) -> str:
    """Render the statistics as the plain-text report the MCP tool returns.

    ``notes`` go right under the header line: freshness, a running refresh,
    a failed one.
    """
    where = f" at {stats.location}" if stats.location else ""
    lines = [
        f"Scientific paper database: collection '{stats.collection}'{where}",
        *notes,
        "",
    ]

    if not stats.total_papers:
        lines.append(
            f"No papers found. Scanned {stats.total_chunks:,} chunks, "
            f"none of them usable (outdated summary chunks are ignored)."
        )
        return "\n".join(lines)

    lines += [
        f"Unique papers: {stats.total_papers:,}",
        f"Chunks: {stats.total_chunks:,} in the collection, "
        f"{stats.counted_chunks:,} counted, "
        f"{stats.skipped_chunks:,} ignored (outdated summaries and rows without article_id)",
        "",
        f"Domains ({_papers(stats.total_papers)} = 100%):",
        *_format_distribution(stats.domains, stats.total_papers),
        "",
        f"Fields ({_papers(stats.total_papers)} = 100%):",
        *_format_distribution(stats.fields, stats.total_papers),
        "",
        "Fields within each domain (% of that domain's papers):",
        *_format_fields_by_domain(stats),
    ]
    return "\n".join(lines)
