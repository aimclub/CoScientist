"""ADK function tools wrapping the Alembic pipeline (GitHub repo → MCP server).

Alembic (CoScientist/alembic) builds a validated FastMCP tool server from a
scientific repository inside Docker. A full build takes tens of minutes, so the
tools here are job-based: ``build_mcp_server`` launches ``start_chain.py`` as a
host-side background subprocess and returns a ``job_id``; ``check_mcp_build``
reports progress (current pipeline stage, log tail) and, once the serve
container is up, the resulting MCP endpoint URL.

Job metadata is atomically persisted, so over A2A — where every orchestrator
delegation may be a fresh process — a later delegation can find and continue an
earlier build via ``list_mcp_builds``.
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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional
try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback for local development
    fcntl = None  # type: ignore[assignment]

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

# /<root>/CoScientist/tools/alembic_tools.py -> /<root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
START_CHAIN = PROJECT_ROOT / "CoScientist" / "alembic" / "start_chain.py"
# Host-side stdout logs of the build subprocesses (the pipeline's own logs live
# inside the build container; this is the start_chain wrapper output).
LOG_DIR = Path(
    os.environ.get(
        "COSCIENTIST_ALEMBIC_LOG_DIR",
        str(PROJECT_ROOT / ".alembic" / "a2a_builds"),
    )
)
JOB_METADATA_DIR = Path(
    os.environ.get("COSCIENTIST_ALEMBIC_JOB_DIR", str(LOG_DIR / "jobs"))
)

logger = logging.getLogger(__name__)

_LOG_TAIL_LINES = 15
_METADATA_VERSION = 1
_RECORD_FIELDS = frozenset(
    {
        "job_id",
        "repo_url",
        "status",
        "started_at",
        "finished_at",
        "log_file",
        "pid",
        "returncode",
        "mcp_url",
        "image",
        "container",
        "error",
        "idempotency_key",
        "run_id",
        "task_id",
        "attempt_id",
    }
)
# Base for the absolute, clickable build-page link handed back to the agent.
# Empty when nothing set it, and then no absolute link is offered at all: the
# page only exists while the web UI is running, and a link that does not open
# sends the agent looking for the build somewhere else on the host.
_WEB_BASE_URL = os.environ.get("COSCIENTIST_WEB_BASE_URL", "").rstrip("/")

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()

# Patterns over start_chain.py output. Keep these tight: cloned READMEs often
# contain the words "image" / "container" and used to poison job metadata.
_URL_RE = re.compile(r"url\s*:\s*(http://\S+/mcp)")
_IMAGE_RE = re.compile(r"image\s*:\s*(alembic-tool:\S+)")
_CONTAINER_RE = re.compile(r"container\s*:\s*(alembic-serve-\S+)")
_STAGE_RE = re.compile(r"STAGE (\d) — (\S+)")
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@contextmanager
def _registry_file_lock() -> Iterator[None]:
    """Serialize read-check-create across processes sharing the registry."""
    JOB_METADATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = JOB_METADATA_DIR / ".registry.lock"
    with open(lock_path, "a+", encoding="utf-8") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _metadata_file(job_id: str) -> Path:
    return JOB_METADATA_DIR / f"{job_id}.json"


def _record_for_disk(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        key: value
        for key, value in rec.items()
        if key in _RECORD_FIELDS and value is not None
    }
    out["metadata_version"] = _METADATA_VERSION
    return out


def _persist_job(rec: Dict[str, Any]) -> None:
    """Atomically replace one job's durable JSON record."""
    JOB_METADATA_DIR.mkdir(parents=True, exist_ok=True)
    target = _metadata_file(rec["job_id"])
    temporary = JOB_METADATA_DIR / (
        f".{rec['job_id']}.{os.getpid()}.{threading.get_ident()}."
        f"{secrets.token_hex(4)}.tmp"
    )
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(
                _record_for_disk(rec),
                stream,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        try:
            directory_fd = os.open(JOB_METADATA_DIR, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _delete_job_metadata(job_id: str) -> None:
    try:
        _metadata_file(job_id).unlink()
    except FileNotFoundError:
        pass


def _valid_disk_record(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("metadata_version") == _METADATA_VERSION
        and isinstance(value.get("job_id"), str)
        and _JOB_ID_RE.fullmatch(value["job_id"]) is not None
        and isinstance(value.get("repo_url"), str)
        and isinstance(value.get("log_file"), str)
        and value.get("status") in {"running", "done", "failed"}
        and isinstance(value.get("started_at"), (int, float))
    )


def _load_jobs_from_disk(*, merge: bool = False) -> int:
    """Load valid records, skipping torn, malformed, and future-version files."""
    loaded: list[Dict[str, Any]] = []
    if JOB_METADATA_DIR.exists():
        for path in JOB_METADATA_DIR.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if not _valid_disk_record(value):
                continue
            rec = {key: value[key] for key in _RECORD_FIELDS if key in value}
            rec["_recovered"] = True
            loaded.append(rec)
    loaded.sort(key=lambda item: (item["started_at"], item["job_id"]))
    if not merge:
        _JOBS.clear()
    for rec in loaded:
        existing = _JOBS.get(rec["job_id"])
        if existing is None:
            _JOBS[rec["job_id"]] = rec
    return len(loaded)


def reload_mcp_builds() -> int:
    """Reconstruct the in-memory adapter from durable metadata.

    This is primarily useful to long-lived coordinators that replace workers.
    Normal process startup performs the same load automatically.
    """
    with _LOCK:
        return _load_jobs_from_disk()


def _repo_name(repo_url: str) -> str:
    """Last path segment of a repo URL, without a trailing ``.git``
    (same rule as alembic.common.get_repo_name, kept local so importing this
    module never touches the alembic package's top-level path setup)."""
    return re.sub(r"\.git$", "", repo_url.rstrip("/").split("/")[-1])


def _repo_identity(repo_url: str) -> str:
    return re.sub(r"\.git$", "", repo_url.strip().rstrip("/")).lower()


def _reuse_snapshot(rec: Dict[str, Any], *, idempotent: bool = False) -> Dict[str, Any]:
    snap = _snapshot(rec, with_log_tail=rec["status"] != "running")
    if idempotent:
        snap["note"] = (
            "The idempotency key already identifies this repository build — "
            f"reusing job {rec['job_id']}."
        )
    elif rec["status"] == "running":
        snap["note"] = (
            "A build for this repository is already running — reusing it. "
            f"Track it with check_mcp_build('{rec['job_id']}')."
        )
    elif rec["status"] == "done":
        snap["note"] = (
            "This repository was already built — reusing the result. "
            "Pass force_rebuild=true to rebuild."
        )
    return snap


def _first_reusable_same_repo(repo_url: str) -> Dict[str, Any] | None:
    """Prefer a live build, then the most recent successful serve for this repo.

    Caller must hold ``_LOCK``.
    """
    same = [
        value
        for value in _JOBS.values()
        if _repo_identity(value["repo_url"]) == _repo_identity(repo_url)
    ]
    for existing in same:
        _refresh_recovered_job(existing)
    for existing in reversed(same):
        if existing["status"] == "running":
            return _reuse_snapshot(existing)
    for existing in reversed(same):
        if existing["status"] == "done" and str(existing.get("mcp_url") or "").startswith("http"):
            return _reuse_snapshot(existing)
    return None


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
    if _JOBS.get(rec["job_id"]) is rec:
        try:
            _persist_job(rec)
        except OSError:
            # The terminal state remains visible in this process. A later
            # recovered snapshot can derive it from the durable log and retry.
            pass


def _pid_is_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _refresh_recovered_job(rec: Dict[str, Any]) -> None:
    """Reconcile a running record whose original watcher no longer exists."""
    if not rec.get("_recovered") or rec.get("status") != "running":
        return
    text = _read_log(rec)
    inferred = _status_from_log(text)
    if inferred == "done":
        _finalize(rec, returncode=0)
        return
    if inferred == "failed":
        _finalize(rec, returncode=1)
        return
    if _pid_is_alive(rec.get("pid")):
        return
    rec["status"] = "failed"
    rec["finished_at"] = time.time()
    rec["error"] = (
        "build process is no longer running after registry recovery; "
        "inspect the persisted log before retrying"
    )
    try:
        _persist_job(rec)
    except OSError:
        pass


def _resolve_env_file() -> Optional[Path]:
    override = os.environ.get("COSCIENTIST_ALEMBIC_ENV_FILE")
    if override:
        path = Path(override)
        return path if path.exists() else None
    for candidate in (
        PROJECT_ROOT / "CoScientist" / ".env",
        PROJECT_ROOT / ".env",
    ):
        if candidate.exists():
            return candidate
    return None


def _start_chain_env() -> Dict[str, str]:
    """Host env for start_chain, with a usable MODEL when OpenRouter is absent."""
    env = os.environ.copy()
    if not env.get("MODEL") and not env.get("OPENROUTER_API_KEY"):
        env["MODEL"] = (
            env.get("LLM__CODER_MODEL")
            or env.get("LLM__MAIN_MODEL")
            or "openai/gpt-4o-mini"
        )
    return env


def _start_chain_cmd(repo_url: str) -> list[str]:
    cmd = [sys.executable, str(START_CHAIN), repo_url]
    env_file = _resolve_env_file()
    if env_file is not None:
        cmd += ["--env-file", str(env_file)]
    return cmd


def _runner(rec: Dict[str, Any]) -> None:
    log_path = Path(rec["log_file"])
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                _start_chain_cmd(rec["repo_url"]),
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT,
                env=_start_chain_env(),
            )
            with _LOCK:
                rec["pid"] = proc.pid
                try:
                    _persist_job(rec)
                except OSError:
                    pass
            returncode = proc.wait()
    except OSError as exc:  # docker/python missing, log dir unwritable, ...
        with _LOCK:
            rec["status"] = "failed"
            rec["error"] = f"could not launch the build subprocess: {exc}"
            rec["finished_at"] = time.time()
            try:
                _persist_job(rec)
            except OSError:
                pass
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
    _refresh_recovered_job(rec)
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
    for key in ("idempotency_key", "run_id", "task_id", "attempt_id", "pid"):
        if rec.get(key) is not None:
            out[key] = rec[key]
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
    idempotency_key: Optional[str] = None,
    run_id: Optional[str] = None,
    task_id: Optional[str] = None,
    attempt_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Start an Alembic build: turn a GitHub repository into a served MCP tool
    server (clone → env → generated+validated tools → FastMCP server in Docker).

    The build runs in the background. This returns immediately with a job_id;
    track it with check_mcp_build(job_id).

    Args:
        repo_url: GitHub repository URL, e.g. "https://github.com/whitead/synspace".
        force_rebuild: Start a fresh build even if this repo already has a
            finished (or running) build in this process.
        idempotency_key: Coordinator-supplied operation key. Repeating the same
            key for the same repository always returns the original job.
        run_id: Optional experiment run associated with this build.
        task_id: Optional experiment task associated with this build.
        attempt_id: Optional task attempt associated with this build.

    Returns:
        status "running" with the job_id to check later; or the existing job for
        this repo (already running/done) unless force_rebuild is set.
    """
    repo_url = (repo_url or "").strip()
    if not re.match(r"^(https?://|git@)\S+/\S+", repo_url):
        return {"status": "error",
                "error": f"repo_url does not look like a git repository URL: {repo_url!r}"}
    idempotency_key = (idempotency_key or "").strip() or None
    associations = {
        "idempotency_key": idempotency_key,
        "run_id": (run_id or "").strip() or None,
        "task_id": (task_id or "").strip() or None,
        "attempt_id": (attempt_id or "").strip() or None,
    }

    try:
        with _LOCK:
            with _registry_file_lock():
                if idempotency_key is not None:
                    # Refresh only for coordinator-keyed requests. This makes
                    # idempotency work across worker processes while preserving
                    # the legacy process-local reuse behavior for unkeyed calls.
                    _load_jobs_from_disk(merge=True)
                    keyed = [
                        value
                        for value in _JOBS.values()
                        if value.get("idempotency_key") == idempotency_key
                    ]
                    for existing in reversed(keyed):
                        if _repo_identity(existing["repo_url"]) != _repo_identity(repo_url):
                            return {
                                "status": "error",
                                "error": (
                                    f"idempotency_key {idempotency_key!r} is already "
                                    "associated with a different repository"
                                ),
                            }
                        return _reuse_snapshot(existing, idempotent=True)
                    # New experiment run_id → new key, but the same repo may
                    # already be served. Reuse that MCP instead of a 30+ min rebuild.
                    if not force_rebuild:
                        reused = _first_reusable_same_repo(repo_url)
                        if reused is not None:
                            return reused

                if idempotency_key is None and not force_rebuild:
                    reused = _first_reusable_same_repo(repo_url)
                    if reused is not None:
                        return reused

                repo_prefix = re.sub(r"[^A-Za-z0-9._-]", "-", _repo_name(repo_url))
                job_id = f"{repo_prefix}-{secrets.token_hex(3)}"
                rec: Dict[str, Any] = {
                    "job_id": job_id,
                    "repo_url": repo_url,
                    "status": "running",
                    "started_at": time.time(),
                    "log_file": str(LOG_DIR / f"{job_id}.log"),
                    **{
                        key: value
                        for key, value in associations.items()
                        if value is not None
                    },
                }
                _JOBS[job_id] = rec
                try:
                    _persist_job(rec)
                except OSError:
                    del _JOBS[job_id]
                    raise
    except OSError as exc:
        return {
            "status": "error",
            "error": f"could not persist Alembic build metadata: {exc}",
        }

    threading.Thread(target=_runner, args=(rec,), daemon=True,
                     name=f"alembic-build-{job_id}").start()
    with _LOCK:
        result = _snapshot(rec, with_log_tail=False)
    result["note"] = (
        "Build started (base image → pipeline → docker commit → serve). "
        "A full build takes tens of minutes: report the job_id back, do "
        f"other work, and call check_mcp_build('{job_id}') later."
    )
    return result


def peek_mcp_build(job_id: str) -> Dict[str, Any]:
    """Sync snapshot of one job (no wait). Reloads durable metadata if needed."""
    with _LOCK:
        rec = _JOBS.get(job_id)
        if rec is None:
            _load_jobs_from_disk(merge=True)
            rec = _JOBS.get(job_id)
        if rec is None:
            return {
                "status": "error",
                "error": (
                    f"unknown job_id {job_id!r} — use list_mcp_builds() "
                    "to see the builds known to this registry."
                ),
            }
        _refresh_recovered_job(rec)
        return _snapshot(rec, with_log_tail=rec["status"] != "running")


def wait_mcp_build(
    job_id: str,
    *,
    timeout_s: float = 1800.0,
    poll_s: float = 5.0,
) -> Dict[str, Any]:
    """Block until a build is done/failed/error, or ``timeout_s`` elapses.

    Experiment Module uses this so the executor never records a premature
    failure while Docker is still building. Interactive McpBuilder turns
    keep the async protocol (return immediately, check later).
    """
    deadline = time.time() + max(0.0, float(timeout_s))
    poll = max(0.05, float(poll_s))
    last = peek_mcp_build(job_id)
    while last.get("status") == "running":
        if time.time() >= deadline:
            out = dict(last)
            out["wait_timed_out"] = True
            out["note"] = (
                f"Build still running after {timeout_s:.0f}s — "
                f"reuse job {job_id}; do not start a new build."
            )
            return out
        time.sleep(poll)
        last = peek_mcp_build(job_id)
    return last


def list_served_mcp_tools(mcp_url: str, timeout_s: float = 8.0) -> list[dict[str, Any]]:
    """Best-effort ``tools/list`` against a served FastMCP endpoint.

    Used after WAIT_DONE so post-build Fedot sees real tool names instead of
    the ``alembic_built_tool`` placeholder. Never raises — empty list on miss.
    """
    url = (mcp_url or "").strip()
    if not url.startswith("http"):
        return []
    timeout_s = max(1.0, float(timeout_s))

    async def _list() -> list[dict[str, Any]]:
        from mcp import ClientSession
        try:
            from mcp.client.streamable_http import streamable_http_client as _http_client
        except ImportError:  # older mcp SDK
            from mcp.client.streamable_http import streamablehttp_client as _http_client

        async with _http_client(url) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                out: list[dict[str, Any]] = []
                for tool in listed.tools or []:
                    name = str(getattr(tool, "name", "") or "").strip()
                    if not name:
                        continue
                    item: dict[str, Any] = {
                        "name": name,
                        "description": str(getattr(tool, "description", "") or "")[:500],
                    }
                    schema = getattr(tool, "inputSchema", None) or getattr(
                        tool, "input_schema", None
                    )
                    if schema:
                        item["input_schema"] = schema
                    out.append(item)
                return out

    async def _list_with_timeout() -> list[dict[str, Any]]:
        return await asyncio.wait_for(_list(), timeout=timeout_s)

    def _run_isolated() -> list[dict[str, Any]]:
        return asyncio.run(_list_with_timeout())

    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _run_isolated()
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run_isolated).result(timeout=timeout_s + 2)
    except Exception as exc:
        logger.warning("list_served_mcp_tools failed url=%s err=%s", url, exc)
        return []


def enrich_snapshot_with_tools(snap: dict[str, Any], timeout_s: float = 8.0) -> dict[str, Any]:
    """Attach ``tools`` from a live MCP when the build snapshot omitted them."""
    if not isinstance(snap, dict) or snap.get("status") != "done":
        return snap
    existing = snap.get("tools") or snap.get("mcp_tools")
    if isinstance(existing, list) and existing:
        return snap
    url = str(snap.get("mcp_url") or "").strip()
    tools = list_served_mcp_tools(url, timeout_s=timeout_s)
    if not tools:
        return snap
    out = dict(snap)
    out["tools"] = tools
    return out


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
                             "to see the builds known to this registry."}
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
    """List every durable Alembic build known to this worker.

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


try:
    _load_jobs_from_disk()
except OSError:
    # Tool import must remain available even if a mounted metadata directory is
    # temporarily unreadable. New builds fail explicitly when persistence is
    # attempted, rather than breaking unrelated agent assembly.
    pass


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
           "peek_mcp_build", "wait_mcp_build", "list_served_mcp_tools",
           "enrich_snapshot_with_tools",
           "web_build_log_file", "web_build_snapshot", "web_list_builds",
           "parse_event_line", "reload_mcp_builds",
           "export_jobs_snapshot", "import_jobs_snapshot",
           "LOG_DIR"]
