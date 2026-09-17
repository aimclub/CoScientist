## What

Adds the **pipeline flow model** and folds the **Result Aggregator** into it as the terminal stage of a single ADK invocation, grounded in the typed research graph, with a working MCP-artifact download chain that produces a report folder of real figures.

## Why

The aggregator previously ran as a **second `run_async`** (two Opik traces per logical run) and reasoned over the raw session-state dict + transcript instead of the validated typed graph that `main` introduced. Server-rendered figures (presigned MinIO URLs in tool results) never reached the report.

## Changes

- **One run / one trace** — `run_root = SequentialAgent("ResearchPipeline", [*pre, orchestrator, *post])`; a single `run_async` drives the whole pipeline, aggregator included. Recursive tracing keeps the aggregator child in the same trace.
- **Graph-primary aggregator** — `tools=[result_formatter, research_graph_readonly]`, `include_contents: none`, `before_agent: [inject_research_context]`; prompt rewritten to read the graph first. New read-only reporter surface (overview/slice/provenance) via `ResearchGraphToolset` + bindings.
- **Artifact capture → download** — `capture_mcp_artifacts` after_tool callback + a global `McpArtifactCapturePlugin` stash presigned figure URLs into `state["mcp_artifacts"]`; `collect_artifacts` downloads them from S3/MinIO into the report `figures/`. Hardened `find_artifact_urls` extractor + `html.unescape` on the presigned URL before download.
- **Reporting subsystem** — `reporting/{collect,finalize,latex}.py`, `result_formatter_tool`, and a `result-aggregator-mcp-server`.
- **Driver collapse** — dropped `_POST_STAGE_DIRECTIVE` / `run_pipeline` / `_runner_for`; `web/app.py` streams the aggregator inside the main loop.

## Verification

- **154 unit tests pass** (`tests/unit`).
- **End-to-end**: tox-antitargets reproduction (Nikitin et al. 2025) produced `logs/reports/tox_full_run/` with **15 real MinIO figures downloaded** and every paper number graph-grounded (12654×44 dataset; filtered gap 0.38→0.70; top-5 antitargets; median ρ −0.236; logP confounder ρ 0.816; figure-8 target-fishing). Confirmed the capture state survives the nested sub-runner boundary into the aggregator's session.

## Notes / follow-ups

- Assumes `RESEARCH_GRAPH__ENABLED=true` (else `research_graph_readonly` drops out and the aggregator would need `include_contents: default`).
- Web + CLI still use a default `ReportConfig()` — threading `--latex` from the browser/CLI is a TODO.
- Content-quality: the qwen aggregator can still hallucinate a stray paragraph despite the graph-primary constraint; the numbers/figures themselves are graph-grounded and real.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
