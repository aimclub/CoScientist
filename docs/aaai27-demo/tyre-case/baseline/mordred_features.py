"""Step 2 of the mordred trial: does ingredient chemistry help on held-out patents?

Feature sets, same model and the same GroupKFold by patent as phr_baseline.py:
  phr            recipe amounts only
  phr+type       plus one-hot ingredient types (accelerators, antioxidant, silane)
  phr+mordred    plus mordred descriptors of those ingredients weighted by their phr
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
TARGETS = ["mooney_viscosity", "tensile_strength_MPa", "elongation_at_break_percent",
           "M300_MPa", "hardness_shore_A", "tan_delta_60C", "t90_min"]
ROLES = [("primary_accelerator_type", "primary_accelerator_phr"),
         ("secondary_accelerator_type", "secondary_accelerator_phr"),
         ("antioxidant_type", "antioxidant_phr"), ("silane_type", "silane_coupling_phr")]

raw = json.load(open(HERE / "mordred_raw.json"))
desc = raw["result"]["descriptors"]
table = pd.DataFrame(desc) if isinstance(desc, list) else pd.DataFrame(desc).T
table = table.apply(pd.to_numeric, errors="coerce")
table.index = raw["names"]
table = table.dropna(axis=1).loc[:, lambda t: t.std() > 0]
table = (table - table.mean()) / table.std()
print("ingredients", table.shape[0], "usable descriptors", table.shape[1])
comp = pd.DataFrame(PCA(n_components=6, random_state=0).fit_transform(table), index=table.index)

df = pd.read_csv(HERE.parent / "tires_2.csv")
phr = [c for c in df.columns if c.endswith("_phr")]
X_phr = df[phr].fillna(-1)
X_type = pd.get_dummies(df[[t for t, _ in ROLES]], dummy_na=False).astype(float)
parts = []
for tcol, pcol in ROLES:
    amount = df[pcol].fillna(0).to_numpy()[:, None]
    vec = comp.reindex(df[tcol]).fillna(0).to_numpy()  # unknown or "other" type -> zeros
    parts.append(pd.DataFrame(vec * np.where(amount > 0, amount, 1.0),
                              columns=[f"{tcol}_m{i}" for i in range(comp.shape[1])]))
X_mord = pd.concat(parts, axis=1)

out = {}
for t in TARGETS:
    d = df[t].notna().to_numpy()
    y, g = df.loc[d, t].to_numpy(float), df.loc[d, "patent_id"].to_numpy()
    res = {}
    for name, X in {"phr": X_phr, "phr+type": pd.concat([X_phr, X_type], axis=1),
                    "phr+mordred": pd.concat([X_phr, X_mord], axis=1)}.items():
        Xd, pred = X[d].to_numpy(float), np.zeros_like(y)
        for tr, te in GroupKFold(5).split(Xd, y, g):
            m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, random_state=0)
            pred[te] = m.fit(Xd[tr], y[tr]).predict(Xd[te])
        res[name] = round(r2_score(y, pred), 3)
    out[t] = res
    print(t, res)
json.dump(out, open(HERE / "mordred_features.json", "w"), indent=1)
