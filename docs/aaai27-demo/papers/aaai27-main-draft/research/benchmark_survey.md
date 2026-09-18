# Scientific-tool benchmark survey (round 2) — verified

Goal: an eval for a system that converts scientific repos into verified MCP tools.
Ideal = (a) real repo + (b) well-defined task + (c) **gold** (value or format) + bonus (d) same tool on multiple input datasets.

## Comparison (verified against arXiv/proceedings/GitHub/HF)

| Benchmark | Repo? | Task? | Gold? | Gold type | Multi-input? | Domains | #tasks | Cite |
|---|---|---|---|---|---|---|---|---|
| **TM-Bench / ToolMaker** | Y (pinned) | Y (task.yaml+sig) | **Y** | **value** `allclose atol=1e-3` + shape | **Y** (per-case ref files) | pathology/bio/med-imaging/ML | 15 / 100+ tests | 2502.11705 ACL-25 |
| **ToolArena** (extended TM-Bench) | Y (pinned+commit) | Y (task.yaml+sig, `requires:` field) | **Y** | **value** `allclose atol=1e-3` + scalar + shape | **Y** (test_invocations) | pathology/bio/med-imaging/genomics | **26** | KatherLab (github, no arXiv id yet) |
| ToolRosella | Y (122→1580 tools) | partial (free-text) | **N** | none (exec + LLM-judge Opus 4.6 + human) | N | 6 dom/35 subdisc | 373 | 2603.09290 |
| CORE-Bench | Y (90 capsules) | Y (reproduce) | **Y** | value, 95% pred-interval | N | CS/social/med | 270/181q | 2409.11363 |
| SUPER | Y (research repos) | Y (setup+exec) | **Y** | value 1e-2 + landmarks | ~ | ML/NLP | 45+152+602 | 2409.07440 EMNLP-24 |
| ScienceAgentBench | Y (44 papers, gold progs) | Y | **Y** | hybrid value/format + LLM-judge | N | bio/chem/geo/neuro | 102 | 2410.05080 ICLR-25 |
| SciCode | ~ (problems) | Y (fn spec) | **Y** | value | ~ | phys/math/mat/bio/chem | 80/338 | 2407.13168 NeurIPS-24 |
| BioCoder | Y (func-level) | Y | **Y** | functional fuzz Pass@K | Y (fuzz) | bioinformatics | 2522 | 2308.16458 |
| ML-Bench | Y (18 ML repos) | Y | **Y** | functional Pass@5 sandbox | **Y** (many/ repo) | ML | 9641/18 | 2311.09835 |
| ResearchCodeBench | Y (20 papers) | Y (masked impl) | **Y** | unit tests | ~ | ML | 212/20 | 2506.02314 |
| PaperBench | Y (replicate) | Y | **Y** | **LLM-judge** rubric | N | ML/AI | 20/8316 | 2504.01848 ICML-25 |
| MLAgentBench | Y | Y (improve) | Y (no gold ans) | value >10% thresh | N | ML-eng | 13 | 2310.03302 ICML-24 |
| DiscoveryBench | ~ | Y | **Y** | LLM-judge (HMS) | N | multi | 264+903 | 2407.01725 |
| BixBench | Y (53 notebooks) | ~ | Y | LLM-judge/MCQ | N | bioinformatics | 53/296q | 2503.00096 |
| BLADE | Y | ~ | Y | hybrid value+graph-iso+judge | Y | data-sci | 12 | 2408.09667 EMNLP-24 |
| DS-1000 | N | Y | **Y** | functional | N | data-sci | 1000 | 2211.11501 ICML-23 |
| SWE-bench / RepoBench | Y (non-sci) | Y | **Y** | value / EM | N | SE | 2294 / ~27k | 2310.06770 / 2306.03091 ICLR-24 |

## ToolRosella gold — DEFINITIVE: none
HF datasets-server `/info`: `downstream` config columns = {id, domain, subdiscipline, query} only — no answer/expected/gold/reference/test column. Paper's 84% = exec success + LLM-judge (Opus 4.6) + human. Scale only, not scoring.

## Recommendation
- **Primary: TM-Bench** — only benchmark mirroring "verified MCP tool from scientific repo" end-to-end, strict numeric gold, multi-input per-case reference files. Limitation: 15 tasks, biomedical-leaning. Successor **ToolArena** (same lineage) for scale.
- **Breadth complements:** **ML-Bench** (multi-input-per-repo scale) and/or **CORE-Bench** (reproducibility of diverse real research repos, value gold).
- **ToolRosella:** repos/tasks for coverage-breadth only; cite as LLM-judge repo-standardisation system + competitor.
- LLM-judge-only gold (weaker for our determinism claim): PaperBench, DiscoveryBench, BixBench.

## Ranked contenders after TM-Bench
Criteria: (1) scientific theme · (2) a real code repo you must / are implied to use ·
(3) gold in some form · (4) readily obtainable & runnable.

**#2a — ScienceAgentBench** (ICLR-25, `OSU-NLP-Group/ScienceAgentBench`, arXiv 2410.05080)
— the best *scientific + gold + available* match.
- (1) ✅ strongest scientific breadth: 102 tasks from real papers in bioinformatics,
  chemistry, GIS/geospatial, psychology/neuroscience.
- (2) ~ each task ships a dataset + a **gold reference program**; code comes from the
  source papers → repo *implied*, not a pinned repo you must wrap (weaker than TM-Bench).
- (3) ✅ but **hybrid**: output value/format checks + LLM-judge for figures (softer than
  TM-Bench value-exact `allclose`).
- (4) ✅ peer-reviewed, GitHub + HF dataset, actively maintained.
- Role for us: broadens domain coverage beyond TM-Bench's biomedical lean; headline second.

**ScienceAgentBench runnability — VERIFIED 2026-07-22 (locally):**
- Code: `git clone https://github.com/OSU-NLP-Group/ScienceAgentBench` → clean (agent.py,
  run_eval.py, `evaluation/harness/`, `compute_scores.py`, `gpt4_visual_judge.py`).
- Gold artefacts: HF dataset = INPUTS only; the gold (`gold_programs/` 102, `eval_programs/`
  111, `datasets/` 76, `scoring_rubrics/` 102) ship in a **1.77 GB password-protected
  SharePoint zip** (`benchmark_verified.zip`, unzip pwd `scienceagentbench`). The anonymous
  SharePoint link 401s on naive curl — needs a cookie jar: GET the `:u:/g/personal/...?e=`
  share URL with `-c cookies.txt` to mint a FedAuth cookie, then GET
  `_layouts/15/download.aspx?share=<TOKEN>` with `-b cookies.txt`. (So "readily available"
  = yes, but the gold is a manual-ish download, not `pip`/`hf` one-liner.)
- Gold harness self-check: ran the `dkpes_model_development_1` gold program (numpy/pandas/
  sklearn RandomForest, tiny CSVs) as the prediction, then its eval → returned
  `(1, {'data_correctness': True, 'func_correctness': True})` = SR 1. The scoring path
  exercised (`from <eval> import eval; eval()`) is exactly what `compute_scores.py` calls.
- Caveats: figure-output tasks additionally need `gpt4_visual_judge.py` (LLM-as-judge, OpenAI
  key) — this is the "hybrid gold" softness; the full 102-task run uses a Docker/conda-per-task
  harness (heavier). The value-based eval path itself is deterministic and verified.

**#2b — CORE-Bench** (`siegelz/core-bench`, arXiv 2409.11363) — **structurally closest to
TM-Bench** and aligned with our reproducibility-first thesis.
- (1) ✅ 90 real research repositories (CodeOcean capsules: code+data+Dockerfile),
  CS / social-science / medicine.
- (2) ✅✅ the task *is* "reproduce this specific provided repository" — tightest
  must-use-the-repo fit after TM-Bench.
- (3) ✅ value-match, 95% prediction-interval tolerance (numeric answers from the run).
- (4) ✅ public but **heavier** (large Docker capsule downloads).
- Role for us: reinforces the "use provided repo + reproducibility gold" structure; the
  reproducibility framing mirrors our thesis.

**CORE-Bench runnability — VERIFIED 2026-07-22 (locally):**
- Code: `git clone https://github.com/siegelz/core-bench` → clean. (Repo note: "no longer
  actively maintained; recommended harness = Princeton HAL." Grader still works standalone.)
- Dataset: `core_train.json` ships unencrypted; `core_test.json.gpg` decrypts with GPG
  passphrase `reproducibility` → 45 test capsules. **Gold answers are embedded** in each
  capsule's `results` field (a list of gold runs). No separate gold download needed for scoring.
- Code capsules: auto-download from `https://corebench.cs.princeton.edu/capsules/<id>.tar.gz`
  — reachable (HTTP 200, `application/x-gzip`, range requests OK) but **~730 MB per capsule**
  → full code-repo set is hundreds of GB. Reproduction runs need **privileged Docker-in-Docker**.
- Gold harness self-check: built a results file with each capsule's report = its gold answers
  (mean of gold runs for numerics → inside the 95% prediction interval) and ran
  `benchmark/evaluations.py::eval_result_file` → **45/45 tasks, 79/79 questions correct**.
- **Grading is fully deterministic** — numeric (95% prediction interval via scipy t-dist),
  list (exact), string (case-insensitive); even "vision"/figure questions are value-matched,
  **NO LLM-judge** in scoring (the `openai` import is only for optional agent-log summaries).
  → a plus over ScienceAgentBench for our determinism thesis. Verified the scoring path, not
  full capsule execution (heavy; hundreds of GB + privileged DinD).

**Honorable mentions (each misses one criterion harder):**
- **SUPER** (EMNLP-24, `allenai/super-benchmark`, 2409.07440): clones+executes real ML/NLP
  research repos, value gold (1e-2) + landmark checks. Repo ✅ gold ✅ available ✅, but
  "scientific" = ML/NLP research, not natural science.
- **ML-Bench** (2311.09835): 18 ML GitHub repos, **best multi-input-per-repo**, functional
  Pass@5 gold. Repo ✅ multi-input ✅, but ML-engineering theme + gold is execution-functional,
  not strict numeric.
- **BioCoder** (2308.16458): bioinformatics, real repo-derived functions, functional fuzz
  gold — but **function-level**, not whole-repo/tool, so it drops the wrap-the-repo shape.

**Pick by what the #2 should ADD next to TM-Bench:** domain breadth → ScienceAgentBench;
"use-the-repo + reproducibility" structure → CORE-Bench. Lead with ScienceAgentBench
(peer-reviewed, most scientific, easiest to get); cite CORE-Bench as the reproducibility
complement.

## Task counts, gold density & GPU (verified 2026-07-22)

| Bench | #tasks | gold density | GPU requirement |
|---|---|---|---|
| **TM-Bench** | **15** (43 multi-input invocations, ~45 test fns) | value-exact allclose ×3 (uni/conch/esm) + exact-scalar ×~4 (pathfinder/stamp_train/stamp_extract/flowmap) + shape/type/existence for rest | **no explicit field** → IMPLIED GPU ×~11 (conch,uni,esm,musk,retfound,stamp_extract,stamp_train,medsam,medsss,flowmap,nnunet-train); CPU ×4 (modernbert,tabpfn,cytopus,pathfinder) |
| **ToolArena** (extended) | **26** | SAME mechanism & rigor tier as TM-Bench: value-exact allclose ×3 (conch/uni/esm) + exact-scalar ×few (pathfinder p_value+HR, flowmap n, stamp_train num_params) + shape/type/existence for ~18-20 | **EXPLICIT `requires:` field** → **cuda ×16** (abrsp,cobra_extract,cobra_heatmaps,conch,eagle,esm,flowmap,medsam,medsss,mopadi,musk,retfound,stamp_extract,stamp_train,totalsegmentator,uni); cpu ×6 (cyvcf2,modernbert,nnunet_preprocess,tabpfn,tiatoolbox_dimensions,tiatoolbox_thumbnailer); unspecified ×4 (cytopus,llmaix,pathfinder,textgrad) |
| **ScienceAgentBench** | **102** (44 papers, 4 disciplines) | reference gold program + output value/format checks + **LLM visual judge** for figure tasks (hybrid) | **no explicit flag**; ~12/102 gold progs use DL frameworks (deepchem ×8, keras ×6, torch ×3, tf ×1, overlapping) → GPU-beneficial but **0 hard-force CUDA** (run on CPU, slow). ~90% pure CPU (pandas/sklearn/matplotlib/geo) |
| **CORE-Bench** | **270** = 90 capsules × 3 difficulty (Easy/Med/Hard); released test = **45 capsules / 79 Q**, train = 45 / 102 Q | numeric 95% prediction-interval + exact list + case-insensitive string; **fully deterministic, NO LLM-judge** | **no per-task GPU boolean in released JSON**; harness distinguishes GPU vs non-GPU tasks (provisions Azure T4 VMs; global `--no_gpu` flag). Minority of capsules GPU-oriented (DL/CUDA papers visible in capsule descriptions) — per-capsule IMPLIED, not labelled |

**"Is ToolArena gold as well-defined?" → YES.** Same human-written per-task pytest (`tests.py`),
same `np.testing.assert_allclose(atol=1e-3)` vs reference `.npy`, same multi-input
`test_invocations`, PLUS an explicit `requires:` (cpu/cuda) field TM-Bench lacks. The strict
VALUE-gold fraction is the same minority as TM-Bench (concentrated on the feature-extractor
tasks conch/uni/esm); most tasks are shape/type/existence contracts in BOTH. ToolArena is the
maintained, containerized, larger (26 vs 15) successor — a strictly better version of the same
gold, just not (yet) a peer-reviewed citation.

## Caveats
Venue UNVERIFIED (arXiv confirmed, peer venue not): ML-Bench, DiscoveryBench, ToolRosella, BixBench, Aviary, LAB-Bench. TM-Bench assertions read from ToolArena submodule (`uni_extract_features/tests.py`), consistent with paper's "100+ unit tests"; frozen `original` branch not line-diffed. ToolArena `requires:` counts read from `tasks/*/task.yaml`; abrsp/eagle carry a template comment beside `cuda` (value taken at face value). SAB/CORE GPU are IMPLIED (no clean per-task flag); ToolArena GPU is the only explicitly-labelled set.
