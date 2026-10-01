"""Container stand-ins: pinned venvs and bubblewrap mounts.

Harbor runs each task's verifier (and its oracle) in a Docker image. Where
Docker is present the harness uses those images unchanged (``docker`` backend).
Where it is not, ``bwrap`` gives the same file layout without root: a fresh
root filesystem with the host's ``/usr`` read-only, the task's paths bound at
their absolute container locations (``/app``, ``/results``, ``/tests``,
``/logs/verifier``…), and a venv built with ``uv`` from the exact pins of the
image's Dockerfile. Nothing else of the host is visible — in particular not
this repository, which holds the solutions.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .tasks import BENCHMARKS_DIR

CACHE_DIR = Path(os.getenv("BENCH_CACHE_DIR", BENCHMARKS_DIR / ".cache"))


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def docker_available() -> bool:
    if not have("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to build verifier/oracle environments")
    return uv


def build_venv(python: str, packages: list[str], dest: Path | None = None) -> Path:
    """A venv with exactly ``packages``. Shared and cached unless ``dest`` is
    given (a private venv for a run that may ``pip install`` into it)."""
    private = dest is not None
    if dest is None:
        key = hashlib.sha256(f"{python}|{'|'.join(sorted(packages))}".encode()).hexdigest()[:16]
        dest = CACHE_DIR / "venvs" / f"py{python}-{key}"
        if (dest / ".ready").exists():
            return dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "UV_CACHE_DIR": str(CACHE_DIR / "uv")}
    subprocess.run([_uv(), "venv", "--quiet", "--seed", "--python", python, str(dest)],
                   check=True, env=env)
    if packages:
        subprocess.run([_uv(), "pip", "install", "--quiet", "--python",
                        str(dest / "bin" / "python"), *packages], check=True, env=env)
    (dest / ".ready").touch()
    if private:
        # Mounted writable: oracle scripts may `pip install` into it.
        (dest / ".private").touch()
    return dest


def _uv_python_dir() -> Path | None:
    try:
        out = subprocess.run([_uv(), "python", "dir"], capture_output=True, text=True)
        p = Path(out.stdout.strip())
        return p if p.is_dir() else None
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Mounts:
    """What a bwrap sandbox sees besides the read-only system."""

    binds: list[tuple[Path, str, bool]] = field(default_factory=list)  # (host, target, writable)
    dirs: list[str] = field(default_factory=list)
    network: bool = False

    def bind(self, host: Path, target: str, writable: bool = False) -> None:
        self.binds.append((host, target, writable))


def bwrap_argv(m: Mounts, *, venv: Path | None, chdir: str, argv: list[str],
               env: dict[str, str] | None = None, unshare_pid: bool = False) -> list[str]:
    cmd = ["bwrap", "--die-with-parent", "--new-session",
           "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
           "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for link in ("bin", "sbin", "lib", "lib32", "lib64"):
        p = Path("/") / link
        if p.is_symlink():
            cmd += ["--symlink", os.readlink(p), f"/{link}"]
        elif p.is_dir():
            cmd += ["--ro-bind", str(p), f"/{link}"]
    if unshare_pid:
        # Killing bwrap then takes every process the command started with it.
        cmd.append("--unshare-pid")
    if not m.network:
        cmd.append("--unshare-net")
    elif Path("/run/systemd/resolve").is_dir():
        cmd += ["--ro-bind", "/run/systemd/resolve", "/run/systemd/resolve"]
    # Interpreters the venvs point at, and the uv binary for tasks that call it.
    pydir = _uv_python_dir()
    if pydir:
        cmd += ["--ro-bind", str(pydir), str(pydir)]
    path = ["/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"]
    uv = shutil.which("uv")
    if uv:
        cmd += ["--ro-bind", uv, "/opt/harness-bin/uv"]
        path.insert(0, "/opt/harness-bin")
    if venv:
        cmd += ["--bind" if (venv / ".private").exists() else "--ro-bind", str(venv), str(venv)]
        path.insert(0, str(venv / "bin"))
    for d in m.dirs:
        cmd += ["--dir", d]
    for host, target, writable in m.binds:
        cmd += ["--bind" if writable else "--ro-bind", str(host), target]
    full_env = {"PATH": ":".join(path), "HOME": "/tmp", "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    if venv:
        full_env["VIRTUAL_ENV"] = str(venv)
    cmd += ["--clearenv"]
    for k, v in full_env.items():
        cmd += ["--setenv", k, v]
    cmd += ["--chdir", chdir, *argv]
    return cmd


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def die_with_parent() -> None:
    """``preexec_fn``: the child gets SIGTERM when the harness dies, however it
    dies. Servers run in their own session (so Ctrl+C reaches them only
    through the harness's orderly stop) and would otherwise outlive a killed
    harness — an orphaned exec server was found running for hours."""
    import ctypes
    import signal

    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, int(signal.SIGTERM))  # PR_SET_PDEATHSIG
    except Exception:  # noqa: BLE001 — not Linux: orderly stop still applies
        pass


def wait_http(url: str, proc: subprocess.Popen, log: Path, seconds: float = 60,
              what: str | None = None) -> None:
    """Wait for ``url`` to answer; with ``what``, say so while waiting."""
    import time
    import urllib.request

    started = time.time()
    deadline = started + seconds
    said = 0.0
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{what or url} exited {proc.returncode}; see {log}")
        try:
            urllib.request.urlopen(url, timeout=2)
            if what:
                print(f"[bench] {what} is up ({time.time() - started:.0f}s)", flush=True)
            return
        except OSError:
            if what and time.time() - said >= 15:
                said = time.time()
                print(f"[bench] waiting for {what}… {said - started:.0f}s "
                      f"(log: {log})", flush=True)
            time.sleep(0.5)
    kill_group(proc)
    raise RuntimeError(f"{what or url} did not come up in {seconds:.0f}s; see {log}")


def start_exec_server(workspace_root: Path, log: Path) -> tuple[subprocess.Popen, str]:
    """The jailed code-exec server (``exec_server.py``) for workspaces under
    ``workspace_root``. Returns (process, base url)."""
    import sys

    from .tasks import PROJECT_ROOT

    if not have("bwrap"):
        raise RuntimeError("isolation needs bwrap; pass --isolation none to run unjailed")
    port = free_port()
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "benchmarks.harness.exec_server", str(workspace_root), str(port)],
        cwd=PROJECT_ROOT, stdout=log.open("w"), stderr=subprocess.STDOUT, start_new_session=True,
        preexec_fn=die_with_parent)
    url = f"http://127.0.0.1:{port}"
    wait_http(url + "/health", proc, log)
    return proc, url


def run_logged(argv: list[str], log: Path, timeout: float) -> tuple[int | None, bool]:
    """Run, tee everything to ``log``; returns (exit code, timed_out)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        fh.write("$ " + " ".join(argv) + "\n\n")
        fh.flush()
        proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            return proc.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            kill_group(proc)
            return None, True


def kill_group(proc: subprocess.Popen, grace: float = 20.0) -> None:
    import signal

    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue
