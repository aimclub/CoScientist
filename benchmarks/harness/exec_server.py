"""The CoderAgent's code-exec server, with every command jailed.

Same HTTP contract and the same ``JobRunner`` (blocklist, timeouts, output
caps) as ``CoScientist/code_exec_server``, loaded by file path so the agent
stack and its ``.env`` never load here. The difference: each command runs in
its own bwrap jail that sees the system binaries and ITS session's workspace
only — not this repository (solutions, tests, ``.env``) and not the
workspaces of other trials running next to it.

    python -m benchmarks.harness.exec_server <workspace_root> <port>
"""
from __future__ import annotations

import importlib.util
import shlex
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import sandbox
from .tasks import PROJECT_ROOT

_RUNNER = PROJECT_ROOT / "CoScientist" / "code_exec_server" / "runner.py"
_spec = importlib.util.spec_from_file_location("code_exec_runner", _RUNNER)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["code_exec_runner"] = _mod  # dataclasses resolve annotations through it
_spec.loader.exec_module(_mod)

PKG_CACHE = sandbox.CACHE_DIR / "agent-pkg-cache"


def jail_command(command: str, workspace: Path) -> str:
    """``command`` as a shell line that runs it jailed in ``workspace``."""
    ws = str(workspace.resolve())
    m = sandbox.Mounts(network=True)
    m.bind(Path(ws), ws, writable=True)
    # Package downloads only — shared so trials don't refetch rdkit each time.
    m.bind(PKG_CACHE, str(PKG_CACHE), writable=True)
    argv = sandbox.bwrap_argv(
        m, venv=None, chdir=ws, argv=["bash", "-c", command],
        env={"HOME": ws, "PYTHONUNBUFFERED": "1",
             "UV_CACHE_DIR": str(PKG_CACHE / "uv"), "PIP_CACHE_DIR": str(PKG_CACHE / "pip")},
        unshare_pid=True)
    return shlex.join(argv)


class JailedJobRunner(_mod.JobRunner):
    async def _run(self, job) -> None:
        # The stored command stays the agent's own text; only the process
        # that executes it is wrapped.
        original = job.command
        job.command = jail_command(original, self._workspace_dir(job.workspace_id))
        try:
            await super()._run(job)
        finally:
            job.command = original


class SubmitRequest(BaseModel):
    command: str
    workspace_id: str = "default"
    timeout: int = 7200


def build_app(workspace_root: str) -> FastAPI:
    PKG_CACHE.mkdir(parents=True, exist_ok=True)
    runner = JailedJobRunner(workspace_root=workspace_root)
    app = FastAPI()

    @app.post("/submit")
    async def submit(req: SubmitRequest) -> dict:
        job = runner.submit(req.command, req.workspace_id, req.timeout)
        return {"job_id": job.job_id, "status": job.status.value}

    @app.get("/result")
    async def result(job_id: str) -> dict:
        job = runner.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
        return job.to_dict()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    root, port = sys.argv[1], int(sys.argv[2])
    uvicorn.run(build_app(root), host="127.0.0.1", port=port, log_level="warning")
