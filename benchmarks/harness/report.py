"""Aggregate trials into numbers people can act on.

* ``summarize(run)``   per-task pass rate, partial credit, time and cost, next
                        to the published baseline; outcome and failure counts.
* ``compare(a, b)``    what a change fixed and what it broke.
* ``backlog(runs)``    reviewed feedback forms ranked by component and tag —
                        the list of things to improve, ordered by evidence.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from .tasks import BENCHMARKS_DIR


def _trials(run_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(run_dir.glob("*/*/trial-*/result.json"))]


def _baseline(task_name: str) -> dict | None:
    bench, name = task_name.split("/", 1)
    for f in (BENCHMARKS_DIR / bench / "baselines").glob("*.json"):
        data = json.loads(f.read_text())
        if name in data.get("tasks", {}):
            return {"system": data.get("system", f.stem), **data["tasks"][name]}
    return None


def _avg(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return mean(xs) if xs else None


def _fmt(x, spec: str = ".2f", none: str = "—") -> str:
    return none if x is None else format(x, spec)


def per_task(trials: list[dict]) -> dict[str, dict[str, Any]]:
    by_task: dict[str, list[dict]] = defaultdict(list)
    for t in trials:
        by_task[t["task_name"]].append(t)
    rows = {}
    for name, ts in sorted(by_task.items()):
        rewards = [t["verifier"].get("reward") for t in ts]
        rows[name] = {
            "trials": len(ts),
            "solved": sum(1 for r in rewards if r is not None and r >= 1.0),
            "verified": sum(1 for r in rewards if r is not None),
            "mean_reward": _avg(rewards),
            "mean_partial": _avg([t["analysis"]["partial_score"] for t in ts]),
            "mean_seconds": _avg([t["agent_seconds"] for t in ts]),
            "mean_cost": _avg([t.get("cost_usd") for t in ts]),
            "outcomes": dict(Counter(t["analysis"]["outcome"] for t in ts)),
            "integrity_flags": sum(1 for t in ts if not t["analysis"]["integrity"]["clean"]),
            "baseline": _baseline(name),
        }
    return rows


def summarize(run_dir: Path) -> dict[str, Any]:
    trials = _trials(run_dir)
    meta = json.loads((run_dir / "run.json").read_text()) if (run_dir / "run.json").is_file() else {}
    rows = per_task(trials)
    outcomes = Counter(t["analysis"]["outcome"] for t in trials)
    failed_tests = Counter()
    tool_errors = Counter()
    for t in trials:
        for c in t["analysis"]["failed_tests"]:
            failed_tests[f"{t['task_name'].split('/')[-1]} :: {c['name'].split('::')[-1]}"] += 1
        for name, s in t["analysis"]["trace"]["by_tool"].items():
            tool_errors[name] += s.get("errors", 0)
    n_tasks = len(rows)
    summary = {
        "run_id": run_dir.name,
        "agent": meta.get("agent"),
        "commit": (meta.get("code") or {}).get("commit"),
        "trials": len(trials),
        "tasks": n_tasks,
        "tasks_solved_any": sum(1 for r in rows.values() if r["solved"]),
        "pass_rate": _avg([r["solved"] / r["trials"] for r in rows.values()]) if rows else None,
        "mean_partial": _avg([r["mean_partial"] for r in rows.values()]),
        "total_cost_usd": sum(t.get("cost_usd") or 0 for t in trials),
        "outcomes": dict(outcomes),
        "per_task": rows,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    md = [
        f"# Benchmark run `{run_dir.name}`",
        "",
        f"agent **{meta.get('agent')}** · commit `{(summary['commit'] or '')[:10]}`"
        f"{' (dirty)' if (meta.get('code') or {}).get('dirty_files') else ''}"
        f" · {summary['trials']} trials over {n_tasks} tasks"
        f" · solved {summary['tasks_solved_any']}/{n_tasks}"
        f" · mean tests passed {_fmt(summary['mean_partial'], '.0%')}"
        f" · cost ${summary['total_cost_usd']:.2f}",
        "",
        "| task | solved | mean tests passed | mean time, s | mean cost, $ | outcomes | baseline (reward · tests · s · $) |",
        "|---|:-:|:-:|--:|--:|---|---|",
    ]
    for name, r in rows.items():
        b = r["baseline"]
        base = (f"{b['system']}: {b['reward']:.0f} · {b['tests']['passed']}/{b['tests']['total']}"
                f" · {b['agent_seconds']:.0f} · {b['cost_usd']:.2f}") if b else "—"
        flags = " ⚠" if r["integrity_flags"] else ""
        md.append(f"| {name}{flags} | {r['solved']}/{r['trials']} | {_fmt(r['mean_partial'], '.0%')} "
                  f"| {_fmt(r['mean_seconds'], '.0f')} | {_fmt(r['mean_cost'])} "
                  f"| {', '.join(f'{k}×{v}' for k, v in r['outcomes'].items())} | {base} |")
    md += ["", "## Outcomes", ""] + [f"- `{k}`: {v}" for k, v in outcomes.most_common()]
    if failed_tests:
        md += ["", "## Most failed tests", ""]
        md += [f"- {k}: {v}" for k, v in failed_tests.most_common(15)]
    if any(tool_errors.values()):
        md += ["", "## Tool errors", ""]
        md += [f"- `{k}`: {v}" for k, v in tool_errors.most_common(10) if v]
    if any(r["integrity_flags"] for r in rows.values()):
        md += ["", "⚠ Some trials touched solution/test files or modified inputs — "
                   "see `analysis.json → integrity` before trusting their reward."]
    md += ["", "Review each failed trial's `feedback.md` and fill in its `feedback.json`; "
               "`python -m benchmarks.harness backlog` turns the reviews into an improvement list."]
    (run_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary


def compare(run_a: Path, run_b: Path) -> str:
    a, b = per_task(_trials(run_a)), per_task(_trials(run_b))
    lines = [f"# `{run_a.name}` → `{run_b.name}`", "",
             "| task | solved A | solved B | tests A | tests B | Δ tests | time A→B, s | cost A→B, $ |",
             "|---|:-:|:-:|:-:|:-:|:-:|---|---|"]
    fixed, broken = [], []
    for name in sorted(set(a) | set(b)):
        ra, rb = a.get(name), b.get(name)
        if not ra or not rb:
            lines.append(f"| {name} | {'—' if not ra else ra['solved']} | {'—' if not rb else rb['solved']} | | | | | |")
            continue
        pa, pb = ra["mean_partial"], rb["mean_partial"]
        delta = None if pa is None or pb is None else pb - pa
        if ra["solved"] == 0 and rb["solved"] > 0:
            fixed.append(name)
        if ra["solved"] > 0 and rb["solved"] == 0:
            broken.append(name)
        lines.append(f"| {name} | {ra['solved']}/{ra['trials']} | {rb['solved']}/{rb['trials']} "
                     f"| {_fmt(pa, '.0%')} | {_fmt(pb, '.0%')} | {_fmt(delta, '+.0%')} "
                     f"| {_fmt(ra['mean_seconds'], '.0f')}→{_fmt(rb['mean_seconds'], '.0f')} "
                     f"| {_fmt(ra['mean_cost'])}→{_fmt(rb['mean_cost'])} |")
    lines += ["", f"Fixed: {', '.join(fixed) or 'none'}", f"Broken: {', '.join(broken) or 'none'}"]
    return "\n".join(lines) + "\n"


def backlog(runs_root: Path) -> str:
    """Reviewed feedback across all runs → what to improve, by evidence."""
    forms = []
    for f in sorted(runs_root.glob("*/*/*/trial-*/feedback.json")):
        data = json.loads(f.read_text())
        if data.get("reviewed"):
            forms.append((f.parent, data))
    if not forms:
        return ("No reviewed feedback yet. Fill in `feedback.json` in failed trials "
                "(set `reviewed: true`) and run this again.\n")
    comp: dict[str, list] = defaultdict(list)
    tags = Counter()
    for trial, d in forms:
        if d.get("verdict") == "correct":
            continue
        comp[d.get("root_cause_component") or "unassigned"].append((trial, d))
        tags.update(d.get("failure_tags") or [])
    lines = [f"# Improvement backlog ({len(forms)} reviewed trials)", "",
             "## By component", ""]
    for name, items in sorted(comp.items(), key=lambda kv: -len(kv[1])):
        tasks = sorted({str(t.parent.name) for t, _ in items})
        lines.append(f"### {name} — {len(items)} failure(s) across {len(tasks)} task(s)")
        for trial, d in items:
            lines.append(f"- `{trial.parent.name}/{trial.name}` ({trial.parents[2].name}): "
                         f"{d.get('what_went_wrong') or '—'} → fix: {d.get('proposed_fix') or '—'}"
                         + (f" [{d['issue_link']}]" if d.get("issue_link") else ""))
        lines.append("")
    lines += ["## Failure tags", ""] + [f"- `{k}`: {v}" for k, v in tags.most_common()]
    verdicts = Counter(d.get("verdict") for _, d in forms)
    lines += ["", "## Verdicts", ""] + [f"- `{k}`: {v}" for k, v in verdicts.most_common()]
    return "\n".join(lines) + "\n"
