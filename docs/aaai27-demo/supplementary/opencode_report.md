# Computational design of tyre rubber recipes from patent data

Research question: can published machine-learning methods for polymers and rubber,
together with open data, predict the properties of a tyre rubber compound from its
recipe well enough to propose new recipes with target properties?

Short answer: property models trained on 3,774 patent compounds interpolate well
inside the dataset and fail to generalize to recipes from unseen patents. Only M300
survives the honest test. Five candidate tread recipes are proposed below, with a
quantified statement of how far their predictions can be trusted.

## 1. Survey of published methods

For each method: what it predicts, how it encodes a compound, and whether code,
weights, and data are available and run on this machine (Python 3.12, CPU).

| Method | Predicts | Encoding | Code | Weights | Data | Runs? |
|---|---|---|---|---|---|---|
| polyBERT (Kuenneth and Ramprasad, Nat. Commun. 2023, doi:10.1038/s41467-023-39868-6) | 8 polymer properties (Tg, Eea, Ei, etc.) from fingerprints | DeBERTa-v2 language model over PSMILES repeat-unit strings; 600-d mean-pooled fingerprint | Official repo Ramprasad-Group/polyBERT ships no source; obtainable by email request under an academic licence | Yes, via HF copies xushijie/polyBERT and kuelumbus/polyBERT | ~80k PSMILES from the paper (fingerprints reusable; property heads absent) | Yes, via the HF copies. Load, tokenize, embed all worked out of the box |
| TransPolymer (Xu et al., npj Comput. Mater. 2023, doi:10.1038/s41524-023-01016-5) | 10 polymer properties (conductivity, band gap, Xc, ...) | RoBERTa (6 layers) over SMILES with a chemical-aware BPE tokenizer; pretrain on ~5M sequences | Yes, github.com/ChangwenXu98/TransPolymer | Yes, ckpt/pretrain.pt (328 MB) included | Yes, pretrain corpus and 10 downstream datasets included | After repair. The custom tokenizer breaks under transformers 5.x (base __init__ calls get_vocab before self.encoder exists). A standalone reimplementation of its BPE (same regex, vocab, merges) loads the published checkpoint cleanly; embeddings verified reproducible |
| PolymerGNN (Queen et al., npj Comput. Mater. 2023, doi:10.1038/s41524-023-01034-3) | IV and Tg of polyesters, jointly | GNN over monomer graphs plus a deep set over monomer compositions; extra resin variables | Yes, github.com/owencqueen/PolymerGNN | No pretrained weights published | Data table (dataset/pub_data.csv, Eastman polyesters) yes; the required monomer .xyz geometries are absent from the repo (only CREST .out logs, no conversion script) | Partially. Code imports and the package installs with current torch-geometric 2.8, but GraphDataset cannot run end to end without regenerating monomer geometries. Scope check: the data are unfilled linear polyesters, so the method is out of scope for filled rubber anyway |
| Wan et al., Compos. Commun. 2024, doi:10.1016/j.coco.2024.102072 | Mechanical properties of polymer nanocomposites from processing + microstructural descriptors | Recipe and process features; microstructure-annotated GNN | No public code found | No | No public dataset | No |
| Wan et al., Chin. J. Polym. Sci. 2024, doi:10.1007/s10118-024-3216-3 | Mechanical properties of CB-filled rubber from processing effects | Recipe/process features | No public code found | No | No public dataset | No |
| Hu et al., J. Mater. Inform. 2024, doi:10.20517/jmi.2024.11 | Tensile stress of natural rubber via data augmentation trained on MD simulation data | SMILES/MD-derived features; augmentation framework | No public code found | No | MD data described in the earlier Polymers 2022 paper (doi:10.3390/polym14091897), also without a public dump | No |
| Roy Choudhury et al., J. Rubber Res. 2025, doi:10.1007/s42464-025-00331-4 | Three mechanical properties of NR-based formulations | Plain recipe features; ANN, RF, decision tree, XGBoost | None | None | "Data will be made available on request" (Springer data-availability statement) | No |
| Zhang et al., Polymers 2022, doi:10.3390/polym14051018 (Mooney soft sensor) | Mooney viscosity of industrial mixes from process variables | Just-in-time semi-supervised learning on mixer process data | No | No | Proprietary plant data | No |
| Zheng et al., Sensors 2020, doi:10.3390/s20030695 (Mooney soft sensor) | Mooney viscosity from mixing process variables | Deep kernel learning on process data | No | No | Proprietary plant data | No |

Two additional observations. First, the two soft-sensor papers predict Mooney from
process trajectories of a specific plant, so their inputs are unavailable for patent
recipes. Second, no surveyed rubber-specific method publishes runnable code and
weights; the runnable ones (polyBERT, TransPolymer) are polymer-text models that
expect a PSMILES repeat unit, and a rubber compound is a mixture of several
elastomers plus fillers, oil, and cure chemicals.

That gap forced a representation decision, described in section 3.

## 2. Data

tires_2.csv: 3,774 compounds from 337 patents; 78 columns; recipe in phr (9
elastomer columns, fillers, oil, cure package), grade/type columns, process
parameters, 15 property columns with gaps.

Cleaning (scripts/02_features.py, bounds in artifacts/cleaning_stats.json):
target values outside physical ranges were set to missing before modelling.
Examples: Mooney values of 0, tan delta up to 141, scorch t5 up to 1,851 min,
abrasion up to 166,000 mm3, tensile up to 162 MPa. Usable sample sizes after
cleaning: Mooney 1,278; M300 1,517; tensile 1,707; elongation 1,553; hardness
1,047; M100 1,115; tan delta 0C 513; tan delta 60C 673; abrasion 485; t90 744;
scorch 392; rebound 297.

Dataset structure. Rows from one patent are near copies: 2,668 of 3,774 rows share
an exact elastomer+filler+oil+sulfur recipe with another row, and 1,400 rows are
identical on every feature column. Median within-patent Mooney variance is 58,
against an overall variance of 533.

Extraction-quality columns (qc_flags, qc_repaired, qc_soft_issues) are metadata
about how the CSV was produced; they were excluded from features. The qc_flags
format ("llm=" vs "ref=") indicates the dataset itself was built by an LLM
extraction pipeline over patents.

## 3. Forward models

### 3.1 Protocol

Features ("plain" representation): 38 numeric recipe/grade/process columns plus 10
derived ratios (filler per 100 elastomer, cb share, sulfur per 100 elastomer,
accelerator-to-sulfur, silane per 100 silica, and similar), plus 14 categorical
type/grade columns one-hot encoded. Missing numeric values imputed to the
training median with indicators; CB_CTAB_m2g has no observed values and is
dropped by the imputer.

Two evaluation protocols, five folds each (scripts/03_baselines.py):
random row-shuffled KFold, and patent GroupKFold holding out all rows of whole
patents. Models: median dummy, ridge (alpha 10), PLS (20 components), random
forest (250 trees), HistGradientBoosting (400 iterations).

### 3.2 Which split reflects use on a new recipe

The patent-grouped split is the honest one. A new recipe from a new producer
corresponds to a patent the model has never seen. The random split answers a
different question: interpolation among near-duplicates. Quantification
(results/leakage_random_split.csv): under the random split, 50 percent of Mooney
test rows and 36 percent of M300 test rows have an exact feature-level duplicate
in the training folds, and 98 to 99 percent of test rows share a patent with a
training row.

### 3.3 Baseline results (best tree model per target)

R2, mean over 5 folds (results/baseline_summary.csv):

| Target | n | Random R2 | Random MAE | Patent R2 | Patent MAE |
|---|---|---|---|---|---|
| mooney_viscosity | 1278 | 0.78 | 6.9 | 0.06 | 16.7 |
| M300_MPa | 1517 | 0.87 | 1.1 | 0.39 | 2.8 |
| M100_MPa | 1115 | 0.79 | 0.4 | 0.10 | 0.8 |
| tensile_strength_MPa | 1707 | 0.80 | 1.5 | 0.06 | 3.3 |
| elongation_at_break_pct | 1553 | 0.69 | 46 | 0.24 | 79 |
| hardness_shore_A | 1047 | 0.85 | 2.3 | -0.24 | 7.3 |
| tan_delta_0C | 513 | 0.82 | 0.04 | 0.02 | 0.13 |
| tan_delta_60C | 673 | 0.74 | 0.02 | -0.08 | 0.04 |
| abrasion_loss_mm3 | 485 | 0.57 | 15 | 0.05 | 23 |
| t90_min | 744 | 0.78 | 4.2 | -0.49 | 9.4 |
| mooney_scorch_t5 | 392 | 0.73 | 2.6 | 0.07 | 5.0 |
| rebound_60C_percent | 297 | 0.89 | 3.5 | -0.71 | 11.7 |

Every target shows the same pattern: strong under the random split, at or below
zero under the patent split, with M300 (R2 0.39, MAE 2.8 MPa) and elongation
(R2 0.24) as partial exceptions.

### 3.4 Representations from the published models that run

polyBERT and TransPolymer accept one polymer PSMILES each. A rubber compound is a
mixture, so each row was encoded as a phr-weighted mean of its elastomer
component fingerprints (scripts/04 and 05). Components: NR, ENR unit,
butadiene-1,4, butadiene-1,2, polystyrene, PAN, PE, PP, PIB, PVDF, HFP,
chloroprene; all 12 validated in RDKit. SBR rows expanded into BD14/BD12/PS using
the row's styrene and vinyl columns (dataset default 23.5 percent styrene where
missing). Full mapping in artifacts/psmiles_report.json.

Representations compared under identical folds (scripts/06_repr_compare.py,
results/representation_summary.csv), targets Mooney and M300:

Mooney viscosity, patent split, best model per representation:
plain 0.06 (RF), no_elastomer_cols 0.02 (RF), plain+polyBERT 0.03 (RF),
polyBERT-fingerprints-only 0.00 (RF), TransPolymer-fingerprints-only -0.00 (RF).
Random split stays at 0.76 to 0.78 everywhere.

M300, patent split, RF: plain 0.391, plain+polyBERT 0.406, polyBERT-only 0.397,
TransPolymer-only 0.398, no-elastomer-columns 0.323. The
fingerprints-only variants carry elastomer identity yet are nearly as strong as
the full plain set (0.39 to 0.41 vs 0.39). Removing all elastomer identity costs
the no_elast variant 0.07 R2, and both polyBERT and TransPolymer restore it to
the plain-set level.

Interpretation. For M300, polyBERT and TransPolymer fingerprints encode the
elastomer phase of a compound about as well as the raw recipe columns do, and
they transfer across patents at the same level. For Mooney, no representation
reaches a useful level under the patent split. Permutation importance
(results/permutation_importance.csv) explains why: the top Mooney feature is
elastomer_mooney_raw (importance 0.26, about four times the next feature), the
measured Mooney of the neat elastomer batch. That input is a laboratory
measurement of the purchased rubber, unavailable before a recipe exists, and the
published structure-only fingerprints cannot replace it. M300 importance
spreads over cure and process variables (vulcanization time 0.12, BR cis 0.06,
NR 0.05, ZnO 0.04).

### 3.5 The measurement-input problem

The dataset mixes three kinds of inputs: recipe amounts, process parameters, and
one ingredient measurement (elastomer_mooney_raw). Modelling with all three
inflates the random-split score and hides the fact that a design-time model
lacks the measurement. All inverse-design models in section 4 therefore exclude
elastomer_mooney_raw.

## 4. Inverse step: five candidate tread recipes

Task: passenger tread, Mooney viscosity 55 to 65, M300 at least 10 MPa.

Method (scripts/07_inverse.py). Per target, an ensemble of five
HistGradientBoosting models trained on the five patent-grouped folds; candidate
prediction is the ensemble mean, ensemble disagreement the std. Honesty metrics
come from the same grouped CV (results/inverse_design_cv.csv): Mooney R2 -0.18,
MAE 18.7; M300 R2 0.29, MAE 2.9. Because the design excludes
elastomer_mooney_raw (a measurement unavailable at design time), the models are
the weaker design-time variant, and the table in 3.3 is the stronger
measurement-time variant.

Candidate space: NR/SSBR/BR blends (elastomer total 100 phr), CB N234/N339/N330,
optional silica Zeosil 1165MP with TESPT silane, TDAE oil, insoluble sulfur,
CBS or TBBS primary accelerator, DPG secondary, 6PPD antioxidant, process
fixed at dataset medians (mix 160 C, cure 150 C, 25 min, 2 stages). 66,202
random candidates; 7,707 passed the target box with support (Mooney 53 to 67,
M300 at least 10.5, nearest-neighbour distance within the 75th percentile of
training distances). The final five were chosen from k-means clusters over the
recipe axes for diversity, then ranked by closeness to target, ensemble
disagreement, and support distance.

### The five recipes (phr)

| # | NR | SSBR | BR | CB (grade) | Silica | TESPT | Oil | S | Primary acc. | Sec. acc. | ZnO | Stearic | 6PPD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 28.6 | 30.6 | 40.8 | 37.4 (N339) | 55.8 | 4.8 | 25.9 | 1.8 | 2.4 TBBS | 1.9 DPG | 3.3 | 1.2 | 1.6 |
| 2 | 52.6 | 41.5 | 5.8 | 10.2 (N339) | 29.9 | 2.8 | 22.4 | 0.9 | 2.4 TBBS | 1.4 DPG | 2.3 | 2.0 | 1.9 |
| 3 | 10.4 | 88.9 | 0.7 | 4.6 (N330) | 74.9 | 7.4 | 28.8 | 1.7 | 1.7 CBS | 1.8 DPG | 4.0 | 1.2 | 1.9 |
| 4 | 47.1 | 20.0 | 32.9 | 23.0 (N330) | 53.3 | 6.2 | 15.6 | 2.1 | 2.0 CBS | 0.6 DPG | 4.1 | 2.1 | 1.8 |
| 5 | 58.0 | 25.2 | 16.8 | 38.5 (N339) | 4.7 | 0.6 | 12.5 | 2.0 | 2.1 CBS | 0.7 DPG | 2.4 | 1.3 | 1.8 |

Recipe 3 assumes SSBR 24 percent styrene, 51 percent vinyl; recipes 1, 4, 5 sit
near 20 to 35 percent styrene with 17 to 53 percent vinyl (full per-row values in
results/candidate_recipes.csv).

### Predicted properties and uncertainty

| # | Mooney (std) | M300 (std) | M100 | Hardness | Tensile | Elong. | tan d 60C | t90 |
|---|---|---|---|---|---|---|---|---|
| 1 | 61.2 (2.9) | 11.1 (1.0) | 3.0 | 67.6 | 18.3 | 400 | 0.13 | 15.4 |
| 2 | 59.7 (2.3) | 11.2 (0.9) | 3.2 | 62.1 | 19.1 | 456 | 0.12 | 18.0 |
| 3 | 58.1 (1.9) | 12.1 (0.8) | 2.6 | 66.9 | 20.0 | 457 | 0.12 | 21.9 |
| 4 | 60.3 (2.2) | 10.7 (1.0) | 2.7 | 65.3 | 17.5 | 472 | 0.09 | 16.3 |
| 5 | 59.4 (1.5) | 11.7 (0.9) | 3.1 | 63.1 | 17.9 | 473 | 0.12 | 15.1 |

### How far these predictions can be trusted

Three independent estimates, all from the same patent-grouped protocol:

1. Model accuracy on unseen patents: Mooney MAE 18.7 (R2 -0.18), M300 MAE 2.9
   (R2 0.29). On a truly new recipe the Mooney point predictions of 58 to 61
   carry an expected error around 19 Mooney units; the 55 to 65 target band is
   about one such error wide.
2. Ensemble disagreement (std across fold models): 1.5 to 2.9 Mooney, 0.8 to 1.0
   MPa on M300. This estimates recipe-to-model sensitivity; it is an optimist's
   error bar, roughly six times smaller than the grouped-CV error.
3. Support distance: the candidates sit 2.9 to 10.8 standardised units from the
   nearest training compound, where typical training compounds sit 0.7 units
   from their nearest neighbour. These are extrapolations into sparsely
   sampled recipe space.

Honest statement. The M300 predictions (10.7 to 12.1, requirement at least 10)
have grouped-CV MAE 2.9, so a two-sided interval around 11 reaches down to about
8. The Mooney predictions are weaker still: the model explains none of the
cross-patent variance. The five recipes are plausible tread formulations by
construction from patent-space ingredients, and their relative ranking may carry
information. Their absolute property values do not meet a design brief on their
own; every candidate needs laboratory verification before any use. Nearest
training neighbours are listed in results/candidate_predictions.csv (e.g.
candidate 1 maps to US7335692B2 T5, measured Mooney 116, M300 9.0), which
underscores the extrapolation risk.

## 5. What works, what does not, which hypotheses held

What ran. polyBERT via the HuggingFace copies: 600-d fingerprints of all
elastomer components and all 3,774 mixtures, used in the representation
comparison. TransPolymer: after reimplementing its tokenizer standalone
(transformers 5.x breaks the original class at import time), the published
checkpoint loaded with zero missing tensors and produced 768-d embeddings of the
same coverage. The full sklearn stack: 12 targets x 5 models x 5 folds x 2
splits; the representation study; the inverse-design pipeline with support
checks; permutation importance; leakage quantification.

What did not run, and why. PolymerGNN: code and data table present, required
monomer xyz geometries absent (the repo ships CREST .out logs with z-matrices
and no converter), and no pretrained weights; its polyester data are also out of
scope for filled rubber. The two Wan 2024 papers, Hu 2024, Roy Choudhury 2025,
and both soft-sensor papers: no public code or data (Roy Choudhury 2025 states
"data available on request"; the soft sensors use proprietary plant logs).

Hypotheses. "Published ML methods for polymers plus open data predict tyre
compound properties well enough for design": supported only for M300 and only at
MAE 2.8 to 2.9 MPa under the honest split; rejected for Mooney (R2 near zero
across every model and representation) and for nine further properties.
"polymer-language representations transfer to filled-rubber mixtures": partially
supported; a phr-weighted component-mean fingerprint matches the plain recipe
columns for M300 across patents and cannot recover Mooney. "The random-split
literature numbers (e.g. XGBoost R2 0.96 in Roy Choudhury 2025) indicate design
capability": rejected for this dataset; the random split measures interpolation
among near-duplicates, with 36 to 50 percent of test rows duplicated in train.

## 6. Where a follow-up study should start

1. Split by patent from the first script onward; report grouped-CV numbers as
   the primary metric. Random-split results on this dataset are decoration.
2. Collect measured Mooney of the neat elastomer batches alongside recipes, or
   predict it from supplier grade specifications first, then feed it to the
   compound model. This was the single dominant feature for Mooney.
3. Grow the dataset across producers and patents to attack the
   337-independent-formulations limit; the effective sample size is the number of
   patents, 337, and the within-patent copies add labels without adding
   information.
4. Verify the five candidates experimentally; each recipe is fully specified and
   reproducible from results/candidate_recipes.csv.
5. Reuse what is saved: the polyBERT and TransPolymer mixture fingerprints
   (artifacts/*_mix_fps.npy), the 66k-candidate pool with per-target
   predictions, uncertainty and support distance
   (artifacts/candidate_pool.parquet), the fixed cleaning bounds, and the
   standalone TransPolymer tokenizer (scripts/05). The tokenizer reimplementation
   is itself a small reusable contribution for anyone running TransPolymer on
   current transformers.

## 7. Files

scripts/01 to 08: exploration, feature build, baselines, polyBERT embeddings,
TransPolymer embeddings (with standalone tokenizer), representation comparison,
inverse design, diagnostics. All runnable with .venv (contents pinned in
artifacts/pip_freeze.txt; torch CPU 2.14, transformers 5.17, scikit-learn 1.8).
artifacts/: cleaned targets and features, both fingerprint sets, PSMILES
mapping report, candidate pool. results/: baseline and representation summaries
with per-fold rows, inverse-design CV, candidate recipes and predictions,
leakage quantification, permutation importances. third_party/: TransPolymer
(with 328 MB checkpoint) and PolymerGNN clones. logs/: full run logs of every
script.