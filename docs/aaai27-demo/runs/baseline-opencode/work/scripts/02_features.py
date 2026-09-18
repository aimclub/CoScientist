"""Build cleaned targets and the 'plain recipe' feature matrix.

Outputs:
  artifacts/features_plain.parquet  - feature table (numeric + categorical cols)
  artifacts/targets.parquet        - cleaned target columns + patent_id + qc metadata
  artifacts/cleaning_stats.json    - how many target values were dropped per column
"""

import json
import numpy as np
import pandas as pd

SEED = 42

TARGET_BOUNDS = {
    # physically plausible ranges; values outside are treated as extraction errors -> NaN
    "mooney_viscosity": (10, 180),
    "mooney_scorch_t5": (0.5, 120),
    "ts2_min": (0.1, 60),
    "Tc10_min": (0.1, 120),
    "t90_min": (0.5, 120),
    "Tc50_min": (0.1, 60),
    "hardness_shore_A": (20, 95),
    "M100_MPa": (0.1, 20),
    "M300_MPa": (0.1, 35),
    "tensile_strength_MPa": (0.5, 60),
    "elongation_at_break_percent": (50, 1200),
    "tan_delta_0C": (0.01, 2),
    "tan_delta_60C": (0.005, 2),
    "abrasion_loss_mm3": (5, 2000),
    "rebound_60C_percent": (10, 100),
}

df = pd.read_csv("tires_2.csv")
n0 = len(df)

# ---------- target cleaning ----------
stats = {}
targets = pd.DataFrame(
    {"patent_id": df["patent_id"], "compound_name": df["compound_name"]}
)
for col, (lo, hi) in TARGET_BOUNDS.items():
    raw = df[col]
    bad = ~raw.notna() | (raw < lo) | (raw > hi)
    n_bad = int((raw.notna() & ((raw < lo) | (raw > hi))).sum())
    stats[col] = {
        "n_kept": int(raw.notna().sum()) - n_bad,
        "n_dropped_out_of_range": n_bad,
        "bounds": [lo, hi],
    }
    targets[col] = pd.to_numeric(
        raw.where(raw.notna() & raw.between(lo, hi)), errors="coerce"
    )

# ---------- features: numeric recipe ----------
ELAST = [
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
PHR = ELAST + [
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
    "accelerator_phr",
]
GRADE_NUM = [
    "SBR_styrene_content_pct",
    "SBR_vinyl_content_pct",
    "BR_cis_content_pct",
    "CB_N2SA_m2g",
    "CB_DBP_ml100g",
    "CB_CTAB_m2g",
    "silica_N2SA_m2g",
    "silica_CTAB_m2g",
    "elastomer_mooney_raw",
]
PROCESS = [
    "mixing_temp_C",
    "vulcanization_temp_C",
    "vulcanization_time_min",
    "mixing_stages",
    "nonproductive_drop_temp_C",
    "productive_drop_temp_C",
]

feat = pd.DataFrame(index=df.index)
for c in PHR + GRADE_NUM + PROCESS:
    feat[c] = pd.to_numeric(df[c], errors="coerce")

tot_el = feat[ELAST].sum(axis=1).replace(0, np.nan)
feat["total_elastomer_phr"] = feat[ELAST].sum(axis=1)
feat["total_filler_phr"] = feat["carbon_black_phr"] + feat["silica_phr"]
feat["filler_per_100_el"] = 100.0 * feat["total_filler_phr"] / tot_el
feat["cb_share_of_filler"] = feat["carbon_black_phr"] / feat[
    "total_filler_phr"
].replace(0, np.nan)
feat["oil_per_100_el"] = 100.0 * feat["oil_phr"] / tot_el
feat["sulfur_per_100_el"] = 100.0 * feat["sulfur_phr"] / tot_el
feat["accel_to_sulfur"] = feat["accelerator_phr"] / feat["sulfur_phr"].replace(
    0, np.nan
)
feat["silane_per_100_silica"] = (
    100.0 * feat["silane_coupling_phr"] / feat["silica_phr"].replace(0, np.nan)
)
feat["sulfur_type_is_insoluble"] = (df["sulfur_type"] == "insoluble").astype(float)
feat["is_oil_extended"] = df["is_oil_extended"].astype(float)

# ---------- features: categorical ----------
CAT = [
    "SBR_type",
    "cure_system_type",
    "oil_type",
    "silane_type",
    "sulfur_type",
    "primary_accelerator_type",
    "secondary_accelerator_type",
    "antioxidant_type",
    "mixer_type",
    "CB_grade",
    "silica_grade",
    "NR_grade",
    "BR_grade",
    "SBR_grade",
]
for c in CAT:
    feat[c] = df[c].astype("string").fillna("__missing__")

# NOTE: qc_* columns are extraction-quality metadata, not recipe info; excluded as features.
feat.to_parquet("artifacts/features_plain.parquet")
targets.to_parquet("artifacts/targets.parquet")

meta = {
    "n_rows": n0,
    "n_patents": int(df["patent_id"].nunique()),
    "n_feature_cols": int(feat.shape[1]),
    "numeric_cols": PHR + GRADE_NUM + PROCESS,
    "derived_cols": [
        "total_elastomer_phr",
        "total_filler_phr",
        "filler_per_100_el",
        "cb_share_of_filler",
        "oil_per_100_el",
        "sulfur_per_100_el",
        "accel_to_sulfur",
        "silane_per_100_silica",
        "sulfur_type_is_insoluble",
        "is_oil_extended",
    ],
    "categorical_cols": CAT,
    "target_cleaning": stats,
}
with open("artifacts/cleaning_stats.json", "w") as f:
    json.dump(meta, f, indent=2)

print("features:", feat.shape)
print("targets kept per column:")
for k, v in stats.items():
    print(f"  {k:28s} kept={v['n_kept']:5d} dropped={v['n_dropped_out_of_range']:3d}")
