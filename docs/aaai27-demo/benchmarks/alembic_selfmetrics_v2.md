# Alembic × TM-Bench — full sweep results (v2, multi-tool)

**Run:** `benchmarks/alembic/runs/2026-07-10_tmbench-all-v2/`
**Model:** `openrouter/z-ai/glm-5.2` (driver for every agent stage)
**Tasks:** all 15 TM-Bench tasks across 14 repositories (STAMP contributes two tasks from one repo)
**Mode:** **target mode + multi-tool** — the explorer/coder prioritise the benchmark's
required tool but also implement the repo's other most important workflow tools, each
backed by tests and evidence-based invocations (per `upgrade.md`). v1 implemented only the
one required tool per repo; v2 turns each repo into a full multi-tool MCP server.
**Harness:** `run_benchmark.py --tasks <15 yaml> --mount-dir <ToolMaker>/benchmark/data --parallel 4`
**Data:** real ToolMaker `benchmark/data` mounted read-only, staged per-task into
`/mount/input` (TCGA WSI slides, MSD CT volumes, tabular CSVs).

This run also carries the three post-v1 hardening fixes (venv-local `ensure_pkg`
re-verify, `ensure_server_packages`, G4 real-fastmcp check) and resilient OpenRouter error
handling (bounded one-line logs + retry, no stack-trace walls). See "What changed since v1".

---

## Headline

| Metric | v1 (single-tool) | **v2 (multi-tool)** |
|---|--:|--:|
| Repos completed (exit 0) | 14 / 14 | **14 / 14** |
| Tools generated | 15 | **77** |
| Tools **passed** (all tests green **and** never crashed) | 10 | **67 / 77** |
| Tools **perfect** (passed **and** every invocation-correctness test green) | 5 | **35 / 77** |
| Unit tests passed | 25 / 25 | **197 / 197** (100 %) |
| Invocation-correctness tests passed | 5 / 5 | **62 / 70** (89 %) |
| Execution-OK (didn't crash) | 10 / 15 | **53 / 63** |
| `installed-<task>` runtime images tagged | 15 / 15 | **15 / 15** |
| `code.py` TM-Bench exports | 12 / 12 | **15 / 15** (one per task) |
| Real MCP servers / shims | 13 real + **1 shim (esm)** | **14 real / 0 shims** |

**All three previously API-blocked repos recovered.** In v1, MUSK / ModernBERT / UNI were
killed by OpenRouter `HTTP 403` policy rejections and produced no tool. In v2 they ran
clean: **UNI 5/5 (all perfect), MUSK 5/5, ModernBERT 5/4** — closing the only "failures"
v1 flagged as re-runnable.

**The esm shim is gone.** v1's one non-functional server (a fake `class FastMCP` stub) is
now structurally impossible: **all 14 servers import a real, venv-local fastmcp with zero
inline shim classes** (grep-verified). The two repos that took the LLM-fallback wrapper
path (PathFinderCRC, UNI) both produced real fastmcp imports — the fallback now yields a
real server or fails G4 honestly.

> **Read "Metrics trust & caveats" before quoting these numbers.** `67 passed` is not
> `67 shippable-and-verified tools`: some passes rest on soft signals (a 120 s-timeout
> counted as runtime-success, or a tool with no invocation-correctness assertion). The
> **35 perfect** tools are the fully-trustworthy core, and of the **15 required TM-Bench
> task tools specifically, only 6 are perfect** — see the required-tool trust table.

---

## Per-repo results (v1 → v2)

| Repo | tools v1→v2 | passed v1→v2 | perfect v1→v2 | tests | invoc | exec | resets | min |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|--:|
| cytopus | 1 → **9** | 1 → **9** | 1 → **9** | 24/24 | 19/19 | 9/9 | 0 | 22 |
| CONCH | 1 → **5** | 1 → **5** | 1 → **4** | 16/16 | 4/4 | 4/5 | 1 | 24 |
| MedSAM | 1 → **5** | 1 → **5** | 1 → **4** | 10/10 | 9/9 | 3/5 | 0 | 57 |
| TabPFN | 1 → **4** | 1 → **4** | 1 → **4** | 13/13 | 8/8 | 1/4 | 0 | 36 |
| PathFinderCRC | 1 → **4** | 1 → **4** | 1 → **3** | 14/14 | 3/3 | 4/4 | 0 | 26 |
| **UNI** ⬆ | 0 → **5** | 0 → **5** | 0 → **5** | 10/10 | 5/5 | 5/5 | 1 | 48 |
| **MUSK** ⬆ | 0 → **5** | 0 → **5** | 0 → **0** | 10/10 | 0/0 | 5/5 | 1 | 21 |
| **ModernBERT** ⬆ | 0 → **5** | 0 → **4** | 0 → **0** | 14/14 | 2/2 | 0/5 | 1 | 53 |
| esm | 1 → **7** | 1 → **7** | 0 → **4** | 15/15 | 4/4 | 7/7 | 1 | 166 |
| MedSSS | 1 → **6** | 0 → **4** | 0 → **1** | 12/12 | 2/6 | 0/6 | 1 | 64 |
| STAMP (×2 tasks) | 2 → **6** | 2 → **4** | 0 → **0** | 13/13 | 2/4 | 4/6 | 1 | 56 |
| nnUNet | 1 → **8** | 0 → **5** | 0 → **0** | 23/23 | 0/2 | 5/8 | 1 | 72 |
| flowmap | 1 → **5** | 1 → **3** | 0 → **1** | 15/15 | 4/4 | 3/5 | 1 | 34 |
| RETFound_MAE | 1 → **3** | 1 → **3** | 0 → **0** | 8/8 | 0/0 | 3/3 | 1 | 56 |
| **TOTAL** | 15 → **77** | 10 → **67** | 5 → **35** | **197/197** | **62/70** | **53/63** | 11 | — |

⬆ = recovered from a v1 OpenRouter-403 block. Avg tools/repo went 1.07 → **5.5**.

---

## Required-task-tool trust (the number that matters for TM-Bench scoring)

TM-Bench scores the **one required tool per task**, whose `code.py` is exported. The other
64 tools are the multi-tool bonus. Judging only the 15 required tools, and auditing each
against its real test/exec evidence (not just the `passed` flag):

| Required task tool | passed | perfect | tests | invoc | exec | trust tier |
|---|:--:|:--:|:--:|:--:|:--:|---|
| cytopus_db | ✓ | ★ | 3/3 | 3/3 | ✓ | **PERFECT** |
| conch_extract_features | ✓ | ★ | 3/3 | 1/1 | ✓ | **PERFECT** |
| medsam_inference | ✓ | ★ | 2/2 | 2/2 | ✓ | **PERFECT** |
| pathfinder_verify_biomarker | ✓ | ★ | 3/3 | 1/1 | ✓ | **PERFECT** |
| tabpfn_predict | ✓ | ★ | 3/3 | 2/2 | ✓ | **PERFECT** |
| uni_extract_features | ✓ | ★ | 2/2 | 1/1 | ✓ | **PERFECT** |
| musk_extract_features | ✓ | – | 2/2 | 0/0 | ✓ | solid (real tests+exec, no correctness ground-truth) |
| flowmap_overfit_scene | ✓ | – | 3/3 | 0/0 | ⏱ | real tests, exec via 120 s-timeout grace |
| nnunet_train_model | ✓ | – | 3/3 | 0/0 | ⏱ | real tests, exec via 120 s-timeout grace |
| esm_fold_predict | ✓ | – | –¹ | –¹ | ⏱ | **weak** — no unit test ran (>120 s), exec = timeout grace |
| stamp_train_classification_model | ✓ | – | –¹ | 0/0 | ✓ | **weak** — no unit test ran; exec = output-path (not invoked) |
| retfound_feature_vector | ✓ | – | –¹ | –¹ | ⏱ | **HOLLOW** — 0 tests + 120 s-timeout exec only |
| stamp_extract_features | ✓ | – | –¹ | –¹ | ⏱ | **HOLLOW** — 0 tests + 120 s-timeout exec only |
| medsss_generate | ✗ | – | 2/2 | 0/0 | ✗ | **honest fail** — `RuntimeError: Failed to infer device type` (CPU) |
| modernbert_predict_masked | ✗ | – | 2/2 | 2/2 | ✗ | **honest fail** — `ValueError: input_string must be a string` at exec |

¹ tool timed out at the 120 s cap before any unit test completed.

**Required-tool tally:** **13/15 passed, 6/15 perfect.** Broken out by trust:
- **6 fully trustworthy** (perfect: real tests + real evidence-based correctness assertion).
- **1 solid** (musk — real tests + real exec, no repo ground-truth to assert on).
- **2 real-tests / timeout-exec** (flowmap, nnUNet — tests green, correctness unverified because exec went long).
- **2 weak** (esm, stamp_train — passed on exec-grace with no unit test that ran).
- **2 HOLLOW** (retfound, stamp_extract — "passed" purely on the 120 s-timeout grace with **zero tests**; same weak-pass class flagged in v1).
- **2 honest failures** (medsss_generate, modernbert_predict_masked — `passed=False`; the required tool crashed at exec on this CPU box, though **4 of each repo's other workflow tools passed**, which is why the repos still show 4-passed totals).

So the required tool's `passed=True` should be read as "ran without crashing," not "verified
correct." The verified-correct required tools are the **6 perfect** ones.

---

## RETFound — did the new HF access fix it?

**No — the gated-weights block recurred.** RETFound's required tool still shows
`GatedRepoError` (2 hits in the log) and its exec is only the 120 s-timeout grace with 0
tests — it never loaded real weights. The granted HF access to `RETFound_mae_natureCFP`
either isn't reaching that specific download, or the repo pulls a *different* gated repo the
token doesn't cover. This is the one v1 "re-runnable with HF access" prediction that did
**not** pan out; worth a targeted check of which HF repo id its `hf_hub_download` actually
requests and whether `HF_TOKEN` is in scope for it.

---

## Metrics trust & caveats (post-hoc log audit)

The headline comes straight from `validation.json` (R2), but not every "passed" is equally
solid — the audit methodology from v1 carries forward:

- **Fully trustworthy — the 35 perfect tools**: real unit tests green **and** a real
  evidence-based invocation-correctness test green. cytopus alone contributes 9 perfect
  tools (24/24 tests, 19/19 invocations) — the clearest demonstration of the multi-tool
  path producing a rich, verified server.
- **8 invocation-correctness tests failed** (invoc 62/70), all on **extra** workflow tools,
  **none on a required task tool**: MedSSS ×3 (`score_benchmark`, `run_mcts_self_gen`,
  `score_trajectories`), nnUNet ×1 (`nnunet_evaluate`), STAMP ×2 (`stamp_deploy_model`,
  `stamp_crossval` — the latter a real `ValueError: Usecols do not match columns`). These
  are the honest cost of writing *varied* evidence-based invocations: harder assertions
  that don't all hold, surfaced rather than hidden.
- **Timeout-grace passes**: several tools' `exec_ok=true` is the 120 s-timeout grace
  (resource-heavy runtime treated as success, not a confirmed correctness signal). Real for
  "didn't crash," not for "produced the right answer."
- **`197/197 tests` and `62/70 invoc` are 100 %/89 % of the tests that ran.** Tools that
  timed out before their tests completed (esm required tool, retfound, stamp_extract)
  contributed **zero** tests — their pass rests entirely on exec-grace.

**Bottom line:** `35 perfect` is the number to trust unconditionally. `67 passed` is a real
signal of breadth (14 rich multi-tool servers, all real) but includes timeout-grace and
no-assertion passes. For the paper's TM-Bench claim specifically, lead with **13/15 required
tools passed, 6/15 verified-perfect**, and disclose the 2 hollow + 2 honest-fail required
tools.

---

## What changed since v1 (validated by this run)

1. **Multi-tool target mode** — explorer proposes required tool(s) first, then the repo's
   other workflow tools; coder implements every one with tests + varied invocations.
   Result: 15 → 77 tools, avg 5.5/repo, without losing the required-tool priority (all 15
   required tools produced + exported).
2. **Shim path closed** — three hardening fixes (venv-local `ensure_pkg` re-verify,
   `ensure_server_packages` for fastmcp+mcp, G4 real-venv-local-fastmcp check). Evidence:
   **14/14 real fastmcp imports, 0 inline shims**; the two LLM-fallback wrappers
   (PathFinderCRC, UNI) both produced real servers. esm — v1's shim — is now a real 7-tool
   server (4 perfect).
3. **Resilient OpenRouter handling** — the 403 stack-trace walls that killed MUSK / UNI /
   ModernBERT in v1 are gone; transient faults now log one line and retry. All three
   recovered to full multi-tool servers. (Note: the *concise* event-loop handler edit in
   `agent_runtime.py` lands on the **next** base-image rebuild — it was made after this
   sweep launched, so it did not affect these logs.)

## Verification of TM-Bench deliverables

- **`installed-<task>` runtime images: 15/15 present** (both STAMP tasks committed off the
  single STAMP image).
- **`code.py` exports: 15/15** — one per task, each a self-contained plain function
  (imports inside the body) with the task-specified signature.

## Suggested follow-ups

1. **RETFound gated weights** — diagnose the specific HF repo id + token scope; it is the
   one required tool still blocked (see section above).
2. **medsss_generate / modernbert_predict_masked** — the two honest required-tool failures.
   MedSSS needs a real accelerator (`Failed to infer device type` on CPU); ModernBERT's
   `input_string must be a string` looks like a fixable input-handling bug in the generated
   tool, not pure hardware — worth a targeted re-run/patch.
3. **Env-budget for mega-downloads** — esm (166 min, 22.5 GB image) and nnUNet dominate
   wall-clock on weight/torch downloads; pre-seeding CPU-torch into the base image would
   free their env budget for repo deps.
4. **Raise/parameterise the 120 s exec cap** for the known resource-heavy required tools
   (retfound, stamp_extract, flowmap, nnUNet) so their exec becomes a real signal instead
   of timeout-grace — in no-timeout mode this converts hollow passes into verified ones.
