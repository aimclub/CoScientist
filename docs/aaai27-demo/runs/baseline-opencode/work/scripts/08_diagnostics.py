"""Diagnostics: (a) quantify near-duplicate leakage under the random split,
(b) permutation importance of the patent-grouped HGB models for Mooney and M300.
"""

import json
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.model_selection import KFold, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

SEED = 42
feat = pd.read_parquet("artifacts/features_plain.parquet")
tgt = pd.read_parquet("artifacts/targets.parquet")
with open("artifacts/cleaning_stats.json") as f:
    meta = json.load(f)
NUM = meta["numeric_cols"] + meta["derived_cols"]
CAT = meta["categorical_cols"]

# ---------- (a) leakage under random split ----------
rows = []
for target in ["mooney_viscosity", "M300_MPa"]:
    mask = tgt[target].notna().values
    X = feat[mask]
    patents = tgt.loc[mask, "patent_id"].values
    key = pd.util.hash_pandas_object(X, index=False)  # full-feature row hash
    for k, (tr, te) in enumerate(KFold(5, shuffle=True, random_state=SEED).split(X)):
        tr_keys = set(key.iloc[tr])
        dup_frac = key.iloc[te].isin(tr_keys).mean()
        same_patent = np.mean(
            [patents[te][i] in set(patents[tr]) for i in range(len(te))]
        )
        rows.append(
            {
                "target": target,
                "fold": k,
                "test_rows_with_exact_duplicate_in_train": dup_frac,
                "test_rows_with_same_patent_in_train": same_patent,
            }
        )
leak = pd.DataFrame(rows)
leak.to_csv("results/leakage_random_split.csv", index=False)
print("leakage under random split (mean over folds):")
print(leak.groupby("target").mean(numeric_only=True).round(3).to_string())


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


# ---------- (b) permutation importance, patent-grouped OOF ----------
imp_rows = []
for target in ["mooney_viscosity", "M300_MPa"]:
    mask = tgt[target].notna().values
    X = feat[mask].reset_index(drop=True)
    y = tgt.loc[mask, target].values
    groups = tgt.loc[mask, "patent_id"].values
    gkf = GroupKFold(5)
    accs = []
    for tr, te in gkf.split(X, groups=groups):
        m = make_hgb()
        m.fit(X.iloc[tr], y[tr])
        pi = permutation_importance(
            m, X.iloc[te], y[te], n_repeats=3, random_state=SEED, n_jobs=4
        )
        accs.append(pi.importances_mean)
    imp = np.mean(accs, axis=0)
    df = pd.DataFrame({"feature": X.columns, "importance": imp}).sort_values(
        "importance", ascending=False
    )
    df["target"] = target
    imp_rows.append(df.head(20))
    print(f"\ntop features for {target}:")
    print(df.head(15).round(4).to_string(index=False))
pd.concat(imp_rows).to_csv("results/permutation_importance.csv", index=False)
