#!/usr/bin/env python3
"""Build an isolated MCP tool container from a GitHub repository.

Flow:
  1. Build ``alembic-base:latest`` (Dockerfile under ``docker/alembic/``)
     if it is not already present locally.
  2. Run a *build* container that executes the alembic pipeline against
     ``<repo_url>``. The pipeline clones, sets up a venv, generates
     ``server.py`` and validates it — all inside the container.
  3. On successful exit, ``docker commit`` the container to
     ``alembic-tool:<repo-name>``. The "improved" image now carries the
     cloned repo, its venv and the generated FastMCP server.
  4. Launch the committed image with a random host port mapped to the
     container's ``$MCP_PORT`` so the MCP server is reachable from the host.

Any of this can happen on another machine: ``--context`` picks a remote Docker
daemon, the served address is derived from that daemon rather than hardcoded to
localhost, and a ``--mount-dir`` is staged into a daemon-side volume, because a
bind mount resolves on the daemon's filesystem and a local path is not there.

Run from anywhere:
    python CoScientist/alembic/start_chain.py <repo_url>
"""
from __future__ import annotations

import argparse
import os
import platform
import random
import secrets
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic.common import BASE_IMAGE, get_repo_name, ensure_base_image
from alembic.remote import (
    advertised_url,
    build_stage_commands,
    context_endpoint,
    host_from_endpoint,
    needs_remote_staging,
    resolve_advertise_host,
    serve_mount_args,
    stage_volume_name,
)
from alembic.targets import detect_gpu, docker_cli, docker_env

# /<root>/CoScientist/alembic/start_chain.py -> /<root>
PROJECT_ROOT     = Path(__file__).resolve().parents[2]
BASE_DOCKERFILE  = PROJECT_ROOT / "docker" / "alembic" / "Dockerfile"
TOOL_REPO        = "alembic-tool"
# Stamped on every build/serve container so a log viewer pointed at a shared
# daemon can filter to ours instead of showing every container on the host.
PROJECT_LABEL    = "project=coscientist"
PORT_RANGE       = (20000, 30000)
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

PASSTHROUGH_ENV = (
    # LLM / agent providers
    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY",
    "GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
    "MODEL", "MODEL_TEMPERATURE", "MODEL_TOP_P",
    "ALEMBIC_TARGET_TASK", "ALEMBIC_TASKS", "ALEMBIC_HINTS", "STAGE_RESET", "DEBUGGING_ROUNDS",
    "MCP_URLS", "OR_APP_NAME", "FEDOTMAS_DEFAULT_MODEL",
    # HuggingFace — needed by ToolMaker subset (CONCH, UNI, MUSK, ...)
    "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_HUB_TOKEN",
    # TabPFN gated model access
    "TABPFN_TOKEN",
    # Wandb — some train/finetune tools call wandb.init at import time.
    # Set WANDB_MODE=offline to disable without leaking the key.
    "WANDB_API_KEY", "WANDB_MODE",
)


def _redact_cmd(cmd: list[str]) -> str:
    """Render a command for logging with every ``-e KEY=VALUE`` value masked.

    ``_run`` launches containers with dozens of secrets (API keys, DB
    passwords) passed via ``-e`` (see ``_env_args``) — printing them verbatim
    leaks them into the per-repo log files run_benchmark.py captures on disk
    (and from there into anything that reads those logs).
    """
    parts = []
    redact_next = False
    for part in cmd:
        if redact_next:
            key = part.split("=", 1)[0]
            parts.append(f"{key}=***")
            redact_next = False
        else:
            parts.append(part)
            redact_next = part == "-e"
    return " ".join(parts)


# The API version the selected daemon needs, set once from --api-version. It is
# applied per call rather than exported, because a pin an old daemon requires is
# rejected by a newer one, and a process-wide value would make one of the two
# unreachable.
_API_VERSION: str | None = None


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"[start-chain] $ {_redact_cmd(cmd)}", flush=True)
    kw.setdefault("env", docker_env(api_version=_API_VERSION))
    return subprocess.run(cmd, **kw)


def _default_platform() -> str | None:
    """linux/amd64 on Apple Silicon so old x86-only wheels (dgl 0.9, etc.)
    pull and run via Rosetta. Native everywhere else (None = no flag)."""
    if sys.platform == "darwin" and platform.machine() in ("arm64", "aarch64"):
        return "linux/amd64"
    return None


def _random_port() -> int:
    return random.randint(*PORT_RANGE)


def _env_args(env_file: Path | None) -> list[str]:
    args: list[str] = []
    if env_file and env_file.exists():
        for k, v in dotenv_values(env_file).items():
            if v is not None:
                args += ["-e", f"{k}={v}"]
    for var in PASSTHROUGH_ENV:
        if var in os.environ:
            args += ["-e", f"{var}={os.environ[var]}"]
    return args


def _volume_exists(context: str | None, volume: str) -> bool:
    """True if the named volume is already on the target daemon, so a
    pre-staged one can skip the copy."""
    return subprocess.run(
        [*docker_cli(context=context), "volume", "inspect", volume],
        capture_output=True,
    ).returncode == 0


def _mount_args(repo: str, ns: argparse.Namespace) -> list[str]:
    """The ``-v`` arguments for the data directory, staging it first if needed.

    A bind mount resolves on the *daemon's* filesystem. Against a remote daemon
    the local path simply does not exist, so the data is copied into a
    daemon-side volume once and mounted from there. ``--stage-volume`` names
    that volume so a large dataset can be staged once and reused.
    """
    if not ns.mount_dir:
        return []
    local_dir = str(Path(ns.mount_dir).resolve())
    volume = None
    if needs_remote_staging(ns.context, context_endpoint(ns.context)):
        volume = ns.stage_volume or stage_volume_name(repo, secrets.token_hex(3))
        if not (ns.stage_volume and _volume_exists(ns.context, volume)):
            print(f"[start-chain] staging {local_dir} -> volume {volume}", flush=True)
            for cmd in build_stage_commands(ns.context, BASE_IMAGE, volume, local_dir):
                r = _run(cmd)
                if r.returncode != 0:
                    sys.exit(r.returncode)
    return serve_mount_args(context=ns.context, mount_dir=local_dir, volume=volume)


def build_image(repo_url: str, ns: argparse.Namespace) -> str:
    repo       = get_repo_name(repo_url)
    cname      = f"alembic-build-{repo}-{secrets.token_hex(3)}"
    tool_image = f"{TOOL_REPO}:{repo}"

    cmd = [*docker_cli(context=ns.context), "run", "--name", cname,
           "--label", PROJECT_LABEL]
    if ns.platform:
        cmd += ["--platform", ns.platform]
    if ns.gpus:
        cmd += ["--gpus", ns.gpus]
    cmd += _mount_args(repo, ns)
    # Bind-mount a host-side workdir into the container's ALEMBIC_WORKDIR so
    # the pipeline's on-disk artifacts (exploration.md, plan.json, output/*)
    # survive after the build container exits. Used by the web UI to render
    # per-job reports; opt-in via env so nothing changes when unset.
    host_workdir = os.environ.get("ALEMBIC_HOST_WORKDIR")
    if host_workdir:
        Path(host_workdir).mkdir(parents=True, exist_ok=True)
        cmd += ["-v", f"{host_workdir}:/work/.alembic"]
    cmd += _env_args(ns.env_file)
    # A soft hint reaches the pipeline through the environment, like the rest of
    # the ALEMBIC_* settings.
    if getattr(ns, "hints", None):
        cmd += ["-e", f"ALEMBIC_HINTS={ns.hints}"]
    cmd += [BASE_IMAGE, "build", repo_url]
    if ns.resume:
        cmd += ["--resume", ns.resume]
    if ns.until:
        cmd += ["--until", ns.until]

    r = _run(cmd)
    if r.returncode != 0:
        sys.stderr.write(
            f"\n[start-chain] pipeline failed (exit {r.returncode}).\n"
            f"  Container kept for inspection: {cname}\n"
            f"  Inspect:  docker logs {cname}\n"
            f"  Shell:    docker commit {cname} alembic-debug:{repo} "
            f"&& docker run --rm -it --entrypoint /bin/bash alembic-debug:{repo}\n"
            f"  Cleanup:  docker rm {cname}\n"
        )
        sys.exit(r.returncode)

    # ── Pre-commit cleanup — keep secrets out of the saved image ──────
    # 1. Wipe pipeline.log inside the container; agent stderr may have
    #    echoed API keys passed at build time.
    _run(
        [*docker_cli(context=ns.context), "exec", cname, "sh", "-c",
         "rm -f /work/.alembic/*/pipeline.log"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # 2. Build --change="ENV KEY=" for every sensitive var so it is
    #    blanked in the committed image's Config.Env. Without this,
    #    `docker inspect <image>` exposes every key passed via -e or
    #    --env-file during build. Serve container still gets real
    #    values at run-time via its own --env-file.
    keys_to_scrub: set[str] = set(PASSTHROUGH_ENV)
    if ns.env_file and Path(ns.env_file).exists():
        for line in Path(ns.env_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                keys_to_scrub.add(line.split("=", 1)[0].strip())
    change_args: list[str] = []
    for key in sorted(keys_to_scrub):
        change_args += ["--change", f"ENV {key}="]

    print(f"[start-chain] committing {cname} -> {tool_image}")
    c = _run([*docker_cli(context=ns.context), "commit", *change_args, cname, tool_image])
    if c.returncode != 0:
        sys.exit(c.returncode)
    _run([*docker_cli(context=ns.context), "rm", cname],
         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tool_image


def serve_image(repo_url: str, tool_image: str, ns: argparse.Namespace) -> None:
    repo  = get_repo_name(repo_url)
    port  = _random_port()
    cname = f"alembic-serve-{repo}-{secrets.token_hex(3)}"

    cmd = [*docker_cli(context=ns.context), "run", "-d", "--name", cname,
           "--label", PROJECT_LABEL, "-p", f"{port}:8000"]
    if ns.platform:
        cmd += ["--platform", ns.platform]
    if ns.gpus:
        cmd += ["--gpus", ns.gpus]
    cmd += _mount_args(repo, ns)
    cmd += _env_args(ns.env_file)
    cmd += [tool_image, "serve", repo_url]

    r = _run(cmd)
    if r.returncode != 0:
        sys.exit(r.returncode)

    host = resolve_advertise_host(
        explicit=ns.advertise_host,
        context_host=host_from_endpoint(context_endpoint(ns.context)),
        a2a_host=os.environ.get("A2A_HOST"),
    )
    print(
        "\n[start-chain] MCP server up.\n"
        f"  image     : {tool_image}\n"
        f"  container : {cname}\n"
        f"  url       : {advertised_url(host, port)}\n"
        f"  logs      : docker logs -f {cname}\n"
        f"  stop      : docker stop {cname} && docker rm {cname}\n"
        f"  relaunch  : docker run -d -p <port>:8000 {tool_image} serve {repo_url}"
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="start_chain",
        description="Build a fully isolated MCP tool container from a GitHub repo.",
    )
    ap.add_argument("repo_url", help="GitHub repository URL")
    ap.add_argument("--rebuild-base", action="store_true",
                    help="Force rebuild of alembic-base:latest")
    ap.add_argument("--gpus", default=None,
                    help='Docker --gpus value, e.g. "all". Off by default.')
    ap.add_argument("--platform", default=None,
                    help='Docker --platform value, e.g. "linux/amd64". '
                         'Auto-set to linux/amd64 on Apple Silicon so x86-only '
                         'wheels (dgl, old torchvision, etc.) run via Rosetta. '
                         'Pass "native" to force the host architecture.')
    ap.add_argument("--resume", default=None,
                    choices=("explorer", "environment", "coder", "validator", "wrapper"),
                    help="Resume the alembic pipeline from a specific stage")
    ap.add_argument("--until", default=None,
                    choices=("explorer", "environment", "coder", "validator", "wrapper"),
                    help="Stop the pipeline after completing this stage "
                         "(e.g. --until explorer runs only exploration). "
                         "Forwarded to alembic.main; implies no serve unless "
                         "it is 'wrapper'.")
    ap.add_argument("--hints", default=None,
                    help="Free-text steer for the explorer: the kind of tool you "
                         "hope to see among the others. No forced signature and "
                         "no gate. Same as setting ALEMBIC_HINTS.")
    ap.add_argument("--mount-dir", default=None,
                    help="Host directory bind-mounted read-only at /mount/data "
                         "inside the build container (TM-Bench input data).")
    ap.add_argument("--no-serve", action="store_true",
                    help="Build and commit only; do not launch the MCP server")
    ap.add_argument("--context", default=None,
                    help="Docker context to build and serve on (a remote daemon). "
                         "Default: the local daemon.")
    ap.add_argument("--api-version", default=None,
                    help="Docker API version this daemon needs (e.g. 1.43 for an "
                         "older remote host). Applied to this run's docker calls "
                         "only; a pin a newer daemon rejects would otherwise make "
                         "it unreachable.")
    ap.add_argument("--advertise-host", default=None,
                    help="Host name to advertise the served MCP at. Default: "
                         "derived from the context's endpoint, then $A2A_HOST, "
                         "then localhost.")
    ap.add_argument("--stage-volume", default=None,
                    help="Name of the daemon-side volume to stage --mount-dir "
                         "into on a remote context. A volume that already "
                         "exists is reused, skipping the copy.")
    ap.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE,
                    help=f"Path to .env to inject (default: {DEFAULT_ENV_FILE})")
    return ap.parse_args()


def main() -> None:
    ns = parse_args()
    global _API_VERSION
    _API_VERSION = ns.api_version
    if ns.platform is None:
        ns.platform = _default_platform()
        if ns.platform:
            print(f"[start-chain] Apple Silicon detected — defaulting to "
                  f"--platform {ns.platform} (Rosetta). "
                  f"Pass --platform native to override.")
    elif ns.platform == "native":
        ns.platform = None
    if ns.gpus is None and detect_gpu(ns.context, env=docker_env(api_version=_API_VERSION)):
        ns.gpus = "all"
        where = f" on {ns.context}" if ns.context else ""
        print(f"[start-chain] GPU detected{where} — passing --gpus all.")
    ensure_base_image(BASE_DOCKERFILE, PROJECT_ROOT,
                      platform=ns.platform, rebuild=ns.rebuild_base,
                      context=ns.context)
    image = build_image(ns.repo_url, ns)
    if ns.no_serve:
        return
    if ns.until and ns.until != "wrapper":
        print(f"[start-chain] --until {ns.until}: not serving "
              f"(server.py is only produced by the wrapper stage).")
        return
    serve_image(ns.repo_url, image, ns)


if __name__ == "__main__":
    main()
