# Final Research Report

## Objective

Can published ML methods for polymers and rubber, combined with open data, predict the properties of a tire rubber compound from its formulation well enough to propose new formulations with target properties? (ResearchQuestion Q1.)

The concrete scope: survey the accessibility of published polymer/rubber ML methods (Hypothesis H1), benchmark their predictive accuracy on open patent data (H2), and use the best surrogate in an inverse-design pipeline to propose at least 5 passenger-tread candidate formulations meeting Mooney viscosity ∈ [55, 65] and M300 ≥ 10 MPa with honest uncertainty (H3). The empirical base was `tires_2.csv` (3774 compounds from 337 patents; Tool T4) plus the published-method corpus (EB2).

## Approach

The study ran as a three-stage computational ML investigation (Constraint C1, C6):

1. **Accessibility survey (H1, VerificationMethod VM1)** — a literature-and-computational survey of 7 methods from the customer's list (polyBERT https://huggingface.co/xushijie/polyBERT, PolymerGNN https://github.com/owencqueen/PolymerGNN, TransPolymer https://github.com/ChangwenXu98/Tra/https://github.com/ChangwenXu98/TransPolymer.git, Wan et al. 2024, Hu et al. 2024, Roy Choudhury 2025, soft-sensor Mooney models), each checked not by claims but by actual installation and minimal runnable executions.
2. **Forward-model benchmark (H2, VM2)** — plain-recipe XGBoost baseline (733 features) vs. the baseline augmented with polyBERT / TransPolymer / WanDNN representations, evaluated with standard metrics (Tool T3) under random split, patent-holdout split, and 5-fold grouped CV by patent, with paired Wilcoxon tests.
3. **Inverse design (H3, VM3)** — NSGA-II optimization (pymoo) over an ensemble of 5×XGBoost+polyBERT surrogates with CV-std uncertainty, on a search space defined by empirical phr ranges from tires_2.csv, ~120k evaluations.

Constraints honored: patent-grouped splits to avoid leakage (C2), open data/code only (C5), and scope explicitly excluded lab validation and patent-FTO checks (Tool T2).

## Results

### H1 — Accessibility survey: **confirmed** (CC2 met, Evidence E1, Conclusion CL1)

4 of the 7 methods were verified actually runnable (not just claimed): polyBERT (600-dim SMILES embeddings of monomers, homopolymer-property predictor), PolymerGNN (2 training epochs on its own dataset; needs torch_geometric==2.5.3; no released weights), TransPolymer (MIT-licensed; pretrained checkpoint ckpt/https://pretrain.pt loaded, CLS embeddings working via a 2-line shim), and Wan et al. 2024 (all 7 Keras .h5 weights working; formulation+process → mechanical properties, the closest analog to this task). For the remaining three (Hu et al. 2024, Roy Choudhury 2025, soft-sensor Mooney models) code/weights could not be found, with specific reasons documented per method (CodeArtifact CA1, dossiers a–h).

### H2 — Forward benchmark: **refuted** (CC1/CC3 not met, Evidence E2, Conclusion CL2)

- Random split is deceptive: R² = 0.74–0.90, driven by patent-family idiosyncrasies (grade one-hot features).
- Patent-holdout (the honest test for truly novel formulations): R² ≈ −0.28 for Mooney viscosity and ≈ 0.0 for M300; MAE 22.9–23.4 and 3.4–3.6 respectively. No model reached the pragmatic threshold R²_holdout ≥ 0.5.
- Public embeddings do not significantly help: for Mooney, p = 0.275 (polyBERT) and 0.309 (TransPolymer) vs. baseline; for M300 embeddings are significantly **worse** than the baseline.

This is a fully documented negative result: representations pretrained on monomer SMILES do not transfer to phr-based compound formulation prediction on unseen patents. Artifacts: benchmark report <object-store link, see the exported session> artifacts archive <object-store link, see the exported session> fixed splits, metrics, and significance tests (CodeArtifact CA2, GeneratedData GD1).

### H3 — Inverse design: **inconclusive with evidence** (CC4 partially met, Evidence E3, Conclusion CL3)

NSGA-II over the ensemble surrogate produced 5 distinct passenger-tread candidates (pairwise phr-Euclidean distance ≥ 14.3, minimum 10.2 phr from any training formulation; NR+SBR+BR = 100 phr with full compounding environment: CB N234, Zeosil 1165 silica, TESPT, TDAE oil, CBS/DPG/insoluble sulfur):

| Candidate | Mooney ± σ | M300 ± σ (MPa) | Survives 1σ on both |
|---|---|---|---|
| C1 | 60.97 ± 3.02 | 11.02 ± 0.97 | **Yes** |
| C2 | 59.96 ± 4.42 | 11.31 ± 1.19 | **Yes** |
| C3 | 60.22 ± 4.75 | 11.45 ± 1.41 | **Yes** |
| C4 | 64.90 ± 3.50 | 10.55 ± 0.30 | No (M300 2σ ≈ 9.96) |
| C5 | 63.21 ± 1.47 | 10.11 ± 0.86 | No (Mooney 2σ > 65) |

All 5 formally meet the targets (Mooney ∈ [55, 65], M300 ≥ 10 MPa), but the honest caveat: none of the ~120k evaluated variants is 2σ-consistent with both targets; cross-patent extrapolation is weak (see H2) and the uncertainty intervals are optimistic (coverage ≈ 0.39). Full formulation tables are in `h3_candidates.csv/.md` in the H3 artifacts (CodeArtifact CA3, GeneratedData GD2).

### Figures and data

The run produced the following collected outputs:

## Figures

### execute_bash

![execute_bash](object-store link, see the exported session)

*Whole architecture diagram collected from the run — the end-to-end pipeline (feature/embedding preparation from tires_2.csv through benchmarking to inverse design) assembled in this study.*

## Data tables

### bm_features_plain — [download](object-store link, see the exported session)

This is the benchmark feature matrix (3774 × 734) underlying the H2 run: per-compound phr amounts, ingredient grade/type one-hots (including the ~300 SBR/BR grade columns shown above, the source of the random-split leakage), process parameters, and QC flags.

Additional run outputs referenced above and available in the run artifacts: the H2 benchmark report and fixed-split artifacts (object-store link, see the exported session) and the H3 candidate tables (`h3_candidates.csv/.md`).

## Discussion

The answer to Q1 is nuanced:

- **Technically, yes** — 4/7 published methods are reproducible from public code/weights, and they can be assembled into an end-to-end inverse-design cycle that returns plausible, chemically sensible candidate formulations (CL1, CL3).
- **Practically, no** — their predictive accuracy on genuinely novel formulations (held-out patents) is insufficient for standalone target-driven design: R²_holdout ≈ 0 on both target properties, and no representation-based model significantly beats a plain-recipe XGBoost baseline (CL2).

The discrepancy between random-split R² (0.74–0.90) and patent-holdout R² (≈ 0) is the central methodological finding: grade one-hot features encode patent-family idiosyncrasies, so random splits reward memorization of near-duplicate formulations from the same patent. This is a caution for any ML work on patent-derived compound data.

The inverse-design results inherit this weakness. The 1σ-consistent candidates C1–C3 are defensible starting points for experimental screening, but the ensemble's uncertainty is optimistic (coverage ≈ 0.39), and no candidate achieves 2σ-consistency on both targets — hence H3's honest status of **inconclusive** rather than confirmed.

Postponed hypotheses (documented with reasons): H4 (physically-meaningful compositional model — e.g. filler volume fraction), H5 (fine-tuning pretrained polymer language models on tires_2.csv), H6 (generative formulation model). H2's negative result closed the question of representation benefit; H3 closed the applied goal.

## Limitations and next steps

1. **Laboratory validation and patent-FTO checks of candidates C1–C5 are mandatory before any synthesis** — explicitly out of scope for this study (Tool T2, CC4 scope note) and marked as such in the graph.
2. **Data breadth**: tires_2.csv covers 337 patents; the patent-holdout failure suggests the dataset does not span enough formulation diversity for extrapolative prediction. Extending coverage with broader patent or industrial data is the most direct remedy.
3. **Feature engineering over transfer embeddings**: given that monomer-SMILES embeddings did not transfer (CL2), physically-meaningful features (H4) are the more promising direction than pretrained language-model representations.
4. **Calibration**: future inverse-design runs should recalibrate uncertainty (e.g. conformal intervals on holdout patents) — the CV-std intervals here were optimistic.
5. **Fine-tuning and generative models** (H5, H6) remain untested backlog items with documented hypotheses and could be evaluated on the fixed splits already released in <object-store link, see the exported session>