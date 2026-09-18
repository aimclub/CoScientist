"""Baseline forward models on the plain recipe representation.

Two evaluation protocols per target:
  - random : 5-fold KFold, rows shuffled  (near-duplicates leak between folds)
  - patent : 5-fold GroupKFold on patent_id (whole patents held out together)

Models: Dummy(median), Ridge, PLS, RandomForest, HistGradientBoosting.
Saves results/baseline_results.csv (long format, one row per fold)
and results/baseline_summary.csv (mean +- std).
"""

import json
import time
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.cross_decomposition import PLSRegression
from sklearn.model_selection import KFold, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SEED = 42
TARGETS = [
    "mooney_viscosity",
    "M300_MPa",
    "M100_MPa",
    "tensile_strength_MPa",
    "elongation_at_break_percent",
    "hardness_shore_A",
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
NUM = meta["numeric_cols"] + meta["derived_cols"]
CAT = meta["categorical_cols"]


def make_model(kind):
    if kind == "dummy":
        return (
            "dummy",
            Pipeline(
                [
                    (
                        "pre",
                        ColumnTransformer(
                            [
                                ("num", SimpleImputer(strategy="median"), NUM),
                                (
                                    "cat",
                                    OneHotEncoder(
                                        handle_unknown="infrequent_if_exist",
                                        min_frequency=8,
                                    ),
                                    CAT,
                                ),
                            ]
                        ),
                    ),
                    ("m", DummyRegressor()),
                ]
            ),
        )
    if kind == "ridge":
        return (
            "ridge",
            Pipeline(
                [
                    (
                        "pre",
                        ColumnTransformer(
                            [
                                (
                                    "num",
                                    Pipeline(
                                        [
                                            (
                                                "imp",
                                                SimpleImputer(
                                                    strategy="median",
                                                    add_indicator=True,
                                                ),
                                            ),
                                            ("sc", StandardScaler()),
                                        ]
                                    ),
                                    NUM,
                                ),
                                (
                                    "cat",
                                    OneHotEncoder(
                                        handle_unknown="infrequent_if_exist",
                                        min_frequency=8,
                                    ),
                                    CAT,
                                ),
                            ]
                        ),
                    ),
                    ("m", Ridge(alpha=10.0)),
                ]
            ),
        )
    if kind == "pls":
        return (
            "pls",
            Pipeline(
                [
                    (
                        "pre",
                        ColumnTransformer(
                            [
                                (
                                    "num",
                                    Pipeline(
                                        [
                                            (
                                                "imp",
                                                SimpleImputer(
                                                    strategy="median",
                                                    add_indicator=True,
                                                ),
                                            ),
                                            ("sc", StandardScaler()),
                                        ]
                                    ),
                                    NUM,
                                ),
                                (
                                    "cat",
                                    OneHotEncoder(
                                        handle_unknown="infrequent_if_exist",
                                        min_frequency=8,
                                    ),
                                    CAT,
                                ),
                            ]
                        ),
                    ),
                    ("m", PLSRegression(n_components=20)),
                ]
            ),
        )
    if kind == "rf":
        return (
            "rf",
            Pipeline(
                [
                    (
                        "pre",
                        ColumnTransformer(
                            [
                                (
                                    "num",
                                    SimpleImputer(
                                        strategy="median", add_indicator=True
                                    ),
                                    NUM,
                                ),
                                (
                                    "cat",
                                    OneHotEncoder(
                                        handle_unknown="infrequent_if_exist",
                                        min_frequency=8,
                                    ),
                                    CAT,
                                ),
                            ]
                        ),
                    ),
                    (
                        "m",
                        RandomForestRegressor(
                            n_estimators=250, n_jobs=-1, random_state=SEED
                        ),
                    ),
                ]
            ),
        )
    if kind == "hgb":
        return (
            "hgb",
            Pipeline(
                [
                    (
                        "pre",
                        ColumnTransformer(
                            [
                                (
                                    "num",
                                    SimpleImputer(
                                        strategy="median", add_indicator=True
                                    ),
                                    NUM,
                                ),
                                (
                                    "cat",
                                    OneHotEncoder(
                                        handle_unknown="infrequent_if_exist",
                                        min_frequency=8,
                                    ),
                                    CAT,
                                ),
                            ]
                        ),
                    ),
                    (
                        "m",
                        HistGradientBoostingRegressor(random_state=SEED, max_iter=400),
                    ),
                ]
            ),
        )
    raise ValueError(kind)


rows = []
for target in TARGETS:
    mask = tgt[target].notna().values
    X = feat[mask].reset_index(drop=True)
    y = tgt.loc[mask, target].values
    groups = tgt.loc[mask, "patent_id"].values
    if mask.sum() < 200:
        print(f"skip {target}: n={mask.sum()}")
        continue
    folds = {
        "random": list(KFold(n_splits=5, shuffle=True, random_state=SEED).split(X)),
        "patent": list(GroupKFold(n_splits=5).split(X, groups=groups)),
    }
    for split_name, split in folds.items():
        for kind in ["dummy", "ridge", "pls", "rf", "hgb"]:
            name, model = make_model(kind)
            t0 = time.time()
            for k, (tr, te) in enumerate(split):
                model.fit(X.iloc[tr], y[tr])
                yp = model.predict(X.iloc[te]).ravel()
                rows.append(
                    {
                        "target": target,
                        "split": split_name,
                        "model": name,
                        "fold": k,
                        "n_train": len(tr),
                        "n_test": len(te),
                        "r2": r2_score(y[te], yp),
                        "mae": mean_absolute_error(y[te], yp),
                        "time_s": round(time.time() - t0, 2),
                    }
                )
            print(
                f"{target:28s} {split_name:7s} {name:6s} done "
                f"({time.time() - t0:.0f}s)",
                flush=True,
            )

res = pd.DataFrame(rows)
res.to_csv("results/baseline_results.csv", index=False)
summ = (
    res.groupby(["target", "split", "model"])
    .agg(
        r2_mean=("r2", "mean"),
        r2_std=("r2", "std"),
        mae_mean=("mae", "mean"),
        mae_std=("mae", "std"),
        n_mean=("n_test", "mean"),
    )
    .reset_index()
)
summ.to_csv("results/baseline_summary.csv", index=False)
print(
    summ.pivot_table(index=["target", "model"], columns="split", values="r2_mean")
    .round(3)
    .to_string()
)
