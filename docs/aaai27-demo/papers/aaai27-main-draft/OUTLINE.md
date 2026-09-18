# AAAI-27 paper outline — "Towards Generalisation of AI4Science Systems"

_Rough structure, will be edited. Reframe from `docs/aaai27-plan.md`: the earlier
plan pitched Alembic adversarially (convert-once **beats** the coder agent on
capability/reliability/economy). Our honest findings deflated that head-to-head
(capability parity, weak economy, narrow drift). This round repositions the same
artefact **systemically**: Alembic is the **experiment module** of a general
AI4Science system, and its job is to grow a **verified, reusable, reproducible
tool catalogue** — value is at the ecosystem level, not per-task capability._

Target: AAAI-27 main technical track. 7 pages main + 2 pages refs. Double-blind.

---

## Thesis (from `docs/aaai27_round2.md`)
1. We build a general AI4Science system.
2. Inside it, a module that creates a **dynamic, extensible, reproducible**
   catalogue of scientific tool code.
3. This removes three current experiment-execution problems: **limited tools**,
   **stochasticity**, **cost**.
4. The MCP servers we create form an **open, reusable ecosystem** for scientific code.

## Narrative spine
Current AI4Science systems run numerical experiments either with (a) stochastic,
expensive **coder agents** that re-derive each run, or (b) a **small fixed** set
of tools / MCP servers. Both cap the *breadth* and *reproducibility* of the
experiment portion. If experiments could instead lean on domain scientists' own
code through a growing catalogue of verified tools, they would be broader, more
reproducible, and cheaper to amortise. We realise this catalogue-builder
(**Alembic**) as the experiment module of a general system (**CoScientist**:
planner → action graph → executor), and characterise honestly *when* a verified
reusable catalogue helps and *when* it does not.

---

## Section-by-section

### Abstract (~150 w) — `sections/abstract.tex`
Problem (two regimes, three costs) → proposal (experiment module that converts
repos into verified served MCP tools, growing a catalogue) → what we measure
(coverage, reproducibility, amortised cost, verification quality) → honest scope
(capability parity; drift narrow). Release code + artefacts + runs.

### 1. Introduction — `sections/introduction.tex`
- P1 AI4Science systems plan & execute numerical experiments; two execution regimes.
- P2 Why both limit: coder generation expensive **and stochastic** (repeated
  runs differ in output *format* and *value*, beyond intrinsic noise); ready
  scientific MCP servers are **too few** for large studies.
- P3 Insight: an extensible ecosystem of verified scientific tooling shifts
  experiments onto scientists' own code and yields a reproducible catalogue.
- P4 Our realisation: experiment module calls Alembic (repo→served verified MCP),
  then invokes the tool; catalogue grows with each conversion.
- P5 Contributions (system; converter; honest empirical characterisation).

### 2. Related Work — `sections/related_work.tex`
- (a) AI4Science / autonomous scientists (Coscientist/Boiko, ChemCrow, AI
  Scientist, Google AI co-scientist, virtual-lab).
- (b) Coder-agent experiment execution: nondeterminism, cost, failure on research
  repos (SUPER, CORE-Bench, PaperBench, GitTaskBench; temp-0 nondeterminism; pass^k).
- (c) Tool-making / repo→MCP converters: **ToolMaker** (ACL-25, only peer-reviewed),
  Code2MCP, **Paper2Agent** (closest competitor), ToolRosella, AutoMCP; classic
  tool-makers (LATM, CRAFT, Voyager, Toolformer).
- (d) MCP ecosystems & scientific MCP registries (BioContextAI; token-economy).
- (e) Reproducible research software / RSE.
- **Our niche:** not "tools beat code" (cf. CodeAct) but "*freeze the verified
  code path once, reuse across a many-call system*"; ecosystem-level reproducibility.
- _Grounded by background-research agent output (`research/` when it lands)._

### 3. A General AI4Science System — `sections/system.tex`
- CoScientist architecture: **planner → action graph → executor** (executor WIP).
- Where the experiment module sits; reuse-vs-build decision (catalogue lookup →
  else convert via Alembic → invoke).
- The catalogue as shared, growing state; served MCP tools composable by the planner.
- Figure: system diagram (reuse `figures/alembic_workflow.tex`, adapt).

### 4. Alembic: Repo → Verified MCP — `sections/alembic.tex`
- Five agents + four **code-enforced gates** (LLM proposes, code disposes).
- **Split venvs** (`.venv` repo+deps / `.venv-server` fastmcp) + `run_function.py`
  subprocess-router invocation contract (no dependency clash by construction).
- **Evidence-based validation**: smoke vs invocation tests; `perfect` bar;
  **mock-guard** (a `test_invoc_` that mocks the repo is demoted → no hollow validation).
- This is the mechanism that makes catalogue entries *verified & reproducible*.
- Figure: `figures/the_alembic.png` / workflow.

### 5. Experimental Setup — `sections/benchmark.tex`
- **Benchmark:** gold-validated scientific-tool tasks. Primary: **TM-Bench**
  (repo + task + pytest gold, strict value/allclose or format, multi-input cases).
  Breadth/coverage: **ToolRosella** repo set (no gold — used for coverage, not
  correctness). _Final choice grounded by benchmark-survey agent._
- **Systems compared:** frozen Alembic catalogue vs same-model coder agent
  (OpenHands + GLM-5.2) re-deriving each run.
- **Metrics:** (i) coverage/adequacy of the catalogue (how many repos → verified
  tools; tool-adequacy audit: 0 hallucinated / gates catch hollow validation);
  (ii) reproducibility (frozen determinism vs coder pass^k & **contract-drift**);
  (iii) amortised cost / break-even #calls across a many-call system;
  (iv) verification quality (mock-guard catch rate).
- Same-model, disclosed operational limits, released runs.

### 6. Results & Findings — `sections/results.tex`
- **Coverage:** self-metrics delivery table (`tables/alembic_selfmetrics_body.tex`).
- **Reproducibility:** frozen tools deterministic; coder re-derivation can silently
  drift — MUSK contract-drift case; **honest**: TabPFN stable → drift needs
  lenient-gold ∧ genuine-ambiguity (narrow but characterised).
- **Economy:** amortised break-even; honest that per-task it is weak, systemic it
  compounds across many calls + growing reuse.
- **Adequacy/trust:** 0/81 hallucinated tools; mock-guard drops 14% of "perfect".
- **Honest negative space:** capability parity; modern coders set up gated/pinned
  envs fine (11/12 hard-repo runs) — so the win is reproducibility + coverage +
  amortisation, NOT "the agent can't."

### 7. Discussion — `sections/discussion.tex`
- Alembic as **ecosystem infrastructure**; when a verified reusable catalogue pays
  off (many-call systems, reproducibility-critical pipelines, obscure repos).
- Threats: coders getting cheaper/more reliable; conversion verification cost;
  gold coverage; catalogue staleness/versioning.

### 8. Limitations — `sections/limitations.tex`
Capability parity; drift narrowness; env-setup not brittle for modern agents; gold
availability; conversion cost. (Integrity-first, matches the honest findings.)

### 9. Conclusion — `sections/conclusion.tex`
Verified reusable tool ecosystems trade a one-time conversion for coverage,
reproducibility, and amortised cost — infrastructure for generalisable AI4Science.

### Appendix + Reproducibility Checklist
Self-metrics, audit, drift probes, benchmark scoring, all runs.

---

## Reused assets
- Template: `aaai2027.sty` / `.bst` (from latent-underspecification paper).
- `references.bib` = EMNLP `custom.bib` (29 entries) + new citations from research agents.
- Figures: `the_alembic.png`, `alembic_workflow.tex`, `alembic_interface.png`,
  `medsam_*` case study (all from `paper-emnlp26/`).
- Tables: regenerate from `docs/scripts/render_tables.sh` (selfmetrics, error stats,
  tmbench compare).

## Open decisions
- Title wording (see `main.tex`; alternatives in the abstract draft note).
- Final benchmark: TM-Bench alone vs TM-Bench + ToolRosella-coverage (pending survey).
- How much of CoScientist's planner/executor is presentable now (executor is WIP)
  — describe as architecture, scope experiments to the experiment module.

---

## DECISIONS locked from round-2 research (see `research/`)
1. **Lead with reproducibility/determinism, NOT cost.** Inference cost is falling
   fast (a live counterargument); determinism is architectural (`he2025nondeterminism`).
2. **Novelty is the top risk.** Paper2Agent / ToolMaker / ToolUniverse already do
   repo/paper->verified-served-MCP. Our defensible delta = the generalising
   planner->action-graph->executor **system that CONSUMES a growing catalogue across
   domains/studies**, with honest conversion+verification cost. Foreground this.
3. **Hybrid framing:** catalogue-first + coding-agent fallback (not tools-vs-code).
4. **Benchmark: TM-Bench primary** (only gold-validated repo->tool bench, value
   `allclose atol=1e-3` + multi-input). Breadth: ML-Bench / CORE-Bench.
   ToolRosella = repos/coverage only (NO gold: exec + LLM-judge + human).
5. **Reframe claim 2** ("too few tools") -> coverage of *arbitrary domain repos*
   (ToolUniverse shows generic ecosystems already exist).
6. **Honesty section stays:** capability parity; drift narrow (lenient-gold AND
   genuine-ambiguity); modern coders set up gated/pinned envs fine.
