"""Live web dashboard for the alembic pipeline (remaster architecture).

A local, browser-based split-screen view that streams a run in real time:

  * top   — the five-stage rail (explorer → environment → coder → validator →
             wrapper), lit as each stage runs / passes / fails;
  * left  — an accumulating column: the exploration report, then the generated
             output files, how to run them (recorded ``setup.sh``), and per-tool
             invocation examples;
  * right — the generated tools as cards with live pass/fail validation badges
             and a **Call** form that invokes each tool-function on demand
             (the same ``invoke_tool_function`` path the validator uses — the
             MCP wrap is only the final stage);
  * bottom — a live activity feed of every agent tool call.

The pipeline is unchanged for the CLI/benchmark: it emits events through the
optional :mod:`alembic.events` bus, which is a no-op unless this dashboard
installs a sink. All UI-shaped enrichment (reading reports/plan.json/output
files off disk) lives here in the web layer, not in the pipeline.

Run:
    python -m alembic.web.server
"""
