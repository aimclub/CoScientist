"""Grade a trial with the task's own verifier, unchanged.

Harbor's ``environment_mode = "separate"``: the verifier runs in a fresh image
built from ``tests/Dockerfile`` that receives ONLY the declared artifacts. The
harness reproduces exactly that — artifacts are first copied out of the agent's
workspace into ``output/artifacts/`` (that copy is the archived submission),
then mounted at their original absolute paths for ``bash /tests/test.sh``.

The verifier writes ``/logs/verifier/reward.txt`` (the score) and normally
``ctrf.json`` (per-test results), which is where the partial-credit and
failure-mode signals come from.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import sandbox
from .tasks import Task, _sha256


def collect_artifacts(task: Task, ws: Path, trial_dir: Path) -> list[dict[str, Any]]:
    """Copy declared outputs from the workspace into the trial; describe them."""
    dest_root = trial_dir / "output" / "artifacts"
    found = []
    for out in task.outputs():
        rel = out["path"].strip("/")
        src, dst = ws / rel, dest_root / rel
        rec: dict[str, Any] = {"path": out["path"], "kind": out["kind"], "present": src.exists()}
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            files = [p for p in dst.rglob("*") if p.is_file()]
            rec.update(files=len(files), bytes=sum(p.stat().st_size for p in files))
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            rec.update(bytes=dst.stat().st_size, sha256=_sha256(dst), mtime=src.stat().st_mtime)
        found.append(rec)
    return found


def pick_backend(requested: str, task: Task) -> tuple[str, str | None]:
    """(backend, reason it is unavailable or None)."""
    if requested == "none":
        return "none", "verification disabled"
    if requested in ("auto", "docker") and sandbox.docker_available():
        return "docker", None
    if requested == "docker":
        return "none", "docker requested but not available"
    blockers = task.local_verifier_blockers()
    if blockers:
        return "none", "local verifier unsupported: " + "; ".join(blockers)
    if not sandbox.have("bwrap"):
        return "none", "neither docker nor bwrap is available"
    return "local", None


def verify(task: Task, trial_dir: Path, requested: str = "auto") -> dict[str, Any]:
    backend, why = pick_backend(requested, task)
    vdir = trial_dir / "verifier"
    if vdir.exists():
        shutil.rmtree(vdir)
    vdir.mkdir(parents=True)
    result: dict[str, Any] = {"backend": backend, "reward": None, "error": why}
    if backend == "none":
        return result

    started = time.time()
    try:
        runner = _run_docker if backend == "docker" else _run_local
        code, timed_out = runner(task, trial_dir, vdir)
        result.update(exit_code=code, timed_out=timed_out)
    except Exception as exc:  # noqa: BLE001 — a broken verifier is a result too
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.time() - started, 1)

    reward_file = vdir / "reward.txt"
    if reward_file.is_file():
        try:
            result["reward"] = float(reward_file.read_text().strip() or "nan")
        except ValueError:
            result["error"] = f"unparseable reward.txt: {reward_file.read_text()[:80]!r}"
    elif not result.get("error"):
        result["error"] = "verifier wrote no reward.txt"
    result["tests"] = read_ctrf(vdir / "ctrf.json")
    return result


def read_ctrf(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))["results"]
    except (ValueError, KeyError):
        return None
    s = data.get("summary", {})
    return {
        "total": s.get("tests", 0), "passed": s.get("passed", 0), "failed": s.get("failed", 0),
        "skipped": s.get("skipped", 0),
        "cases": [{"name": t.get("name"), "status": t.get("status"),
                   "message": _failure_text(t)}
                  for t in data.get("tests", [])],
    }


def _failure_text(test: dict) -> str | None:
    """The assertion pytest printed ("E  ..." lines), else CTRF's generic message."""
    trace = test.get("trace") or ""
    e_lines = [ln[1:].strip() for ln in trace.splitlines() if ln.startswith("E ")]
    text = "\n".join(e_lines) or test.get("message") or trace
    return text[-1500:] or None


# ── backends ─────────────────────────────────────────────────────────────────
def _artifact_sources(task: Task, trial_dir: Path) -> list[tuple[Path, str]]:
    root = trial_dir / "output" / "artifacts"
    pairs = []
    for out in task.outputs():
        src = root / out["path"].strip("/")
        if src.exists():
            pairs.append((src, out["path"].rstrip("/") or "/"))
    return pairs


def _run_local(task: Task, trial_dir: Path, vdir: Path) -> tuple[int | None, bool]:
    spec = task.io_spec()["verifier"]
    venv = sandbox.build_venv(spec["python"], spec["packages"])
    # The verifier may write next to its tests; never let it touch the repo copy.
    tests = trial_dir / ".verifier_tests"
    if tests.exists():
        shutil.rmtree(tests)
    shutil.copytree(task.path / "tests", tests)

    m = sandbox.Mounts(network=spec["network"] != "no-network")
    m.dirs += [d for d in spec["precreated_dirs"] if d not in ("/tests", "/logs/verifier")]
    m.bind(tests, "/tests", writable=True)
    m.bind(vdir, "/logs/verifier", writable=True)
    for extra in spec["extra_files"]:
        m.bind(task.path / extra["source"], extra["target"].rstrip("/"))
    for src, target in _artifact_sources(task, trial_dir):
        m.bind(src, target, writable=True)
    argv = sandbox.bwrap_argv(m, venv=venv, chdir=spec["workdir"] or "/",
                              argv=["bash", "/tests/test.sh"])
    try:
        return sandbox.run_logged(argv, vdir / "test-stdout.txt", spec["timeout_sec"] + 60)
    finally:
        shutil.rmtree(tests, ignore_errors=True)


def _run_docker(task: Task, trial_dir: Path, vdir: Path) -> tuple[int | None, bool]:
    spec = task.io_spec()["verifier"]
    tag = f"coscientist-bench-verifier-{task.name}:{task.checksum()[:12]}"
    if subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode:
        subprocess.run(["docker", "build", "-q", "-t", tag, str(task.path / "tests")],
                       check=True, capture_output=True)
    net = ["--network", "none"] if spec["network"] == "no-network" else []
    cid = subprocess.run(
        ["docker", "create", *net, "-v", f"{vdir.resolve()}:/logs/verifier", tag,
         "bash", "/tests/test.sh"],
        check=True, capture_output=True, text=True).stdout.strip()
    try:
        for src, target in _artifact_sources(task, trial_dir):
            arg = f"{src}/." if src.is_dir() else str(src)
            subprocess.run(["docker", "cp", arg, f"{cid}:{target}"], check=True, capture_output=True)
        return sandbox.run_logged(["docker", "start", "-a", cid], vdir / "test-stdout.txt",
                                  spec["timeout_sec"] + 120)
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
