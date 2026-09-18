# Учёт задач: AAAI-27 Demo

Дедлайн: 18 сентября 2026, 23:59 AoE (19 сентября, 14:59 МСК).

Статусы: `[ ]` не начато, `[~]` в работе, `[x]` готово, `[-]` отменено.

## A. Подготовка текста
- [x] A1. Требования call и AuthorKit27 зафиксированы: `research/aaai_demo_papers.md`
- [x] A2. Разобрано 13 принятых demo-статей AAAI-24/25/26: `research/aaai_demo_papers.md`
- [x] A3. Related work: `research/related_work.md` и `.bib` (49 записей). Не найдена статья Typed Research Graph, нужна bib-запись от Глеба
- [x] A4. План статьи уточнён по образцам принятых демо и реализован в `paper/main.tex`

## B. Кейс с резиной: пробное решение
- [x] B1. Постановка и метрика: `tyre-case/TASK_DEFINITION.md`; опорная модель на phr: R² 0.6–0.9 при случайном разбиении, ниже нуля по патентам (кроме M300, 0.31)
- [x] B2. Пробное решение: phr + эмбеддинги polyBERT через сервер Alembic. Прироста при разбиении по патентам нет, кроме удлинения (−0.26 → 0.10). Таблица в `tyre-case/TASK_DEFINITION.md`
- [x] B3. Ожидаемый путь и места обрыва: `tyre-case/EXPECTED_PATH.md`

## C. Alembic-серверы для кейса
- [x] C1. Доступ проверен: polyBERT закрыт (код по запросу, Academic Research Use License без права распространения, официальные веса на HF сняты; есть неофициальные зеркала `xushijie/polyBERT`). PolymerGNN открыт, лицензии нет
- [x] C2. polyBERT: `polyBERT-fac250`, 4/4 perfect, локально; вызов `embed_blend` совпал с ручным результатом Наргизы до 6 знака. Журнал: `tyre-case/ALEMBIC_BUILD_LOG.md`
- [x] C3. PolymerGNN: `PolymerGNN-3b749e`, 4/4 perfect (train_joint_cv, list_dataset_monomers, predict_polymer_properties, get_composition_embedding); вызов проверен
- [x] C4. PolymerGNN в хабе: `peanutbuttermilk/alembic-tool-polymergnn`. polyBERT только локально
- [x] C5. Что Alembic обошёл сам: таблица по пяти сборкам в `tyre-case/ALEMBIC_BUILD_LOG.md`

## D. CoScientist end-to-end (локально)
- [x] D1. Сервисы подняты, веб-сервер перезапущен с GLM-5.3, сборка агентом включена, FEDOT выключен. Лог: `logs/web_demo.log`. Замечание: `researchAgent.maxSearches=2`, `hypothesesAgent.maxActiveHypotheses=1`, для основного прогона стоит поднять
- [x] D2b. Правило «инструменты выдают данные, вычисления поверх них делает CoderAgent» в `experiment_react` и `task_router`
- [x] D2. Правило «нужно ЗАПУСТИТЬ метод из названного репозитория ⇒ McpBuilderAgent» добавлено в `task_router` и `orchestrator` (`agents/prompts/templates.py`); сборка и 64 теста проходят
- [x] D3. Три пробных прогона, разбор в `runs/NOTES.md`. Путь через каталог и сервер Alembic работает; найдена ошибка: ExperimentAgent получил неверный косинус (0.764 вместо 0.832), подогнав задачу под инструмент
- [x] D0. Датасет: `http://172.17.0.1:19000/agent-vault/permanent/datasets/tyre_compounds.zip` (анонимное чтение `permanent/` включено)
- [x] D4. Итоговый промпт: `tyre-case/PROMPT.md` (ждёт вычитки)
- [x] D5. `tyre-main-2` завершён: 105 мин, 3,44 $, отчёт на английском, 6 гипотез с вердиктами, экспорт `.cossession.zip`. Ход 2: агент запустил сборки Wan et al. и TransPolymer (идут). Разбор в `runs/NOTES.md`

## E. Бейзлайн
- [x] E1. Бейзлайн opencode завершён: 103 шага, ~60 мин, 6,28 $, отчёт `runs/baseline-opencode/work/REPORT.md`; разбор в `runs/NOTES.md`. По глубине анализа сильнее `tyre-main-1`
- [x] E2. Сравнение трёх траекторий (Наргиза, opencode, CoScientist): `TYRES_TRAJECTORIES.md`; таблица в статье (Table 1)

## F. Статья и видео
- [x] F1. Рисунок архитектуры: `paper/figures/architecture.tex` (TikZ, собирается в PDF), вставлен в статью
- [~] F2. Статья `paper/main.tex`: 2 страницы + ссылки, все числа прогонов вписаны (таблица CoScientist vs opencode, серверы Wan и TransPolymer, follow-up за 4 мин и 0,14 $). Осталось: авторы и e-mail, bib-запись Typed Research Graph, ссылка на видео
- [~] F3. Сценарий видео с числами прогонов: `video/SCRIPT.md`; запись экрана за вами
- [ ] F4. Озвучка через Qwen3-TTS, монтаж, до 5 минут
- [ ] F5. Подача в OpenReview (supplementary собран в `supplementary/`: промпты, оба отчёта, сводка прогона, постановка, датасет, инструкция по каталогу)

- [x] C7. mordred-community: `mordred-community-10e89b`, 5/5 perfect (descriptors_from_smiles, descriptors_by_name, list_descriptors, descriptors_from_file, mixture_descriptor), зарегистрирован в каталоге. Запись билда осталась в статусе running из-за перезапуска веб-сервера во время сборки; загружен в хаб: `peanutbuttermilk/alembic-tool-mordred-community` (запись билда восстановлена вручную). Проверка пользы: прироста R² по патентам нет (таблица в `tyre-case/TASK_DEFINITION.md`)
- [x] C6. Поиск дополнительных инструментов: `research/extra_tools.md` (10 репозиториев, около 30 отклонённых, таблица датасетов)

- [x] D6. Локальный каталог: Postgres, Qdrant, эмбеддер bge-m3 (5002); polyBERT и PolymerGNN зарегистрированы. Реранкер не стартует, см. G4

- [x] D7. Сборщик итогов прогона: `runs/collect_run.py` (время по агентам, вызовы MCP и Alembic, токены и стоимость, граф по типам узлов, гипотезы, экспорт сессии `--export`)

- [x] D8. Follow-up сессия `tyre-followup-1`: агент нашёл сервер Wan в каталоге, вызвал `predict_strength` и `predict_elongation`, ответ за 4,3 мин и 0,14 $ (прочность 20,2 МПа, удлинение 418 %)
- [x] C8. Серверы, собранные агентом в сессии: Wan et al. `rubber-mechanical-properties-prediction-1c872d` (4/4 perfect, загружен в хаб `alembic-tool-rubber-mechanical-properties-prediction`, лицензии у репозитория нет), TransPolymer `TransPolymer-acee03` (5/5 perfect, в хабе `alembic-tool-transpolymer`). В каталоге 19 серверов (polyBERT загружен вручную)

## G. На потом
- [ ] G1. paper-analysis MCP (7334): нужны Chroma, сервисы эмбеддингов и реранкера, vision-модель. Даёт разбор полных текстов статей в литобзоре
- [ ] G2. HITL в экспериментах
- [ ] G3. Compose для result-aggregator собирается с неверным контекстом (берёт корневой `pyproject.toml`, модуль `server` не находится)
- [ ] G4. Локальный reranker-service: модель `gte-multilingual-reranker-base` падает на текущей transformers
