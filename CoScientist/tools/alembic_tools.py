"""ADK function tools wrapping the Alembic pipeline (GitHub repo → MCP server).

Alembic (CoScientist/alembic) builds a validated FastMCP tool server from a
scientific repository inside Docker. A full build takes tens of minutes, so the
tools here are job-based: ``build_mcp_server`` launches ``start_chain.py`` as a
host-side background subprocess and returns a ``job_id``; ``check_mcp_build``
reports progress (current pipeline stage, log tail) and, once the serve
container is up, the resulting MCP endpoint URL.

Jobs are process-wide (like the coder's local job registry), so over A2A —
where every orchestrator delegation is a fresh session — a later delegation can
find and continue an earlier build via ``list_mcp_builds``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from google.adk.tools import ToolContext

# /<root>/CoScientist/tools/alembic_tools.py -> /<root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
START_CHAIN = PROJECT_ROOT / "CoScientist" / "alembic" / "start_chain.py"
# Host-side stdout logs of the build subprocesses (the pipeline's own logs live
# inside the build container; this is the start_chain wrapper output).
LOG_DIR = PROJECT_ROOT / ".alembic" / "a2a_builds"

logger = logging.getLogger(__name__)

_LOG_TAIL_LINES = 15
_MAX_JOBS = 200  # cap registry size; evict oldest finished jobs past this
# Base for the absolute, clickable build-page link handed back to the agent.
# Empty when nothing set it, and then no absolute link is offered at all: the
# page only exists while the web UI is running, and a link that does not open
# sends the agent looking for the build somewhere else on the host.
_WEB_BASE_URL = os.environ.get("COSCIENTIST_WEB_BASE_URL", "").rstrip("/")

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()

# Patterns over start_chain.py / alembic.main output.
_URL_RE = re.compile(r"url\s*:\s*(http://\S+/mcp)")
_IMAGE_RE = re.compile(r"image\s*:\s*(\S+)")
_CONTAINER_RE = re.compile(r"container\s*:\s*(\S+)")
_STAGE_RE = re.compile(r"STAGE (\d) — (\S+)")


def _repo_name(repo_url: str) -> str:
    """Last path segment of a repo URL, without a trailing ``.git``
    (same rule as alembic.common.get_repo_name, kept local so importing this
    module never touches the alembic package's top-level path setup)."""
    return re.sub(r"\.git$", "", repo_url.rstrip("/").split("/")[-1])


def _evict_finished_jobs() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    for job_id, rec in list(_JOBS.items()):
        if rec["status"] != "running":
            del _JOBS[job_id]
        if len(_JOBS) <= _MAX_JOBS:
            return


def _read_log(rec: Dict[str, Any]) -> str:
    try:
        return Path(rec["log_file"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _finalize(rec: Dict[str, Any], returncode: int) -> None:
    """Parse the finished build's log into the job record (under _LOCK)."""
    text = _read_log(rec)
    rec["returncode"] = returncode
    rec["finished_at"] = time.time()
    if returncode == 0:
        url = _URL_RE.search(text)
        image = _IMAGE_RE.search(text)
        container = _CONTAINER_RE.search(text)
        rec["status"] = "done"
        rec["mcp_url"] = url.group(1) if url else None
        rec["image"] = image.group(1) if image else None
        rec["container"] = container.group(1) if container else None
    else:
        rec["status"] = "failed"


def _runner(rec: Dict[str, Any]) -> None:
    log_path = Path(rec["log_file"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [sys.executable, str(START_CHAIN), rec["repo_url"]],
                stdout=log, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT,
            )
            with _LOCK:
                rec["pid"] = proc.pid
            returncode = proc.wait()
    except OSError as exc:  # docker/python missing, log dir unwritable, ...
        with _LOCK:
            rec["status"] = "failed"
            rec["error"] = f"could not launch the build subprocess: {exc}"
            rec["finished_at"] = time.time()
        return
    with _LOCK:
        _finalize(rec, returncode)
    # The catalogue entry is made here, when the build finishes, and not when
    # someone asks about it. An agent that starts a build and reports the job_id
    # back (which is what its prompt tells it to do) may never poll, and a tool
    # that exists but is in no catalogue is a tool the next run rebuilds from
    # scratch. Own thread, no event loop of its own, so asyncio.run is safe here.
    #
    # This thread is a daemon, so a host process that exits before the build
    # ends takes it down and nothing here runs — the build container finishes
    # regardless, but its result is lost. That is the same boundary the whole
    # job registry has (``_JOBS`` lives in memory), and it does not bite the
    # long-lived processes the system actually runs in: the web server, the A2A
    # services and the REPL all outlive their builds.
    try:
        asyncio.run(_register_in_catalogue(rec))
    except Exception as exc:  # noqa: BLE001 — the build itself succeeded
        logger.warning("catalogue registration thread failed: %s", exc)


def _snapshot(rec: Dict[str, Any], with_log_tail: bool = True) -> Dict[str, Any]:
    """The tool-facing view of one job record (call under _LOCK)."""
    out = {
        "job_id": rec["job_id"],
        "repo_url": rec["repo_url"],
        "status": rec["status"],
        "elapsed_seconds": round((rec.get("finished_at") or time.time()) - rec["started_at"]),
        # Live build page in the CoScientist web UI (tails this build's log and
        # renders the streamed pipeline events). ``progress_page`` is relative
        # and always present, since the web layer resolves it itself.
        "progress_page": f"/builds/{rec['job_id']}",
    }
    if _WEB_BASE_URL:
        out["progress_url"] = f"{_WEB_BASE_URL}/builds/{rec['job_id']}"
    text = _read_log(rec) if (with_log_tail or rec["status"] != "running") else ""
    stages = _STAGE_RE.findall(text)
    if stages:
        out["stage"] = f"{stages[-1][0]}/5 {stages[-1][1]}"
    if rec["status"] == "running":
        if with_log_tail:
            out["log_tail"] = "\n".join(text.splitlines()[-_LOG_TAIL_LINES:])
        out["note"] = ("The build is still running (a full build takes tens of "
                       "minutes). Do other work and call "
                       f"check_mcp_build('{rec['job_id']}') again later; do not "
                       "poll in a tight loop. That call is the only source of "
                       "this build's result. An MCP server found any other way "
                       "on this host belongs to some earlier build and says "
                       "nothing about this one.")
    elif rec["status"] == "done":
        out["mcp_url"] = rec.get("mcp_url")
        out["image"] = rec.get("image")
        out["container"] = rec.get("container")
        if not rec.get("mcp_url"):
            out["note"] = ("Build finished but no MCP URL was printed — the image "
                           f"{rec.get('image') or 'alembic-tool:<repo>'} was likely "
                           "built with serving skipped; check the log.")
    else:
        out["error"] = rec.get("error") or "\n".join(text.splitlines()[-_LOG_TAIL_LINES:])
    return out


async def build_mcp_server(
    repo_url: str,
    force_rebuild: bool = False,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Start an Alembic build: turn a GitHub repository into a served MCP tool
    server (clone → env → generated+validated tools → FastMCP server in Docker).

    The build runs in the background. This returns immediately with a job_id;
    track it with check_mcp_build(job_id).

    Args:
        repo_url: GitHub repository URL, e.g. "https://github.com/whitead/synspace".
        force_rebuild: Start a fresh build even if this repo already has a
            finished (or running) build in this process.

    Returns:
        status "running" with the job_id to check later; or the existing job for
        this repo (already running/done) unless force_rebuild is set.
    """
    repo_url = (repo_url or "").strip()
    if not re.match(r"^(https?://|git@)\S+/\S+", repo_url):
        return {"status": "error",
                "error": f"repo_url does not look like a git repository URL: {repo_url!r}"}

    with _LOCK:
        if not force_rebuild:
            # Prefer a live build; else the most recent finished one.
            same = [r for r in _JOBS.values() if r["repo_url"] == repo_url]
            for rec in reversed(same):
                if rec["status"] == "running":
                    snap = _snapshot(rec, with_log_tail=False)
                    snap["note"] = ("A build for this repository is already running — "
                                    f"reusing it. Track it with check_mcp_build('{rec['job_id']}').")
                    return snap
            for rec in reversed(same):
                if rec["status"] == "done":
                    snap = _snapshot(rec)
                    snap["note"] = ("This repository was already built in this process — "
                                    "reusing the result. Pass force_rebuild=true to rebuild.")
                    return snap

        job_id = f"{_repo_name(repo_url)}-{secrets.token_hex(3)}"
        rec: Dict[str, Any] = {
            "job_id": job_id,
            "repo_url": repo_url,
            "status": "running",
            "started_at": time.time(),
            "log_file": str(LOG_DIR / f"{job_id}.log"),
        }
        _evict_finished_jobs()
        _JOBS[job_id] = rec

    threading.Thread(target=_runner, args=(rec,), daemon=True,
                     name=f"alembic-build-{job_id}").start()
    return {
        "status": "running",
        "job_id": job_id,
        "repo_url": repo_url,
        "note": ("Build started (base image → pipeline → docker commit → serve). "
                 "A full build takes tens of minutes: report the job_id back, do "
                 f"other work, and call check_mcp_build('{job_id}') later. That "
                 "call is the only source of this build's result; an MCP server "
                 "found any other way on this host belongs to some earlier "
                 "build."),
    }


async def check_mcp_build(
    job_id: str, tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """Check an Alembic build started by build_mcp_server.

    Args:
        job_id: The id returned by build_mcp_server.

    Returns:
        status "running" with the current pipeline stage and a log tail;
        "done" with the served MCP endpoint (mcp_url), image and container;
        or "failed" with the error tail of the build log.
    """
    with _LOCK:
        rec = _JOBS.get(job_id)
        if rec is None:
            return {"status": "error",
                    "error": f"unknown job_id {job_id!r} — use list_mcp_builds() "
                             "to see the builds known to this process."}
        out = _snapshot(rec)
    # Outside the lock: publishing talks to the registry over the network.
    await _publish_to_catalogue(rec, out, tool_context)
    return out


async def _register_in_catalogue(rec: Dict[str, Any]) -> None:
    """Ingest a finished build's MCP server into the rag_tools registry, once.

    This is the durable half: it needs nothing from the session, so it runs the
    moment the build finishes and does not wait for an agent to ask. Called
    again from a poll it is a no-op, because the attempt is recorded on the job.

    Never raises — a registry that is down must not turn a successful build into
    a failed tool call. The outcome is kept on the record and reported back to
    the agent as ``registered``.
    """
    if rec.get("status") != "done" or not rec.get("mcp_url") or "registered" in rec:
        return
    rec["registered"] = True  # one attempt per build, however often it is polled

    from CoScientist.tools.registry_bridge import register_mcp_server

    name = _repo_name(rec["repo_url"])
    try:
        server = await register_mcp_server(
            rec["mcp_url"], name, description=f"Alembic build of {rec['repo_url']}"
        )
    except Exception as exc:  # noqa: BLE001 — the build itself succeeded
        logger.warning("catalogue registration failed for %s: %s", name, exc)
        rec["registered"] = False
        rec["registration_error"] = f"{type(exc).__name__}: {exc}"
        return

    # A server row with no tools behind it is not a registration: retrieval
    # scores tools, so nothing will ever surface it. Say so instead of
    # reporting success the agent cannot act on.
    from rag_tools.storage.models import ToolStatus

    if getattr(server, "status", None) == ToolStatus.ERROR:
        rec["registered"] = False
        rec["registration_error"] = (
            f"{name} was added to the catalogue but its tools could not be "
            "indexed, so retrieval will not find it"
        )


async def _publish_to_catalogue(
    rec: Dict[str, Any], out: Dict[str, Any], tool_context: Optional[ToolContext]
) -> None:
    """Report the catalogue outcome and make the tool callable in this run.

    By the time a poll gets here the build thread has normally registered the
    server already; the call below only covers a record that never went through
    that thread. What is left is the run-scoped half: putting the url into
    ``deployed_mcps`` so the executor can call the tool without waiting for a
    retrieval round.
    """
    if out.get("status") != "done" or not out.get("mcp_url"):
        return
    await _register_in_catalogue(rec)
    out["registered"] = rec.get("registered", False)
    if rec.get("registration_error"):
        out["registration_error"] = rec["registration_error"]

    if tool_context is not None:
        from CoScientist.tools.registry_bridge import resolve_into_state

        # ADK records a state change on assignment, so the list is rebuilt and
        # put back whole instead of being appended to in place.
        state = {"deployed_mcps": list(
            (getattr(tool_context, "state", None) or {}).get("deployed_mcps") or []
        )}
        resolve_into_state(state, out["mcp_url"], _repo_name(rec["repo_url"]))
        tool_context.state["deployed_mcps"] = state["deployed_mcps"]


async def list_mcp_builds(tool_context: Optional[ToolContext] = None) -> Dict[str, Any]:
    """List every Alembic build known to this process (running and finished).

    Use this to recover a lost job_id or to find an MCP server that was already
    built for a repository in an earlier delegation/session.

    Returns:
        builds: one summary per job (job_id, repo_url, status, stage/mcp_url).
    """
    with _LOCK:
        return {"builds": [_snapshot(rec, with_log_tail=False)
                           for rec in _JOBS.values()]}


ALEMBIC_TOOLS = [build_mcp_server, check_mcp_build, list_mcp_builds]


# ── Web dashboard support ─────────────────────────────────────────────────────
# The CoScientist web UI (CoScientist/web/app.py) renders a live build page that
# tails a build's log and forwards the ``ALEMBIC_EVENT`` lines the container
# streams. These helpers are plain (non-ADK) functions the web layer calls.
#
# A build's log lives on disk at LOG_DIR/<job_id>.log regardless of which
# process started it, so the web helpers work even when the McpBuilderAgent runs
# in a separate A2A process: the in-memory _JOBS record is authoritative when
# present, and disk is the fallback (status re-derived from the log).
_EVENT_PREFIX = "ALEMBIC_EVENT "


def _status_from_log(text: str) -> str:
    """Best-effort status for a build we only know from its on-disk log (started
    by another process, so not in this process's _JOBS)."""
    if _URL_RE.search(text) or '"status": "complete"' in text:
        return "done"
    for marker in ("pipeline failed", "Traceback (most recent call last)",
                   "failed to connect to the docker API", '"status": "failed"'):
        if marker in text:
            return "failed"
    return "running"


def web_build_log_file(job_id: str) -> Optional[Path]:
    """Path to a build's log, or None if there is no such build."""
    with _LOCK:
        rec = _JOBS.get(job_id)
    if rec is not None:
        return Path(rec["log_file"])
    p = LOG_DIR / f"{job_id}.log"
    return p if p.exists() else None


def web_build_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
    """Status/result view of one build for the web page. In-memory record wins;
    otherwise reconstruct a minimal snapshot from the on-disk log."""
    with _LOCK:
        rec = _JOBS.get(job_id)
        if rec is not None:
            return _snapshot(rec)
    log = LOG_DIR / f"{job_id}.log"
    if not log.exists():
        return None
    text = log.read_text(encoding="utf-8", errors="replace")
    status = _status_from_log(text)
    out: Dict[str, Any] = {"job_id": job_id, "status": status,
                           "progress_page": f"/builds/{job_id}"}
    if _WEB_BASE_URL:
        out["progress_url"] = f"{_WEB_BASE_URL}/builds/{job_id}"
    if status == "done":
        url = _URL_RE.search(text)
        image = _IMAGE_RE.search(text)
        container = _CONTAINER_RE.search(text)
        out["mcp_url"] = url.group(1) if url else None
        out["image"] = image.group(1) if image else None
        out["container"] = container.group(1) if container else None
    elif status == "failed":
        out["error"] = "\n".join(text.splitlines()[-_LOG_TAIL_LINES:])
    stages = _STAGE_RE.findall(text)
    if stages:
        out["stage"] = f"{stages[-1][0]}/5 {stages[-1][1]}"
    return out


def web_list_builds() -> list:
    """Every build the web UI can show: in-memory records merged with any
    on-disk logs from other processes/sessions, newest first."""
    seen: Dict[str, Dict[str, Any]] = {}
    with _LOCK:
        for rec in _JOBS.values():
            seen[rec["job_id"]] = _snapshot(rec, with_log_tail=False)
    if LOG_DIR.exists():
        for log in LOG_DIR.glob("*.log"):
            jid = log.stem
            if jid in seen:
                continue
            snap = web_build_snapshot(jid)
            if snap is not None:
                snap["mtime"] = log.stat().st_mtime
                seen[jid] = snap
    return sorted(seen.values(),
                  key=lambda s: s.get("mtime", s.get("elapsed_seconds", 0)),
                  reverse=True)


def parse_event_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one ``ALEMBIC_EVENT <json>`` log line into its event dict, or None
    if the line is not a structured event."""
    if not line.startswith(_EVENT_PREFIX):
        return None
    try:
        return json.loads(line[len(_EVENT_PREFIX):])
    except (ValueError, TypeError):
        return None


# ── Session-bundle helpers ────────────────────────────────────────────────────
# Called by session_bundle.py to snapshot / restore the in-memory job registry
# when exporting or importing a .cossession.zip archive.

_SNAPSHOT_KEYS = ("job_id", "repo_url", "status", "mcp_url", "image",
                  "container", "started_at", "finished_at", "log_file")


def export_jobs_snapshot() -> list:
    """Serialisable snapshot of every job in the process-wide registry."""
    with _LOCK:
        return [{k: rec.get(k) for k in _SNAPSHOT_KEYS} for rec in _JOBS.values()]


def import_jobs_snapshot(jobs: list) -> None:
    """Restore job records from a previously exported snapshot.

    * ``running`` → ``failed`` (the original process is gone).
    * ``log_file`` is repointed to this process's LOG_DIR.
    * Existing records with the same job_id are NOT overwritten.
    """
    with _LOCK:
        for rec in jobs:
            jid = rec.get("job_id")
            if not jid or jid in _JOBS:
                continue
            entry = dict(rec)
            if entry.get("status") == "running":
                entry["status"] = "failed"
                entry["error"] = "Build was running when the session was exported."
                entry.setdefault("finished_at", entry.get("started_at"))
            entry["log_file"] = str(LOG_DIR / f"{jid}.log")
            _JOBS[jid] = entry


__all__ = ["ALEMBIC_TOOLS", "build_mcp_server", "check_mcp_build", "list_mcp_builds",
           "web_build_log_file", "web_build_snapshot", "web_list_builds",
           "parse_event_line", "export_jobs_snapshot", "import_jobs_snapshot",
           "LOG_DIR"]
