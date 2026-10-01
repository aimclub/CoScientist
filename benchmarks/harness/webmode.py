"""Benchmark trials through the web UI.

In this mode the harness is a client of a CoScientist web server: it creates a
session per trial for the user ``benchmark``, seeds the session's sandbox
workspace, sends the prompt over the same websocket the browser uses and
records everything the server broadcasts. A person can open the same session
in a browser at any time — watch the agents, answer HITL cards, pause, stop.

The server is a dedicated one (``serve``), not the everyday instance: it keeps
its users, sessions, graphs and sandbox workspaces under ``runs/.web/``, and
its code-exec backend is the jailed ``exec_server`` — the web process runs
every session's commands, so isolation has to be the server's. Sessions stay
browsable afterwards: ``python -m benchmarks.harness serve`` reopens them.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from . import sandbox
from .tasks import PROJECT_ROOT

BENCH_USER = "benchmark"


def web_home() -> Path:
    from .runner import RUNS_DIR

    return RUNS_DIR / ".web"


# ── the server ───────────────────────────────────────────────────────────────
def server_env(home: Path, exec_url: str, hitl: str | None, coder: str,
               overrides: dict[str, str]) -> dict:
    env = {
        **os.environ,
        "CODER__MODE": coder,
        # Everything the web keeps, kept apart from the everyday instance.
        "WEB_STATE_DIR": str(home / "state"),
        "RESEARCH_GRAPH_DIR": str(home / "graph"),
        "GRAPH_SNAPSHOT_DIR": str(home / "graph"),
        "SESSION_SNAPSHOTS_DIR": str(home / "session_snapshots"),
        "AGENT_LOG_FILE": str(home / "logs" / "agent_events.log"),
        "AGENT_LOG_JSONL": str(home / "logs" / "agent_events.jsonl"),
        "PYTHONUNBUFFERED": "1",
        **overrides,
    }
    if coder == "local":
        env.update({"CODE_EXEC__URL": exec_url,
                    "CODE_EXEC__WORKSPACE_ROOT": str(home / "workspaces")})
    if hitl:
        env["HITL__MODE"] = hitl
    return env


def serve(port: int, *, isolation: str, hitl: str | None, coder: str,
          env_overrides: dict[str, str]) -> tuple[list[subprocess.Popen], dict]:
    """Start the exec server and the web server; returns (processes, info)."""
    home = web_home()
    (home / "workspaces").mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    procs: list[subprocess.Popen] = []
    exec_url = ""
    if coder == "local" and isolation == "bwrap":
        # With the OpenHands coder nothing runs here: the sandbox is the jail.
        proc, exec_url = sandbox.start_exec_server(home / "workspaces", home / "logs" / "exec_server.log")
        procs.append(proc)
    log = home / "logs" / "web.log"
    web = subprocess.Popen(
        [sys.executable, "-m", "CoScientist", "web", "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT_ROOT, env=server_env(home, exec_url, hitl, coder, env_overrides),
        stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True,
        preexec_fn=sandbox.die_with_parent)
    procs.append(web)
    url = f"http://127.0.0.1:{port}"
    try:
        # Loading the whole agent stack takes a while; say so instead of
        # looking hung.
        sandbox.wait_http(url + "/api/users", web, log, seconds=300,
                          what=f"the web server on {url}")
    except Exception:
        stop(procs)
        raise
    info = {"url": url, "workspace_root": str(home / "workspaces"), "coder": coder,
            "isolation": isolation if coder == "local" else "openhands-sandbox",
            "hitl_mode": hitl, "pids": [p.pid for p in procs], "started_at": time.time()}
    (home / "server.json").write_text(json.dumps(info, indent=2))
    return procs, info


def stop(procs: list[subprocess.Popen]) -> None:
    for p in reversed(procs):
        sandbox.kill_group(p, grace=15)
    info = web_home() / "server.json"
    if info.is_file():
        info.unlink()


def running_server() -> dict | None:
    """The dedicated server started by ``serve``, if it is up."""
    path = web_home() / "server.json"
    if not path.is_file():
        return None
    info = json.loads(path.read_text())
    try:
        urllib.request.urlopen(info["url"] + "/api/users", timeout=3)
        return info
    except OSError:
        path.unlink(missing_ok=True)  # left by a server that died without stopping
        return None


# ── the client ───────────────────────────────────────────────────────────────
class WebClient:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def _req(self, method: str, path: str, body: dict | None = None) -> Any:
        req = urllib.request.Request(
            self.url + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"null")

    def get(self, path: str) -> Any:
        return self._req("GET", path)

    def ensure_user(self, nickname: str = BENCH_USER) -> str:
        for u in self.get("/api/users")["users"]:
            if u["nickname"].casefold() == nickname.casefold():
                return u["id"]
        return self._req("POST", "/api/users", {"nickname": nickname})["user"]["id"]

    def upload_dataset(self, user_id: str, session_id: str, data: bytes,
                       filename: str = "inputs.zip") -> dict:
        """Attach a .zip as the session's sandbox dataset — the UI's upload button."""
        import httpx

        r = httpx.post(f"{self.url}/api/users/{user_id}/sessions/{session_id}/dataset",
                       files={"file": (filename, data, "application/zip")}, timeout=600)
        r.raise_for_status()
        return r.json()

    def create_session(self, user_id: str, title: str) -> str:
        return self._req("POST", f"/api/users/{user_id}/sessions", {"title": title[:120]})["session"]["id"]


def stop_session(url: str, user_id: str, session_id: str, wait: float = 30) -> bool:
    """Stop a session's run, as the UI's Stop button does; True once idle.

    Needed whenever the harness goes away mid-run: the run is the server's
    task and would otherwise carry on — or sit paused on a HITL card — with
    nobody collecting its result.
    """
    from websockets.sync.client import connect

    ws_url = url.replace("http", "ws", 1).rstrip("/") + "/ws?" + urlencode(
        {"user_id": user_id, "session_id": session_id})
    try:
        with connect(ws_url, open_timeout=10) as ws:
            ws.send(json.dumps({"type": "stop_chat"}))
            end = time.monotonic() + wait
            while time.monotonic() < end:
                try:
                    msg = json.loads(ws.recv(timeout=5))
                except TimeoutError:
                    continue
                if msg.get("type") == "status" and msg.get("status") in ("idle", "stopped"):
                    return True
    except Exception:  # noqa: BLE001 — best effort on the way out
        return False
    return False


def workspace_for(workspace_root: Path, session_id: str) -> Path:
    """Where CoderToolset puts a session's sandbox (``seed_coder_workspace``)."""
    import re

    safe = re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:48] or "session"
    return workspace_root / f"ws_{safe}"


class _Recorder:
    """The websocket stream, raw and normalized to the harness trace format."""

    def __init__(self, trace: Path):
        trace.mkdir(parents=True, exist_ok=True)
        self.raw = (trace / "ws_events.jsonl").open("a", encoding="utf-8")
        self.events = (trace / "events.jsonl").open("a", encoding="utf-8")
        self.hitl = (trace / "hitl.jsonl").open("a", encoding="utf-8")
        self._calls: dict[str, tuple[float, dict]] = {}

    def _put(self, fh, rec: dict) -> None:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        fh.flush()

    def __call__(self, msg: dict) -> None:
        now = time.time()
        self._put(self.raw, {"t": now, **msg})
        kind = msg.get("type")
        if kind == "tool_activity":
            phase, cid = msg.get("phase"), str(msg.get("call_id"))
            if phase == "call":
                self._calls[cid] = (now, msg)
                return
            t0, call = self._calls.pop(cid, (None, {}))
            status = "exception" if phase == "error" else _status_of(msg.get("result"))
            self._put(self.events, {
                "t": now, "ev": "tool", "agent": msg.get("author"), "tool": msg.get("tool"),
                "call_id": cid, "ms": round((now - t0) * 1000) if t0 else None, "status": status,
                "args": _text(call.get("args_full") or call.get("args")),
                "result": _text(msg.get("error") if phase == "error"
                                else msg.get("result_full") or msg.get("result")),
            })
        elif kind == "agent_event":
            self._put(self.events, {"t": now, "ev": "agent_message", "agent": msg.get("author"),
                                    "final": msg.get("is_final")})
        elif kind in ("hitl_request", "hitl_response", "hitl_timeout", "hitl_cancelled",
                      "work_order_notice"):
            self._put(self.hitl, {"t": now, **msg})
        elif kind == "error":
            self._put(self.events, {"t": now, "ev": "run_error", "message": msg.get("message")})

    def close(self) -> None:
        for fh in (self.raw, self.events, self.hitl):
            fh.close()


def _text(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)


def _status_of(result: Any) -> str | None:
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return None
    if isinstance(result, dict):
        return result.get("status") or ("error" if result.get("error") else None)
    return None


async def drive(url: str, user_id: str, session_id: str, prompt: str, timeout: float,
                trace: Path, log=print, dataset_url: str | None = None) -> dict[str, Any]:
    """Send the prompt and follow the run to its end; returns its status.

    The run is a server-side task: losing the socket does not stop it, so the
    client reconnects. Stop at the deadline is the same ``stop_chat`` the UI
    sends. A paused run waits for a person — the deadline still applies.
    """
    import websockets

    ws_url = url.replace("http", "ws", 1).rstrip("/") + "/ws?" + urlencode(
        {"user_id": user_id, "session_id": session_id})
    rec = _Recorder(trace)
    deadline = time.monotonic() + timeout
    state: dict[str, Any] = {"status": None, "final": None, "accepted": False,
                             "paused_seconds": 0.0, "hitl_requests": 0}
    sent = stopping = False
    paused_since = None
    try:
        while True:
            try:
                async with websockets.connect(ws_url, max_size=None, ping_interval=20) as ws:
                    if not sent:
                        if dataset_url:
                            # The session's dataset archive, as the paperclip in
                            # the UI attaches it; the coder passes it on.
                            await ws.send(json.dumps({"type": "set_dataset_url",
                                                      "dataset_url": dataset_url}))
                        await ws.send(json.dumps({"type": "chat_message", "message": prompt}))
                        sent = True
                    while True:
                        if not stopping and time.monotonic() > deadline:
                            log(f"[web] {session_id}: deadline — stopping the run")
                            await ws.send(json.dumps({"type": "stop_chat"}))
                            stopping = True
                            state["status"] = "timeout"
                            deadline = time.monotonic() + 180  # grace to wind down
                        elif stopping and time.monotonic() > deadline:
                            return state
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=15)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"type": "ping"}))
                            continue
                        msg = json.loads(raw)
                        rec(msg)
                        kind = msg.get("type")
                        if kind == "dataset_url_rejected":
                            state.update(status="crash",
                                         error=f"dataset link rejected: {msg.get('message')}")
                            return state
                        if kind == "chat_accepted":
                            state["accepted"] = True
                        elif kind == "chat_rejected":
                            state.update(status="crash", error=msg.get("message"))
                            return state
                        elif kind == "final_response":
                            state["final"] = msg.get("content")
                        elif kind == "hitl_request":
                            state["hitl_requests"] += 1
                            log(f"[web] {session_id}: waiting for a HITL decision — "
                                f"{(msg.get('message') or '')[:80]!r}")
                        elif kind == "error" and state["accepted"]:
                            state["error"] = msg.get("message")
                        elif kind == "status" and state["accepted"]:
                            s = msg.get("status")
                            if s == "paused" and paused_since is None:
                                paused_since = time.monotonic()
                                log(f"[web] {session_id}: run paused — resume or stop it in the UI")
                            elif s != "paused" and paused_since is not None:
                                state["paused_seconds"] += time.monotonic() - paused_since
                                paused_since = None
                            if s == "idle":
                                if state["status"] != "timeout":
                                    state["status"] = "run_error" if state.get("error") else "ok"
                                return state
            except (OSError, websockets.ConnectionClosed) as exc:
                if time.monotonic() > deadline + 300:
                    state.update(status=state["status"] or "crash", error=f"connection lost: {exc}")
                    return state
                log(f"[web] {session_id}: socket dropped ({exc}); reconnecting")
                await asyncio.sleep(3)
    finally:
        rec.close()
