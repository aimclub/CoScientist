"""One CoScientist trial, in its own process.

The parent (``runner``) prepares the trial directory and environment, starts
``python -m benchmarks.harness.worker <trial_dir>/worker.json`` in a new
process group and kills the group at the deadline. A process per trial is not
optional: several CoScientist settings (the pinned coder workspace among them)
are read once at import time, and a timed-out run must take its shell jobs
down with it.

Writes, inside the trial directory:
  config.json             the settings the system actually ran with (secrets redacted)
  output/final_report.md  the system's answer text
  output/report/          the packaged report folder, when one was produced
  metrics.json            usage ledger (also checkpointed during the run)
  trace/events.jsonl      structured trace (BenchTracePlugin)
  trace/hitl.jsonl        every human-in-the-loop request, auto-approved
  worker_result.json      exit status of the run itself
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

_SECRET_KEY = re.compile(r"(key|token|secret|passw|credential|auth|cookie)", re.I)


def redact(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key) for v in value]
    if _SECRET_KEY.search(key) and value not in (None, "", False, True) and not isinstance(value, (int, float)):
        return "<redacted>"
    if isinstance(value, str):
        return re.sub(r"(://)[^/@\s]+@", r"\1<redacted>@", value)
    return value


def _settings_dump() -> dict:
    from CoScientist.config import get_settings

    return redact(json.loads(get_settings().model_dump_json()))


def _make_hitl_handler(log_path: Path):
    from CoScientist.hitl import AbstractHITLHandler, HITLResponse
    from CoScientist.hitl.models import HITLAction, HITLDecisionSource

    class RecordingAutoApprove(AbstractHITLHandler):
        """No human in a benchmark: approve, pick the default, and keep a record —
        how often the system wanted a human is itself worth measuring."""

        async def handle_request(self, request):
            option = request.default_option or (request.options[0] if request.options else None)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.time(), "agent": request.agent_name,
                                     "action": request.action_type.value,
                                     "trigger": request.trigger, "message": request.message[:2000],
                                     "options": request.options, "chosen": option},
                                    ensure_ascii=False) + "\n")
            action = request.action_type
            return HITLResponse(
                action=HITLAction.SELECT if action == HITLAction.SELECT else HITLAction.APPROVE,
                selected_option=option, approved=True,
                decision_source=HITLDecisionSource.MODE_AUTO,
                system_reason="benchmark run: no operator",
            )

        async def notify(self, payload: dict) -> None:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.time(), "notice": payload.get("kind"),
                                     "agent": payload.get("agent_name")}, default=str) + "\n")

    return RecordingAutoApprove()


async def _bound_sandbox(manager) -> str | None:
    """The OpenHands sandbox the session ended bound to, where its files are."""
    try:
        from CoScientist.tools.coder_tools.openhands_sandbox import SESSION_STATE_KEY

        session = await manager.session_service.get_session(
            app_name=manager.app_name, user_id=manager.user_id, session_id=manager.session_id)
        return (session.state.get(SESSION_STATE_KEY) if session else None) or None
    except Exception:  # noqa: BLE001
        return None


async def _main(spec: dict) -> dict:
    trial = Path(spec["trial_dir"])
    out = trial / "output"
    out.mkdir(parents=True, exist_ok=True)
    (trial / "config.json").write_text(json.dumps(
        {"harness": spec, "settings": _settings_dump()}, indent=2, default=str))

    from CoScientist.main import CoScientistManager

    from benchmarks.harness.trace_plugin import BenchTracePlugin

    key = (spec["user_id"], spec["session_id"])
    tracer = BenchTracePlugin(trial / "trace" / "events.jsonl", trial / "metrics.json", key)
    manager = CoScientistManager(
        app_name="coscientist_bench",
        user_id=spec["user_id"], session_id=spec["session_id"],
        hitl_handler=_make_hitl_handler(trial / "trace" / "hitl.jsonl"),
        plugins=[tracer],
        # e.g. the task inputs as the session's dataset archive (OpenHands coder)
        initial_state=spec.get("initial_state") or {},
    )
    status: dict[str, Any] = {"status": "ok"}
    try:
        result = await manager.run(spec["prompt"], verbose=False)
        (out / "final_report.md").write_text(result.markdown or "", encoding="utf-8")
        if result.report_dir and Path(result.report_dir).is_dir():
            shutil.copytree(result.report_dir, out / "report", dirs_exist_ok=True)
            status["report_dir"] = str(result.report_dir)
        if manager._run_error is not None:
            status.update(status="run_error", error=f"{type(manager._run_error).__name__}: "
                                                    f"{manager._run_error}"[:2000])
    except BaseException as exc:  # noqa: BLE001 — record, then let the parent decide
        status.update(status="crash", error=f"{type(exc).__name__}: {exc}"[:2000],
                      traceback=traceback.format_exc()[-8000:])
    finally:
        tracer.flush_metrics(force=True)
        status["sandbox_id"] = await _bound_sandbox(manager)
        try:
            await manager.close()
        except Exception:  # noqa: BLE001
            pass
    return status


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    started = time.time()
    status = asyncio.run(_main(spec))
    status["seconds"] = round(time.time() - started, 1)
    Path(spec["trial_dir"], "worker_result.json").write_text(json.dumps(status, indent=2))
    return 0 if status["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
