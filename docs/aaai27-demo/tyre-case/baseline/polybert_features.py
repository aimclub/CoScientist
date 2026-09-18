"""Trial solution for the tyre case: recipe columns plus polyBERT blend fingerprints.

The fingerprint of a compound is the phr-weighted mean of the polyBERT vectors
of its elastomers, computed by the Alembic server (tool embed_psmiles). Same
model and the same split by patent as phr_baseline.py.
"""
import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
MCP_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:22012/mcp"
# Repeat units of the elastomer columns of tires_2.csv.
PSMILES = {
    "NR_phr": "[*]CC(C)=CC[*]",
    "BR_phr": "[*]CC=CC[*]",
    "SBR_phr": "[*]CC=CCCC([*])c1ccccc1",
    "NBR_phr": "[*]CC=CCCC([*])C#N",
    "EPDM_phr": "[*]CCCC([*])C",
    "IIR_phr": "[*]CC(C)(C)CC(C)=CC[*]",
    "FKM_phr": "[*]CC(F)(F)C(F)(F)C([*])(F)C(F)(F)F",
    "ENR_phr": "[*]CC1(C)OC1C[*]",
    "CR_phr": "[*]CC(Cl)=CC[*]",
}
TARGETS = ["mooney_viscosity", "tensile_strength_MPa", "elongation_at_break_percent",
           "M300_MPa", "hardness_shore_A", "tan_delta_60C"]


async def fingerprints():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(MCP_URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            out = {}
            for col, ps in PSMILES.items():  # one call each: a long result is cut to 20 numbers
                res = await s.call_tool("embed_psmiles", {"psmiles": [ps]})
                out[col] = json.loads(res.content[0].text)
            return out


RAW = HERE / "polybert_raw.json"
if not RAW.exists():  # step 1, needs the mcp package
    json.dump(asyncio.run(fingerprints()), open(RAW, "w"))
    print("fetched", RAW)
    sys.exit(0)

# step 2, needs scikit-learn
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.metrics import r2_score  # noqa: E402
from sklearn.model_selection import GroupKFold  # noqa: E402


def vector(res):
    """The first list of numbers inside a tool result, whatever the key is."""
    if isinstance(res, list) and res and isinstance(res[0], (int, float)):
        return res
    for v in (res.values() if isinstance(res, dict) else res if isinstance(res, list) else []):
        found = vector(v)
        if found:
            return found
    return None


raw = json.load(open(RAW))
vec = {c: np.array(vector(r), dtype=float) for c, r in raw.items()}
dim = {len(v) for v in vec.values()}
print("fingerprint length:", dim)

df = pd.read_csv(HERE.parent / "tires_2.csv")
phr = [c for c in df.columns if c.endswith("_phr")]
el = df[list(PSMILES)].fillna(0).to_numpy(float)
share = el / np.clip(el.sum(1, keepdims=True), 1e-9, None)
fp = share @ np.vstack([vec[c] for c in PSMILES])
fp = PCA(n_components=min(8, fp.shape[1]), random_state=0).fit_transform(fp)

out = {}
for t in TARGETS:
    d = df[t].notna().to_numpy()
    y, g = df.loc[d, t].to_numpy(float), df.loc[d, "patent_id"].to_numpy()
    res = {}
    for name, X in {"phr": df.loc[d, phr].fillna(-1).to_numpy(float),
                    "phr+polyBERT": np.hstack([df.loc[d, phr].fillna(-1).to_numpy(float), fp[d]]),
                    "polyBERT": fp[d]}.items():
        pred = np.zeros_like(y)
        for tr, te in GroupKFold(5).split(X, y, g):
            m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, random_state=0)
            pred[te] = m.fit(X[tr], y[tr]).predict(X[te])
        res[name] = round(r2_score(y, pred), 3)
    out[t] = res
    print(t, res)
json.dump(out, open(HERE / "polybert_features.json", "w"), indent=1)
