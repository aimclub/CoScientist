"""Task data in and out of the OpenHands sandbox.

With ``CODER__MODE=openhands`` the CoderAgent does its work in the OpenHands
sandbox service — a separate machine whose ``/workspace`` the harness cannot
see. The system already has a door for data: the session's ``dataset_url``, a
link to a .zip that the coder hands to ``run_sandbox_task`` and the sandbox
unpacks into ``/workspace``. The harness uses that door unchanged:

* in:  the task inputs, laid out as in the task container (``app/data/…``),
       zipped, put in the CoScientist S3 bucket, presigned, and set as the
       session's ``dataset_url`` — so ``/app/data/x`` arrives as
       ``/workspace/app/data/x``;
* out: after the run, the graded paths are downloaded from the sandbox's
       ``/workspace`` (``GET /api/v1/files/download``) into the trial's local
       mirror, and graded from there as in every other mode. Containers stay
       readable for their cooldown (2 h by default) after their last task.

Only the sandbox HTTP API and S3 are touched here; nothing in this module
imports the agent stack.
"""
from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx

from .tasks import Task

SANDBOX_WORKSPACE = "/workspace"
_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "site-packages", ".cache"}
# Tool results sit in the traces as JSON inside JSON, so quotes may be escaped.
_ID_RE = re.compile(r'\\?"sandbox_id\\?"\s*:\s*\\?"([A-Za-z0-9_.-]+)|[?&]task_id=([A-Za-z0-9_-]+)')


def _settings():
    from CoScientist.config import get_settings

    return get_settings()


def coder_mode() -> str:
    """The coder backend this deployment is configured for (``.env``)."""
    return _settings().web.coder_mode


def sandbox_api() -> str:
    url = (_settings().web.sandbox_url or "").rstrip("/")
    if not url:
        raise RuntimeError("CODER__MODE=openhands but SANDBOX_URL is not set")
    return url if url.endswith("/api/v1") else url + "/api/v1"


# ── in ───────────────────────────────────────────────────────────────────────
def inputs_zip(task: Task, staged: Path) -> bytes:
    """The staged inputs (container layout) as a zip, plus empty output dirs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(p for p in staged.rglob("*") if p.is_file()):
            zf.write(f, f.relative_to(staged).as_posix())
        for d in task.precreated_dirs():
            zf.writestr(d.strip("/") + "/", b"")
    return buf.getvalue()


def publish_inputs(data: bytes, run_id: str, ttl_seconds: int) -> dict[str, str]:
    """Put the archive in the CoScientist bucket; returns bucket, key and GET link.

    Same storage helpers the web UI's sandbox-dataset upload uses. The key is
    opaque on purpose: the link is visible to the agents, and a key naming the
    benchmark and task would tell them where to look for answers.
    """
    import tempfile

    from CoScientist.reporting.s3_upload import presign_ref, upload_and_ref

    prefix = f"benchmark-inputs/{re.sub(r'[^A-Za-z0-9_-]', '', run_id)[-24:]}/{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "inputs.zip"
        path.write_bytes(data)
        ref = upload_and_ref(path, prefix)
    if ref is None:
        raise RuntimeError("S3 upload failed or S3 is not configured (S3__* in .env)")
    url = presign_ref(*ref, min(max(ttl_seconds, 3600), 7 * 24 * 3600))
    if not url:
        raise RuntimeError("could not presign the inputs archive")
    return {"bucket": ref[0], "key": ref[1], "url": url}


# ── out ──────────────────────────────────────────────────────────────────────
def sandbox_ids(trial: Path, known: list[str] | None = None) -> list[str]:
    """Sandboxes the session used, oldest first (the last one is the bound one).

    From the session state the worker saved, and from every tool result in the
    trace that names one (``run_sandbox_task``/``check_sandbox_task`` results,
    watch links).
    """
    ids: list[str] = []
    for name in ("trace/events.jsonl", "trace/ws_events.jsonl"):
        p = trial / name
        if p.is_file():
            for m in _ID_RE.finditer(p.read_text(encoding="utf-8", errors="replace")):
                sid = m.group(1) or m.group(2)
                if sid not in ids:
                    ids.append(sid)
    for sid in known or []:
        if sid in ids:
            ids.remove(sid)
        ids.append(sid)
    return ids


def _download(api: str, sid: str, path: str, timeout: float = 300) -> bytes | None:
    with httpx.stream("GET", f"{api}/files/download", params={"path": path, "task_id": sid},
                      timeout=timeout) as r:
        if r.status_code != 200:
            return None
        return r.read()


def fetch_outputs(task: Task, trial: Path, ids: list[str]) -> list[dict[str, Any]]:
    """Graded paths from the sandbox into ``trial/workspace``; newest sandbox wins."""
    api = sandbox_api()
    ws = trial / "workspace"
    given = {i["target"] for i in task.inputs()}
    fetched = []
    for out in task.outputs():
        if out["path"] in given:
            continue  # an input re-shipped to the verifier; the local copy is it
        rel = out["path"].strip("/")
        rec: dict[str, Any] = {"path": out["path"], "sandbox_id": None}
        for sid in reversed(ids):
            try:
                data = _download(api, sid, f"{SANDBOX_WORKSPACE}/{rel}")
            except httpx.HTTPError as exc:
                rec["error"] = f"{sid}: {exc}"
                continue
            if data is None:
                continue
            dest = ws / rel
            if out["kind"] == "dir":
                dest.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    zf.extractall(dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            rec.update(sandbox_id=sid, bytes=len(data))
            break
        fetched.append(rec)
    return fetched


def list_workspace(sid: str, max_entries: int = 3000, max_depth: int = 6) -> list[dict]:
    """The sandbox ``/workspace`` tree (names, sizes), skipping environments."""
    api = sandbox_api()
    out: list[dict] = []
    queue = [(SANDBOX_WORKSPACE, 0)]
    while queue and len(out) < max_entries:
        path, depth = queue.pop(0)
        try:
            r = httpx.get(f"{api}/files", params={"path": path, "task_id": sid}, timeout=30)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        for e in r.json().get("entries", []):
            full = e.get("path") or f"{path.rstrip('/')}/{e.get('name')}"
            out.append({**e, "path": full})
            is_dir = str(e.get("type", "")).lower() in ("dir", "directory", "folder")
            if is_dir and depth < max_depth and e.get("name") not in _SKIP_DIRS:
                queue.append((full, depth + 1))
    return out


def save_records(trial: Path, ids: list[str], max_trajectory_mb: int = 200) -> dict[str, Any]:
    """Per sandbox: workspace listing, the sandbox agent's trajectory, metrics."""
    api = sandbox_api()
    summary: dict[str, Any] = {}
    for sid in ids:
        d = trial / "trace" / "sandbox" / sid
        d.mkdir(parents=True, exist_ok=True)
        rec: dict[str, Any] = {}
        try:
            listing = list_workspace(sid)
            (d / "workspace_files.json").write_text(json.dumps(listing, indent=2))
            rec["files"] = len(listing)
        except Exception as exc:  # noqa: BLE001 — records are extras
            rec["files_error"] = str(exc)
        for name, path in (("metrics.json", "/metrics"), ("status.json", "/status")):
            try:
                r = httpx.get(f"{api}{path}", params={"task_id": sid}, timeout=30)
                if r.status_code == 200:
                    (d / name).write_text(json.dumps(r.json(), indent=2))
            except httpx.HTTPError:
                pass
        try:
            cap = max_trajectory_mb << 20
            with httpx.stream("GET", f"{api}/trajectory", params={"task_id": sid}, timeout=300) as r, \
                    (d / "trajectory.json").open("wb") as fh:
                if r.status_code == 200:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
                        if fh.tell() > cap:
                            rec["trajectory_truncated"] = True
                            break
            rec["trajectory_bytes"] = (d / "trajectory.json").stat().st_size
        except httpx.HTTPError as exc:
            rec["trajectory_error"] = str(exc)
        summary[sid] = rec
    return summary
