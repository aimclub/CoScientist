# AAAI-27 paper — "Towards Generalisation of AI4Science Systems"

Round-2 reframe of the Alembic paper: from the adversarial "convert-once beats the
coder agent" pitch (`../aaai27-plan.md`) to a **systemic** framing — Alembic is the
experiment module of a general AI4Science system that grows a verified, reusable,
reproducible tool catalogue. See `OUTLINE.md` for the full structure and
`research/` for the verified literature review and benchmark survey that ground it.

## Build
```bash
cd paper-aaai27
pdflatex main && bibtex main && pdflatex main && pdflatex main
```
Compiles to a 5-page draft (abstract + intro + related work + setup written;
system / alembic / results / discussion are structured stubs). Requires a TeX
Live with `newtxtext` (in `aaai2027.sty`). The `algorithm`/`algorithmic` packages
are **commented out** in `main.tex` — install `texlive-science` and uncomment to
add the gated-generation-loop algorithm block.

## Layout
- `main.tex` — AAAI-2027 submission class, `\input`s sections in order.
- `sections/` — one file per section (abstract, introduction, related_work,
  system, alembic, benchmark, results, discussion, limitations, conclusion,
  appendix).
- `references.bib` — 53 entries (29 reused from the EMNLP demo + 24 verified
  round-2 additions).
- `figures/` — reused: `the_alembic.png`, `alembic_workflow.tex`,
  `alembic_interface.png`, `medsam_*` case study.
- `tables/` — regenerate via `../scripts/render_tables.sh`.
- `research/prior_work.md`, `research/benchmark_survey.md` — the grounding survey.
- `ReproducibilityChecklist.tex` — AAAI-27 kit checklist (appended after refs).

## Status / TODO
- **Written:** abstract, introduction, related work, experimental setup.
- **Stubs:** system (CoScientist planner→action-graph→executor), alembic
  (pipeline+gates+split-venv+mock-guard — port from `../../README.md`), results
  (self-metrics, drift, audit, economy), discussion, limitations, conclusion.
- **Anonymisation:** draft uses no author names (template author is "Anonymous
  Submission"); before submission scrub identifying repo URLs / system names per
  the AAAI double-blind rule.
- **Open decisions:** title wording; how much of the (WIP) executor to present;
  whether to add ML-Bench / CORE-Bench experiments beyond TM-Bench.
