## Objective

Can published ML methods for polymers and rubber, together with open data, predict the properties of a tire rubber compound from its formulation (phr recipe) well enough to propose new formulations with target properties (ResearchQuestion Q1)? The run targeted, concretely: Mooney viscosity and M300 on the open patent dataset `tires_2.csv` (3774 compounds, 337 patents), a forward-model benchmark against a plain-recipe baseline, and an inverse-design step producing at least 5 candidate passenger-tread recipes with ensemble-predicted Mooney 55–65 and M300 ≥ 10 MPa.

## Approach

The study was a fully computational ML investigation (Constraint C1) run on the patent dataset T4 (`tires_2.csv`), with strict ML hygiene norms (Constraint C2): patent-grouped splits to avoid leakage from near-duplicate compounds within patents, seed-42 fixed splits, standard R²/MAE metrics and uncertainty evaluation (Tool T3). Only open data, code and public models were used (Constraint C5; Resource R1: 0 paid resources).

Three tested hypotheses, each with a pre-registered ConfirmationCriteria (CC2/CC3/CC4):

- **H1 (refuted)** — public pre-trained representations (polyBERT embeddings, TransPolymer CLS embeddings, Wan et al. formulation representation learning) improve Mooney/M300 prediction over a plain-recipe XGBoost baseline. Verified by VM1 (survey + benchmark; Tools T1, T5, T6, T7; code artifacts CA1).
- **H2 (refuted)** — the best forward model achieves practically useful patent-holdout accuracy: R²_holdout ≥ 0.5, MAE ≤ 0.5·SD(target), CV–holdout stability within 0.1, calibrated uncertainty (conformal coverage ≥ 80% at α=0.2). Verified by VM2 (done; code CA2).
- **H3 (inconclusive)** — constrained inverse design over the phr formulation space yields ≥ 5 feasible, novel candidate recipes with predicted Mooney ∈ [55, 65], M300 ≥ 10 MPa, quantified uncertainty and robustness. Verified by VM3 (constrained evolutionary neighborhood search anchored to training presence patterns; code CA3, Evidence E4).

Four hypotheses remain documented as postponed backlog: H4 (hybrid features), H5 (secondary properties), H6 (publication-to-patent domain-gap audit), H7 (data-efficiency scaling), and H8 (mandatory laboratory confirmation of candidates, explicitly out of scope per Tool T2).

## Results

### Survey of public methods (E2)

Of 9 surveyed published methods, only **Wan et al. 2024** (https://github.com/Vanguer/rubber-mechanical-properties-prediction) natively works with phr formulations; polyBERT, TransPolymer, PolymerGNN, polyGNN and PolyNC are monomer-SMILES methods, applicable to multicomponent recipes only via phr-weighted aggregation of ingredient embeddings. Licenses: TransPolymer — MIT (https://github.com/ChangwenXu98/TransPolymer, checkpoint https://pretrain.pt); Wan et al. — open repository; polyBERT — GTRC Academic (non-commercial, patent pending). Roy Choudhury et al. 2025 could not be located (no fix attempted). Mooney soft-sensors operate on process variables, not formulations — inapplicable to recipe design.

### Forward-model benchmark (E1, E3; H1 and H2 refuted)

After missing-value filtering: Mooney n=1282 (120 patents), M300 n=1517 (177 patents); splits fixed with seed 42.

| model | Mooney R² (random → patent-holdout) | M300 R² (random → patent-holdout) |
|---|---|---|
| plain-recipe XGBoost (baseline) | 0.743 → **−0.23** | 0.898 → **+0.02** |
| polyBERT (phr-weighted) | 0.752 → −0.23 | 0.895 → −0.09 (significantly worse, p<1e−4) |
| TransPolymer CLS | 0.744 → −0.23 | 0.903 → 0.00 |
| WanDNN | 0.361 → −0.18 | 0.792 → −0.05 |

- **H1 refuted (CL1, CC2 not met):** no public representation significantly beat the plain-recipe baseline on both split types for either target.
- **H2 refuted (CL2, CC3 not met):** the best model (tuned plain XGB for both targets) fails every CC3 sub-condition — Mooney R²_holdout = −0.228 (worse than predicting the mean), MAE = 23.42 (0.83·SD), CV–holdout delta 0.18 > 0.1, conformal coverage 0.626 at α=0.2. M300 holdout R² ≈ 0.02. The random-split R² of 0.74–0.90 is inflated by near-duplicate compounds within patents. The E3 diagnosis is a genuine patent distribution shift (KS 0.16–0.17 on targets, up to 0.35 on carbon_black), not leakage or underfitting.

### Inverse design (E4, H3 inconclusive)

VM3's constrained evolutionary neighborhood search (anchored to training presence patterns — NR/SBR/BR + full curing system, phr within per-ingredient 1–99 pct bounds) produced 5 candidates satisfying the CC4 requirements: ensemble-mean Mooney 59.8–62.8 (within [55,65]), M300 10.5–14.1 MPa (≥10), member std 0.72–0.98 (Mooney) / 0.23–0.34 (M300), novelty (NN-distance ≥ 0.46 vs 0.30 threshold), robustness ≥ 4/5 CV folds on both targets. Example candidate C1: SBR 90.7 phr; silica 28.7; S 1.55; accelerators/ZnO/stearic acid; cure 177 °C/13 min → predicted Mooney 61.1 ± 0.72, M300 12.9 ± 0.30 MPa. Full 742-feature vectors are in `vm3_candidates.csv`.

However, **H3 remains inconclusive** rather than confirmed: the validator (CL3) notes that the recorded execution provenance shows only a successful write of the candidate vectors, and the novelty metric was truncated in transmission — the numbers nominally satisfy the criterion but could not be fully verified from provenance.

![execute_bash](figures/execute_bash_whole_arch.jpg)

The architecture figure collected above is the single figure artifact retained by this run; the remaining collected outputs are machine-level data tables (33 files, e.g. `tables/embed_psmiles_result.json`, containing raw polyBERT embedding vectors from `bm_embeddings.py`) that serve as reproducibility artifacts rather than reader-facing summaries.

### Verdict on Q1

Public ML methods in their current form do **not** predict tire-compound properties reliably enough for application to unseen patents (the main barrier being patent-level distribution shift, not representation quality). Within the training distribution, models do work and allow machine generation of formally valid candidate recipes with target properties — at screening-level, predicted-only confidence.

## Discussion

The most informative finding is negative and mechanistic: the collapse from random-split R² 0.74–0.90 to patent-holdout R² ≈ 0 or below is attributable to real distribution shift between patents, not to model choice, leakage, or underfitting — polyBERT, TransPolymer and plain features all fail almost identically on holdout. This reframes the practical bottleneck for Q1: better representations alone will not fix patent-level generalization; more diverse training patents or domain adaptation would be needed. It also retroactively explains why published monomer-SMILES methods do not transfer: they were never formulation-native in the first place (only Wan et al. 2024 works on phr directly), and the Wan et al. architecture's weights are not transferable to this dataset (T6), so it had to be retrained, performing below the XGBoost baseline.

The 5 inverse-design candidates should be read with the refutation of H2 in mind: since the forward ensemble does not generalize to unseen patents, the candidates carry predicted-only confidence within the training distribution. The validator additionally flagged (CL3) that VM3's execution provenance was incomplete and the novelty metric truncated, which is why H3 was recorded as inconclusive despite the candidate table nominally meeting CC4. Three of four ConfirmationCriteria (CC2–CC4) are marked not_met in the graph, consistent with two refutations and one inconclusive verdict; all three Conclusions CL1–CL3 are approved by the ValidatorAgent.

All hypotheses H4–H8 remain documented postponed items in the backlog; H8 (laboratory confirmation) is explicitly required before any candidate is trusted.

## Limitations and next steps

- **Validity bounds (CL1, CL2):** all refutations are bounded to `tires_2.csv`, the two targets (Mooney, M300), the three public representations as implemented, the plain-recipe XGBoost baseline, seed-42 group-aware splits and the paired-bootstrap protocol. They do not rule out better patent-level generalization from richer features, more diverse training patents, other model classes, or domain adaptation.
- **H3 verification:** re-run VM3 with full execution provenance and a complete novelty-metric report so the CC4 check can be independently confirmed; the pipeline (`vm3_design.py`, artifacts `vm3_candidates.csv`, `vm3_report.md`) is fully reproducible.
- **Backlog:** test H4 (hybrid phr + embedding features), H5 (secondary properties — tensile strength, elongation, hardness, tan delta), H6 (formal domain-gap audit vs published accuracies), H7 (data-efficiency scaling with number of distinct training patents).
- **Mandatory follow-up:** H8 — laboratory mixing/curing and ISO 37 / ISO 289 measurement of the 5 candidates (out of scope per T2, explicitly required before any practical use).
- **Reusable assets:** all scripts and artifacts are preserved (`bm_features.py`, `bm_embeddings.py`, `bm_metrics.csv`, `bm_significance_bootstrap.csv`, `vm2_final.py`, `vm2_*` metrics/CV/conformal/leakage-audit/seed files, `splits/`); the TransPolymer embedding wrapper (T5) and Wan et al. predictor (T6) are registered as callable Tools for follow-up studies.