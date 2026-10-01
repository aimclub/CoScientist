"""Turn a finished trial into findings: what happened, why it failed, what to fix.

``analyze`` derives everything mechanically from files the trial already holds
(verifier output, trace, workspace) and writes ``analysis.json``. It also
writes ``feedback.json`` / ``feedback.md`` — a review form prefilled with those
findings, which a person completes; ``report`` aggregates the completed forms
into the improvement backlog. Reviewed forms are never overwritten.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .tasks import PROJECT_ROOT, Task, _sha256

# Vocabulary for feedback.json. Kept small on purpose: a backlog only ranks
# well when reviewers pick from the same few words.
VERDICTS = ("system_failure", "harness_issue", "task_issue", "correct")
COMPONENTS = ("orchestrator", "planner", "hypotheses", "research", "coder",
              "task_executor", "tools", "llm", "report", "infra", "harness", "other")
FAILURE_TAGS = (
    "misread_task", "wrong_method", "numeric_error", "units_or_rounding",
    "output_format", "output_path", "gave_up_early", "looped", "tool_failure",
    "env_missing_dependency", "timeout", "hallucinated_result", "no_verification",
    "ignored_input_file", "over_planning", "delegation_failure",
)

_PRESENCE = re.compile(r"exist", re.I)
_FORMAT = re.compile(r"format|structure|order|label|keys|lines|valid|sig_?fig|json|header|"
                     r"schema|column|parse|shape|type|array", re.I)
# Only what makes sense when hunting for the answer key — an agent naming its
# own script solve.py is not one of them.
_LEAK = re.compile(r"(?<![\w.])/solution/|solution/solve|-name\s+['\"]?solve|"
                   r"tests?/test_(?:outputs|result|verifier|adversarial)|ground_truth|"
                   r"harbor-canary|26b5c67b|terminal-bench|tbench|openscience|"
                   r"energy_references|benchmarks/", re.I)


# What only someone looking for this benchmark's answers would fetch or type.
_WEB_LEAK = re.compile(r"harbor-canary|26b5c67b|harbor-framework|terminal-bench|tbench\.ai|"
                       r"benchmarks-openscience|openscience", re.I)


def classify_test(name: str) -> str:
    short = (name or "").split("::")[-1]
    if _PRESENCE.search(short):
        return "presence"
    if _FORMAT.search(short):
        return "format"
    return "correctness"


def _events(trial: Path) -> list[dict]:
    path = trial / "trace" / "events.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def trace_stats(events: list[dict]) -> dict[str, Any]:
    tools: dict[str, Counter] = defaultdict(Counter)
    agents: dict[str, Counter] = defaultdict(Counter)
    repeats = Counter()
    errors = []
    for e in events:
        ev, agent = e.get("ev"), e.get("agent") or "?"
        if ev == "tool":
            t = tools[e["tool"]]
            t["calls"] += 1
            t["ms"] += e.get("ms") or 0
            bad = e.get("status") in ("error", "exception", "timeout", "blocked")
            t["errors"] += bad
            agents[agent]["tool_calls"] += 1
            repeats[(e["tool"], e.get("args"))] += 1
            if bad:
                errors.append({"agent": agent, "tool": e["tool"], "status": e.get("status"),
                               "detail": (e.get("error") or e.get("result") or "")[:400]})
        elif ev == "model":
            a = agents[agent]
            a["model_calls"] += 1
            a["prompt_tokens"] += e.get("prompt_tokens") or 0
            a["output_tokens"] += e.get("output_tokens") or 0
            a["model_ms"] += e.get("ms") or 0
            if e.get("error"):
                errors.append({"agent": agent, "model_error": e["error"],
                               "detail": e.get("error_message")})
        elif ev == "agent_start":
            agents[agent]["turns"] += 1
        elif ev == "agent_message":  # web mode: what the UI shows per agent
            agents[agent]["messages"] += 1
        elif ev in ("model_error", "run_error"):
            errors.append({"agent": agent, ev: e.get("error"), "detail": e.get("message")})
    return {
        "tool_calls": sum(t["calls"] for t in tools.values()),
        "tool_errors": sum(t["errors"] for t in tools.values()),
        "model_calls": sum(a["model_calls"] for a in agents.values()),
        "by_tool": {k: dict(v) for k, v in sorted(tools.items(), key=lambda kv: -kv[1]["calls"])},
        "by_agent": {k: dict(v) for k, v in sorted(agents.items(), key=lambda kv: -kv[1]["model_calls"])},
        "repeated_calls": [{"tool": t, "count": n, "args": (a or "")[:200]}
                           for (t, a), n in repeats.most_common(5) if n >= 3],
        "errors": errors[:40],
    }


def integrity(trial: Path, events: list[dict]) -> dict[str, Any]:
    """Signals that a result may not be the system's own work.

    The CoderAgent's local sandbox is a working directory, not a jail: a
    command can reach the rest of the disk, including this repository's
    solutions and tests. So every tool call is checked for known-answer paths
    (``suspicious_accesses``) and for leaving the workspace at all
    (``escaped_workspace``) — the latter is not cheating by itself, but makes
    the reward untrustworthy until someone has looked.
    """
    # Workspace paths are blanked first; any run-dir or repository path left
    # over, or a relative climb, points outside the sandbox.
    roots = sorted({str(trial.parents[2]), str(PROJECT_ROOT)}, key=len, reverse=True)
    escape_re = re.compile("|".join(map(re.escape, roots)) + r"|(?:^|[\s'\"=;(])\.\./", re.M)
    # Longest first: the resolved path (web mode) may contain the others.
    inside = sorted({str(trial / "ws_workspace"), str(trial / "workspace"),
                     str((trial / "workspace").resolve())}, key=len, reverse=True)
    leaks, escapes = [], []
    for e in events:
        if e.get("ev") != "tool":
            continue
        args = e.get("args") or ""
        # The run directory itself is named after the benchmark; only what is
        # left once the workspace prefix is gone says where a command went.
        local = args
        for path in inside:
            local = local.replace(path, "")
        m = _LEAK.search(local.replace(str(trial), "").replace(str(trial.parents[2]), ""))
        if m:
            leaks.append({"tool": e["tool"], "agent": e.get("agent"), "match": m.group(0),
                          "args": args[:300]})
        if escape_re.search(local):
            escapes.append({"tool": e["tool"], "agent": e.get("agent"), "args": args[:300]})
    # The OpenHands sandbox has no copy of this repository but does have the
    # internet: look for the benchmark being searched for from inside it.
    for traj in sorted((trial / "trace" / "sandbox").glob("*/trajectory.json")):
        with traj.open(encoding="utf-8", errors="replace") as fh:
            text = fh.read(50 << 20)
        for m in _WEB_LEAK.finditer(text):
            leaks.append({"tool": "sandbox", "agent": traj.parent.name, "match": m.group(0),
                          "args": text[max(0, m.start() - 150):m.end() + 150]})
            if len(leaks) >= 20:
                break
    modified = []
    seeded = trial / "input" / "seeded.json"
    ws = trial / "workspace"
    if seeded.is_file():
        for item in json.loads(seeded.read_text()):
            p = ws / item["target"].lstrip("/")
            if not p.is_file():
                modified.append({"path": item["target"], "change": "deleted"})
            elif _sha256(p) != item["sha256"]:
                modified.append({"path": item["target"], "change": "modified"})
    return {"suspicious_accesses": leaks[:20], "escaped_workspace": escapes[:20],
            "inputs_modified": modified, "clean": not (leaks or escapes or modified)}


def _misplaced(task: Task, ws: Path) -> list[str]:
    """Expected output files that exist, but elsewhere — in the local workspace
    or, with the OpenHands coder, in a sandbox's /workspace listing."""
    hits: list[str] = []
    missing = [Path(o["path"].rstrip("/")).name for o in task.outputs()
               if not (ws / o["path"].strip("/")).exists()]
    if not missing:
        return hits
    if ws.is_dir():
        for name in missing:
            hits += [str(p.relative_to(ws)) for p in ws.rglob(name)
                     if ".venv" not in p.parts and "site-packages" not in p.parts][:5]
    for listing in sorted((ws.parent / "trace" / "sandbox").glob("*/workspace_files.json")):
        for e in json.loads(listing.read_text()):
            if Path(str(e.get("path", ""))).name in missing:
                hits.append(f"sandbox {listing.parent.name}:{e['path']}")
    return hits[:10]

def classify_outcome(result: dict, tests: dict | None, artifacts: list[dict],
                     misplaced: list[str]) -> str:
    agent = result.get("agent_status")
    reward = result.get("reward")
    if reward is not None and reward >= 1.0:
        return "solved"
    if not all(a["present"] for a in artifacts):
        if misplaced:
            return "wrong_output_path"
        if agent == "timeout":
            return "timeout_no_output"
        if agent in ("crash", "run_error"):
            return "agent_crash"
        return "no_output"
    if reward is None:
        return "unverified"
    if not tests or not tests.get("cases"):
        return "verifier_error"
    failed = [classify_test(c["name"]) for c in tests["cases"] if c["status"] != "passed"]
    if "format" in failed or "presence" in failed:
        return "format_error"
    return "wrong_answer" if failed else "verifier_error"


def analyze(task: Task, trial: Path, result: dict) -> dict[str, Any]:
    events = _events(trial)
    vres = result.get("verifier") or {}
    tests = vres.get("tests")
    artifacts = result.get("artifacts") or []
    misplaced = _misplaced(task, trial / "workspace")
    outcome = classify_outcome(
        {"agent_status": result.get("agent_status"), "reward": vres.get("reward")},
        tests, artifacts, misplaced)
    by_kind: dict[str, Counter] = defaultdict(Counter)
    for c in (tests or {}).get("cases", []):
        by_kind[classify_test(c["name"])][c["status"]] += 1
    stats = trace_stats(events)
    if not stats["model_calls"]:
        _model_stats_from_metrics(stats, trial / "metrics.json")
    hitl = trial / "trace" / "hitl.jsonl"
    started = result.get("agent_started_epoch")
    first_artifact = min((a["mtime"] for a in artifacts if a.get("mtime")), default=None)
    analysis = {
        "outcome": outcome,
        "partial_score": (tests["passed"] / tests["total"]) if tests and tests.get("total") else None,
        "tests_by_kind": {k: dict(v) for k, v in by_kind.items()},
        "failed_tests": [c for c in (tests or {}).get("cases", []) if c["status"] != "passed"],
        "misplaced_outputs": misplaced,
        "seconds_to_first_artifact": round(first_artifact - started, 1)
        if first_artifact and started else None,
        "hitl_requests": _count_hitl(hitl),
        "trace": stats,
        "integrity": integrity(trial, events),
    }
    (trial / "analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False, default=str))
    write_feedback_form(task, trial, result, analysis)
    return analysis


def _model_stats_from_metrics(stats: dict, path: Path) -> None:
    """Per-agent model usage from the usage ledger, for traces without model
    events (web mode, where the harness only sees what the server broadcasts)."""
    if not path.is_file():
        return
    for a in json.loads(path.read_text()).get("agents") or []:
        llm = a.get("llm") or {}
        row = stats["by_agent"].setdefault(a["agent"], {})
        row.update(model_calls=llm.get("calls", 0), prompt_tokens=llm.get("prompt_tokens", 0),
                   output_tokens=llm.get("completion_tokens", 0),
                   model_ms=round((llm.get("seconds") or 0) * 1000))
    stats["model_calls"] = sum(r.get("model_calls", 0) for r in stats["by_agent"].values())


def _count_hitl(path: Path) -> int:
    """Requests only: the web log also holds responses, timeouts and notices."""
    if not path.is_file():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        n += rec.get("type") == "hitl_request" or "action" in rec
    return n


# ── review form ──────────────────────────────────────────────────────────────
_AUTO_TAGS = {
    "wrong_output_path": ["output_path"], "format_error": ["output_format"],
    "timeout_no_output": ["timeout"], "no_output": ["gave_up_early"],
    "agent_crash": ["tool_failure"],
}


def write_feedback_form(task: Task, trial: Path, result: dict, analysis: dict) -> None:
    fpath = trial / "feedback.json"
    if fpath.is_file() and json.loads(fpath.read_text()).get("reviewed"):
        return
    tags = list(_AUTO_TAGS.get(analysis["outcome"], []))
    if analysis["trace"]["repeated_calls"]:
        tags.append("looped")
    if analysis["trace"]["tool_errors"]:
        tags.append("tool_failure")
    form = {
        "reviewed": False,
        "reviewer": None,
        "verdict": "correct" if analysis["outcome"] == "solved" else None,
        "root_cause_component": None,
        "failure_tags": [],
        "what_went_wrong": "",
        "what_should_have_happened": "",
        "proposed_fix": "",
        "issue_link": None,
        "_allowed": {"verdict": VERDICTS, "root_cause_component": COMPONENTS,
                     "failure_tags": FAILURE_TAGS},
        "_auto": {"outcome": analysis["outcome"], "suggested_tags": sorted(set(tags))},
    }
    fpath.write_text(json.dumps(form, indent=2, ensure_ascii=False))
    (trial / "feedback.md").write_text(_feedback_md(task, result, analysis, form["_auto"]["suggested_tags"]),
                                       encoding="utf-8")


def _feedback_md(task: Task, result: dict, analysis: dict, tags: list[str]) -> str:
    v = result.get("verifier") or {}
    t = analysis["trace"]
    lines = [
        f"# {task.full_name} — {result['trial_name']}",
        "",
        f"- **Outcome:** `{analysis['outcome']}`  reward={v.get('reward')}  "
        f"partial={_pct(analysis['partial_score'])}  verifier={v.get('backend')}",
        f"- **Agent:** status=`{result.get('agent_status')}`  wall={result.get('agent_seconds')}s  "
        f"cost=${result.get('cost_usd') or 0:.2f}  model calls={t['model_calls']}  "
        f"tool calls={t['tool_calls']} (errors {t['tool_errors']})  HITL={analysis['hitl_requests']}",
        f"- **Integrity:** {'clean' if analysis['integrity']['clean'] else '⚠ CHECK — see analysis.json'}",
        "",
        "## Failed tests",
    ]
    for c in analysis["failed_tests"] or []:
        msg = (c.get("message") or "").strip().splitlines()
        lines.append(f"- `{c['name'].split('::')[-1]}` ({classify_test(c['name'])}): "
                     f"{msg[0][:300] if msg else ''}")
    if not analysis["failed_tests"]:
        lines.append("- none" if v.get("reward") == 1.0 else f"- n/a ({v.get('error')})")
    if analysis["misplaced_outputs"]:
        lines += ["", f"Output written to the wrong place: {analysis['misplaced_outputs']}"]
    lines += ["", "## Agents", "", "| agent | turns | model calls | tool calls | prompt tok | output tok |",
              "|---|---:|---:|---:|---:|---:|"]
    for name, a in t["by_agent"].items():
        lines.append(f"| {name} | {a.get('turns', 0)} | {a.get('model_calls', 0)} | "
                     f"{a.get('tool_calls', 0)} | {a.get('prompt_tokens', 0)} | {a.get('output_tokens', 0)} |")
    if t["errors"]:
        lines += ["", "## Errors (first 10)"]
        lines += [f"- {json.dumps(e, ensure_ascii=False)[:400]}" for e in t["errors"][:10]]
    lines += [
        "", "## Review",
        "Fill in `feedback.json` (set `reviewed: true`). Files to look at: `input/prompt.md`, "
        "`output/final_report.md`, `output/artifacts/`, `verifier/test-stdout.txt`, "
        "`trace/events.jsonl`, `trace/agent_events.log`, `workspace/`.",
        f"Suggested tags: {', '.join(tags) or '—'}",
    ]
    return "\n".join(lines) + "\n"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"
