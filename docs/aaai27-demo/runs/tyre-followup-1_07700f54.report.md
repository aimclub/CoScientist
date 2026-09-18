# Report: Prediction of Tensile Strength and Elongation at Break for a Passenger-Tread Rubber Candidate

## Objective

The ResearchQuestion Q1 asks: using the Wan et al. 2024 rubber mechanical-property DNN models (bundled in the code repository `Vanguer/rubber-mechanical-properties-prediction`, https://github.com/Vanguer/rubber-mechanical-properties-prediction), predict the **tensile strength** and **elongation at break** for a passenger-tread tyre compound candidate with the following formulation:

- Rubber phase: SBR 70 phr / BR 30 phr (no NR, no IR)
- Carbon black: 50 phr (no specific grade given)
- Mixing time: 3.5 min
- Mastication time: 25 min
- Rolling time: 0.5 min

## Approach

The run was carried out by the ExperimentAgent using the Wan et al. 2024 Keras DNN models shipped with the repository — `strength.h5` (tensile strength) and `elongation.h5` (elongation at break) — invoked through the `predict_strength` and `predict_elongation` MCP tools on server `f894020ac42422fd`.

Key encoding decisions recorded in Evidence E1:

1. **Blend encoding:** The SBR/BR blend was encoded fractionally as SBR = 0.7, BR = 0.3, NR = 0, IR = 0. The tools accepted this fractional one-hot encoding directly, so no single-rubber one-hot fallback (which the tools would otherwise enforce) was needed.
2. **Filler encoding:** Fill-2 (carbon black amount) = 50 phr. Fill-1 (carbon-black grade index) = 2 — a mid-range grade used as a default, since the request specified no particular grade.
3. **Processing parameters:** mixing 3.5 min, mastication 25 min, rolling 0.5 min, passed through as given.

The graph contains no formal Hypothesis, Conclusion, or VerificationMethod nodes for this run — the single Evidence node E1 (status: obtained, computational subtype) directly answers the question, and the ResearchQuestion Q1 remains open only in the sense that a refinement with a specific carbon-black grade was noted as possible.

## Results

Evidence E1, produced by the ExperimentAgent via two recorded tool executions, yields:

| Property | Predicted value |
|---|---|
| Tensile strength (`predict_strength`, `strength.h5`) | **20.17 MPa** (20.17400297557817) |
| Elongation at break (`predict_elongation`, `elongation.h5`) | **417.8 %** (417.84585059594116) |

The full feature vector used was: SBR = 0.7, BR = 0.3, NR = 0, IR = 0, Fill-1 (grade index) = 2, Fill-2 (carbon black) = 50 phr, mixing 3.5 min, mastication 25 min, rolling 0.5 min.

A note on figures and tables: `format_results` collected **zero figures and zero data tables** from this run — the results exist only as numerical tool outputs recorded in the graph, so this report reproduces them in the table above rather than referencing any image or data files.

## Discussion

The predicted profile — roughly 20 MPa tensile strength with about 420 % elongation at break — is a reasonable, mid-range characteristic for a carbon-black-filled SBR/BR passenger-tread compound. The blend encoding finding is worth highlighting: the Wan et al. 2024 models' input schema was originally validated under a strict single-rubber one-hot encoding, but the prediction tools accepted the fractional blend encoding (0.7 / 0.3) without complaint. This means compound formulators can query blend compositions directly rather than being forced into single-rubber approximations — a genuinely useful property of the tooling, though it rests on the assumption that the models were trained on or generalize sensibly to such fractional inputs, which this run did not independently verify.

The main interpretive caveat is the carbon-black grade: the prediction assumes a mid-grade carbon black (grade index 2 as a default). Since the candidate specified only the loading (50 phr) and not the grade, the predicted values should be treated as a mid-range estimate. If an actual grade (e.g., N115 / N330 / N550-type indices) is specified, the prediction can be re-run for a more precise estimate.

There were no failures or refuted branches in this run — both tool calls returned cleanly (isError: False in the recorded provenance).

## Limitations and next steps

1. **Carbon-black grade is assumed, not specified.** Re-run the prediction with an explicit grade index matching the intended carbon black to sharpen the estimate; grade choice materially shifts both strength and elongation.
2. **Blend-encoding validity is unverified.** The acceptance of fractional one-hot blend inputs was observed but not validated against known experimental data for SBR/BR blends. A sanity check against published SBR/BR tread-compound property ranges (or lab measurements) would confirm the models interpolate sensibly across blends.
3. **Single-point prediction, no uncertainty.** The DNN models return point estimates; no confidence or error bar is available. Comparing against several benchmark formulations within the models' training domain would help gauge local reliability.
4. **Processing window.** The run fixed mixing 3.5 min, mastication 25 min, rolling 0.5 min; a small sensitivity sweep over these process parameters would reveal which levers most affect the predicted properties.