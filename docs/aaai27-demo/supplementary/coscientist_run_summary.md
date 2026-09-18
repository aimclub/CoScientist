# tyre-main-2_e7fa204e

- finished: True, wall time 104.7 min
- LLM: 175 calls, 5,619,668 tokens (3,856,320 cached), $3.44
- tool calls 174, sandbox commands 97, searches 0
- Alembic calls: {}
- MCP tool calls: {}
- graph: 40 nodes, 56 edges, {'ResearchQuestion': 1, 'Constraint': 6, 'Tool': 5, 'Resource': 1, 'EmpiricalBase': 2, 'ConfirmationCriteria': 4, 'CostModel': 1, 'Hypothesis': 6, 'VerificationMethod': 3, 'Evidence': 3, 'Conclusion': 3, 'CodeArtifact': 3, 'GeneratedData': 2}

| agent | starts | minutes |
|---|---|---|
| ResearchPipeline | 1 | 104.7 |
| OrchestratorAgent | 1 | 102.6 |
| TaskExecutorAgent | 3 | 97.7 |
| CoderAgent | 4 | 96.5 |
| HypothesesAgent | 2 | 2.3 |
| ResultAggregatorAgent | 1 | 1.6 |
| ContextInitAgent | 1 | 0.5 |

| hypothesis | status | text |
|---|---|---|
| H1 | confirmed | Гипотеза доступности: опубликованные методы из списка заказчика (polyBERT на HuggingFace, PolymerGNN, TransPolymer, Wan et al. (обе работы), Hu et al., Roy Choudhury et al. 2025, soft-sensor Mooney-мо |
| H2 | refuted | Гипотеза бенчмарка: публичные представления (эмбеддинги polyBERT/TransPolymer, графовые PolymerGNN, рецептурные representation-learning подходы Wan/Hu/Roy Choudhury) статистически значимо улучшают про |
| H3 | inconclusive | Гипотеза обратного дизайна: оптимизация поверх лучшего обученного суррогата (из бенчмарка H2) с честной оценкой неопределённости (анsembles / CV-std / conformal-интервалы) позволяет найти не менее 5 д |
| H4 | postponed | Простая физически-осмысленная композиционная модель (объёмная доля наполнителя по/hash-признакам, содержание масла и эластомеров, вулканизационные переменные, типовые взаимодействия) сопоставима с пуб |
| H5 | postponed | Fine-tuning предобученных полимерных языковых моделей (polyBERT/TransPolymer) на данных tires_2.csv даёт дополнительный прирост качества прогноза Mooney/M300 относительно замороженных эмбеддингов. |
| H6 | postponed | Генеративная модель рецептур (token-based LM/VAE в стиле полимерных языковых моделей, обучение на phr-рецептурах из tires_2.csv) способна напрямую семплировать новые рецептуры в целевой области свойст |
