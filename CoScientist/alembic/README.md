# Alembic

## Overview

Alembic is a multi-agent pipeline that automatically generates a deployable [FastMCP](https://github.com/jlowin/fastmcp) server from any scientific GitHub repository. Given a repo URL, it clones the code, sets up a reproducible Python environment, writes tool functions with pytest tests, validates every tool against the repo's own code, renders a FastMCP server, and packages the result as a Docker image — all without human intervention.

The LLM proposes; **code disposes.** Each stage ends at a deterministic *gate* — a plan check, an env check, an artefact check, a validation loop — that the model cannot talk its way past. A failed gate rolls the stage's files back to a checkpoint and reruns it with a note.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Getting Started](#getting-started)
- [Live Dashboard (Web UI)](#live-dashboard-web-ui)
- [Running a Benchmark](#running-a-benchmark)
- [Project Structure](#project-structure)
- [Configuration](#configuration)

---

## How It Works

The pipeline runs five stages inside a Docker container, each followed by a code-enforced gate:

| Stage | Driver | What it does | Gate |
|---|---|---|---|
| 1 | **Explorer** (agent) | Clones the repo, reads the code, writes a `plan.json` of tools to build | plan is well-formed & non-empty |
| 2 | **Environment** (agent) | Builds the main `.venv` (repo + deps), writes `reports/environment.md` | repo imports cleanly under `.venv` |
| 3 | **Coder** (agent) | Writes one `output/tools/<tool>.py` per tool plus `test_smoke_*` / `test_invoc_*` tests | files exist & compile |
| 4 | **Validator** (code, not an agent) | Runs pytest + a live invocation per tool through the tools venv; calls a **Debugger** agent on failures | every tool green |
| 5 | **Wrapper** (code + fallback agent) | Renders `output/server.py` deterministically and builds the separate `.venv-server` (fastmcp) | server compiles & imports |

**Two venvs, never mixed:** `.venv` holds the repo and its dependencies (where tools and tests run); `.venv-server` holds only fastmcp. Every tool shells through `helpers/run_function.py` in the tools venv, printing a `<<<ALEMBIC_RESULT>>>` sentinel + JSON — so `server.py` is a subprocess router, not an in-process shim, and a dependency clash between the repo and fastmcp is impossible.

**Validation is evidence-based.** Tests split by name: `test_smoke_*` (does it run?) vs `test_invoc_*` (is the output correct?). A tool is `perfect` only if it passes **and** has ≥1 green invocation test. A `test_invoc_*` that mocks or patches the repo instead of calling it is automatically reclassified as a smoke test — so a tool can't reach `perfect` on hollow, self-referential validation.

On success the build container is committed to `alembic-tool:<repo-name>` and launched with the MCP server listening on a random host port.

---

## Getting Started

**Prerequisites:** Docker, Python 3.11+, and a `.env` file at the project root with at least one LLM API key.

```env
OPENROUTER_API_KEY=sk-or-...
MODEL=openrouter/qwen/qwen3-235b-a22b-2507   # optional override
```

**Build and serve a repo in one command:**

```bash
python CoScientist/alembic/start_chain.py https://github.com/Roestlab/massformer
```

The script:
1. Builds `alembic-base:latest` once (skipped on subsequent runs).
2. Runs the pipeline inside a container.
3. Commits the result and starts the MCP server.

```
[start-chain] MCP server up.
  url       : http://localhost:24371/mcp
  logs      : docker logs -f alembic-serve-massformer-a1b2c3
  stop      : docker stop alembic-serve-massformer-a1b2c3 && docker rm alembic-serve-massformer-a1b2c3
```

**Useful flags:**

```bash
# Resume from a specific stage (workdir is preserved)
python CoScientist/alembic/start_chain.py <repo_url> --resume coder

# Build image without starting the server
python CoScientist/alembic/start_chain.py <repo_url> --no-serve

# Force rebuild of the base image
python CoScientist/alembic/start_chain.py <repo_url> --rebuild-base

# GPU access inside the container
python CoScientist/alembic/start_chain.py <repo_url> --gpus all
```

### Guiding what gets built

By default the Explorer decides autonomously which tools to expose. You can steer
it with one of two mechanisms, at opposite ends of a strictness spectrum:

- **Required tasks (hard, enforced).** Pin exact tool(s) — name, argument names,
  return shape — that *must* appear, verified against real repo code by the plan
  gate (the run fails if one can't be grounded). Used for TM-Bench-style
  evaluation. Set `ALEMBIC_TASKS` (env) or pass `--tasks` to a JSON/YAML task
  object, a path, or comma-separated paths (each `{name, description, arguments,
  returns, example}`); several tasks run against one repo. `ALEMBIC_TARGET_TASK`
  is the old single-task spelling.

- **Soft hint (steer, not enforced).** Free-text describing the *idea* of a tool
  you'd like to see mined **among the others**, with no forced name/signature and
  no gate — applied to the Explorer stage only, dropped silently if the repo has
  no real code for it. Set `ALEMBIC_HINTS` (env) or pass `--hints`:

  ```bash
  python CoScientist/alembic/start_chain.py <repo_url> \
    --hints "a train + a predict entry point for the survival model"
  ```

  The two compose: required tools stay pinned while the hint steers the rest.

---

## Live Dashboard (Web UI)

A local, browser-based dashboard that runs the pipeline **without Docker** and
streams every stage and agent action in real time:

- **top** — the five-stage rail (explorer → environment → coder → validator →
  wrapper), lit as each stage runs / passes / fails;
- **left** — an accumulating column: the exploration report, the generated
  output files, how to run them (the recorded `setup.sh`), and per-tool
  invocation examples;
- **right** — the generated tools as cards with live pass/fail validation
  badges (hover a failure for the error) and a **Call** form that invokes each
  tool-function on demand — the same `invoke_tool_function` path the validator
  uses, so you can exercise a tool the instant the Coder writes it (wrapping to
  a real MCP server is only the final stage);
- **bottom** — a live activity feed of every agent tool call.

**Prerequisites:** the same `.env` as [Getting Started](#getting-started), plus
`fastapi` and `uvicorn` (already in the project `requirements.txt`).

**Start it (from the repo root):**

```bash
python CoScientist/alembic/web/server.py
```

Then open **http://127.0.0.1:8100**, paste a repo URL (e.g.
`https://github.com/whitead/synspace`) and press **Run**.

Notes:
- Run it from the project root — the pipeline writes its workdir to `./.alembic/`,
  the same location as the CLI.
- **Stop** invalidates the run; the pipeline unwinds at its next stage/tool
  boundary (a subprocess already in flight finishes first).
- The pipeline itself is unchanged for the CLI/benchmark: it emits events
  through the optional `alembic.events` bus, a no-op unless the dashboard
  installs a sink. All UI enrichment (reading `plan.json` / `validation.json` /
  the output files off disk) lives in `web/app.py`, not in the pipeline.

---

## Running a Benchmark

`benchmarks/alembic/run_benchmark.py` processes multiple repos in parallel
(with a `git ls-remote` reachability pre-check) and writes a Markdown
summary.

```bash
# Explicit list, 4 parallel workers (default)
python benchmarks/alembic/run_benchmark.py \
    --repos https://github.com/Roestlab/massformer \
            https://github.com/whitead/synspace \
            https://github.com/CrystalEye42/OpenChemIE

# From a file (one URL per line, '#' = comment), 8 workers
python benchmarks/alembic/run_benchmark.py \
    --repos-file repos.txt \
    --parallel 8
```

Results default to `benchmarks/alembic/runs/<timestamp>/` (`summary.md`,
`summary.json`, `logs/*.log`) — pass `--output`/`--json-output`/`--log-dir`
to override.

---

## Project Structure

```
CoScientist/alembic/
├── agents.py          # The 5 LLM agents (explorer, environment, coder, debugger, wrapper)
├── main.py            # Pipeline orchestrator + gates + the deterministic validator loop
├── contract.py        # ToolReport / passed / perfect — what counts as a validated tool
├── config.py          # Stages, timeouts, model string (all env-overridable)
├── start_chain.py     # CLI: build base image → run pipeline → commit → serve
├── common.py          # Shared Docker helpers (ensure_base_image, get_repo_name)
├── events.py          # Optional live-event bus (no-op for CLI; feeds the web UI)
├── instructions/      # System prompts for each agent
├── tools/             # Agent tools (fs, shell, venv, invoke, codegen) + scripts/run_function.py
└── web/               # Live dashboard: FastAPI + WebSocket (app.py, server.py, templates/)

docker/alembic/
├── Dockerfile         # Base image (python:3.11 + build deps + alembic code)
├── entrypoint.py      # Container entrypoint (build / serve / help)
├── serve.py           # FastMCP server launcher inside container
└── requirements.txt   # Pipeline dependencies

benchmarks/alembic/
└── run_benchmark.py   # Parallel multi-repo runner (git ls-remote pre-check → summary.md)
```

---

## Configuration

All settings are passed through environment variables (`.env` or shell):

| Variable | Default | Description |
|---|---|---|
| `MODEL` | `openrouter/qwen/qwen3-235b-a22b-2507` | LiteLLM model string for all agents |
| `OPENROUTER_API_KEY` | — | Required when using OpenRouter |
| `OPENAI_API_KEY` | — | Required when using OpenAI models |
| `TAVILY_API_KEY` | — | Optional; enables web search inside the Explorer |
| `MCP_PORT` | `8000` | Port the FastMCP server listens on inside the container |
| `ALEMBIC_WORKDIR` | `/work/.alembic` | In-container working directory for repos and reports |
