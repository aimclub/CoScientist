# tyre-followup-1_07700f54

- finished: True, wall time 4.3 min
- LLM: 20 calls, 122,431 tokens (41,536 cached), $0.14
- tool calls 17, sandbox commands 0, searches 0
- Alembic calls: {}
- MCP tool calls: {'ExperimentAgent:predict_strength': 1, 'ExperimentAgent:predict_elongation': 1}
- graph: 2 nodes, 1 edges, {'ResearchQuestion': 1, 'Evidence': 1}

| agent | starts | minutes |
|---|---|---|
| ResearchPipeline | 1 | 4.3 |
| OrchestratorAgent | 1 | 4.2 |
| TaskExecutorAgent | 1 | 3.6 |
| ToolPipelineAgent | 1 | 3.2 |
| ToolPreparerAgent | 1 | 3.1 |
| ParallelToolSearcherAgent | 1 | 3.1 |
| ToolWebSearcherAgent | 1 | 3.1 |
| ExecutorSwitchAgent | 1 | 0.1 |
| ExperimentAgent | 1 | 0.1 |
| LocalToolsExtractorAgent | 1 | 0.1 |
| ResultAggregatorAgent | 1 | 0.1 |
| ToolRetrieverAgent | 1 | 0.1 |
| ContextInitAgent | 1 | 0.0 |
| ToolReranker | 1 | 0.0 |
| FullSetToolReranker | 1 | 0.0 |
| WebToolsDeployerAgent | 1 | 0.0 |

| hypothesis | status | text |
|---|---|---|
