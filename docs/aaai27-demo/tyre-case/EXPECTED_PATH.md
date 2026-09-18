# Ожидаемый путь CoScientist по кейсу (B3)

Карта системы: `CoScientist/agents/system.yaml`, промпты в `CoScientist/agents/prompts/templates.py`.

| Шаг | Агент | Что делает в кейсе | Что остаётся |
|---|---|---|---|
| 0 | ContextInitAgent | Рамка исследования: цель, ограничения, данные | `research_frame.json` |
| 1 | OrchestratorAgent | Делит задачу: литература, гипотезы, исполнение. Перед делегированием зовёт `retrieve_tools` | узлы Q в графе |
| 2 | ResearchAgent | Tavily и OpenAlex (`papers_search`): работы по ML для резиновых смесей, какие из них имеют код | узлы Evidence, Publication |
| 3 | HypothesesAgent | Гипотезы: эмбеддинги полимеров улучшают перенос между патентами; честная проверка требует разбиения по патентам | узлы Hypothesis |
| 4 | TaskExecutorAgent → McpBuilderAgent | Для репозиториев с рабочим кодом: `list_mcp_builds` → `build_mcp_server`. polyBERT находится локально, PolymerGNN в хабе или локально, третий репозиторий (TransPolymer) конвертируется в ходе прогона | серверы, `validation.json`, образы |
| 5 | ToolPipelineAgent → ExperimentAgent | Вызывает инструменты серверов: эмбеддинги каучуков из `tires_2.csv`, результат в S3 | файлы в vault, узлы GeneratedData |
| 6 | CoderAgent (+ DatasetCollectorAgent) | Датасет из zip, признаки phr и phr + эмбеддинги, GroupKFold по `patent_id`, обратный поиск рецептур | код и метрики в `workspace/`, узлы CodeArtifact |
| 7 | Фоновый валидатор | Вердикты по гипотезам | статусы Hypothesis |
| 8 | ResultAggregatorAgent | Отчёт Markdown по графу | Report |
| 9 | Экспорт | `POST /api/users/{u}/sessions/{s}/export` | `.cossession.zip`: сессия, оба графа, траектория песочницы, сборки MCP |

## Где путь может оборваться
1. **Правило вызова Alembic слишком узкое.** Сейчас McpBuilderAgent включается, только если запрос явно просит MCP-сервер из репозитория (`templates.py:852-858`, `1700-1708`). В кейсе репозитории названы как источники методов, и роутер отдаст всё CoderAgent, который начнёт клонировать и ставить зависимости сам.
2. **Агенту запрещено собирать.** `ALEMBIC__AGENT_BUILD_ENABLED` по умолчанию False. Без него шаг «агент конвертирует в ходе прогона» невозможен.
3. **Передача файлов между ExperimentAgent и CoderAgent.** Эмбеддинги уходят в S3, кодер забирает их через vault (`get_download_link`). Нужен запущенный vault-сервер и `MCP__VAULT_URL`.
4. **Датасет.** Вложение принимает только http(s)-ссылку на `.zip`. `tires_2.csv` нужно упаковать и отдать по ссылке (MinIO, префикс `permanent/`).
5. **Локальные серверы не попадают в каталог инструментов**, пока не задан `A2A_HOST`. ExperimentAgent видит их через `deployed_mcps` той же сессии, этого для кейса хватает.

## Предлагаемая правка промптов (D2)
Расширить правило в `task_router` и `orchestrator`, остальной поток не трогать:

> The task needs to RUN a method that lives in a named code repository (its model, pipeline, or functions), and no ready tool covers it ⇒ McpBuilderAgent first: it reuses a local server, pulls one from the hub, or converts the repository. Then call the server's tools through ToolPipelineAgent. CoderAgent handles the analysis around the tool results. A repository that is only cited as background, or a plain library installable with pip and used in a few lines, does NOT trigger this rule.
