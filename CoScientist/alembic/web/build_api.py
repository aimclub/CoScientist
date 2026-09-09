"""Shared FastAPI router for the MCP-build dashboard.

Serves per-job artifact reads + a live WebSocket that tails the build log and
forwards structured ``ALEMBIC_EVENT`` lines. Mounted by both the standalone
alembic dashboard (``CoScientist.alembic.web.app``) and the main CoScientist web
UI (``CoScientist.web.app``) so the "MCP Builds" tab is byte-identical across
both entry points.
"""
from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from CoScientist.alembic.web import artifacts
from CoScientist.tools import alembic_tools


router = APIRouter()


def _running_containers() -> set[str]:
    """Names of currently running docker containers (empty set on any failure —
    docker missing, daemon down, permission denied). Used only to annotate the
    builds list, so failure just leaves builds marked "unknown"."""
    if not shutil.which("docker"):
        return set()
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    return {n.strip() for n in out.stdout.splitlines() if n.strip()}


def _annotate_container_status(builds: list) -> list:
    """Add ``container_active`` (bool|None) to each build snapshot: True if the
    build's container name is in ``docker ps``, False if it isn't, None when
    docker itself is unreachable or the build has no container yet."""
    running = _running_containers()
    docker_ok = bool(shutil.which("docker"))
    for b in builds:
        name = b.get("container")
        if not name:
            b["container_active"] = None
        elif not docker_ok:
            b["container_active"] = None
        else:
            b["container_active"] = name in running
    return builds


# ── list + snapshot ────────────────────────────────────────────────────────
@router.get("/api/builds")
async def api_builds():
    builds = await asyncio.to_thread(alembic_tools.web_list_builds)
    return JSONResponse({"builds": _annotate_container_status(builds)})


@router.post("/api/builds")
async def api_start_build(payload: dict):
    """Kick off a fresh alembic pipeline for ``repo_url``. Delegates to the
    same daemon-subprocess launcher the agent flow uses, so the build is fully
    detached from this HTTP request: closing the browser, refreshing, or
    navigating elsewhere never touches the running pipeline."""
    repo_url = (payload.get("repo_url") or "").strip()
    force = bool(payload.get("force_rebuild"))
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url is required")
    return JSONResponse(
        await alembic_tools.build_mcp_server(repo_url, force_rebuild=force)
    )


def _resolve(job_id: str) -> tuple[dict, Path, str]:
    """(snapshot, workdir, repo_url) for a job, else raise 404. Also 404 when
    the job exists but has no persisted workdir (legacy build)."""
    snap = alembic_tools.web_build_snapshot(job_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"unknown build {job_id!r}")
    workdir = alembic_tools.web_build_workdir(job_id)
    repo_url = snap.get("repo_url") or alembic_tools.web_build_repo_url(job_id)
    if workdir is None or not repo_url:
        raise HTTPException(status_code=404,
                            detail="build has no persisted artifacts (legacy build)")
    return snap, workdir, repo_url


@router.get("/api/builds/{job_id}")
async def api_build(job_id: str):
    snap = alembic_tools.web_build_snapshot(job_id)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"unknown build {job_id!r}")
    _annotate_container_status([snap])
    return JSONResponse(snap)


# ── per-job artifact reads ─────────────────────────────────────────────────
@router.get("/api/builds/{job_id}/report")
async def api_report(job_id: str):
    _, workdir, repo_url = _resolve(job_id)
    r = artifacts.build_report(workdir, repo_url)
    return JSONResponse(r or {})


@router.get("/api/builds/{job_id}/tools")
async def api_tools(job_id: str):
    _, workdir, repo_url = _resolve(job_id)
    return JSONResponse(artifacts.build_tools(workdir, repo_url))


@router.get("/api/builds/{job_id}/examples")
async def api_examples(job_id: str):
    _, workdir, repo_url = _resolve(job_id)
    return JSONResponse(artifacts.build_examples(workdir, repo_url))


@router.get("/api/builds/{job_id}/files")
async def api_files(job_id: str):
    _, workdir, repo_url = _resolve(job_id)
    return JSONResponse({"files": artifacts.build_files(workdir, repo_url)})


@router.get("/api/builds/{job_id}/setup", response_class=PlainTextResponse)
async def api_setup(job_id: str):
    _, workdir, repo_url = _resolve(job_id)
    return PlainTextResponse(artifacts.build_setup(workdir, repo_url) or "")


@router.get("/api/builds/{job_id}/checks")
async def api_checks(job_id: str):
    _, workdir, repo_url = _resolve(job_id)
    return JSONResponse({"checks": artifacts.build_checks(workdir, repo_url)})


@router.get("/builds/{job_id}/artifacts.zip")
async def api_bundle(job_id: str):
    _, workdir, repo_url = _resolve(job_id)
    data = await asyncio.to_thread(artifacts.bundle_zip, workdir, repo_url)
    if data is None:
        raise HTTPException(status_code=404, detail="no built server for this build")
    name = artifacts._repo_name(repo_url)
    return StreamingResponse(
        io.BytesIO(data), media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="{name}-mcp-bundle.zip"'})


# ── live WebSocket: tail log + hydrate derived events ──────────────────────
async def _hydrate(ws: WebSocket, workdir: Path, repo_url: str) -> None:
    """Push the full set of derived panel events from on-disk state (safe to
    call at any time — the frontend treats each as an idempotent replace)."""
    report = artifacts.build_report(workdir, repo_url)
    if report:
        await ws.send_json({"type": "report", "report": "exploration", **report})
    await ws.send_json({"type": "server", **artifacts.build_tools(workdir, repo_url)})
    await ws.send_json({"type": "examples", **artifacts.build_examples(workdir, repo_url)})
    setup = artifacts.build_setup(workdir, repo_url)
    if setup is not None:
        await ws.send_json({"type": "setup", "content": setup})
    await ws.send_json({"type": "files", "files": artifacts.build_files(workdir, repo_url)})
    for chk in artifacts.build_checks(workdir, repo_url):
        await ws.send_json({"type": "check", **chk})


@router.websocket("/builds/ws/{job_id}")
async def build_ws(ws: WebSocket, job_id: str):
    await ws.accept()
    log_file = alembic_tools.web_build_log_file(job_id)
    if log_file is None:
        await ws.send_json({"type": "error", "message": f"unknown build {job_id}"})
        await ws.close()
        return

    snap = alembic_tools.web_build_snapshot(job_id) or {}
    workdir = alembic_tools.web_build_workdir(job_id)
    repo_url = snap.get("repo_url") or alembic_tools.web_build_repo_url(job_id)

    await ws.send_json({"type": "snapshot", **snap})
    if workdir is not None and repo_url:
        try:
            await _hydrate(ws, workdir, repo_url)
        except Exception as exc:  # noqa: BLE001 — never break the stream
            await ws.send_json({"type": "log",
                                "line": f"[hydrate] {type(exc).__name__}: {exc}"})

    # Finished build → emit terminal + close.
    if snap.get("status") in ("done", "failed"):
        await ws.send_json({"type": "status", **snap})
        await ws.close()
        return

    pos = 0
    last_hydrate = 0.0
    try:
        while True:
            try:
                text = log_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if len(text) > pos:
                chunk = text[pos:]
                pos = len(text)
                if not chunk.endswith("\n"):
                    last_nl = chunk.rfind("\n")
                    if last_nl != -1:
                        pos -= len(chunk) - last_nl - 1
                        chunk = chunk[:last_nl + 1]
                    else:
                        pos -= len(chunk)
                        chunk = ""
                stage_progressed = False
                for line in chunk.splitlines():
                    ev = alembic_tools.parse_event_line(line)
                    if ev is not None:
                        await ws.send_json(ev)
                        if ev.get("type") == "stage" and ev.get("status") in ("done", "failed"):
                            stage_progressed = True
                    elif line.strip():
                        await ws.send_json({"type": "log", "line": line})
                # Re-hydrate whenever a stage crosses a boundary — cheap disk reads.
                loop_now = asyncio.get_event_loop().time()
                if stage_progressed and workdir is not None and repo_url \
                        and loop_now - last_hydrate > 1.0:
                    try:
                        await _hydrate(ws, workdir, repo_url)
                    except Exception:  # noqa: BLE001
                        pass
                    last_hydrate = loop_now

            snap = alembic_tools.web_build_snapshot(job_id)
            if snap and snap.get("status") in ("done", "failed"):
                if workdir is not None and repo_url:
                    try:
                        await _hydrate(ws, workdir, repo_url)
                    except Exception:  # noqa: BLE001
                        pass
                await ws.send_json({"type": "status", **snap})
                break

            await asyncio.sleep(0.6)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"[build_ws] error ({job_id}): {exc}")


__all__ = ["router"]
