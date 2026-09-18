"""Explore tires_2.csv: shape, targets, feature columns, near-duplicate structure."""

import pandas as pd
import numpy as np

pd.set_option("display.width", 200)

df = pd.read_csv("tires_2.csv")
print(f"shape: {df.shape}")
print(f"patents: {df.patent_id.nunique()}")
rows_per_patent = df.groupby("patent_id").size()
print(
    "rows per patent: min {}, median {}, max {}".format(
        rows_per_patent.min(), rows_per_patent.median(), rows_per_patent.max()
    )
)

targets = [
    "mooney_viscosity",
    "mooney_scorch_t5",
    "ts2_min",
    "Tc10_min",
    "t90_min",
    "Tc50_min",
    "hardness_shore_A",
    "M100_MPa",
    "M300_MPa",
    "tensile_strength_MPa",
    "elongation_at_break_percent",
    "tan_delta_0C",
    "tan_delta_60C",
    "abrasion_loss_mm3",
    "rebound_60C_percent",
]

print("\n=== targets ===")
for t in targets:
    s = df[t]
    n = s.notna().sum()
    if n:
        print(
            f"{t:32s} n={n:4d}  min={s.min():9.3g} median={s.median():9.3g} max={s.max():9.3g}"
        )
    else:
        print(f"{t:32s} EMPTY")

print("\n=== feature columns (non-target) ===")
feat_cols = [c for c in df.columns if c not in targets + ["patent_id", "compound_name"]]
for c in feat_cols:
    pass
print(df[feat_cols].dtypes.value_counts())

print("\nmissingness of feature cols (top 30):")
miss = df[feat_cols].isna().mean().sort_values(ascending=False)
print((miss.head(30) * 100).round(1).to_string())

print("\n=== categorical value counts (key type cols) ===")
for c in [
    "SBR_type",
    "cure_system_type",
    "oil_type",
    "silane_type",
    "sulfur_type",
    "primary_accelerator_type",
    "secondary_accelerator_type",
    "antioxidant_type",
    "CB_grade",
    "silica_grade",
    "NR_grade",
    "BR_grade",
    "mixer_type",
    "SBR_grade",
]:
    if c in df.columns:
        vc = df[c].value_counts(dropna=False).head(8)
        print(f"\n{c}: {df[c].nunique(dropna=True)} unique")
        print(vc.to_string())

print("\n=== elastomer phr presence ===")
elast = [
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
for c in elast:
    used = (df[c] > 0).sum()
    print(
        f"{c:10s} used in {used:4d} compounds, median phr when used: "
        f"{df.loc[df[c] > 0, c].median() if used else float('nan')}"
    )

print("\n=== near-duplicate structure ===")
num_feats = df[
    elast + ["carbon_black_phr", "silica_phr", "oil_phr", "sulfur_phr"]
].fillna(0)
D = num_feats.values
# same-recipe duplicates ignoring everything else
key = num_feats.apply(lambda r: tuple(r.round(2)), axis=1)
print(
    "exact duplicate recipe rows (elastomer+filler+oil+sulfur):",
    key.duplicated().sum(),
    "of",
    len(key),
)
same_patent_dup = 0
for pat, g in df.groupby("patent_id"):
    k = key.loc[g.index]
    same_patent_dup += k.duplicated().sum()
print("... of which within the same patent:", int(same_patent_dup))

# rows that are identical on ALL features (recipe + types + process)
allfeat = df[feat_cols].copy()
obj_cols = allfeat.select_dtypes(include="object").columns
allfeat[obj_cols] = allfeat[obj_cols].fillna("__NA__")
key2 = allfeat.apply(lambda r: tuple(r.astype(str)), axis=1)
print("rows identical on ALL feature columns:", key2.duplicated().sum())

# target similarity within patents vs across (Mooney)
if df.mooney_viscosity.notna().sum() > 50:
    sub = df[df.mooney_viscosity.notna()]
    within_var, across_var = [], []
    for pat, g in sub.groupby("patent_id"):
        if len(g) >= 2:
            within_var.append(g.mooney_viscosity.var())
    print("within-patent Mooney variance (median):", np.median(within_var))
    print("overall Mooney variance:", sub.mooney_viscosity.var())

df.to_parquet("artifacts/tires_2.parquet")
print("\nsaved artifacts/tires_2.parquet")
