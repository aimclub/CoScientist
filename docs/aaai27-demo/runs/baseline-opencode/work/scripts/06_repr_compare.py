"""Compare recipe representations under identical CV folds.

Representations:
  plain          - full plain feature set (recipe phr + grades + process + types)
  no_elast       - plain minus all elastomer-identity columns (ablation)
  polybert       - no_elast + 600-d polyBERT mixture fingerprints
  tp             - no_elast + 768-d TransPolymer mixture fingerprints
  plain+polybert - plain with polyBERT fingerprints appended
  chem-min       - polyBERT fingerprints + filler/oil/cure phr only (no grades/process)

Targets: mooney_viscosity, M300_MPa. Models: ridge, rf, hgb.
Splits: random KFold(5) and patent GroupKFold(5) - identical folds for all reps.
"""

import json
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import KFold, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SEED = 42
TARGETS = ["mooney_viscosity", "M300_MPa"]
MODELS = ["ridge", "rf", "hgb"]

feat = pd.read_parquet("artifacts/features_plain.parquet")
tgt = pd.read_parquet("artifacts/targets.parquet")
with open("artifacts/cleaning_stats.json") as f:
    meta = json.load(f)
NUM = meta["numeric_cols"] + meta["derived_cols"]
CAT = meta["categorical_cols"]

pb = np.load("artifacts/polybert_mix_fps.npy")
tp = np.load("artifacts/transpolymer_mix_fps.npy")

ELAST_ID = [
    "NR_phr",
    "SBR_phr",
    "BR_phr",
    "NBR_phr",
    "EPDM_phr",
    "IIR_phr",
    "FKM_phr",
    "ENR_phr",
    "CR_phr",
    "SBR_type",
    "SBR_grade",
    "NR_grade",
    "BR_grade",
    "SBR_styrene_content_pct",
    "SBR_vinyl_content_pct",
    "BR_cis_content_pct",
]
CHEM_MIN_NUM = [
    "carbon_black_phr",
    "silica_phr",
    "silane_coupling_phr",
    "oil_phr",
    "resin_phr",
    "antioxidant_phr",
    "wax_phr",
    "sulfur_phr",
    "primary_accelerator_phr",
    "secondary_accelerator_phr",
    "zinc_oxide_phr",
    "stearic_acid_phr",
]


def with_fp(base, fp, tag):
    X = base.copy()
    for j in range(fp.shape[1]):
        X[f"{tag}_{j}"] = fp[:, j]
    return X


def build(repr_name):
    if repr_name == "plain":
        return feat.copy(), NUM, CAT
    if repr_name == "no_elast":
        num = [
            c for c in NUM if c not in ELAST_ID and not c.startswith("total_elastomer")
        ]
        cat = [c for c in CAT if c not in ELAST_ID]
        return feat.drop(columns=[c for c in ELAST_ID if c in feat.columns]), num, cat
    if repr_name == "polybert":
        base, num, cat = build("no_elast")
        X = with_fp(base, pb, "pb")
        return X, num + [f"pb_{j}" for j in range(pb.shape[1])], cat
    if repr_name == "tp":
        base, num, cat = build("no_elast")
        X = with_fp(base, tp, "tp")
        return X, num + [f"tp_{j}" for j in range(tp.shape[1])], cat
    if repr_name == "plain+polybert":
        X = with_fp(feat, pb, "pb")
        return X, NUM + [f"pb_{j}" for j in range(pb.shape[1])], CAT
    if repr_name == "chem-min":
        keep_num = CHEM_MIN_NUM + ["total_filler_phr", "filler_per_100_el"]
        X = feat[keep_num].copy()
        X = with_fp(X, pb, "pb")
        return X, keep_num + [f"pb_{j}" for j in range(pb.shape[1])], []
    raise ValueError(repr_name)


def make_model(kind, num, cat):
    lin_num = Pipeline(
        [
            ("imp", SimpleImputer(strategy="median", add_indicator=True)),
            ("sc", StandardScaler()),
        ]
    )
    tree_num = SimpleImputer(strategy="median", add_indicator=True)
    onehot = OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=8)
    if kind == "ridge":
        return Pipeline(
            [
                (
                    "pre",
                    ColumnTransformer([("num", lin_num, num), ("cat", onehot, cat)]),
                ),
                ("m", Ridge(alpha=10.0)),
            ]
        )
    if kind == "rf":
        return Pipeline(
            [
                (
                    "pre",
                    ColumnTransformer([("num", tree_num, num), ("cat", onehot, cat)]),
                ),
                (
                    "m",
                    RandomForestRegressor(
                        n_estimators=250, n_jobs=-1, random_state=SEED
                    ),
                ),
            ]
        )
    if kind == "hgb":
        return Pipeline(
            [
                (
                    "pre",
                    ColumnTransformer([("num", tree_num, num), ("cat", onehot, cat)]),
                ),
                ("m", HistGradientBoostingRegressor(random_state=SEED, max_iter=400)),
            ]
        )
    raise ValueError(kind)


REPRS = ["plain", "no_elast", "polybert", "tp", "plain+polybert", "chem-min"]
rows = []
for target in TARGETS:
    mask = tgt[target].notna().values
    y = tgt.loc[mask, target].values
    groups = tgt.loc[mask, "patent_id"].values
    idx = np.where(mask)[0]
    folds = {
        "random": list(KFold(n_splits=5, shuffle=True, random_state=SEED).split(idx)),
        "patent": list(GroupKFold(n_splits=5).split(idx, groups=groups)),
    }
    for repr_name in REPRS:
        X, num, cat = build(repr_name)
        X = X.iloc[idx].reset_index(drop=True)
        for split_name, split in folds.items():
            for kind in MODELS:
                for k, (tr, te) in enumerate(split):
                    m = make_model(kind, num, cat)
                    m.fit(X.iloc[tr], y[tr])
                    yp = m.predict(X.iloc[te]).ravel()
                    rows.append(
                        {
                            "target": target,
                            "repr": repr_name,
                            "split": split_name,
                            "model": kind,
                            "fold": k,
                            "n_test": len(te),
                            "r2": r2_score(y[te], yp),
                            "mae": mean_absolute_error(y[te], yp),
                        }
                    )
        print(f"{target} {repr_name} done", flush=True)

res = pd.DataFrame(rows)
res.to_csv("results/representation_results.csv", index=False)
summ = (
    res.groupby(["target", "repr", "split", "model"])
    .agg(
        r2_mean=("r2", "mean"),
        r2_std=("r2", "std"),
        mae_mean=("mae", "mean"),
        mae_std=("mae", "std"),
    )
    .reset_index()
)
summ.to_csv("results/representation_summary.csv", index=False)
for target in TARGETS:
    print(f"\n== {target} ==")
    sub = (
        summ[summ.target == target]
        .pivot_table(index=["repr", "model"], columns="split", values="r2_mean")
        .round(3)
    )
    print(sub.to_string())
