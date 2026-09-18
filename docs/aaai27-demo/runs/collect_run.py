"""Collect what one CoScientist web session left behind, for the paper tables.

usage: collect_run.py <events.jsonl> [--export]
Reads the event log written by run_session.py, the session's graph files, and
the web API (metrics, builds). Writes <events>.summary.json and .summary.md.
--export also saves the .cossession.zip bundle next to them.
"""
import collections
import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[3]
INFRA_TOOLS = {"update_task_status", "research_commit", "research_query", "research_overview",
               "research_context_slice", "research_set_focus", "get_graph_history", "transfer_to_agent"}


def main():
    log = Path(sys.argv[1]).resolve()
    ev = [json.loads(l) for l in open(log)]
    import re
    text = json.dumps(ev[:40])  # the ids appear in the first events of the session
    uid = re.search(r"user_[0-9a-f]{32}", text).group(0)
    sid = re.search(r"session_[0-9a-f]{32}", text).group(0)
    out = {"user_id": uid, "session_id": sid, "wall_seconds": ev[-1]["_t"],
           "finished": any(e["type"] == "final_response" for e in ev)}

    # time per agent: from agent_start to the matching agent_end
    open_at, spent, starts = {}, collections.Counter(), collections.Counter()
    for e in ev:
        if e["type"] != "tool_activity":
            continue
        a = e.get("author")
        if e.get("phase") == "agent_start":
            open_at[a] = e["_t"]; starts[a] += 1
        elif e.get("phase") == "agent_end" and a in open_at:
            spent[a] += e["_t"] - open_at.pop(a)
    out["agents"] = {a: {"starts": starts[a], "seconds": round(spent[a])} for a in starts}

    calls = [e for e in ev if e["type"] == "tool_activity" and e.get("phase") == "call"]
    by_tool = collections.Counter((e.get("author"), e.get("tool")) for e in calls)
    out["tool_calls_total"] = len(calls)
    out["mcp_tool_calls"] = {f"{a}:{t}": n for (a, t), n in by_tool.most_common()
                             if a == "ExperimentAgent" and t not in INFRA_TOOLS}
    out["alembic_calls"] = {t: n for (a, t), n in by_tool.items()
                            if t in ("build_mcp_server", "check_mcp_build", "list_mcp_builds")}
    out["sandbox_commands"] = sum(n for (a, t), n in by_tool.items() if t == "execute_bash")
    out["searches"] = sum(n for (a, t), n in by_tool.items()
                          if t and a == "ResearchAgent" and ("search" in t or "tavily" in t.lower()))
    out["llm_errors"] = sum("could not be reached" in str(e.get("content")) for e in ev)
    out["no_matching_tool"] = sum("NO_MATCHING_TOOL" in str(e.get("content")) for e in ev
                                  if e["type"] == "agent_event" and e.get("author") == "ExperimentAgent")

    gdir = ROOT / "graph_runs" / "sessions" / uid / sid
    g = json.load(open(gdir / "research_active.json"))
    out["graph"] = {"nodes": len(g["nodes"]), "edges": len(g["edges"]),
                    "by_type": dict(collections.Counter(n["type"] for n in g["nodes"])),
                    "hypotheses": [{"id": n["id"], "status": n.get("status"),
                                    "text": str(n["attrs"].get("statement") or n["attrs"].get("formulation") or "")[:200]}
                                   for n in g["nodes"] if n["type"] == "Hypothesis"]}
    ex = gdir / "execution.json"
    if ex.exists():
        x = json.load(open(ex))
        out["execution_graph_nodes"] = len(x.get("nodes", []))

    with httpx.Client(base_url=BASE, timeout=120) as http:
        m = http.get(f"/api/users/{uid}/sessions/{sid}/metrics").json()
        out["llm"] = {k: m["llm"].get(k) for k in ("calls", "prompt_tokens", "completion_tokens",
                                                   "cached_tokens", "reasoning_tokens", "total_tokens", "cost_usd")}
        if "--export" in sys.argv:
            r = http.post(f"/api/users/{uid}/sessions/{sid}/export")
            if r.headers.get("content-type", "").startswith("application/json"):
                out["export"] = r.json()
            else:
                z = log.with_suffix(".cossession.zip"); z.write_bytes(r.content)
                out["export"] = {"file": z.name, "bytes": len(r.content)}

    final = [e for e in ev if e["type"] == "final_response"]
    if final:
        log.with_suffix(".report.md").write_text(final[-1]["content"])
    log.with_suffix(".summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))

    md = [f"# {log.stem}", "", f"- finished: {out['finished']}, wall time {round(out['wall_seconds'] / 60, 1)} min",
          f"- LLM: {out['llm']['calls']} calls, {out['llm']['total_tokens']:,} tokens "
          f"({out['llm']['cached_tokens']:,} cached), ${out['llm']['cost_usd']:.2f}",
          f"- tool calls {out['tool_calls_total']}, sandbox commands {out['sandbox_commands']}, searches {out['searches']}",
          f"- Alembic calls: {out['alembic_calls']}", f"- MCP tool calls: {out['mcp_tool_calls']}",
          f"- graph: {out['graph']['nodes']} nodes, {out['graph']['edges']} edges, {out['graph']['by_type']}",
          "", "| agent | starts | minutes |", "|---|---|---|"]
    md += [f"| {a} | {v['starts']} | {round(v['seconds'] / 60, 1)} |"
           for a, v in sorted(out["agents"].items(), key=lambda kv: -kv[1]["seconds"])]
    md += ["", "| hypothesis | status | text |", "|---|---|---|"]
    md += [f"| {h['id']} | {h['status']} | {h['text']} |" for h in out["graph"]["hypotheses"]]
    log.with_suffix(".summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


main()
