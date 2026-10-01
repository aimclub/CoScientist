"""``python -m benchmarks.harness <command>`` — run from the repository root
with the project venv (``.venv/bin/python``), so the CoScientist agent imports.

    list                          tasks, their IO and whether they can be graded here
    sync                          regenerate tasks/<name>/io.json
    run [--benchmark B] [--task T] [--agent coscientist|oracle] [--trials K]
        [--parallel N] [--timeout S] [--verifier auto|local|docker|none]
        [--isolation auto|bwrap|none] [--coder auto|openhands|local]
        [--web [--web-port P] [--hitl auto|basic|debug] [--no-keep-web]]
                                  --web: one command — starts the benchmark web server
                                  (unless `serve` is already up), runs the trials through
                                  it, then keeps it open for browsing until Ctrl+C
    serve [--port P] [--hitl …] [--env KEY=VALUE …]
                                  just the benchmark web server (browse past sessions,
                                  or share one server between several runs)
        [--label L] [--env KEY=VALUE ...]
    verify <trial_dir> [--verifier …]   re-grade an existing trial
    report <run_dir>              rewrite summary.md / summary.json
    compare <run_a> <run_b>       fixed / broken between two runs
    backlog                       reviewed feedback → ranked improvement list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report, runner, verifier
from .tasks import iter_tasks, write_io_spec


def _run_path(p: str) -> Path:
    path = Path(p)
    return path if path.exists() else runner.RUNS_DIR / p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m benchmarks.harness",
                                 description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def selection(p):
        p.add_argument("--benchmark", "-b", action="append", default=[])
        p.add_argument("--task", "-t", action="append", default=[])

    selection(sub.add_parser("list"))
    selection(sub.add_parser("sync"))
    r = sub.add_parser("run")
    selection(r)
    r.add_argument("--agent", choices=["coscientist", "oracle"], default="coscientist")
    r.add_argument("--trials", "-k", type=int, default=1)
    r.add_argument("--parallel", "-j", type=int, default=1)
    r.add_argument("--timeout", type=float, help="agent seconds per trial (default: the task's)")
    r.add_argument("--verifier", choices=["auto", "local", "docker", "none"], default="auto")
    r.add_argument("--isolation", choices=["auto", "bwrap", "none"], default="auto",
                   help="jail the agent's shell commands (default: bwrap when available)")
    r.add_argument("--coder", choices=["auto", "openhands", "local"], default="auto",
                   help="where the CoderAgent works (default: CODER__MODE from .env)")
    r.add_argument("--web", action="store_true",
                   help="run through the web UI (uses a running `serve`, else starts one)")
    r.add_argument("--web-port", type=int, default=8765)
    r.add_argument("--no-keep-web", dest="keep_web", action="store_false",
                   help="web mode: stop the server this run started as soon as the run ends "
                        "(default: keep it open for browsing until Ctrl+C)")
    r.add_argument("--hitl", choices=["auto", "basic", "debug"],
                   help="web mode: HITL__MODE for a server this run starts "
                        "(default: the server's own, i.e. ask and wait 10 min)")
    r.add_argument("--label", help="free text, recorded with the run (e.g. 'planner-off')")
    r.add_argument("--run-id")
    r.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                   help="environment override for the agent process (repeatable)")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--isolation", choices=["auto", "bwrap", "none"], default="auto")
    sv.add_argument("--hitl", choices=["auto", "basic", "debug"])
    sv.add_argument("--coder", choices=["auto", "openhands", "local"], default="auto")
    sv.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    v = sub.add_parser("verify")
    v.add_argument("trial_dir", type=Path)
    v.add_argument("--verifier", choices=["auto", "local", "docker"], default="auto")
    rp = sub.add_parser("report")
    rp.add_argument("run")
    c = sub.add_parser("compare")
    c.add_argument("run_a")
    c.add_argument("run_b")
    sub.add_parser("backlog")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for t in iter_tasks(a.benchmark, a.task):
            spec = t.io_spec()
            backend, why = verifier.pick_backend("auto", t)
            print(f"{t.full_name}\n  in : {len(spec['inputs'])} file(s) under "
                  f"{', '.join('/' + r for r in spec['roots'])}"
                  f"\n  out: {', '.join(o['path'] for o in spec['outputs'])}"
                  f"\n  verifier here: {backend}{f' ({why})' if why else ''}"
                  f"\n  budget: {spec['agent_environment']['timeout_sec']:.0f}s, "
                  f"expert estimate {spec['expert_time_estimate_hours']}h")
        return 0
    if a.cmd == "sync":
        for t in iter_tasks(a.benchmark, a.task):
            print(write_io_spec(t))
        return 0
    if a.cmd == "run":
        tasks = iter_tasks(a.benchmark, a.task)
        if not tasks:
            print("no tasks matched", file=sys.stderr)
            return 2
        env = dict(kv.split("=", 1) for kv in a.env)
        opts = {k: getattr(a, k) for k in ("agent", "trials", "parallel", "timeout",
                                           "verifier", "isolation", "label", "run_id",
                                           "web", "web_port", "hitl", "coder", "keep_web")}
        opts["env"] = env
        try:
            run_dir = runner.run(tasks, opts)
        except KeyboardInterrupt:
            return 130
        print((run_dir / "summary.md").read_text())
        return 0
    if a.cmd == "serve":
        import time

        from . import sandbox, webmode

        if webmode.running_server():
            print(f"already running: {webmode.running_server()['url']}")
            return 0
        isolation = a.isolation if a.isolation != "auto" else (
            "bwrap" if sandbox.have("bwrap") else "none")
        from . import sandbox_io

        coder = sandbox_io.coder_mode() if a.coder == "auto" else a.coder
        procs, info = webmode.serve(a.port, isolation=isolation, hitl=a.hitl, coder=coder,
                                    env_overrides=dict(kv.split("=", 1) for kv in a.env))
        print(f"benchmark web server: {info['url']}  (coder={coder}, isolation={info['isolation']}, "
              f"hitl={a.hitl or 'server default'})\n"
              f"runs started with --web attach to it; Ctrl+C stops it. "
              f"Logs: {webmode.web_home() / 'logs'}")
        try:
            while all(p.poll() is None for p in procs):
                time.sleep(2)
            print("a server process exited; see the logs", file=sys.stderr)
        except KeyboardInterrupt:
            pass
        finally:
            webmode.stop(procs)
        return 0
    if a.cmd == "verify":
        res = runner.reverify(a.trial_dir.resolve(), a.verifier)
        print(f"reward={res['verifier'].get('reward')} outcome={res['analysis']['outcome']} "
              f"error={res['verifier'].get('error')}")
        return 0
    if a.cmd == "report":
        run_dir = _run_path(a.run)
        report.summarize(run_dir)
        print((run_dir / "summary.md").read_text())
        return 0
    if a.cmd == "compare":
        print(report.compare(_run_path(a.run_a), _run_path(a.run_b)))
        return 0
    if a.cmd == "backlog":
        text = report.backlog(runner.RUNS_DIR)
        (runner.RUNS_DIR / "backlog.md").parent.mkdir(parents=True, exist_ok=True)
        (runner.RUNS_DIR / "backlog.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
