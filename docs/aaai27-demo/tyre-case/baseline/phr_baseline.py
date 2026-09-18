"""Reference baseline for the tyre case: gradient boosting on recipe columns.

Random split vs split by patent, per target. Rows of one patent are near
copies, so the random split overstates the quality.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold, KFold

HERE = Path(__file__).resolve().parent
TARGETS = ["mooney_viscosity", "tensile_strength_MPa", "elongation_at_break_percent",
           "M300_MPa", "hardness_shore_A", "tan_delta_60C"]
LEAK = {"mooney_scorch_t5", "ts2_min", "Tc10_min", "t90_min", "Tc50_min", "M100_MPa",
        "tan_delta_0C", "abrasion_loss_mm3", "rebound_60C_percent", *TARGETS}

df = pd.read_csv(HERE.parent / "tires_2.csv")
num = [c for c in df.select_dtypes("number").columns if c not in LEAK]
phr = [c for c in num if c.endswith("_phr")]


def score(cols, target, splitter, groups):
    d = df[df[target].notna()]
    cols = [c for c in cols if d[c].notna().any()]  # an all-empty column breaks the binning
    X, y, g = d[cols].fillna(-1).to_numpy(float), d[target].to_numpy(float), d["patent_id"].to_numpy()
    pred = np.zeros_like(y, dtype=float)
    for tr, te in splitter.split(X, y, g if groups else None):
        m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, random_state=0)
        pred[te] = m.fit(X[tr], y[tr]).predict(X[te])
    return {"n": len(y), "patents": int(pd.Series(g).nunique()),
            "r2": round(r2_score(y, pred), 3), "mae": round(mean_absolute_error(y, pred), 3)}


out = {}
for t in TARGETS:
    out[t] = {
        "phr_random": score(phr, t, KFold(5, shuffle=True, random_state=0), False),
        "phr_by_patent": score(phr, t, GroupKFold(5), True),
        "all_numeric_random": score(num, t, KFold(5, shuffle=True, random_state=0), False),
        "all_numeric_by_patent": score(num, t, GroupKFold(5), True),
    }
json.dump(out, open(HERE / "phr_baseline.json", "w"), indent=1)
for t, r in out.items():
    print(t, r["phr_random"]["n"], r["phr_random"]["patents"],
          *(f'{k}={v["r2"]}' for k, v in r.items()))
