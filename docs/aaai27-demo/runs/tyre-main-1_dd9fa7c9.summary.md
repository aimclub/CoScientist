# tyre-main-1_dd9fa7c9

- finished: True, wall time 41.3 min
- LLM: 241 calls, 6,310,528 tokens (4,811,680 cached), $3.17
- tool calls 223, sandbox commands 104, searches 0
- Alembic calls: {}
- MCP tool calls: {'ExperimentAgent:embed_blend': 7, 'ExperimentAgent:embed_psmiles': 1}
- graph: 49 nodes, 73 edges, {'ResearchQuestion': 1, 'Constraint': 6, 'Tool': 4, 'Resource': 1, 'EmpiricalBase': 2, 'ConfirmationCriteria': 5, 'CostModel': 1, 'Hypothesis': 5, 'VerificationMethod': 3, 'GeneratedData': 3, 'Evidence': 9, 'Conclusion': 4, 'CodeArtifact': 5}

| agent | starts | minutes |
|---|---|---|
| ResearchPipeline | 1 | 41.3 |
| OrchestratorAgent | 1 | 40.4 |
| TaskExecutorAgent | 3 | 37.9 |
| CoderAgent | 4 | 30.0 |
| ToolPipelineAgent | 3 | 7.0 |
| ExecutorSwitchAgent | 3 | 5.3 |
| ExperimentAgent | 3 | 5.3 |
| ToolPreparerAgent | 3 | 1.7 |
| ParallelToolSearcherAgent | 3 | 1.6 |
| LocalToolsExtractorAgent | 3 | 1.4 |
| HypothesesAgent | 1 | 1.1 |
| ToolRetrieverAgent | 3 | 1.1 |
| ToolWebSearcherAgent | 3 | 0.9 |
| ResultAggregatorAgent | 1 | 0.7 |
| ToolReranker | 3 | 0.3 |
| ContextInitAgent | 1 | 0.3 |
| DatasetCollectorAgent | 1 | 0.2 |
| FullSetToolReranker | 3 | 0.1 |
| WebToolsDeployerAgent | 3 | 0.0 |

| hypothesis | status | text |
|---|---|---|
| H1 | inconclusive | A usable subset of the listed published polymer-ML methods (polyBERT, PolymerGNN, TransPolymer) has runnable public code/weights that can either directly predict properties or provide featurization (e |
| H2 | inconclusive | Forward models built on plain composition (phr) features with standard regressors (gradient boosting / random forest / ridge) achieve positive R2 and competitive accuracy for Mooney viscosity and M300 |
| H3 | inconclusive | Because rows within one patent are near-duplicates, random-split metrics substantially overestimate generalization to genuinely new recipes: on held-out-patent (group) splits, R2 drops by ≥0.1 (possib |
| H4 | inconclusive | Once a forward model with acceptable group-split accuracy exists, constrained inverse design (optimization/search over phr space within realistic formulation bounds) can propose 5 distinct candidate r |
| H5 | postponed | Adding process parameters and ingredient grade/type descriptors on top of plain phr materially improves forward accuracy (≥0.03 R2 or ≥10% MAE reduction) on patent-group splits for Mooney and M300. |
