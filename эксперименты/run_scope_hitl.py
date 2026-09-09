#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the PCSK9 prompt four times with different pipeline-scope HITL choices.

Each variant writes into its own folder under эксперименты/scope_hitl_pcsk9/.
Scope SELECT/form are scripted; every other HITL is auto-approved so the run
is unattended.

Usage:
  uv run python эксперименты/run_scope_hitl.py              # all four, sequential
  uv run python эксперименты/run_scope_hitl.py skip         # one variant
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ROOT = Path(os.environ.get("SCOPE_HITL_ROOT") or (HERE / "scope_hitl_pcsk9"))
PROMPT = (
    os.environ.get("SCOPE_HITL_PROMPT")
    or (
        "Can you suggest molecules that inhibit Proprotein Convertase "
        "Subtilisin/Kexin Type 9 with enhanced bioavailability and the ability "
        "to cross the BBB?"
    )
).strip()
TIMEOUT_S = 4800

# form_values keys must match CoScientist.hitl.pipeline_scope.LANES / FORM_BLOCK.
FORM_BLOCK = "пункты пайплайна"
VARIANTS = {
    "skip": {
        "selected": "пропустить",
        "form_values": None,
        "note": "HITL skip — orchestrator picks a basket as today",
    },
    "research": {
        "selected": "свой набор",
        "form_values": {FORM_BLOCK: {"research": "да"}},
        "note": "custom: ResearchAgent only",
    },
    "experiments": {
        "selected": "свой набор",
        "form_values": {FORM_BLOCK: {"experiments": "да"}},
        "note": "custom: ExperimentModuleAgent only",
    },
    "research_experiments": {
        "selected": "свой набор",
        "form_values": {FORM_BLOCK: {"research": "да", "experiments": "да"}},
        "note": "custom: ResearchAgent then ExperimentModuleAgent",
    },
}


def load_base_env(out: Path, variant: str) -> dict[str, str]:
    env = os.environ.copy()
    env_file = REPO / ".env" if (REPO / ".env").is_file() else REPO / "CoScientist" / ".env"
    for key, val in dotenv_values(env_file).items():
        if val is not None and key not in env:
            env[key] = val
    env.pop("SESSION_ID", None)
    env["SESSION_ID"] = f"scope_{variant}_{int(time.time())}"
    env["COSCIENTIST_CONFIG"] = str(REPO / "CoScientist" / "agents" / "experiments.yaml")
    env["HITL__ENABLED"] = "true"
    env["ORCHESTRATOR__SCOPE_HITL"] = "true"
    env["COSCIENTIST_EXPERIMENT_HITL_AUTO_APPROVE"] = "1"
    env["COSCIENTIST_EXPERIMENT_AUDIT_STDOUT"] = "1"
    env["EXPERIMENTS__ROUTE_FEDOT"] = "true"
    env["EXPERIMENTS__ROUTE_ALEMBIC"] = "false"
    env["HYPOTHESES__MAX_ACTIVE"] = "2"
    env["EXPERIMENTS__MAX_GENERATE_NUM"] = "3"
    env["EXPERIMENTS__MAX_PLAN_TASKS"] = "8"
    env["COSCIENTIST_FEDOT_TIMEOUT_S"] = "1200"
    env["GRAPH_SNAPSHOT_DIR"] = str(out / "graph_runs")
    env["RESEARCH_GRAPH_DIR"] = str(out / "graph_runs")
    artifacts = out / "artifacts"
    reports = out / "reports"
    artifacts.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    env["EXPERIMENTS__ARTIFACTS_DIR"] = str(artifacts)
    env["EXPERIMENTS__REPORTS_DIR"] = str(reports)
    env["REPORTS_ROOT"] = str(reports)
    env["SESSION_SNAPSHOTS_DIR"] = str(out / "session_snapshots")
    env["PYTHONPATH"] = str(REPO) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["LLM__CODER_MODEL"] = "openai/deepseek-v3.2"
    return env


def extract_plan(log_text: str, out: Path) -> None:
    marker = "EXPERIMENT_DESIGN_MATRIX\n"
    if marker not in log_text:
        return
    body = log_text.split(marker, 1)[1]
    cut = re.search(r"\n(?:EXPERIMENT_|INFO:|\x1b\[)", body)
    text = body[: cut.start()] if cut else body[:8000]
    (out / "plan.md").write_text(text.strip() + "\n", encoding="utf-8")


class ScopeScriptHandler:
    """Answer pipeline-scope HITL; auto-approve everything else."""

    def __init__(self, selected: str, form_values: dict | None, log: list):
        from CoScientist.hitl.pipeline_scope import OPTION_CUSTOM, OPTION_SKIP, SELECT_OPTIONS
        from CoScientist.hitl.models import HITLAction, HITLResponse

        self.selected = selected
        self.form_values = form_values
        self.log = log
        self._SELECT_OPTIONS = set(SELECT_OPTIONS)
        self._OPTION_CUSTOM = OPTION_CUSTOM
        self._HITLAction = HITLAction
        self._HITLResponse = HITLResponse
        self._FORM_BLOCK = FORM_BLOCK

    async def handle_request(self, request):
        payload = {
            "agent_name": request.agent_name,
            "action_type": request.action_type.value,
            "message": request.message[:300],
            "options": list(request.options or []),
            "has_form": bool(request.form),
        }
        options = set(request.options or [])
        if request.action_type == self._HITLAction.SELECT and options == self._SELECT_OPTIONS:
            payload["handled_as"] = "scope_select"
            payload["selected_option"] = self.selected
            self.log.append(payload)
            return self._HITLResponse(
                action=self._HITLAction.SELECT,
                approved=True,
                selected_option=self.selected,
            )
        blocks = ((request.form or {}).get("blocks") or []) if request.form else []
        titles = {block.get("title") for block in blocks}
        if request.form and self._FORM_BLOCK in titles:
            payload["handled_as"] = "scope_form"
            payload["form_values"] = self.form_values
            self.log.append(payload)
            return self._HITLResponse(
                action=self._HITLAction.APPROVE,
                approved=True,
                form_values=self.form_values,
            )
        payload["handled_as"] = "auto_approve"
        self.log.append(payload)
        return self._HITLResponse(action=self._HITLAction.APPROVE, approved=True)


async def _worker_async(variant: str, out: Path) -> dict:
    from CoScientist.agents.common import hitl_handler
    from CoScientist.main import CoScientistManager

    spec = VARIANTS[variant]
    hitl_log: list = []
    handler = ScopeScriptHandler(spec["selected"], spec["form_values"], hitl_log)
    hitl_handler.set_delegate(handler)
    manager = CoScientistManager(
        hitl_handler=handler,
        session_id=os.environ["SESSION_ID"],
        user_id=f"scope_hitl_{variant}",
    )
    await manager.initialize()
    state_scope = None
    result = None
    try:
        result = await manager.run(PROMPT)
        session = await manager.session_service.get_session(
            app_name=manager.app_name,
            user_id=manager.user_id,
            session_id=manager.session_id,
        )
        state = dict(getattr(session, "state", None) or {}) if session else {}
        state_scope = {
            "pipeline_scope": state.get("pipeline_scope"),
            "pipeline_scope_directive": state.get("pipeline_scope_directive"),
        }
    finally:
        await manager.close()
    (out / "hitl.json").write_text(
        json.dumps(
            {"events": hitl_log, "state": state_scope},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    text = getattr(result, "markdown", None) or str(result)
    (out / "final_response.md").write_text(str(text) + "\n", encoding="utf-8")
    report_dir = getattr(result, "report_dir", None)
    return {
        "hitl_events": len(hitl_log),
        "report_dir": str(report_dir) if report_dir else None,
        "state_scope": state_scope,
    }


def run_worker(variant: str) -> int:
    spec = VARIANTS[variant]
    out = ROOT / variant
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.txt").write_text(PROMPT + "\n", encoding="utf-8")
    (out / "scope.json").write_text(
        json.dumps(
            {
                "variant": variant,
                "selected": spec["selected"],
                "form_values": spec["form_values"],
                "note": spec["note"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    started = time.time()
    import asyncio

    extra = asyncio.run(_worker_async(variant, out))
    elapsed = time.time() - started
    payload = {
        "id": variant,
        "session": os.environ.get("SESSION_ID"),
        "elapsed_s": round(elapsed, 1),
        "rc": 0,
        "timed_out": False,
        **extra,
    }
    (out / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


def run_one_subprocess(variant: str) -> int:
    spec = VARIANTS[variant]
    out = ROOT / variant
    out.mkdir(parents=True, exist_ok=True)
    env = load_base_env(out, variant)
    log_path = out / "console.log"
    started = time.time()
    print(f"START variant={variant} session={env['SESSION_ID']} out={out}", flush=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as fh:
        fh.write(
            f"# variant={variant}\n# session={env['SESSION_ID']}\n"
            f"# note={spec['note']}\n# timeout={TIMEOUT_S}\n{'=' * 72}\n"
        )
        fh.flush()
        proc = subprocess.Popen(
            ["uv", "run", "python", str(Path(__file__).resolve()), "--worker", variant],
            cwd=str(REPO),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        timed_out = False
        rc = None
        while True:
            if time.time() - started > TIMEOUT_S:
                timed_out = True
                note = "\n[runner] TIMEOUT — killing process\n"
                fh.write(note)
                print(note, end="", flush=True)
                proc.kill()
                rc = -9
                break
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                rc = proc.returncode
                break
            if line:
                fh.write(line)
                fh.flush()
                sys.stdout.write(line)
                sys.stdout.flush()
        elapsed = time.time() - started
        footer = f"\n# DONE elapsed={elapsed:.1f}s rc={rc} timed_out={timed_out}\n"
        fh.write(footer)
        print(footer, end="", flush=True)
    extract_plan(log_path.read_text(encoding="utf-8", errors="replace"), out)
    run_meta = out / "run.json"
    if run_meta.is_file():
        meta = json.loads(run_meta.read_text(encoding="utf-8"))
        meta["timed_out"] = timed_out
        meta["rc"] = rc
        meta["elapsed_s"] = round(elapsed, 1)
        run_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        run_meta.write_text(
            json.dumps(
                {
                    "id": variant,
                    "session": env["SESSION_ID"],
                    "elapsed_s": round(elapsed, 1),
                    "rc": rc,
                    "timed_out": timed_out,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if rc == 0 and not timed_out else 1


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--worker"]:
        if len(args) != 2 or args[1] not in VARIANTS:
            raise SystemExit(f"usage: {sys.argv[0]} --worker {{{'|'.join(VARIANTS)}}}")
        return run_worker(args[1])
    names = list(VARIANTS) if not args else args
    unknown = [name for name in names if name not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variants {unknown}; choose from {list(VARIANTS)}")
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "prompt.txt").write_text(PROMPT + "\n", encoding="utf-8")
    failed = 0
    for name in names:
        failed += 0 if run_one_subprocess(name) == 0 else 1
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
