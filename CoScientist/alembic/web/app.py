"""FastAPI app: serves the dashboard and streams an alembic run over a WebSocket.

The pipeline emits low-level events (``pipeline``/``stage``/``tool_call``/
``tool_result``/``validation``) through :mod:`alembic.events`. This module
installs a per-run sink that:

  * forwards every raw event to the browser (drives the rail + activity feed),
    and
  * **enriches** each stage boundary by reading the run's on-disk artifacts —
    which, in the remaster architecture, are the authoritative source of truth
    (R2: everything is structured data on disk):
      - ``write_report`` result / explorer done  -> ``report`` (exploration map);
      - explorer/coder/validator done            -> ``server`` (tool cards, with
                                                     live pass/fail once known);
      - environment done                         -> ``setup`` (recorded setup.sh);
      - coder/wrapper done                       -> ``files`` (generated output)
                                                     + ``examples`` (per-tool
                                                     sample invocations)
                                                     + ``check`` (syntax/tests).

Manual, on-demand tool calls from the UI run through ``invoke_tool_function`` —
the same execution path the validator uses (the MCP wrap is only the final
stage), so a tool can be exercised the instant the coder has written it.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import mimetypes
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from alembic import events
from alembic.common import get_repo_name
from alembic.contract import load_plan
from alembic.main import run_pipeline
from alembic.tools.invoke import invoke_tool_function
from alembic.tools.paths import output_dir, rel_or_ignored, reports_dir, repo_path

WEB_DIR = Path(__file__).parent
TEMPLATE_PATH = WEB_DIR / "templates" / "index.html"

_MAX_FILE_CHARS = 14_000

# ---------------------------------------------------------------------------
# Inline image rendering for live invocations
# ---------------------------------------------------------------------------
# The dashboard runs in the browser and cannot read files off the host disk, so
# a tool that produces an image and returns its *path* would only show as a
# filename chip. Deterministically (no LLM), we walk a tool's result and swap
# any image file path for a base64 ``data:`` URI, which the frontend renders
# inline as <img>. This works for every tool regardless of how it was written.
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_MAX_INLINE_BYTES = 8 * 1024 * 1024   # per-image cap — keep the WS payload sane


def _img_data_uri(path: Path) -> Optional[str]:
    """Base64 ``data:`` URI for an image file, or None if missing/unreadable/
    over the inline cap."""
    try:
        if not path.is_file() or path.stat().st_size > _MAX_INLINE_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    ext = path.suffix.lower()
    mime = "image/svg+xml" if ext == ".svg" else (mimetypes.types_map.get(ext) or "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _resolve_img(s: str, base_dir: Path) -> Optional[Path]:
    """An existing image file named by ``s`` — absolute, or relative to the
    tool's output dir (its cwd) or the process cwd. Length-guarded so we never
    stat a large blob of text that merely ends in ``.png``."""
    if len(s) > 512 or Path(s).suffix.lower() not in _IMG_EXTS:
        return None
    p = Path(s)
    for cand in ((p,) if p.is_absolute() else (base_dir / p, p)):
        if cand.is_file():
            return cand
    return None


def _inline_images(obj, base_dir: Path, _depth: int = 0):
    """Recursively replace image file paths in a tool result with base64
    ``data:`` URIs. Already-inlined URIs and non-image values pass through
    unchanged; depth is bounded so a pathological structure can't spin."""
    if _depth > 6:
        return obj
    if isinstance(obj, str):
        if obj.startswith("data:image/"):
            return obj
        p = _resolve_img(obj, base_dir)
        if p is not None:
            uri = _img_data_uri(p)
            if uri is not None:
                return uri
        return obj
    if isinstance(obj, list):
        return [_inline_images(x, base_dir, _depth + 1) for x in obj]
    if isinstance(obj, dict):
        return {k: _inline_images(v, base_dir, _depth + 1) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Artifact download — a self-contained, `docker build`-able serving bundle
# ---------------------------------------------------------------------------
# The zip IS a Docker build context: the generated code + the (source-only)
# clone laid out under .alembic/<name>/, plus a generated Dockerfile + the
# serve launcher. Rebuilds both venvs from setup.sh inside the image — no LLM,
# no `docker commit`. Venvs are NOT shipped (host-specific, non-relocatable).
_ARTIFACT_INCLUDE = ("tools", "tests", "helpers", "tmbench", "server.py", "setup.sh")
_ARTIFACT_SKIP = {".venv", ".venv-server", "__pycache__"}
_DOCKER_DIR = Path(__file__).resolve().parents[3] / "docker" / "alembic"


def _bundle_dockerfile(name: str, repo_url: str) -> str:
    return f'''# Self-contained serving image for {name} — generated by alembic.
# Build & run:
#   docker build -t {name}-mcp .
#   docker run -p 8000:8000 {name}-mcp        # MCP (streamable-http) on :8000
FROM python:3.11
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 \\
    ALEMBIC_WORKDIR=/work/.alembic MCP_PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends \\
        git curl ca-certificates build-essential pkg-config \\
        libcairo2 libfontconfig1 libx11-6 libxext6 libxrender1 \\
        libgl1 libglib2.0-0 libsm6 libxcb1 \\
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /work
COPY .alembic /work/.alembic
# 1. rebuild the main venv (repo + deps + editable install) from the transcript
RUN bash /work/.alembic/{name}/output/setup.sh
# 2. isolated server venv with the MCP runtime (fastmcp/mcp)
RUN uv venv /work/.alembic/{name}/output/.venv-server --python 3.11 \\
 && uv pip install --python /work/.alembic/{name}/output/.venv-server/bin/python fastmcp mcp
COPY serve.py      /usr/local/bin/serve.py
COPY entrypoint.py /usr/local/bin/entrypoint.py
EXPOSE 8000
ENTRYPOINT ["python", "/usr/local/bin/entrypoint.py"]
CMD ["serve", "{repo_url}"]
'''


def _bundle_readme(name: str, repo_url: str) -> str:
    return (
        f"# {name} — MCP server bundle\n\n"
        f"Generated by **alembic** from `{repo_url}`. Self-contained: builds a "
        "container that serves the generated tools as a FastMCP (streamable-http) "
        "server — no LLM, no `docker commit`.\n\n"
        "## Build & run\n```\n"
        f"docker build -t {name}-mcp .\n"
        f"docker run -p 8000:8000 {name}-mcp\n```\n"
        "The MCP server listens on `http://localhost:8000`.\n\n"
        "## Layout\n"
        f"- `.alembic/{name}/output/` — generated `tools/`, `tests/`, `server.py`, `helpers/`, `setup.sh`\n"
        f"- `.alembic/{name}/repos/`  — cloned repo source (installed editable)\n"
        "- `Dockerfile` — rebuilds both venvs from `setup.sh` + a fixed fastmcp install, then serves\n"
        "- `serve.py`, `entrypoint.py` — the HTTP-serve launcher\n\n"
        "## Notes\n"
        "- Venvs are rebuilt inside the image from `setup.sh` (portable, "
        "interpreter-targeted commands) — not shipped.\n"
        "- Large model weights downloaded during the build are not bundled; if a "
        "tool needs them, ensure `setup.sh` re-downloads them.\n"
    )


def _portable_setup_sh(out: Path, repo: Path, name: str) -> str:
    """setup.sh made portable for `RUN bash setup.sh` inside the image (which
    does `cd /work`, where .alembic/<name> lives): absolute host paths (from runs
    before the record fix) are rewritten to workdir-relative, and any
    `uv pip install` that lost its `--python` is re-targeted at the main venv so
    it lands there rather than in the image's system Python."""
    txt = (out / "setup.sh").read_text(encoding="utf-8")
    txt = txt.replace(str(out.resolve()), f".alembic/{name}/output")
    txt = txt.replace(str(repo.resolve()), f".alembic/{name}/repos")
    venvpy = f".alembic/{name}/output/.venv/bin/python"
    lines = []
    for line in txt.splitlines():
        if line.lstrip().startswith("uv pip install ") and "--python" not in line:
            line = line.replace("uv pip install ", f"uv pip install --python {venvpy} ", 1)
        lines.append(line)
    return "\n".join(lines) + "\n"


def _bundle_zip(repo_url: str) -> Optional[bytes]:
    """A `docker build`-able bundle for ``repo_url``, or None if no server was
    built. Venvs excluded; clone included source-only (IGNORE-filtered)."""
    name = get_repo_name(repo_url)
    out = output_dir(repo_url)
    if not out.exists() or not (out / "server.py").exists():
        return None
    repo = repo_path(repo_url)
    prefix = f".alembic/{name}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # 1. generated build artefacts -> .alembic/<name>/output/
        for item in _ARTIFACT_INCLUDE:
            p = out / item
            if item == "setup.sh" and p.is_file():
                z.writestr(f"{prefix}/output/setup.sh", _portable_setup_sh(out, repo, name))
            elif p.is_file():
                z.write(p, f"{prefix}/output/{p.name}")
            elif p.is_dir():
                for f in p.rglob("*"):
                    rel = f.relative_to(out)
                    if f.is_file() and not any(part in _ARTIFACT_SKIP for part in rel.parts):
                        z.write(f, f"{prefix}/output/{rel}")
        # 2. the clone (source only) -> .alembic/<name>/repos/ (editable install target)
        if repo.is_dir():
            for f in repo.rglob("*"):
                if f.is_file() and rel_or_ignored(f, repo) is not None:
                    z.write(f, f"{prefix}/repos/{f.relative_to(repo)}")
        # 3. docker glue + README at the bundle root
        for fn in ("serve.py", "entrypoint.py"):
            src = _DOCKER_DIR / fn
            if src.exists():
                z.writestr(fn, src.read_text(encoding="utf-8"))
        z.writestr("Dockerfile", _bundle_dockerfile(name, repo_url))
        z.writestr("README.md", _bundle_readme(name, repo_url))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Disk readers — turn the run's on-disk state into UI-shaped payloads
# ---------------------------------------------------------------------------
def _split_sections(md: str) -> dict[str, str]:
    """Split a markdown report into ``{h2-title: body}`` on ``## `` headers.

    Text before the first ``## `` is stored under the leading ``# `` title as
    ``_title``. Robust to free-form content — no strict schema."""
    sections: dict[str, str] = {}
    current = "_intro"
    buf: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif line.startswith("# ") and current == "_intro" and not buf:
            sections["_title"] = line[2:].strip()
        else:
            buf.append(line)
    sections[current] = "\n".join(buf).strip()
    return {k: v for k, v in sections.items() if v or k == "_title"}


def _read_report(report_path: str) -> Optional[dict]:
    try:
        content = Path(report_path).read_text(encoding="utf-8")
    except OSError:
        return None
    return {"raw": content, "sections": _split_sections(content)}


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_output_files(out: Path) -> list[dict]:
    """Collect the generated artefacts (server.py + tools/helpers/tests) as
    ``{path, lang, content}`` — setup.sh is surfaced separately (how-to-run)."""
    files: list[dict] = []

    def add(p: Path, lang: str) -> None:
        if not p.is_file():
            return
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        if len(txt) > _MAX_FILE_CHARS:
            txt = txt[:_MAX_FILE_CHARS] + "\n… (truncated)"
        files.append({"path": str(p.relative_to(out)), "lang": lang, "content": txt})

    add(out / "server.py", "python")
    for sub in ("tools", "helpers", "tests"):
        d = out / sub
        if d.is_dir():
            for f in sorted(d.glob("*.py")):
                add(f, "python")
    return files


def _read_setup(out: Path) -> Optional[str]:
    p = out / "setup.sh"
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _tools_payload() -> dict:
    """The right-panel tool cards, merged from plan.json (names + real params +
    purpose) and, once the validator has run, validation.json (verdicts)."""
    plan = load_plan()
    if not plan:
        return {"tools": [], "title": ""}
    validation = _read_json(reports_dir() / "validation.json") or {}
    by_name = {t.get("name"): t for t in validation.get("tools", [])}
    tools = []
    for t in plan.tools:
        v = by_name.get(t.name, {})
        status = v.get("status")            # perfect | passed | failed | untested
        badge = {"perfect": "pass", "passed": "pass",
                 "failed": "fail"}.get(status)   # None -> pending in the UI
        tools.append({
            "name": t.name,
            "sig": ", ".join(t.params),
            "ret": "dict",
            "desc": t.purpose,
            "target": t.target,
            "status": badge,                    # pass | fail | None(pending)
            "verdict": status,                  # richer label for the card
            "exec_ok": v.get("exec_ok"),
            "invoc_passed": v.get("invoc_passed"),
            "invoc_total": v.get("invoc_total"),
            "perfect": bool(v.get("perfect")),
            "error": v.get("error") or None,
        })
    return {"tools": tools, "title": f"{plan.repo_url.rstrip('/').split('/')[-1]} · MCP server"}


def _examples_payload() -> dict:
    """Per-tool invocation examples from the plan's sample_args + evidence."""
    plan = load_plan()
    if not plan:
        return {"examples": []}
    examples = []
    for t in plan.tools:
        if t.sample_args is None:
            continue
        examples.append({"name": t.name, "args": t.sample_args,
                         "evidence": t.evidence or ""})
    return {"examples": examples}


def _syntax_check() -> Optional[dict]:
    """The coder artefact gate (G3) result → a 'syntax' check badge."""
    status = _read_json(reports_dir() / "stage_status.json") or {}
    coder = status.get("coder")
    if not coder:
        return None
    passed = coder.get("status") == "passed"
    gate = coder.get("gate", {})
    detail = "" if passed else json.dumps(gate.get("errors", gate), ensure_ascii=False)[:2000]
    return {"name": "syntax", "passed": passed, "detail": detail}


def _tests_check() -> Optional[dict]:
    """The validator counts → a 'tests' check badge."""
    validation = _read_json(reports_dir() / "validation.json")
    if not validation:
        return None
    c = validation.get("counts", {})
    tp, tt = c.get("tests_passed") or 0, c.get("tests_total") or 0
    passed = bool(tt) and tp >= tt
    detail = f"smoke tests {tp}/{tt}; tools passed {c.get('tools_passed', 0)}/{c.get('tools_total', 0)}"
    return {"name": "tests", "passed": passed, "detail": detail}


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(title="Alembic Pipeline Dashboard", version="2.0.0")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return TEMPLATE_PATH.read_text(encoding="utf-8")

    @app.get("/artifacts")
    async def artifacts(repo: str):
        """Download a self-contained, `docker build`-able MCP bundle for ``repo``."""
        data = await asyncio.to_thread(_bundle_zip, repo)
        if data is None:
            return Response("no built server for this repo yet", status_code=404)
        name = get_repo_name(repo)
        return StreamingResponse(
            io.BytesIO(data), media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}-mcp-bundle.zip"'})

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"type": "connected",
                            "timestamp": datetime.now().isoformat()})

        # active["run_id"] is bumped on every run/stop; a stale run (possibly
        # blocked in a sync subprocess asyncio can't interrupt) unwinds itself
        # the next time its sink is called and sees it is no longer current.
        active: dict = {"task": None, "run_id": 0, "repo_url": None}

        async def send(msg: dict) -> None:
            try:
                await ws.send_json(msg)
            except (RuntimeError, WebSocketDisconnect):
                pass

        # -- enrichment: raw event -> browser, plus derived panel events -------
        async def _forward(msg: dict) -> None:
            await send(msg)
            mtype = msg.get("type")

            if mtype == "tool_result" and msg.get("name") == "write_report":
                path = (msg.get("response") or {}).get("report_path")
                if path:
                    parsed = _read_report(path)
                    if parsed:
                        await send({"type": "report", "report": Path(path).stem,
                                    "stage": msg.get("stage"), **parsed})

            elif mtype == "stage" and msg.get("status") in ("done", "failed"):
                await _enrich_stage(msg.get("stage"))

        async def _enrich_stage(stage: Optional[str]) -> None:
            try:
                await _enrich_stage_inner(stage)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — enrichment must never break the stream
                print(f"[alembic-web] enrich({stage}) failed: {exc}")

        async def _enrich_stage_inner(stage: Optional[str]) -> None:
            out = output_dir()
            if stage == "explorer":
                rep = reports_dir() / "exploration.md"
                if rep.is_file():
                    parsed = _read_report(str(rep))
                    if parsed:
                        await send({"type": "report", "report": "exploration",
                                    "stage": "explorer", **parsed})
                await send({"type": "server", **_tools_payload()})
                await send({"type": "examples", **_examples_payload()})

            elif stage == "environment":
                setup = _read_setup(out)
                if setup is not None:
                    await send({"type": "setup", "content": setup})

            elif stage == "coder":
                await send({"type": "files", "files": _read_output_files(out)})
                await send({"type": "server", **_tools_payload()})
                await send({"type": "examples", **_examples_payload()})
                chk = _syntax_check()
                if chk:
                    await send({"type": "check", **chk})

            elif stage == "validator":
                await send({"type": "server", **_tools_payload()})
                chk = _tests_check()
                if chk:
                    await send({"type": "check", **chk})

            elif stage == "wrapper":
                await send({"type": "files", "files": _read_output_files(out)})
                await send({"type": "server", **_tools_payload()})

        def make_sink(my_run: int):
            async def sink(msg: dict) -> None:
                if my_run != active["run_id"]:
                    raise asyncio.CancelledError()
                await _forward(msg)
            return sink

        async def run(repo_url: str, resume_from: Optional[str],
                      target: Optional[str], my_run: int) -> None:
            token = events.set_sink(make_sink(my_run))
            try:
                # `target` (optional) is forwarded verbatim as the task spec —
                # run_pipeline._load_tasks accepts a JSON/YAML task object, a
                # path, or comma-separated paths (empty => native mode).
                await run_pipeline(repo_url, resume_from=resume_from,
                                   tasks_cli=(target or None))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — surface to the UI
                if my_run == active["run_id"]:
                    await send({"type": "pipeline", "status": "error",
                                "message": str(exc)})
            finally:
                events.reset_sink(token)

        async def _serve_in_container(repo_url: str) -> None:
            """Build a serving MCP image from the already-built output (no LLM, no
            commit) and run it — streaming docker output to the UI. Needs a docker
            daemon on the host; emits ``SERVE_URL=`` on success."""
            root = Path(__file__).resolve().parents[3]        # outer repo root (has docker/)
            script = root / "docker" / "alembic" / "build_serve.sh"
            if not script.exists():
                await send({"type": "serve_status", "status": "error",
                            "message": f"build script missing: {script}"})
                return
            await send({"type": "serve_status", "status": "building",
                        "message": "building + starting MCP container (docker)…"})
            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash", str(script), repo_url, cwd=str(root),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            except FileNotFoundError:
                await send({"type": "serve_status", "status": "error",
                            "message": "bash/docker not available on host"})
                return
            url = None
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                await send({"type": "serve_log", "line": line})
                if line.startswith("SERVE_URL="):
                    url = line.split("=", 1)[1].strip()
            rc = await proc.wait()
            if rc == 0 and url:
                await send({"type": "serve_status", "status": "ready", "url": url})
            else:
                await send({"type": "serve_status", "status": "error",
                            "message": f"container serve build exited rc={rc}"})

        async def _do_invoke(tool: str, args: dict, call_id) -> None:
            """Invoke a generated tool-function with user args (blocking subprocess)."""
            try:
                res = await invoke_tool_function(tool, args)
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "error": str(exc)}
            ok = bool(res.get("ok"))
            output = res.get("result") if ok else None
            if ok:
                try:   # never let viz-prep break a successful invocation
                    output = await asyncio.to_thread(_inline_images, output, output_dir())
                except Exception:  # noqa: BLE001
                    pass
            await send({
                "type": "invoke_result", "call_id": call_id, "tool": tool, "ok": ok,
                "output": output,
                "reason": res.get("reason"),
                "error": None if ok else (res.get("error") or res.get("stderr") or "call failed"),
                "traceback": res.get("traceback"),
            })

        try:
            while True:
                data = json.loads(await ws.receive_text())
                mt = data.get("type", "")

                if mt == "run":
                    repo_url = (data.get("repo_url") or "").strip()
                    if not repo_url:
                        await send({"type": "error", "message": "empty repo_url"})
                        continue
                    active["run_id"] += 1          # invalidate any in-flight run first
                    active["repo_url"] = repo_url
                    my_run = active["run_id"]
                    old = active["task"]
                    if old and not old.done():
                        old.cancel()               # do NOT await — may be in a subprocess
                    active["task"] = asyncio.create_task(
                        run(repo_url, data.get("resume_from"),
                            (data.get("target") or "").strip() or None, my_run))

                elif mt == "serve":
                    repo_url = (data.get("repo_url") or active.get("repo_url") or "").strip()
                    if not repo_url:
                        await send({"type": "serve_status", "status": "error",
                                    "message": "run a repo to a built server first"})
                    else:
                        asyncio.create_task(_serve_in_container(repo_url))

                elif mt == "stop":
                    active["run_id"] += 1
                    old = active["task"]
                    active["task"] = None
                    if old and not old.done():
                        old.cancel()
                    await send({"type": "pipeline", "status": "cancelled"})

                elif mt == "invoke":
                    tool = data.get("tool")
                    args = data.get("args") or {}
                    call_id = data.get("call_id")
                    if not active.get("repo_url") or not tool:
                        await send({"type": "invoke_result", "call_id": call_id,
                                    "tool": tool, "ok": False,
                                    "error": "no built tools yet — run a repo first"})
                    else:
                        asyncio.create_task(_do_invoke(tool, args, call_id))

                elif mt == "ping":
                    await send({"type": "pong"})

        except WebSocketDisconnect:
            active["run_id"] += 1
            if active["task"] and not active["task"].done():
                active["task"].cancel()
        except Exception as exc:  # noqa: BLE001
            print(f"[alembic-web] ws error: {exc}")
            active["run_id"] += 1
            if active["task"] and not active["task"].done():
                active["task"].cancel()

    return app
