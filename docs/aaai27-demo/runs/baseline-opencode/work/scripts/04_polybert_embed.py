"""Elastomer -> PSMILES mapping, polyBERT fingerprints, mixture embeddings.

Component PSMILES follow the polyBERT convention: repeat unit with [*] endpoints.
Copolymers are expanded into weighted sub-component blends:
  SBR: butadiene(1,4)/(1,2) + polystyrene, weighted by the row's styrene/vinyl columns
  ENR: NR + epoxidized isoprene (ENR-25 assumption)
  EPDM: PE/PP 55/45; NBR: BD/PAN 70/30; FKM: VDF/HFP 70/30
Row fingerprint = phr-weighted mean of elastomer fingerprints.

Outputs:
  artifacts/polybert_component_fps.npy  (n_components x 600)
  artifacts/polybert_mix_fps.npy        (3774 x 600)
  artifacts/psmiles_report.json
"""

import json
import numpy as np
import pandas as pd
import torch
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")

COMPONENT_PSMILES = {
    "NR": "[*]CC(C)=CC[*]",  # cis-1,4-polyisoprene
    "ENR": "[*]CC(C)1OC1C[*]",  # 2,3-epoxidized isoprene unit
    "BD14": "[*]CC=CC[*]",  # 1,4-polybutadiene
    "BD12": "[*]CC(C=C)[*]",  # 1,2-vinyl polybutadiene
    "PS": "[*]CC(c1ccccc1)[*]",  # polystyrene
    "PAN": "[*]CC(C#N)[*]",  # polyacrylonitrile
    "PE": "[*]CC[*]",
    "PP": "[*]CC(C)[*]",
    "PIB": "[*]CC(C)(C)[*]",  # polyisobutylene
    "PVDF": "[*]CC(F)(F)[*]",
    "HFP": "[*]C(F)(F)C(F)(C(F)(F)F)[*]",
    "CR": "[*]CC(Cl)=CC[*]",  # polychloroprene
}

# elastomer column -> default sub-component weights (before SBR composition override)
ELASTOMER_BLEND = {
    "NR_phr": {"NR": 1.0},
    "ENR_phr": {"NR": 0.75, "ENR": 0.25},
    "BR_phr": {"BD14": 1.0},
    "NBR_phr": {"BD14": 0.70, "PAN": 0.30},
    "EPDM_phr": {"PE": 0.55, "PP": 0.45},
    "IIR_phr": {"PIB": 1.0},
    "FKM_phr": {"PVDF": 0.70, "HFP": 0.30},
    "CR_phr": {"CR": 1.0},
}

report = {"valid": {}, "invalid": []}
for name, smi in COMPONENT_PSMILES.items():
    mol = Chem.MolFromSmiles(smi)
    (report["valid"] if mol is not None else report["invalid"])[name] = (
        smi if mol is not None else smi
    )
print("PSMILES validation:", {k: len(v) for k, v in report.items()})

# ---------------- load polyBERT ----------------
from sentence_transformers import SentenceTransformer

try:
    model = SentenceTransformer("xushijie/polyBERT", device="cpu")
    print("loaded xushijie/polyBERT via sentence-transformers")
except Exception as e:
    print("sentence-transformers load failed:", e)
    from transformers import AutoTokenizer, AutoModel

    tok = AutoTokenizer.from_pretrained("xushijie/polyBERT")
    amodel = AutoModel.from_pretrained("xushijie/polyBERT")

    class _M:
        def encode(self, s, batch_size=64, show_progress_bar=False):
            out = []
            for i in range(0, len(s), batch_size):
                batch = s[i : i + batch_size]
                enc = tok(batch, padding=True, truncation=True, return_tensors="pt")
                with torch.no_grad():
                    o = amodel(**enc)
                m = enc["attention_mask"].unsqueeze(-1).float()
                out.append((o[0] * m).sum(1) / m.sum(1).clamp(min=1e-9))
            return torch.cat(out).numpy()

    model = _M()
    print("loaded via transformers fallback")

names = list(COMPONENT_PSMILES)
comp_fps = model.encode(
    [COMPONENT_PSMILES[n] for n in names], batch_size=32, show_progress_bar=True
)
comp_fps = np.asarray(comp_fps, dtype=np.float32)
print("component fingerprints:", comp_fps.shape)
np.save("artifacts/polybert_component_fps.npy", comp_fps)

# ---------------- per-row mixture fingerprint ----------------
feat = pd.read_parquet("artifacts/features_plain.parquet")
FPS = dict(zip(names, comp_fps))


def elastomer_blend(col, row):
    if col == "SBR_phr":
        s = row.get("SBR_styrene_content_pct")
        s = 23.5 if not np.isfinite(s) else min(max(s, 0.0), 60.0) / 100.0
        v = row.get("SBR_vinyl_content_pct")
        v = 0.0 if not np.isfinite(v) else min(max(v, 0.0), 80.0) / 100.0
        return {"BD14": (1 - s) * (1 - v), "BD12": (1 - s) * v, "PS": s}
    return ELASTOMER_BLEND[col]


comp_cols = list(ELASTOMER_BLEND) + ["SBR_phr"]
fps = np.zeros((len(feat), comp_fps.shape[1]), dtype=np.float32)
used_rows = 0
for i, row in feat.iterrows():
    phr = {c: row[c] for c in comp_cols}
    total = sum(phr.values())
    if total <= 0:
        fps[i] = np.nan
        continue
    acc = np.zeros(comp_fps.shape[1], dtype=np.float64)
    for c, p in phr.items():
        if p <= 0:
            continue
        share = p / total
        for comp, w in elastomer_blend(c, row).items():
            acc += share * w * FPS[comp]
    fps[i] = acc.astype(np.float32)
    used_rows += 1

np.save("artifacts/polybert_mix_fps.npy", fps)
report["n_rows_embedded"] = used_rows
report["fp_dim"] = int(comp_fps.shape[1])
with open("artifacts/psmiles_report.json", "w") as f:
    json.dump(report, f, indent=2)
print("mixture fingerprints:", fps.shape, "rows with elastomers:", used_rows)
print("nan rows:", int(np.isnan(fps).any(axis=1).sum()))
