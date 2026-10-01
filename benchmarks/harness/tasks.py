"""Harbor tasks: loading, the IO contract, workspace seeding, the agent prompt.

A Harbor task is a directory with ``task.toml``, ``instruction.md``,
``environment/Dockerfile`` (the container the agent works in), ``tests/``
(the verifier, normally its own image) and ``solution/`` (the oracle). The
instruction talks in absolute container paths (``/app/data/x.xls``,
``/results/output.json``).

CoScientist does not run inside that container: its CoderAgent executes in a
per-session workspace directory. So the harness maps every container path
``/X/...`` to ``<workspace>/X/...``, seeds the inputs there the way the
Dockerfile's ``COPY`` lines would, rewrites the instruction to relative paths,
and after the run hands the declared ``artifacts`` to the original verifier at
their original absolute paths. Nothing in the upstream task is edited.

``io.json`` (written by ``sync``) is that contract made explicit per task, so
a reviewer can see what goes in and what is graded without reading Dockerfiles.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

BENCHMARKS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BENCHMARKS_DIR.parent

# Container roots that are harness plumbing, never part of the agent's world.
_PLUMBING_ROOTS = {"logs", "tests", "solution", "tmp", "opt", "usr", "etc"}

_PIN_RE = re.compile(r"""["']?([A-Za-z0-9][A-Za-z0-9_.\-\[\]]*==[A-Za-z0-9_.+!\-]+)["']?""")


# ── Dockerfile reading ───────────────────────────────────────────────────────
@dataclass
class DockerfileInfo:
    """The few facts the harness needs from a Dockerfile, nothing more."""

    base_image: str = ""
    workdir: str = "/"
    copies: list[tuple[str, str]] = field(default_factory=list)   # (src, dst)
    copies_from_stage: list[str] = field(default_factory=list)    # COPY --from=…
    mkdirs: list[str] = field(default_factory=list)
    pip_pins: list[str] = field(default_factory=list)
    python: str | None = None
    stages: int = 0

    @classmethod
    def parse(cls, path: Path) -> "DockerfileInfo":
        info = cls()
        if not path.is_file():
            return info
        text = re.sub(r"\\\n", " ", path.read_text(encoding="utf-8"))
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            op, _, rest = line.partition(" ")
            op, rest = op.upper(), rest.strip()
            if op == "FROM":
                # Earlier stages are build helpers; only the last one is the image.
                info.stages += 1
                info.base_image = rest.split()[0]
                info.copies, info.mkdirs, info.pip_pins, info.python = [], [], [], None
            elif op == "WORKDIR":
                info.workdir = rest
            elif op == "COPY":
                parts = rest.split()
                if any(p.startswith("--from") for p in parts):
                    info.copies_from_stage.append(rest)
                    continue
                parts = [p for p in parts if not p.startswith("--")]
                if len(parts) >= 2:
                    for src in parts[:-1]:
                        info.copies.append((src, parts[-1]))
            elif op == "RUN":
                for m in re.finditer(r"mkdir\s+-p\s+([^&;|]+)", rest):
                    info.mkdirs += [p for p in m.group(1).split() if p.startswith("/")]
                if re.search(r"pip3?\s+install", rest):
                    info.pip_pins += [m.group(1) for m in _PIN_RE.finditer(rest)]
                m = re.search(r"--python\s+(\d+\.\d+)", rest)
                if m:
                    info.python = m.group(1)
        info.python = info.python or _python_of(info.base_image)
        return info


def _python_of(image: str) -> str:
    """Python version a base image ships, for building an equivalent venv."""
    m = re.match(r"python:(\d+\.\d+)", image)
    if m:
        return m.group(1)
    if image.startswith("ubuntu:24.04"):
        return "3.12"
    if image.startswith("ubuntu:22.04"):
        return "3.10"
    return "3.11"


# ── Task ─────────────────────────────────────────────────────────────────────
@dataclass
class Task:
    benchmark: str
    name: str
    path: Path
    toml: dict[str, Any]
    instruction: str
    env: DockerfileInfo
    tests: DockerfileInfo

    @property
    def full_name(self) -> str:
        return f"{self.benchmark}/{self.name}"

    @property
    def agent_timeout_sec(self) -> float:
        return float(self.toml.get("agent", {}).get("timeout_sec", 3600))

    @property
    def verifier_timeout_sec(self) -> float:
        return float(self.toml.get("verifier", {}).get("timeout_sec", 600))

    # ── IO contract ──────────────────────────────────────────────────────────
    def outputs(self) -> list[dict[str, str]]:
        """Declared artifacts: what leaves the agent's container for grading."""
        out = []
        for a in self.toml.get("artifacts", []):
            p = a["source"] if isinstance(a, dict) else a
            out.append({"path": p, "kind": "dir" if p.endswith("/") else "file"})
        return out

    def inputs(self) -> list[dict[str, str]]:
        """Every file the environment Dockerfile places in the container."""
        files = []
        ctx = self.path / "environment"
        for src, dst in self.env.copies:
            s = ctx / src.rstrip("/")
            if not s.exists():
                continue
            if s.is_dir():
                for f in sorted(p for p in s.rglob("*") if p.is_file()):
                    files.append({"source": str(f.relative_to(self.path)),
                                  "target": _join(dst, str(f.relative_to(s)))})
            else:
                target = _join(dst, s.name) if dst.endswith("/") else dst
                files.append({"source": str(s.relative_to(self.path)), "target": target})
        return files

    def precreated_dirs(self) -> list[str]:
        dirs = set(self.env.mkdirs)
        dirs.update(str(Path(o["path"]).parent) if o["kind"] == "file"
                    else o["path"].rstrip("/") for o in self.outputs())
        return sorted(d for d in dirs if _root_of(d) not in _PLUMBING_ROOTS)

    def roots(self) -> list[str]:
        """Top-level container dirs the agent's world consists of (``app``…)."""
        paths = [i["target"] for i in self.inputs()] + [o["path"] for o in self.outputs()]
        paths += self.precreated_dirs() + [self.env.workdir]
        return sorted({r for r in map(_root_of, paths) if r and r not in _PLUMBING_ROOTS})

    def verifier_extra_files(self) -> list[dict[str, str]]:
        """Files the verifier image copies OUTSIDE /tests (e.g. reference data)."""
        extra = []
        for src, dst in self.tests.copies:
            if src in (".", "./") or dst.rstrip("/") == "/tests" or dst.startswith("/tests/"):
                continue
            s = self.path / "tests" / src.rstrip("/")
            if s.exists():
                extra.append({"source": str(s.relative_to(self.path)),
                              "target": _join(dst, s.name) if dst.endswith("/") and s.is_file() else dst})
        return extra

    def local_verifier_blockers(self) -> list[str]:
        """Why this verifier cannot be reproduced without its Docker image."""
        reasons = []
        if self.tests.copies_from_stage:
            reasons.append("verifier image copies build-stage outputs "
                           f"({'; '.join(self.tests.copies_from_stage)})")
        if not (self.path / "tests" / "Dockerfile").is_file():
            reasons.append("no tests/Dockerfile")
        return reasons

    def checksum(self) -> str:
        h = hashlib.sha256()
        for f in sorted(p for p in self.path.rglob("*") if p.is_file() and p.name != "io.json"):
            h.update(str(f.relative_to(self.path)).encode())
            h.update(f.read_bytes())
        return h.hexdigest()

    def io_spec(self) -> dict[str, Any]:
        meta = self.toml.get("metadata", {})
        env_cfg = self.toml.get("environment", {})
        ver_cfg = self.toml.get("verifier", {})
        blockers = self.local_verifier_blockers()
        return {
            "task": self.full_name,
            "checksum": self.checksum(),
            "tags": meta.get("tags", []),
            "expert_time_estimate_hours": meta.get("expert_time_estimate_hours"),
            "instruction": "instruction.md",
            "workdir": self.env.workdir,
            "roots": self.roots(),
            "inputs": self.inputs(),
            "precreated_dirs": self.precreated_dirs(),
            "outputs": self.outputs(),
            "agent_environment": {
                "base_image": self.env.base_image,
                "python": self.env.python,
                "packages": self.env.pip_pins,
                "network": env_cfg.get("network_mode", "public"),
                "cpus": env_cfg.get("cpus"),
                "memory_mb": env_cfg.get("memory_mb"),
                "timeout_sec": self.agent_timeout_sec,
            },
            "verifier": {
                "mode": ver_cfg.get("environment_mode", "shared"),
                "entrypoint": "tests/test.sh",
                "base_image": self.tests.base_image,
                "python": self.tests.python,
                "packages": self.tests.pip_pins,
                "workdir": self.tests.workdir,
                "precreated_dirs": sorted(set(self.tests.mkdirs)),
                "extra_files": self.verifier_extra_files(),
                "network": ver_cfg.get("environment", {}).get("network_mode", "public"),
                "timeout_sec": self.verifier_timeout_sec,
                "local_supported": not blockers,
                "local_blockers": blockers,
            },
            "oracle": "solution/solve.sh",
        }

    # ── Agent side ───────────────────────────────────────────────────────────
    def seed_workspace(self, ws: Path) -> list[dict[str, str]]:
        """Lay the container's inputs out in ``ws``; returns them with hashes."""
        seeded = []
        for item in self.inputs():
            dst = ws / item["target"].lstrip("/")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path / item["source"], dst)
            seeded.append({**item, "sha256": _sha256(dst)})
        for d in self.precreated_dirs():
            (ws / d.lstrip("/")).mkdir(parents=True, exist_ok=True)
        return seeded

    def localize(self, text: str, base: str = ".") -> str:
        """Rewrite absolute container paths under ``base`` (``./app/…`` for the
        local workspace, ``/workspace/app/…`` for the OpenHands sandbox)."""
        roots = "|".join(map(re.escape, self.roots()))
        if not roots:
            return text
        return re.sub(rf"(?<![\w.~/-])/({roots})(?=/|\b)", rf"{base}/\1", text)

    def render_prompt(self, timeout_sec: float, coder: str = "local") -> str:
        """The instruction as the system receives it.

        ``coder="local"``: inputs sit in the CoderAgent's own workspace.
        ``coder="openhands"``: inputs travel as the session's dataset archive,
        which the sandbox unpacks into ``/workspace``; outputs must stay there.
        """
        base = "/workspace" if coder == "openhands" else "."
        body = re.sub(r"<!--.*?-->\s*", "", self.instruction, flags=re.S).strip()
        body = re.sub(r"You have \d+ seconds", f"You have {int(timeout_sec)} seconds", body)
        body = self.localize(body, base)
        # Some tasks ship inputs to the verifier as artifacts too; those are not
        # something the agent produces.
        given = {i["target"] for i in self.inputs()}
        outputs = ", ".join(f"`{self.localize(o['path'], base)}`" for o in self.outputs()
                            if o["path"] not in given)
        pkgs = ", ".join(self.env.pip_pins) or "none beyond the standard library"
        mapping = ", ".join(f"`/{r}/…` → `{base}/{r}/…`" for r in self.roots())
        workdir = self.localize(self.env.workdir, base) if self.env.workdir != "/" else base
        if coder == "openhands":
            where = (
                "Execution environment: the work is done in the OpenHands sandbox. "
                "The task's input files are in the dataset archive attached to this "
                "session (`dataset_url`); pass it to the sandbox and it is unpacked "
                "into `/workspace` with the task's layout. Absolute container paths "
                f"were rewritten under `/workspace` ({mapping}); the task's own "
                f"working directory is `{workdir}`.\n"
                f"Graded output: {outputs} — inside the sandbox. An automatic "
                "verifier reads ONLY these paths from the sandbox workspace, exactly "
                "as specified below; files elsewhere, uploads and the written report "
                "are not graded.\n"
            )
        else:
            where = (
                "Execution environment: your code-execution sandbox workspace stands in "
                "for the task's container. Absolute container paths were rewritten "
                f"relative to the workspace root ({mapping}); the working directory of "
                "`execute_bash` is that root. The task's own working directory is "
                f"`{workdir}`. Input files are already in place.\n"
                f"Graded output: {outputs} — an automatic verifier checks ONLY these "
                "paths, exactly as specified below; the written report is not graded.\n"
            )
        return (
            "[Benchmark task — autonomous run. Do not ask questions: make reasonable "
            "assumptions and finish the task.]\n\n"
            f"{where}"
            f"Python {self.env.python} reference packages: {pkgs}. Install what you "
            "need.\n\n"
            "---\n\n"
            f"{body}\n"
        )

def _root_of(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else ""


def _join(base: str, rel: str) -> str:
    return base.rstrip("/") + "/" + rel


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Discovery ────────────────────────────────────────────────────────────────
def benchmark_dirs() -> list[Path]:
    return sorted(p.parent for p in BENCHMARKS_DIR.glob("*/benchmark.toml"))


def load_benchmark(bench_dir: Path) -> dict[str, Any]:
    return tomllib.loads((bench_dir / "benchmark.toml").read_text(encoding="utf-8"))


def load_task(task_dir: Path) -> Task:
    return Task(
        benchmark=task_dir.parent.parent.name,
        name=task_dir.name,
        path=task_dir,
        toml=tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8")),
        instruction=(task_dir / "instruction.md").read_text(encoding="utf-8"),
        env=DockerfileInfo.parse(task_dir / "environment" / "Dockerfile"),
        tests=DockerfileInfo.parse(task_dir / "tests" / "Dockerfile"),
    )


def iter_tasks(benchmarks: Iterable[str] = (), names: Iterable[str] = ()) -> list[Task]:
    """Tasks selected by benchmark name(s) and task name(s); empty = all."""
    benchmarks, names = set(benchmarks), set(names)
    tasks = []
    for bdir in benchmark_dirs():
        if benchmarks and bdir.name not in benchmarks:
            continue
        for tname in load_benchmark(bdir)["selection"]["tasks"]:
            if names and tname not in names and f"{bdir.name}/{tname}" not in names:
                continue
            tasks.append(load_task(bdir / "tasks" / tname))
    return tasks


def write_io_spec(task: Task) -> Path:
    path = task.path / "io.json"
    path.write_text(json.dumps(task.io_spec(), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
