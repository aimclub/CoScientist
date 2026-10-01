"""Run trials: prepare → agent → collect → verify → analyze.

Run layout (``benchmarks/runs/`` is git-ignored)::

    runs/<run_id>/
      run.json                       pre-run snapshot: code version, host, tools, tasks, args
      summary.md, summary.json       written by ``report`` at the end
      <benchmark>/<task>/trial-<k>/
        input/      prompt.md (exact text sent), io.json, seeded.json (input hashes)
        workspace/  the agent's sandbox workspace — inputs, its scripts, outputs
        output/     artifacts/ (graded files), final_report.md, report/
        verifier/   reward.txt, ctrf.json, test-stdout.txt
        trace/      events.jsonl, agent_events.{log,jsonl}, hitl.jsonl, graph/
        agent.log   stdout/stderr of the agent process
        config.json settings the system ran with (CoScientist agent only)
        metrics.json, result.json, analysis.json, feedback.{json,md}
    runs/ledger.jsonl                one flat row per trial, across all runs
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import analysis, sandbox, verifier
from .tasks import BENCHMARKS_DIR, PROJECT_ROOT, Task, load_benchmark

RUNS_DIR = Path(os.getenv("BENCH_RUNS_DIR", BENCHMARKS_DIR / "runs"))
HARNESS_VERSION = "1"
_ledger_lock = threading.Lock()


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).isoformat()


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _tool_version(argv: list[str]) -> str | None:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def snapshot_before(run_id: str, agent: str, tasks: list[Task], opts: dict) -> dict[str, Any]:
    """Everything needed to reproduce or compare this run, taken before it starts."""
    diff = _git("diff", "HEAD")
    import hashlib

    benches = {t.benchmark for t in tasks}
    return {
        "run_id": run_id,
        "harness_version": HARNESS_VERSION,
        "created_at": _iso(),
        "agent": agent,
        "label": opts.get("label"),
        "options": opts,
        "code": {
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": len(_git("status", "--porcelain").splitlines()),
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff else None,
        },
        "host": {
            "platform": platform.platform(), "python": platform.python_version(),
            "cpus": os.cpu_count(),
        },
        "tools": {
            "uv": _tool_version(["uv", "--version"]),
            "bwrap": _tool_version(["bwrap", "--version"]),
            "docker": _tool_version(["docker", "--version"]),
        },
        "benchmarks": {b: load_benchmark(BENCHMARKS_DIR / b)["source"] for b in sorted(benches)},
        "tasks": [{"name": t.full_name, "checksum": t.checksum()} for t in tasks],
    }


# ── agents ───────────────────────────────────────────────────────────────────
def _run_coscientist(task: Task, trial: Path, prompt: str, timeout: float,
                     session_id: str, env_overrides: dict[str, str],
                     isolation: str, coder: str,
                     initial_state: dict | None = None) -> dict[str, Any]:
    trace = trial / "trace"
    trace.mkdir(parents=True, exist_ok=True)
    spec = {"trial_dir": str(trial), "user_id": "benchmark", "session_id": session_id,
            "prompt": prompt, "task": task.full_name, "timeout_sec": timeout,
            "initial_state": initial_state or {}}
    (trial / "worker.json").write_text(json.dumps(spec, indent=2))
    env = {
        **os.environ,
        # Nobody is watching: never wait for a human.
        "HITL__MODE": "auto",
        # Keep the run's own records inside the trial — including the research
        # graph and the session→sandbox bindings, which otherwise land in the
        # project's graph_runs/ and would let one trial continue in another
        # trial's sandbox.
        "GRAPH_SNAPSHOT_DIR": str(trace / "graph"),
        "RESEARCH_GRAPH_DIR": str(trace / "graph"),
        "SANDBOX_BINDINGS_FILE": str(trace / "sandbox_bindings.json"),
        "AGENT_LOG_FILE": str(trace / "agent_events.log"),
        "AGENT_LOG_JSONL": str(trace / "agent_events.jsonl"),
        "SESSION_SNAPSHOTS_DIR": str(trace / "session_snapshots"),
        "PYTHONUNBUFFERED": "1",
    }
    jail = None
    if coder == "openhands":
        # Work happens in the OpenHands sandbox; the inputs reach it as the
        # session's dataset archive (initial_state), outputs are fetched after.
        env["CODER__MODE"] = "openhands"
    else:
        # CoderToolset resolves a pinned id to `<root>/ws_<id>`; point that at
        # the seeded workspace so the agent starts where its inputs are.
        (trial / "ws_workspace").symlink_to("workspace", target_is_directory=True)
        # Commands run on this machine — by default jailed, because a plain
        # working directory lets a command find this repository's solutions
        # (an early smoke run did `find / -name solve.sh`).
        exec_url = ""
        if isolation == "bwrap":
            jail, exec_url = sandbox.start_exec_server(trial, trace / "exec_server.log")
        env.update({"CODE_EXEC__URL": exec_url, "CODER__MODE": "local",
                    "CODE_EXEC__WORKSPACE_ROOT": str(trial), "CODER_WORKSPACE_ID": "workspace"})
    env.update(env_overrides)
    try:
        code, timed_out = _run_proc(
            [sys.executable, "-m", "benchmarks.harness.worker", str(trial / "worker.json")],
            trial / "agent.log", timeout, cwd=PROJECT_ROOT, env=env)
    finally:
        if jail is not None:
            sandbox.kill_group(jail, grace=5)
    wr = trial / "worker_result.json"
    status = json.loads(wr.read_text()) if wr.is_file() else {}
    if timed_out:
        status["status"] = "timeout"
    elif not status:
        status = {"status": "crash", "error": f"worker exited {code} without a result"}
    status["exit_code"] = code
    return status


def _run_web(trial: Path, prompt: str, timeout: float, web: dict,
             session_id: str, dataset_url: str | None = None) -> dict[str, Any]:
    """The trial as a web session: the server runs it, a person may follow it."""
    import asyncio

    from . import webmode
    from .worker import redact

    client = webmode.WebClient(web["url"])
    user_id = web["user_id"]
    base = f"/api/users/{user_id}/sessions/{session_id}"
    print(f"[bench] {trial.parent.name} #{trial.name[6:]}: web session {session_id}", flush=True)
    with _ledger_lock:
        web["active"].add(session_id)
    try:
        status = asyncio.run(webmode.drive(web["url"], user_id, session_id, prompt, timeout,
                                           trial / "trace", log=lambda m: print(m, flush=True),
                                           dataset_url=dataset_url))
    finally:
        with _ledger_lock:
            web["active"].discard(session_id)
    (trial / "output").mkdir(exist_ok=True)
    (trial / "output" / "final_report.md").write_text(status.get("final") or "", encoding="utf-8")
    for name, path in (("metrics.json", "/metrics"), ("trace/graph.json", "/graph"),
                       ("trace/artifacts.json", "/artifacts")):
        try:
            (trial / name).write_text(json.dumps(client.get(base + path), indent=2, default=str))
        except Exception as exc:  # noqa: BLE001 — a missing extra must not lose the trial
            status.setdefault("collection_errors", []).append(f"{path}: {exc}")
    try:
        settings = client.get(base + "/settings")
    except Exception:  # noqa: BLE001
        settings = None
    (trial / "config.json").write_text(json.dumps(
        {"harness": {"mode": "web", "url": web["url"], "user_id": user_id,
                     "session_id": session_id, "timeout_sec": timeout},
         "session_settings": redact(settings)}, indent=2, default=str))
    return {k: v for k, v in status.items() if k != "final"}


def _collect_from_sandbox(task: Task, trial: Path, status: dict) -> dict[str, Any]:
    """Graded outputs and records out of the OpenHands sandbox(es) the run used."""
    from . import sandbox_io

    ids = sandbox_io.sandbox_ids(trial, [status["sandbox_id"]] if status.get("sandbox_id") else [])
    if not ids:
        return {"ids": [], "error": "the run never started a sandbox"}
    out: dict[str, Any] = {"ids": ids}
    try:
        out["fetched"] = sandbox_io.fetch_outputs(task, trial, ids)
    except Exception as exc:  # noqa: BLE001 — grading then sees no output, and says so
        out["fetch_error"] = f"{type(exc).__name__}: {exc}"
    try:
        out["records"] = sandbox_io.save_records(trial, ids)
    except Exception as exc:  # noqa: BLE001
        out["records_error"] = f"{type(exc).__name__}: {exc}"
    return out


def _run_oracle(task: Task, trial: Path, timeout: float) -> dict[str, Any]:
    """The task's reference solution through the same pipeline. A harness
    check: every task the oracle cannot solve here is a harness problem."""
    if not sandbox.have("bwrap"):
        return {"status": "crash", "error": "oracle needs bwrap"}
    spec = task.io_spec()["agent_environment"]
    venv = sandbox.build_venv(spec["python"], spec["packages"], dest=trial / ".oracle-venv")
    ws = trial / "workspace"
    m = sandbox.Mounts(network=True)
    for root in task.roots():
        (ws / root).mkdir(parents=True, exist_ok=True)
        m.bind(ws / root, f"/{root}", writable=True)
    m.bind(task.path / "solution", "/solution")
    uv_cache = sandbox.CACHE_DIR / "uv"
    uv_cache.mkdir(parents=True, exist_ok=True)
    m.bind(uv_cache, str(uv_cache), writable=True)
    argv = sandbox.bwrap_argv(m, venv=venv, chdir=task.env.workdir or "/",
                              argv=["bash", "/solution/solve.sh"],
                              env={"UV_CACHE_DIR": str(uv_cache)})
    try:
        code, timed_out = sandbox.run_logged(argv, trial / "agent.log", timeout)
    finally:
        shutil.rmtree(venv, ignore_errors=True)
    if timed_out:
        return {"status": "timeout", "exit_code": None}
    return {"status": "ok" if code == 0 else "crash", "exit_code": code}


def _run_proc(argv, log: Path, timeout: float, cwd: Path, env: dict) -> tuple[int | None, bool]:
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, cwd=cwd, env=env,
                                start_new_session=True)
        try:
            return proc.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            sandbox.kill_group(proc, grace=60)
            return None, True


# ── one trial ────────────────────────────────────────────────────────────────
def run_trial(task: Task, run_dir: Path, k: int, opts: dict) -> dict[str, Any]:
    trial = run_dir / task.benchmark / task.name / f"trial-{k}"
    if trial.exists():
        shutil.rmtree(trial)
    (trial / "input").mkdir(parents=True)
    timeout = float(opts.get("timeout") or task.agent_timeout_sec)
    prompt = task.render_prompt(
        timeout, opts.get("coder", "local") if opts["agent"] != "oracle" else "local")
    (trial / "input" / "prompt.md").write_text(prompt, encoding="utf-8")
    (trial / "input" / "io.json").write_text(json.dumps(task.io_spec(), indent=2))
    agent = opts["agent"]
    web = opts.get("_web")
    if web:
        # The server names the session and, from it, the sandbox directory;
        # the inputs go there and trial/workspace points at it.
        from . import webmode

        client = webmode.WebClient(web["url"])
        session_id = client.create_session(web["user_id"], f"{task.name} #{k} · {run_dir.name}")
        ws = webmode.workspace_for(Path(web["workspace_root"]), session_id)
        ws.mkdir(parents=True, exist_ok=True)
        (trial / "workspace").symlink_to(ws.resolve(), target_is_directory=True)
    else:
        session_id = re.sub(r"[^A-Za-z0-9_]", "_", f"bench_{run_dir.name}_{task.name}_{k}")
    seeded = task.seed_workspace(trial / "workspace")
    (trial / "input" / "seeded.json").write_text(json.dumps(seeded, indent=2))
    coder = opts.get("coder", "local") if agent != "oracle" else "local"
    dataset_url = None
    if coder == "openhands":
        from . import sandbox_io

        archive = sandbox_io.inputs_zip(task, trial / "workspace")
        if web:
            # Through the UI's own upload: S3, then the session's dataset link.
            up = webmode.WebClient(web["url"]).upload_dataset(web["user_id"], session_id, archive)
            pub = {"key": up.get("s3_key"), "via": "web upload"}
        else:
            pub = sandbox_io.publish_inputs(archive, run_dir.name, int(timeout) + 6 * 3600)
            dataset_url = pub["url"]
        # The link is a bearer token for the archive: keep where it points, not it.
        (trial / "input" / "dataset.json").write_text(json.dumps(
            {k: v for k, v in pub.items() if k != "url"}, indent=2))

    started = time.time()
    if agent == "oracle":
        status = _run_oracle(task, trial, timeout)
    elif web:
        status = _run_web(trial, prompt, timeout, web, session_id, dataset_url)
    else:
        status = _run_coscientist(task, trial, prompt, timeout, session_id,
                                  opts.get("env") or {}, opts.get("isolation", "bwrap"), coder,
                                  {"dataset_url": dataset_url} if dataset_url else None)
    agent_finished = time.time()
    if coder == "openhands":
        status["sandbox"] = _collect_from_sandbox(task, trial, status)

    artifacts = verifier.collect_artifacts(task, trial / "workspace", trial)
    v_started = time.time()
    vres = verifier.verify(task, trial, opts.get("verifier", "auto"))
    finished = time.time()

    metrics = {}
    if (trial / "metrics.json").is_file():
        metrics = json.loads((trial / "metrics.json").read_text())
    llm, totals = metrics.get("llm", {}), metrics.get("totals", {})

    result = {
        # Harbor-compatible core (same field names as harbor's result.json).
        "id": str(uuid.uuid4()),
        "task_name": task.full_name,
        "trial_name": f"{task.name}__{k}",
        "source": task.benchmark,
        "task_checksum": task.checksum(),
        "agent_info": {"name": "coscientist" if agent != "oracle" else "oracle",
                       "version": _git("rev-parse", "--short", "HEAD")},
        "agent_result": {
            "n_input_tokens": llm.get("prompt_tokens"),
            "n_cache_tokens": llm.get("cached_tokens"),
            "n_output_tokens": llm.get("completion_tokens"),
            "cost_usd": totals.get("cost_usd"),
            "metadata": {"status": status, "cost_complete": totals.get("complete")},
        },
        "verifier_result": {"rewards": {"reward": vres.get("reward")}},
        "exception_info": status.get("error"),
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "agent_execution": {"started_at": _iso(started), "finished_at": _iso(agent_finished)},
        "verifier": {"started_at": _iso(v_started), "finished_at": _iso(finished)},
        # Harness extensions.
        "run_id": run_dir.name,
        "trial_dir": str(trial),
        "agent_status": status.get("status"),
        "agent_seconds": round(agent_finished - started, 1),
        "agent_started_epoch": started,
        "timeout_sec": timeout,
        "cost_usd": totals.get("cost_usd"),
        "artifacts": artifacts,
        "verifier": vres,
    }
    result["analysis"] = analysis.analyze(task, trial, result)
    (trial / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    _append_ledger(result, opts)
    return result


def _append_ledger(r: dict, opts: dict) -> None:
    a = r["analysis"]
    row = {
        "run_id": r["run_id"], "label": opts.get("label"), "agent": r["agent_info"]["name"],
        "commit": r["agent_info"]["version"], "task": r["task_name"], "trial": r["trial_name"],
        "reward": r["verifier"].get("reward"), "partial_score": a["partial_score"],
        "outcome": a["outcome"], "agent_status": r["agent_status"],
        "agent_seconds": r["agent_seconds"], "cost_usd": r["cost_usd"],
        "input_tokens": r["agent_result"]["n_input_tokens"],
        "output_tokens": r["agent_result"]["n_output_tokens"],
        "tool_calls": a["trace"]["tool_calls"], "tool_errors": a["trace"]["tool_errors"],
        "verifier_backend": r["verifier"].get("backend"),
        "integrity_clean": a["integrity"]["clean"], "finished_at": r["finished_at"],
    }
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with _ledger_lock, (RUNS_DIR / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── a run ────────────────────────────────────────────────────────────────────
def run(tasks: list[Task], opts: dict) -> Path:
    agent = opts["agent"]
    if opts.get("isolation", "auto") == "auto":
        opts["isolation"] = "bwrap" if sandbox.have("bwrap") else "none"
    if agent != "oracle" and opts.get("coder", "auto") == "auto":
        from . import sandbox_io

        opts["coder"] = sandbox_io.coder_mode()
    if opts.get("coder") == "openhands" and int(opts.get("parallel", 1)) > 1:
        print("[bench] note: the OpenHands sandbox runs one container at a time — parallel "
              "trials queue for it, and the queueing counts against their time", flush=True)
    run_id = opts.get("run_id") or "{}_{}{}".format(
        datetime.now().strftime("%Y%m%d-%H%M%S"), agent,
        f"_{re.sub(r'[^A-Za-z0-9_-]', '-', opts['label'])}" if opts.get("label") else "")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(snapshot_before(run_id, agent, tasks, opts),
                                                 indent=2, default=str))
    jobs = [(t, k) for t in tasks for k in range(1, int(opts.get("trials", 1)) + 1)]
    print(f"[bench] run {run_id}: {len(jobs)} trial(s), agent={agent}, "
          f"parallel={opts.get('parallel', 1)} → {run_dir}", flush=True)
    started_server = _attach_web(opts) if opts.get("web") and agent != "oracle" else None
    if opts.get("_web"):
        meta = json.loads((run_dir / "run.json").read_text())
        meta["web"] = {k: opts["_web"].get(k)
                       for k in ("url", "isolation", "hitl_mode", "coder", "user_id")}
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2, default=str))
    interrupted = False
    try:
        try:
            _run_jobs(jobs, run_dir, opts)
        except KeyboardInterrupt:
            interrupted = True
            print("[bench] interrupted — summarizing the trials that finished", flush=True)
        from .report import summarize

        summarize(run_dir)
        if started_server and not interrupted and opts.get("keep_web", True):
            _serve_until_interrupted(started_server, opts["_web"]["url"], run_dir)
    finally:
        if started_server:
            from . import webmode

            webmode.stop(started_server)
    if interrupted:
        raise KeyboardInterrupt
    return run_dir


def _serve_until_interrupted(procs: list, url: str, run_dir: Path) -> None:
    """Keep the server this run started open for browsing the sessions."""
    print(f"[bench] run finished — summary: {run_dir / 'summary.md'}\n"
          f"[bench] the web UI stays open at {url} to browse the sessions; "
          "Ctrl+C stops it (--no-keep-web exits right away)", flush=True)
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(2)
        print("[bench] the web server exited", flush=True)
    except KeyboardInterrupt:
        pass


def _attach_web(opts: dict) -> list | None:
    """Connect the run to a web server; start a dedicated one if none is up.
    Returns the processes to stop afterwards, or None when attaching."""
    from . import webmode

    procs = None
    info = webmode.running_server()
    if info is None:
        print("[bench] starting the benchmark web server…", flush=True)
        procs, info = webmode.serve(int(opts.get("web_port") or 8765),
                                    isolation=opts["isolation"], hitl=opts.get("hitl"),
                                    coder=opts["coder"], env_overrides=opts.get("env") or {})
    elif opts.get("env") or opts.get("hitl"):
        print("[bench] note: --env/--hitl apply when the server starts; the running "
              "server keeps its own configuration", flush=True)
    opts["isolation"] = info.get("isolation", opts["isolation"])
    if info.get("coder") and info["coder"] != opts.get("coder"):
        print(f"[bench] note: the running server uses the {info['coder']} coder", flush=True)
        opts["coder"] = info["coder"]
    opts["_web"] = {**info, "user_id": webmode.WebClient(info["url"]).ensure_user(),
                    "active": set()}
    print(f"[bench] follow the run at {info['url']} as user '{webmode.BENCH_USER}' — "
          f"sessions are titled '<task> #<trial> · <run id>'", flush=True)
    return procs


def _run_jobs(jobs: list, run_dir: Path, opts: dict) -> None:
    import signal

    # SIGTERM gets the same cleanup as Ctrl+C: web runs live in the server.
    previous = signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        with ThreadPoolExecutor(max_workers=int(opts.get("parallel", 1))) as pool:
            futs = {pool.submit(run_trial, t, run_dir, k, opts): (t, k) for t, k in jobs}
            try:
                _report_progress(futs)
            except KeyboardInterrupt:
                # Stop the server-side runs BEFORE the pool waits for its
                # threads: each thread returns once its session goes idle,
                # and its trial is still collected and graded.
                web = opts.get("_web")
                if web:
                    for sid in list(web["active"]):
                        print(f"[bench] interrupted — stopping web session {sid}", flush=True)
                        from . import webmode

                        webmode.stop_session(web["url"], web["user_id"], sid)
                for f in futs:
                    f.cancel()
                raise
    finally:
        signal.signal(signal.SIGTERM, previous)


def _raise_interrupt(*_: Any) -> None:
    raise KeyboardInterrupt


def _report_progress(futs: dict) -> None:
    for fut in as_completed(futs):
        t, k = futs[fut]
        try:
            r = fut.result()
            a = r["analysis"]
            print(f"[bench] {t.full_name} #{k}: reward={r['verifier'].get('reward')} "
                  f"outcome={a['outcome']} tests={_frac(r['verifier'].get('tests'))} "
                  f"{r['agent_seconds']:.0f}s", flush=True)
        except Exception as exc:  # noqa: BLE001 — one broken trial must not end the run
            print(f"[bench] {t.full_name} #{k}: HARNESS ERROR {type(exc).__name__}: {exc}",
                  flush=True)


def reverify(trial: Path, backend: str) -> dict:
    """Re-grade an existing trial (e.g. after fixing the harness or on a Docker host)."""
    from .tasks import load_task

    result = json.loads((trial / "result.json").read_text())
    bench, name = result["task_name"].split("/", 1)
    task = load_task(BENCHMARKS_DIR / bench / "tasks" / name)
    result["trial_dir"] = str(trial)
    if (trial / "workspace").is_dir():
        shutil.rmtree(trial / "output" / "artifacts", ignore_errors=True)
        result["artifacts"] = verifier.collect_artifacts(task, trial / "workspace", trial)
    result["verifier"] = verifier.verify(task, trial, backend)
    result["verifier_result"] = {"rewards": {"reward": result["verifier"].get("reward")}}
    result["analysis"] = analysis.analyze(task, trial, result)
    (trial / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return result


def _frac(tests: dict | None) -> str:
    return f"{tests['passed']}/{tests['total']}" if tests else "-"
