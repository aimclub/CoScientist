# Pipeline flow model + Result Aggregator (single-run, graph-grounded, artifact download)

## Summary

This branch turns the Result Aggregator into the **terminal stage of a single pipeline run**, grounds it in the typed **research graph** instead of the raw transcript, and adds a working **MCP-artifact download chain** so server-rendered figures land in the report folder. The net effect: one `run_async` → one Opik trace → a self-contained deliverable directory (`report.md` + `MANIFEST.json` + `figures/` with real images).

---

## Motivation

Two problems the `main` merge left behind:

1. **The aggregator ran as a second `run_async`.** The old driver executed the orchestrator, then kicked the aggregator off separately with a static `_POST_STAGE_DIRECTIVE`. In Opik this surfaced as **two traces for one logical run**, and the aggregator's events weren't part of the pipeline invocation.
2. **The aggregator couldn't see the graph.** It reasoned over the session-state dict + workspace + raw transcript prose, not the validated typed graph (`Hypothesis` / `Evidence` / `Conclusion` / …) that every worker now writes. It also had no way to recover the **presigned figure URLs** that MCP tools return — those live only in the tool-result envelope and never reached the report.

Goal: **one invocation, one trace, graph as the source of truth, real figures on disk.**

---

## Architecture

### 1. Single-run root — `SequentialAgent`

The pipeline is now composed as **one ADK `SequentialAgent`** and driven by a single `run_async`:

```python
# CoScientist/agents/__init__.py
run_root = SequentialAgent(
    name="ResearchPipeline",
    sub_agents=[*pipeline_pre_agents, orchestrator_agent, *pipeline_post_agents],
)
```

- Opik traces per invocation, so **one invocation = one trace**. `track_adk_agent_recursive(run_root, …)` traces the aggregator child inside the same trace.
- `config.root` stays `OrchestratorAgent` — the *delegation* root is unchanged, so no routing/test churn. The orchestrator delegates via `AgentTool` function-calls (not ADK sub-agent transfer), so parenting it under the `SequentialAgent` doesn't change routing.
- `main.py` builds `App(root_agent=run_root, plugins=[…])`; the graph plugins wrap the whole invocation, so they cover the aggregator child automatically.
- **Driver collapsed** to a single `run()`: deleted `_POST_STAGE_DIRECTIVE`, `run_pipeline`, `_runner_for`, and the `_runners` bookkeeping. `run()` writes `report_config` into state **before** the run (the aggregator reads it mid-invocation via `format_results`), then takes the **last** final-response text as the report (fallback → any final text → S3/partial finalizer).

### 2. Graph-primary aggregator

`ResultAggregatorAgent` is reconfigured to trust the graph, not the transcript:

- `tools: [result_formatter, research_graph_readonly]`
- `include_contents: none` — cheaper, and forces every claim to trace to a graph node instead of hallucinating from transcript prose.
- `before_agent: [inject_research_context]` — seeds `state['research_context']` with the graph overview as a starting point.
- Prompt rewritten to **read the graph first** (`research_overview` → `research_provenance` / `research_context_slice` per Conclusion/Evidence), then `format_results` to collect figures/tables, then write the report grounding every claim in a node and reporting refuted/negative results honestly.

### 3. Read-only graph surface for the reporter

A new **read-only surface** on the research-graph toolset, so the aggregator can *read* provenance without being able to *write* nodes:

- `ResearchGraphToolset(surface="reporter")` → `[research_overview, research_context_slice, research_provenance]` — **no `research_commit`**, no orchestrator-only tools.
- Registered in `bindings.py` as `research_graph_readonly` (`optional`, `runtime_resolved`). No changes to write-permission or the edge schema.

### 4. MCP-artifact capture → download chain

The part that makes figures real. MCP tools (e.g. the tox-antitargets suite) render a figure server-side and return a **presigned MinIO/S3 URL** inside the tool result (commonly under `metadata.figure.artifact`). With the aggregator running `include_contents: none`, that link is invisible unless it is captured at the tool boundary.

**Two capture seams, by necessity:**

| Seam | Where | Covers |
|------|-------|--------|
| `capture_mcp_artifacts` (agent `after_tool` callback) | on `ExperimentAgent` | MCP calls made by sub-agents (AgentTool delegations) |
| `McpArtifactCapturePlugin` (App-level plugin) | global | MCP calls at the top level |

Both stash de-duplicated `{url, tool}` records into `state["mcp_artifacts"]`. **Two seams are required** because App-level plugins do **not** fire for sub-agent (AgentTool) MCP calls — the figure tools run inside a nested runner, so the agent-level `after_tool` callback is the only place that sees them. The plugin must also run **before** the tool-result truncation plugin so it sees the full, untruncated URL.

**Download** (`reporting/collect.py`):
- `collect_artifacts(session_id, state, …, graph_nodes=)` scans every `*_artifacts` state key **and** artifact URLs attached to graph nodes, then downloads each into the report's `figures/`.
- `find_artifact_urls` is a robust extractor: JSON walk + regex fallback for Pydantic/`repr`/escaped forms + recursion.
- `_download` calls `html.unescape(url)` first — MCP servers (and LLMs copying URLs into graph prose) often HTML-escape `&`→`&amp;`, which corrupts the AWS SigV4 query params and makes MinIO answer **403**.
- Workspace scan hardened (`_WORKSPACE_SKIP_DIRS`, prune `.git`, cap `_MAX_WORKSPACE_FILES`) so a CoderAgent `git clone` can't flood the report with bundled example assets.

> **Key finding from the live run:** the tool-response path carries **raw `&`** in presigned URLs and is authoritative; the graph-node path is lossy (the LLM even fabricated a wrong host when copying a URL into prose). Capture at the tool seam is the reliable source; graph-node URLs are best-effort.

### 5. Reporting subsystem (`CoScientist/reporting/`)

- `collect.py` — figure/table collection, artifact download, workspace scan.
- `finalize.py` — assembles the deliverable folder, extracts references, writes `MANIFEST.json`, invokes LaTeX.
- `result_formatter_tool` — the tool the aggregator calls to materialize the folder; reads `report_config` from state mid-invocation.
- `mcp-servers/result-aggregator-mcp-server/` — standalone MCP server variant.

### 6. Web integration

`web/app.py` drops the post-stage loop and `_POST_STAGE_DIRECTIVE` import; the aggregator now streams as the **terminal segment of the same run**. Sets `report_config` into state before the main loop, captures the last final-response text via `_final_text` (also fixes a `parts[0].text` thinking-part bug), then finalizes and sends the enriched `final_response` (`report_dir` / `manifest`).

---

## LaTeX rendering (secondary)

`reporting/latex.py` renders the final markdown to LaTeX in four modes — `skip` (default), `standalone`, `body` (Overleaf fragment), `tree` (multi-file `latex/` project). Uses `pandoc` when available, with a built-in markdown→LaTeX fallback. It's wired through `ReportConfig` and driven end-to-end from `scripts/run_reproduction.py --latex …`. **Still partial:** the web UI and interactive CLI currently pass a default `ReportConfig()` (always `skip`) — threading a real `--latex` selector from those two entrypoints is the remaining follow-up (marked `TODO(planning)` in `app.py`).

---

## Verification

- **154 unit tests pass** (`tests/unit`), including new assertions on `run_root` shape and aggregator wiring.
- **End-to-end** — tox-antitargets reproduction (Nikitin et al. 2025) produced `logs/reports/tox_full_run/` with **15 real MinIO figures downloaded** and every paper number graph-grounded: 12654×44 dataset; filtered antitarget/toxicity gap 0.38→0.70; top-5 antitargets (KCNH2/AVPR1A/CACNA1C/KCNQ1/EDNRA); median Spearman ρ −0.236; logP confounder ρ 0.816; figure-8 inverse-docking target-fishing. **Confirmed the capture state survives the nested sub-runner boundary** into the aggregator's session (`format_results → figures_count: 15`).

## Assumptions / follow-ups

- Assumes `RESEARCH_GRAPH__ENABLED=true`. `research_graph_readonly` is `optional`, so if the graph is disabled it drops out — combined with `include_contents: none` the aggregator would then have only `format_results`, and should be flipped back to `include_contents: default`.
- Thread `--latex` from web + interactive CLI (renderer already works; only the entrypoints are unwired).
- Content-quality: the aggregator LLM can still over-write a stray unsupported paragraph despite the graph-primary constraint; the numbers and figures themselves are graph-grounded and real. Worth a prompt tightening, separate from this plumbing.
