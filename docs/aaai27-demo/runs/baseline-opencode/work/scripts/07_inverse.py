"""Inverse step: propose passenger-tread candidate recipes with
Mooney viscosity 55-65 and M300 >= 10 MPa.

Design feature set = plain features minus elastomer_mooney_raw (a lab measurement
of the neat elastomer batch; unknown a priori for a new recipe).

Ensemble: for every target, 5 HistGradientBoosting models trained on the 5
patent-grouped CV folds (each fold model also predicts its held-out patents,
giving honest grouped-CV metrics for the same model class used for proposals).
Candidate prediction = mean across the 5 fold models; disagreement = std.

Candidates: random sampling within realistic passenger-tread bounds
(elastomer blends NR/SSBR/BR; CB N234/N339/N330; optional silica Zeosil 1165MP
with TESPT; TDAE oil; soluble/insoluble sulfur + CBS/TBBS + DPG; process fixed
to dataset medians). Support check via standardized nearest-neighbour distance
against the training rows.

Outputs:
  results/inverse_design_cv.csv      - grouped-CV metrics of the proposal models
  results/candidate_recipes.csv      - the 5 proposed recipes in phr
  results/candidate_predictions.csv  - all predicted properties + uncertainty
"""

import json
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler

SEED = 42
rng = np.random.default_rng(SEED)
N_CAND = 100_000
TARGETS = [
    "mooney_viscosity",
    "M300_MPa",
    "M100_MPa",
    "hardness_shore_A",
    "tensile_strength_MPa",
    "elongation_at_break_percent",
    "tan_delta_0C",
    "tan_delta_60C",
    "abrasion_loss_mm3",
    "t90_min",
    "mooney_scorch_t5",
    "rebound_60C_percent",
]

feat = pd.read_parquet("artifacts/features_plain.parquet")
tgt = pd.read_parquet("artifacts/targets.parquet")
with open("artifacts/cleaning_stats.json") as f:
    meta = json.load(f)
NUM = [
    c
    for c in meta["numeric_cols"] + meta["derived_cols"]
    if c != "elastomer_mooney_raw"
]
CAT = meta["categorical_cols"]


def make_hgb():
    return Pipeline(
        [
            (
                "pre",
                ColumnTransformer(
                    [
                        (
                            "num",
                            SimpleImputer(strategy="median", add_indicator=True),
                            NUM,
                        ),
                        (
                            "cat",
                            OneHotEncoder(
                                handle_unknown="infrequent_if_exist", min_frequency=8
                            ),
                            CAT,
                        ),
                    ]
                ),
            ),
            ("m", HistGradientBoostingRegressor(random_state=SEED, max_iter=400)),
        ]
    )


# ---------- train per-target patent-grouped ensembles ----------
ensembles = {}
cv_rows = []
group_kfold = GroupKFold(n_splits=5)
for target in TARGETS:
    mask = tgt[target].notna().values
    if mask.sum() < 250:
        continue
    X = feat[mask].reset_index(drop=True)
    y = tgt.loc[mask, target].values
    groups = tgt.loc[mask, "patent_id"].values
    models, oof = [], []
    for tr, te in group_kfold.split(X, groups=groups):
        m = make_hgb()
        m.fit(X.iloc[tr], y[tr])
        yp = m.predict(X.iloc[te]).ravel()
        cv_rows.append(
            {
                "target": target,
                "r2": r2_score(y[te], yp),
                "mae": mean_absolute_error(y[te], yp),
                "n_test": len(te),
            }
        )
        models.append(m)
    ensembles[target] = models
    print(f"trained ensemble for {target} (n={mask.sum()})", flush=True)

cv = pd.DataFrame(cv_rows)
cv_agg = (
    cv.groupby("target")
    .agg(r2_mean=("r2", "mean"), mae_mean=("mae", "mean"))
    .reset_index()
)
cv_agg.to_csv("results/inverse_design_cv.csv", index=False)
print("\ngrouped-CV metrics of proposal models:")
print(cv_agg.round(3).to_string(index=False))

# ---------- candidate space (passenger tread) ----------
n = N_CAND
NR = rng.uniform(0, 60, n)
BR = rng.uniform(0, 50, n)
SBR = np.clip(100.0 - NR - BR, 20, 100)
NR = 100.0 - SBR - BR
styrene = rng.uniform(15, 40, n)
vinyl = rng.uniform(0, 65, n)
cb = rng.uniform(0, 85, n)
silica = rng.uniform(0, 80, n)
bad = (cb + silica < 40) | (cb + silica > 110)
NR, BR, SBR = NR[~bad], BR[~bad], SBR[~bad]
styrene, vinyl, cb, silica = styrene[~bad], vinyl[~bad], cb[~bad], silica[~bad]
n = len(NR)
oil = rng.uniform(0, 30, n)
resin = rng.uniform(0, 8, n)
antiox = rng.uniform(0.8, 2.5, n)
wax = rng.uniform(0, 2.5, n)
sulfur = rng.uniform(0.8, 2.6, n)
prim_kind = rng.choice(["CBS", "TBBS"], n)
prim = rng.uniform(0.6, 2.4, n)
dpg = np.where(silica > 20, rng.uniform(0.5, 2.0, n), rng.uniform(0, 1.0, n))
zno = rng.uniform(2, 5, n)
stearic = rng.uniform(1, 3, n)
silane = np.where(silica > 0, silica * rng.uniform(0.08, 0.12, n), 0.0)
cb_grade = rng.choice(["N234", "N339", "N330"], n)

cand = pd.DataFrame(
    {
        "NR_phr": NR,
        "SBR_phr": SBR,
        "BR_phr": BR,
        "NBR_phr": 0.0,
        "EPDM_phr": 0.0,
        "IIR_phr": 0.0,
        "FKM_phr": 0.0,
        "ENR_phr": 0.0,
        "CR_phr": 0.0,
        "carbon_black_phr": cb,
        "silica_phr": silica,
        "silane_coupling_phr": silane,
        "oil_phr": oil,
        "resin_phr": resin,
        "antioxidant_phr": antiox,
        "wax_phr": wax,
        "sulfur_phr": sulfur,
        "primary_accelerator_phr": prim,
        "secondary_accelerator_phr": dpg,
        "zinc_oxide_phr": zno,
        "stearic_acid_phr": stearic,
        "accelerator_phr": prim + dpg,
    }
)
# grade numerics unknown -> NaN (imputed to training medians by the pipelines)
for c in [
    "SBR_styrene_content_pct",
    "SBR_vinyl_content_pct",
    "BR_cis_content_pct",
    "CB_N2SA_m2g",
    "CB_DBP_ml100g",
    "CB_CTAB_m2g",
    "silica_N2SA_m2g",
    "silica_CTAB_m2g",
    "elastomer_mooney_raw",
]:
    cand[c] = np.nan
cand["SBR_styrene_content_pct"] = styrene
cand["SBR_vinyl_content_pct"] = vinyl
for c, v in {
    "mixing_temp_C": 160.0,
    "vulcanization_temp_C": 150.0,
    "vulcanization_time_min": 25.0,
    "mixing_stages": 2.0,
    "nonproductive_drop_temp_C": 160.0,
    "productive_drop_temp_C": 105.0,
}.items():
    cand[c] = v
tot_el = cand[
    [
        "NR_phr",
        "SBR_phr",
        "BR_phr",
        "NBR_phr",
        "EPDM_phr",
        "IIR_phr",
        "FKM_phr",
        "ENR_phr",
        "CR_phr",
    ]
].sum(axis=1)
cand["total_elastomer_phr"] = tot_el
cand["total_filler_phr"] = cand["carbon_black_phr"] + cand["silica_phr"]
cand["filler_per_100_el"] = 100 * cand["total_filler_phr"] / tot_el
cand["cb_share_of_filler"] = cand["carbon_black_phr"] / cand[
    "total_filler_phr"
].replace(0, np.nan)
cand["oil_per_100_el"] = 100 * cand["oil_phr"] / tot_el
cand["sulfur_per_100_el"] = 100 * cand["sulfur_phr"] / tot_el
cand["accel_to_sulfur"] = cand["accelerator_phr"] / cand["sulfur_phr"]
cand["silane_per_100_silica"] = (
    100 * cand["silane_coupling_phr"] / cand["silica_phr"].replace(0, np.nan)
)
cand["sulfur_type_is_insoluble"] = 1.0
cand["is_oil_extended"] = 0.0

cand["SBR_type"] = "SSBR"
cand["cure_system_type"] = np.where(sulfur > 1.5, "CV", "SEV")
cand["oil_type"] = np.where(oil > 0.5, "TDAE", "__missing__")
cand["silane_type"] = np.where(silica > 0, "TESPT", "__missing__")
cand["sulfur_type"] = "insoluble"
cand["primary_accelerator_type"] = prim_kind
cand["secondary_accelerator_type"] = np.where(dpg > 0.05, "DPG", "__missing__")
cand["antioxidant_type"] = "6PPD"
cand["mixer_type"] = "internal"
cand["CB_grade"] = cb_grade
cand["silica_grade"] = np.where(silica > 0, "Zeosil 1165MP", "__missing__")
cand["NR_grade"] = np.where(NR >= 10, "SMR20", "__missing__")
cand["BR_grade"] = np.where(BR >= 10, "Nipol BR1220", "__missing__")
cand["SBR_grade"] = "__missing__"

missing_cols = [c for c in feat.columns if c not in cand.columns]
for c in missing_cols:
    cand[c] = feat[c].dtype.kind == "f" and np.nan or "__missing__"
cand = cand[list(feat.columns)]

# ---------- predict with ensembles ----------
pred_mean, pred_std = {}, {}
for target, models in ensembles.items():
    ps = np.stack([m.predict(cand).ravel() for m in models])
    pred_mean[target] = ps.mean(axis=0)
    pred_std[target] = ps.std(axis=0)
    print(f"predicted {target} for candidates", flush=True)

P = pd.DataFrame(pred_mean)
S = pd.DataFrame(pred_std)
print("\nprediction distributions over candidate pool:")
print(
    P[["mooney_viscosity", "M300_MPa", "M100_MPa", "hardness_shore_A"]]
    .describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
    .round(2)
    .to_string()
)

# ---------- support check: NN distance vs training rows ----------
num_design = [c for c in NUM if not c.startswith(("pb_", "tp_"))]
Ftr_raw = feat[num_design].copy()
Ftr_fill = Ftr_raw.fillna(Ftr_raw.median())
scaler = RobustScaler().fit(Ftr_fill)
Ftr = scaler.transform(Ftr_fill)
nn = NearestNeighbors(n_neighbors=1).fit(Ftr)
d_cand = nn.kneighbors(scaler.transform(cand[num_design].fillna(Ftr_raw.median())))[
    0
].ravel()
# training self-consistency: distance to the 2nd neighbour (1st is the row itself)
nn2 = NearestNeighbors(n_neighbors=2).fit(Ftr)
d_train = nn2.kneighbors(Ftr)[0][:, 1]
pct_thresh = np.percentile(d_train, 75)
in_support = (d_cand <= pct_thresh).astype(int)
print(
    "candidate NN-distance: median %.2f, training 75pct %.2f"
    % (np.median(d_cand), pct_thresh)
)


# ---------- selection (progressively relaxed if the strict box is empty) ----------
def box_filter(m_lo, m_hi, m300_min, use_support):
    f = (
        (P.mooney_viscosity >= m_lo)
        & (P.mooney_viscosity <= m_hi)
        & (P.M300_MPa >= m300_min)
    )
    if use_support:
        f &= in_support == 1
    return f


ok = box_filter(53, 67, 10.5, True)
for relax in [
    (53, 67, 10.5, False),
    (50, 70, 9.5, True),
    (50, 70, 9.5, False),
    (47, 72, 9.0, False),
]:
    if ok.sum() >= 50:
        break
    ok = box_filter(*relax)
if ok.sum() < 50:
    # fall back to ranked candidates nearest the target box
    dist_box = (
        np.maximum(0, 53 - P.mooney_viscosity)
        + np.maximum(0, P.mooney_viscosity - 67)
        + 5 * np.maximum(0, 10.0 - P.M300_MPa)
        + 0.02 * d_cand
    )
    ok = dist_box <= np.percentile(dist_box, 0.2)
idx = np.where(ok)[0]
print(f"candidates passing filters: {len(idx)} / {len(P)}")

# save the full pool for reuse by follow-up studies
pool = cand.copy()
for t in P.columns:
    pool[f"pred_{t}"] = P[t].values
    pool[f"std_{t}"] = S[t].values
pool["nn_dist"] = d_cand
pool["in_support"] = in_support
pool.to_parquet("artifacts/candidate_pool.parquet", index=False)

sel = cand.iloc[idx].copy()
selP = P.iloc[idx]
selS = S.iloc[idx]
sel_d = d_cand[idx]
if len(sel) >= 5:
    thr_m = np.nanmedian(selS.mooney_viscosity)
    thr_3 = np.nanmedian(selS.M300_MPa)
    stable = (selS.mooney_viscosity <= thr_m) & (selS.M300_MPa <= thr_3)
    if stable.sum() >= 50:
        keep = np.where(stable)[0]
        sel, selP, selS, sel_d = (
            sel.iloc[keep].copy(),
            selP.iloc[keep],
            selS.iloc[keep],
            sel_d[keep],
        )
        idx = idx[keep]
score = (
    np.abs(selP.mooney_viscosity - 60.0) * 0.5
    + np.abs(selP.M300_MPa - 13.0) * 0.3
    + selS.mooney_viscosity * 0.5
    + selS.M300_MPa * 1.0
    + sel_d * 0.02
)
sel = sel.assign(score=score.values)

if len(sel) >= 5:
    from sklearn.cluster import KMeans

    km_cols = [
        "NR_phr",
        "SBR_phr",
        "BR_phr",
        "carbon_black_phr",
        "silica_phr",
        "oil_phr",
        "sulfur_phr",
    ]
    Xkm = RobustScaler().fit_transform(sel[km_cols].fillna(0))
    km = KMeans(n_clusters=5, random_state=SEED, n_init=10).fit(Xkm)
    sel = sel.assign(cluster=km.labels_)
else:
    sel = sel.assign(cluster=np.zeros(len(sel), dtype=int))

picks = []
for cl in range(5):
    g = sel[sel.cluster == cl].sort_values("score")
    if len(g):
        picks.append(g.index[0])
if len(picks) < 5:  # top up from global best score
    for p in sel.sort_values("score").index:
        if p not in picks:
            picks.append(p)
        if len(picks) == 5:
            break
print("picked clusters sizes:", sel.cluster.value_counts().to_dict())

# nearest training compound for each pick
pick_rows = []
for p in picks:
    Fp = scaler.transform(cand.loc[[p], num_design].fillna(Ftr_raw.median()))
    j = int(nn.kneighbors(Fp)[1].ravel()[0])
    pick_rows.append(
        {
            "recipe_idx": int(p),
            "NN_patent": tgt.iloc[j]["patent_id"],
            "NN_compound": tgt.iloc[j]["compound_name"],
            "NN_dist": float(d_cand[p]),
            "NN_actual_mooney": tgt.iloc[j]["mooney_viscosity"],
            "NN_actual_M300": tgt.iloc[j]["M300_MPa"],
        }
    )
nn_info = pd.DataFrame(pick_rows)

sel.loc[picks].to_csv("results/candidate_recipes.csv", index=False)
out = sel.loc[picks].copy()
for t in TARGETS:
    if t in P.columns:
        out[f"pred_{t}"] = selP.loc[picks, t].values
        out[f"std_{t}"] = selS.loc[picks, t].values
out["nn_dist"] = d_cand[np.array(picks, dtype=int)]
out = pd.concat([out.reset_index(drop=True), nn_info.reset_index(drop=True)], axis=1)
out.to_csv("results/candidate_predictions.csv", index=False)

print("\n=== 5 candidate recipes ===")
show = [
    "NR_phr",
    "SBR_phr",
    "BR_phr",
    "carbon_black_phr",
    "CB_grade",
    "silica_phr",
    "silane_coupling_phr",
    "oil_phr",
    "sulfur_phr",
    "primary_accelerator_phr",
    "secondary_accelerator_phr",
    "pred_mooney_viscosity",
    "std_mooney_viscosity",
    "pred_M300_MPa",
    "std_M300_MPa",
    "nn_dist",
]
print(out[show].round(2).to_string(index=False))
