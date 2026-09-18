# Дополнительные репозитории для шинного кейса: кандидаты в MCP-серверы

Дата проверки: 2026-09-17. Метаданные (последний push, лицензия SPDX, звёзды, размер) взяты из GitHub API `repos/OWNER/NAME`. README прочитаны через `repos/OWNER/NAME/readme`. Версии и лицензии пакетов сверены с PyPI JSON API. Всё, что взято из памяти и не сверено с кодом или README, помечено словом «не проверено».

## Главные выводы

1. Открытого кода именно по резиновым смесям почти нет. Поиск по GitHub (`rubber compound`, `vulcanization`, `cure kinetics`, `Payne effect`, `Kraus model`, `Guth Gold`, `Kamal Sourour`, `moving die rheometer`, `tire tread`, `scorch time`) дал около десяти репозиториев по теме. У всех 0-4 звезды. Лицензия с рабочим кодом есть у одного (GPL-3.0, DSC-кинетика отверждения полиэфирной смолы). Остальные: ноутбук без лицензии, веса без кода обучения, пустые репозитории.
2. Формулы Гута-Голда, Крауса, Камала-Суру и Исаева-Денга занимают по 5-15 строк. Готового лицензированного пакета с ними не найдено. Практичный путь: свой маленький репозиторий `rubber-physics` под своей лицензией, затем конвертер. Это предложение, в шортлист оно не входит.
3. Открытых наборов данных «рецепт в phr + свойства вулканизата» сопоставимого размера не найдено (Zenodo API, HuggingFace API, веб-поиск). Набор из 3774 смесей сам по себе редкость.
4. polyBERT закрыт для Docker Hub. README `Ramprasad-Group/polyBERT` (push 2026-05-18) сообщает: Academic Research Use License, «Redistribution is not permitted», код выдаётся по запросу. Запрос к `huggingface.co/api/models/kuelumbus/polyBERT` вернул ошибку авторизации. Образ с polyBERT публиковать нельзя.
5. У TabPFN веса лицензируются отдельно от кода. Код Apache-2.0. Веса TabPFN-2.5, 2.6, 3, 3.5 идут под некоммерческими лицензиями, по умолчанию берётся 3.5, при первом запуске нужен вход через браузер или `TABPFN_TOKEN`. Веса TabPFN-2 идут под Prior Labs License (Apache 2.0 плюс требование атрибуции). Для образа годится только закреплённая версия V2.

## Шортлист (по убыванию пользы и простоты конвертации)

| # | Репозиторий | Лицензия | Последний push | Звёзды | Класс | GPU |
|---|---|---|---|---|---|---|
| 1 | JacksonBurns/mordred-community | BSD-3-Clause | 2026-09-14 | 115 | (a) дескрипторы | нет |
| 2 | emdgroup/baybe | Apache-2.0 | 2026-09-17 | 510 | (e) обратный дизайн | нет |
| 3 | scikit-learn-contrib/MAPIE | BSD-3-Clause | 2026-09-08 | 1590 | (f) неопределённость | нет |
| 4 | scikit-adaptation/skada | BSD-3-Clause | 2026-09-17 | 166 | (f) сдвиг домена | нет |
| 5 | anyoptimization/pymoo | Apache-2.0 | 2026-07-07 | 2960 | (e) NSGA-II | нет |
| 6 | experimental-design/bofire | BSD-3-Clause | 2026-09-17 | 414 | (e) смеси с ограничениями | нет |
| 7 | adtzlr/felupe | GPL-3.0 | 2026-09-08 | 184 | (d) гиперупругость | нет |
| 8 | MLCIL/scikit-fingerprints | MIT | 2026-09-17 | 393 | (a) отпечатки | нет |
| 9 | Henrium/MolSets | MIT | 2025-01-28 | 35 | (c) модель смеси | желателен |
| 10 | ChangwenXu98/TransPolymer | MIT | 2023-11-17 | 97 | (b) эмбеддинги полимеров | желателен |

---

### 1. mordred-community

- URL: https://github.com/JacksonBurns/mordred-community
- Лицензия BSD-3-Clause. Push 2026-09-14. PyPI `mordredcommunity` 2.0.7, Python >=3.9. Размер репозитория 2 МБ.
- Проверено по README: 1613 двумерных и 213 трёхмерных дескрипторов, API совпадает с исходным `mordred`, есть CLI `python -m mordred file.smi -o out.csv`. Исходный `mordred-descriptor/mordred` не обновлялся с 2024-02-07.
- Зависимость: RDKit (BSD-3-Clause, push 2026-09-15). GPU не нужен.

Инструменты:

| Имя | Вход (JSON) | Выход (JSON) |
|---|---|---|
| `compute_descriptors` | `{"smiles": ["..."], "ignore_3d": true, "subset": ["SLogP","TopoPSA"]}` | `{"columns": [...], "rows": [[...]], "failed": [idx]}` |
| `list_descriptors` | `{"ignore_3d": true}` | `{"names": [...], "count": 1613}` |
| `phr_weighted_descriptors` | `{"recipe": [{"smiles": "...", "phr": 1.5}], "basis": "phr" или "mol"}` | `{"features": {"name": value}}` |
| `validate_smiles` | `{"smiles": ["..."]}` | `{"valid": [true], "canonical": ["..."]}` |

Польза. Сейчас CBS, TBBS, DPG, 6PPD, TESPT входят в модель как отдельные столбцы phr. Новый патент часто приносит ингредиент, которого нет в обучении, и столбец для него пуст. Дескрипторы переводят названия в общее химическое пространство: содержание серы в ускорителе, число аминогрупп, logP масла. Взвешенная по phr или по молям сумма даёт признаки вида «моль сульфенамидных групп на 100 phr каучука». Такие признаки переносятся между патентами. Оговорка: эффект на отложенных патентах не измерен, это гипотеза для проверки.

Риски. Нужна таблица «название ингредиента → SMILES» (её придётся собрать отдельно). Масла и смолы являются смесями, для них SMILES условен. Часть дескрипторов возвращает NaN, нужен фильтр.

Hint:

> Expose mordred-community as a molecular descriptor server for small-molecule rubber additives (accelerators, antioxidants, silanes, plasticizers). Tools: compute_descriptors(smiles list, ignore_3d flag, optional descriptor subset) returning a JSON table with NaN replaced by null and a list of failed indices; list_descriptors returning descriptor names; validate_smiles returning RDKit canonical SMILES; phr_weighted_descriptors that takes a recipe as a list of {smiles, phr} and returns phr-weighted and mole-weighted sums of a chosen descriptor subset. Use `from mordred import Calculator, descriptors` with RDKit Mol objects. 2D descriptors only by default. No GPU, no model weights. Inputs and outputs must be plain JSON.

---

### 2. BayBE

- URL: https://github.com/emdgroup/baybe
- Лицензия Apache-2.0. Push 2026-09-17. PyPI `baybe` 0.15.0, Python 3.10-3.14. Базовые зависимости: `botorch`, `gpytorch`, `torch`, `scikit-learn`, `pandas`. Extra `chem` добавляет химические кодировки.
- Проверено по README: гибридные пространства поиска, ограничения (в том числе на число компонентов смеси), `SubstanceParameter` с химическими кодировками, цели Парето и desirability, перенос обучения между кампаниями, сериализация объектов, импорт готовых измерений, анализ важности признаков (extra `insights`).

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `create_campaign` | `{"parameters": [{"name": "silica_phr", "type": "continuous", "bounds": [0, 90]}, {"name": "accelerator", "type": "substance", "smiles": {"CBS": "..."}}], "constraints": [...], "targets": [{"name": "tan_delta_60", "mode": "MIN"}, {"name": "abrasion", "mode": "MIN"}], "objective": "pareto"}` | `{"campaign_json": "..."}` |
| `add_measurements` | `{"campaign_json": "...", "rows": [{...}]}` | `{"campaign_json": "...", "n_measurements": 120}` |
| `recommend` | `{"campaign_json": "...", "batch_size": 8}` | `{"candidates": [{...}], "campaign_json": "..."}` |
| `posterior_predict` | `{"campaign_json": "...", "candidates": [{...}]}` | `{"mean": [...], "std": [...]}` (не проверено: точное имя метода) |
| `feature_importance` | `{"campaign_json": "..."}` | `{"importance": {"param": value}}` |

Польза. Это шаг обратного дизайна: найти рецепт с низким tan δ при 60 °C, высоким tan δ при 0 °C и малым истиранием. Сериализация кампании в JSON хорошо ложится на MCP, состояние передаётся между вызовами без сервера с памятью. Перенос обучения (параметр задачи) позволяет объявить каждый патент или заявителя отдельной задачей. Так модель учится на общем тренде и допускает сдвиг между патентами. `SubstanceParameter` кодирует ускорители дескрипторами, то есть связывает этот сервер с п. 1.

Риски. Torch на CPU делает образ тяжёлым (оценка 1.5-2 ГБ, не проверено). Гауссов процесс на 3774 точках и 30+ признаках считается долго (не измерено), для демо нужна подвыборка. API до версии 1.0 меняется, версию надо закрепить.

Hint:

> Wrap BayBE (pip install "baybe[chem]") as a stateless formulation-optimization server. All state travels as the campaign JSON string produced by Campaign.to_json(). Tools: create_campaign(parameters, constraints, targets, objective) supporting NumericalContinuousParameter, NumericalDiscreteParameter, CategoricalParameter and SubstanceParameter (name to SMILES map) plus a Pareto or desirability objective; add_measurements(campaign_json, rows) returning the updated JSON; recommend(campaign_json, batch_size) returning candidate recipes as JSON rows plus the updated JSON; posterior_predict(campaign_json, candidates) returning mean and std per target; feature_importance(campaign_json). CPU-only torch. Cap training rows at 1000 and report when subsampling happens.

---

### 3. MAPIE

- URL: https://github.com/scikit-learn-contrib/MAPIE
- Лицензия BSD-3-Clause. Push 2026-09-08. PyPI `MAPIE` 1.5.0, Python >=3.10. Зависимости: scikit-learn, numpy.
- README не читался в этой проверке. Имена классов версии 1.x (`SplitConformalRegressor`, `CrossConformalRegressor`, `ConformalizedQuantileRegressor`) не проверены.

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `fit_conformal_regressor` | `{"X": [[...]], "y": [...], "groups": ["patent_id"], "method": "split" или "cross" или "cqr", "confidence": 0.9, "base_model": "hist_gbm"}` | `{"model_id": "...", "calibration_coverage": 0.91}` |
| `predict_interval` | `{"model_id": "...", "X": [[...]]}` | `{"y_pred": [...], "lower": [...], "upper": [...]}` |
| `coverage_by_group` | `{"model_id": "...", "X": [[...]], "y": [...], "groups": [...]}` | `{"coverage": {"group": value}, "mean_width": 12.3}` |
| `flag_out_of_domain` | `{"model_id": "...", "X": [[...]], "width_quantile": 0.9}` | `{"flags": [true, false]}` |

Польза. Модель с R² около нуля на новых патентах нельзя пускать в обратный дизайн без меры доверия. Конформные интервалы с калибровкой по группам (калибровочный набор состоит из целых патентов) показывают честную ширину прогноза для нового патента. `coverage_by_group` напрямую измеряет описанную проблему: покрытие на случайном разбиении против покрытия на отложенных патентах. Ширина интервала служит штрафом в оптимизаторе из п. 2 и п. 5.

Риски. Гарантия покрытия требует обмениваемости данных. Между патентами она нарушена, поэтому калибровать нужно по патентам. Серверу нужно хранить обученную модель: файл на диске по `model_id`.

Hint:

> Expose MAPIE 1.x as a conformal-prediction server for tabular regression. Tools: fit_conformal_regressor(X, y, groups, method in {split, cross, cqr}, confidence, base_model) that splits train and calibration sets by group id (GroupShuffleSplit or GroupKFold, never by row), stores the fitted object with joblib under a model_id and returns calibration coverage; predict_interval(model_id, X) returning point prediction, lower and upper bounds; coverage_by_group(model_id, X, y, groups) returning empirical coverage and mean interval width per group; flag_out_of_domain(model_id, X, width_quantile). Base models: HistGradientBoostingRegressor and RandomForestRegressor. JSON arrays in and out, CPU only.

---

### 4. skada

- URL: https://github.com/scikit-adaptation/skada
- Лицензия BSD-3-Clause. Push 2026-09-17. PyPI `skada` 0.6.0, Python >=3.9. Размер репозитория 2 МБ.
- README не читался. Состав методов (перевзвешивание KLIEP/KMM, CORAL, выравнивание подпространств, аргумент `sample_domain`) не проверен.
- Причина выбора skada перед ADAPT: `adapt-python/adapt` (BSD-2-Clause, push 2025-12-02) по PyPI и README жёстко требует `tensorflow`, `cvxopt`, `scikeras`, а README советует закрепить `tensorflow==2.15.0`. Образ получается тяжёлым и хрупким.

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `fit_da_regressor` | `{"X_source": [[...]], "y_source": [...], "X_target": [[...]], "method": "coral" или "kmm" или "kliep" или "subspace", "base_model": "ridge"}` | `{"model_id": "..."}` |
| `predict` | `{"model_id": "...", "X": [[...]]}` | `{"y_pred": [...]}` |
| `estimate_importance_weights` | `{"X_source": [[...]], "X_target": [[...]], "method": "kmm"}` | `{"weights": [...], "effective_sample_size": 412.0}` |
| `domain_shift_report` | `{"X_source": [[...]], "X_target": [[...]]}` | `{"domain_classifier_auc": 0.97, "top_shifted_features": [...]}` |

Польза. Отложенный патент является новым доменом с известными X и неизвестными y. Это постановка адаптации домена без меток. `domain_shift_report` отвечает на первый вопрос исследования: сдвиг сидит в рецептах (ковариатный) или в связи рецепта со свойством (разные методики испытаний у заявителей). Если классификатор доменов даёт AUC около 0.5, а ошибка всё равно большая, то причина в методиках измерения, и тогда помогает нормировка цели внутри патента. Оговорка: для сдвига в условиях испытаний методы без меток помогают слабо.

Риски. Часть методов skada рассчитана на классификацию, поддержку регрессии нужно проверить по каждому методу. `domain_shift_report` придётся дописать на scikit-learn, в skada такой функции может не быть.

Hint:

> Wrap skada (pip install skada) as an unsupervised domain adaptation server for tabular regression where each patent is a domain. Tools: fit_da_regressor(X_source, y_source, X_target, method in {coral, subspace, kmm, kliep}, base_model in {ridge, hist_gbm}) storing a fitted pipeline under model_id; predict(model_id, X); estimate_importance_weights(X_source, X_target, method) returning per-row source weights and effective sample size; domain_shift_report(X_source, X_target) that trains a scikit-learn domain classifier with cross-validation and returns AUC and the most shifted features. Verify regression support for each skada adapter and skip those that are classification-only. CPU only, JSON arrays.

---

### 5. pymoo

- URL: https://github.com/anyoptimization/pymoo
- Лицензия Apache-2.0. Push 2026-07-07. PyPI `pymoo` 0.6.2, Python >=3.10. Зависимости лёгкие (numpy, scipy), torch не нужен.
- README не читался. Наличие NSGA-II, NSGA-III и индикатора гиперобъёма не проверено по коду, взято из общего знания о пакете.

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `optimize_recipe` | `{"surrogate_ids": {"tan_delta_60": "m1", "abrasion": "m2"}, "directions": {"tan_delta_60": "min"}, "bounds": {"silica_phr": [0, 90]}, "linear_constraints": [...], "fixed": {"ZnO_phr": 3}, "pop_size": 100, "n_gen": 100}` | `{"pareto_X": [{...}], "pareto_F": [[...]]}` |
| `pareto_filter` | `{"F": [[...]], "directions": ["min", "max"]}` | `{"nondominated_idx": [...]}` |
| `hypervolume` | `{"F": [[...]], "ref_point": [...]}` | `{"hv": 0.73}` |
| `pick_compromise` | `{"F": [[...]], "weights": [0.5, 0.5]}` | `{"index": 17}` |

Польза. «Магический треугольник» шины (сопротивление качению, сцепление на мокром, износ) является классической многоцелевой задачей. NSGA-II работает поверх любой готовой модели, в том числе поверх бустинга, и не требует гауссова процесса. Ограничения задаются прямо: сумма каучуков 100 phr, отношение силан/силика, верхняя граница интервала из MAPIE как штраф.

Риски. Серверу нужен доступ к суррогатным моделям (общий каталог с joblib-файлами либо вызов другого MCP-сервера). Эволюционный поиск охотно уходит в области, где суррогат врёт, поэтому связка с п. 3 обязательна.

Hint:

> Expose pymoo as a multi-objective recipe optimizer over pre-trained surrogate models. Tools: optimize_recipe(surrogate paths as joblib files with a predict method, objective directions, variable bounds in phr, linear equality and inequality constraints such as total elastomer equals 100 phr, fixed ingredients, pop_size, n_gen, seed) running NSGA-II and returning Pareto-optimal recipes and objective values as JSON; pareto_filter(F, directions) using NonDominatedSorting; hypervolume(F, ref_point); pick_compromise(F, weights) using pymoo decomposition or pseudo-weights. Optional uncertainty penalty: when a surrogate returns (mean, std) add k*std to minimized objectives. CPU only, no torch.

---

### 6. BoFire

- URL: https://github.com/experimental-design/bofire
- Лицензия BSD-3-Clause. Push 2026-09-17. PyPI `bofire` 0.5.0, Python 3.11-3.14. Ядро без torch (`pydantic`, `pandas`, `formulaic`). Extra `optimization` тянет BoTorch. Extra `cheminfo` добавляет химические кодировки.
- Проверено по README: смешанные пространства, разделение выходов и целей (минимум, максимум, близость к целевому значению), ограничения, одно- и многоцелевая байесовская оптимизация, химические ядра, планы эксперимента с ограничениями, сериализация задач и стратегий для REST. Ограничение NChooseK (не больше k ненулевых компонентов) не проверено.

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `define_domain` | `{"inputs": [...], "outputs": [...], "constraints": [{"type": "LinearEquality", "features": ["NR","SBR","BR"], "coefficients": [1,1,1], "rhs": 100}]}` | `{"domain_json": "..."}` |
| `sample_feasible` | `{"domain_json": "...", "n": 50}` | `{"candidates": [{...}]}` |
| `generate_doe` | `{"domain_json": "...", "n": 20, "criterion": "d-optimal"}` | `{"candidates": [{...}]}` |
| `ask` | `{"domain_json": "...", "experiments": [{...}], "strategy": "mobo", "n": 8}` | `{"candidates": [{...}], "predictions": [{...}]}` |

Польза. Пересекается с BayBE, сильнее в двух местах: линейные ограничения смеси и планы эксперимента на ограниченной области. Цель «близко к значению» подходит для твёрдости и вязкости по Муни, где нужен коридор. Сериализация через pydantic упрощает JSON-схемы инструментов. В демо достаточно одного из двух серверов (п. 2 или п. 6), выбор по результату конвертации.

Риски. `pandas>=3.0.0` в зависимостях может конфликтовать с другими пакетами в одном окружении. Python >=3.11.

Hint:

> Wrap BoFire (pip install "bofire[optimization,cheminfo]") as a constrained-mixture design server. State is passed as pydantic JSON (domain.model_dump_json()). Tools: define_domain(inputs, outputs with objectives Minimize, Maximize or CloseToTarget, constraints LinearEquality, LinearInequality, NChooseK) returning domain_json; sample_feasible(domain_json, n); generate_doe(domain_json, n, criterion); ask(domain_json, experiments, strategy in {sobo, mobo, random}, n) that maps the strategy, calls tell with the experiments and returns candidates with predicted mean and std. CPU-only torch.

---

### 7. FElupe (подгонка гиперупругих моделей)

- URL: https://github.com/adtzlr/felupe
- Лицензия GPL-3.0-or-later. Push 2026-09-08. PyPI `felupe` 11.0.0, Python >=3.10. Зависимости: numpy, scipy.
- Проверено по коду `src/felupe/constitution/_base.py`: метод `ConstitutiveMaterial.optimize(ux=None, ps=None, bx=None, incompressible=False, relative=False, **kwargs)` подгоняет параметры методом наименьших квадратов по данным «удлинение-напряжение» для одноосного, плоского сдвига и двухосного нагружения. Возвращает копию материала и `scipy.optimize.OptimizeResult`. Соседний пакет `adtzlr/hyperelastic` (GPL-3.0, push 2026-02-13) по README содержит Нео-Гука, Муни-Ривлина, Йео как частные случаи модели третьего порядка.
- GPL-3.0 допускает публикацию образа на Docker Hub при условии доступности исходников. Сервер-обёртка тоже должен идти под GPL-совместимой лицензией.

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `fit_hyperelastic` | `{"model": "mooney_rivlin" или "yeoh" или "neo_hooke" или "ogden", "uniaxial": {"stretch": [1.0, 2.0, 4.0], "stress_mpa": [0, 2.1, 9.8]}, "incompressible": true, "relative": true}` | `{"params": {"C10": 0.41, "C01": 0.12}, "rmse": 0.2, "success": true}` |
| `fit_from_moduli` | `{"M100": 2.1, "M300": 9.8, "tensile": 21.0, "elongation_pct": 520, "model": "yeoh"}` | `{"params": {...}, "rmse": 0.3}` |
| `predict_stress` | `{"model": "yeoh", "params": {...}, "stretch": [1.5, 2.5], "mode": "uniaxial"}` | `{"stress_mpa": [...]}` |
| `compare_models` | `{"uniaxial": {...}}` | `{"ranking": [{"model": "yeoh", "rmse": 0.2, "aic": -11.2}]}` |

Польза. Цели M100, M300, прочность и удлинение при разрыве являются точками одной кривой растяжения. `fit_from_moduli` сворачивает три-четыре коррелированные цели в 2-3 физических параметра (C10 связан с плотностью сшивки и долей наполнителя). Прогноз физических параметров с последующим восстановлением модулей даёт согласованные ответы. Оговорка: подгонка трёх параметров Йео по трём точкам точна по построению, мерой качества она не служит. Эффект на отложенных патентах не измерен.

Риски. GPL-3.0. Модель Огдена по трём точкам неустойчива, по умолчанию стоит брать Муни-Ривлина или Йео.

Hint:

> Expose FElupe's constitutive-model fitting as a hyperelastic curve-fitting server for rubber tensile data (GPL-3.0, keep the wrapper GPL-compatible). Use felupe.NeoHooke, MooneyRivlin, Yeoh, Ogden wrapped in felupe.Hyperelastic or ConstitutiveMaterial and call .optimize(ux=[stretch, stress], incompressible=True, relative=...). Tools: fit_hyperelastic(model, uniaxial stretch and engineering stress arrays, optional planar and biaxial data) returning parameters, RMSE and success flag; fit_from_moduli(M100, M300, tensile strength, elongation at break) that builds points at stretch 2.0, 4.0 and 1+Eb/100; predict_stress(model, params, stretch, mode); compare_models(data) ranking models by RMSE and AIC. Only numpy and scipy, no GPU.

---

### 8. scikit-fingerprints

- URL: https://github.com/MLCIL/scikit-fingerprints (редирект с `scikit-fingerprints/scikit-fingerprints`)
- Лицензия MIT. Push 2026-09-17. PyPI `scikit-fingerprints` 2.1.0, Python 3.10-3.13.
- README не читался. Состав отпечатков (ECFP, MACCS, Avalon, Mordred и другие) и параллельный расчёт не проверены.

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `compute_fingerprint` | `{"smiles": [...], "kind": "ecfp" или "maccs" или "rdkit2d", "n_bits": 1024, "count": true}` | `{"matrix": [[...]], "shape": [n, 1024]}` |
| `ingredient_similarity` | `{"query_smiles": "...", "library": {"CBS": "..."}, "kind": "ecfp", "top_k": 5}` | `{"neighbors": [{"name": "TBBS", "tanimoto": 0.71}]}` |
| `cluster_ingredients` | `{"library": {...}, "n_clusters": 6}` | `{"clusters": {"CBS": 0}}` |
| `list_fingerprints` | `{}` | `{"kinds": [...]}` |

Польза. Дополняет п. 1. `ingredient_similarity` решает частую задачу с патентами: новый ускоритель или антиоксидант сопоставляется с ближайшим известным, и его phr добавляется в столбец функционального класса. Кластеры ингредиентов дают признаки «phr сульфенамидов», «phr гуанидинов», «phr п-фенилендиаминов». Такие столбцы заполнены в каждом патенте.

Риски. Малые. Если конвертер осилит только один сервер класса (a), брать п. 1.

Hint:

> Expose scikit-fingerprints as a fingerprint and similarity server for rubber additives. Tools: compute_fingerprint(smiles list, kind, n_bits, count) returning a dense JSON matrix (cap at 2048 columns); ingredient_similarity(query_smiles, library as name to SMILES map, kind, top_k) returning Tanimoto neighbors; cluster_ingredients(library, n_clusters) using Butina or agglomerative clustering on Tanimoto distance; list_fingerprints. Use the scikit-learn transformer API (fit_transform on SMILES lists). CPU only.

---

### 9. MolSets

- URL: https://github.com/Henrium/MolSets
- Лицензия MIT. Push 2025-01-28. Размер 573 КБ. Статья: PRX Energy 3, 023006 (2024).
- Проверено по README и дереву файлов: `models.py`, `dmpnn.py`, `main.py`, `predict.py`, `data_utils.py`. Есть контрольная точка `results/GraphConv_3_h16_e32_att16_tanh.pt` (44 КБ), обучена на проводимости литиевых электролитов. Файлы `.pkl` лежат в Git LFS, запасная ссылка ведёт на Google Drive. Зависимости: PyTorch >=2.0, PyG, torch-scatter для DMPNN. README предупреждает о конфликтах версий в `environment.yml`.
- API в виде пакета нет. Гиперпараметры и пути задаются правкой скриптов.

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `prepare_mixture_dataset` | `{"rows": [{"components": [{"smiles": "...", "weight_fraction": 0.3, "mol_weight": 264.4}], "target": 1.2}]}` | `{"dataset_id": "..."}` |
| `train_molsets` | `{"dataset_id": "...", "groups": [...], "hidden": 16, "epochs": 200}` | `{"model_id": "...", "val_mae": 0.31}` |
| `predict_mixture` | `{"model_id": "...", "mixtures": [...]}` | `{"y_pred": [...]}` |
| `embed_mixture` | `{"model_id": "...", "mixtures": [...]}` | `{"embeddings": [[...]]}` |

Польза. Модель инвариантна к порядку компонентов и принимает смесь с любым набором молекул. Это архитектурный ответ на проблему новых ингредиентов в отложенных патентах. Применима к молекулярной части рецепта: вулканизующая группа, антиоксиданты, силан. Оговорка: готовые веса обучены на электролитах и для резины бесполезны, нужен свой цикл обучения. Техуглерод и силика графом не описываются и подаются отдельным вектором, для этого надо менять `models.py`.

Риски. Сборка PyG и torch-scatter, скрипты с зашитыми путями, конвертеру придётся делать рефакторинг. Вероятность чистой конвертации средняя. Запасной вариант: `chemprop/chemprop` (MIT по файлу LICENSE, push 2026-09-01, PyPI 2.3.1, Python >=3.11), поддержка многокомпонентного входа в v2 не проверена.

Hint:

> Wrap MolSets (molecular graph deep sets for mixture properties) as a train-and-predict server. The repo has no package API: refactor main.py and predict.py into functions and remove hard-coded paths. Tools: prepare_mixture_dataset(rows with components {smiles, weight_fraction, mol_weight} and a target) converting SMILES to torch_geometric graphs with data_utils; train_molsets(dataset_id, groups for a grouped validation split, hyperparameters) saving a checkpoint under model_id; predict_mixture(model_id, mixtures); embed_mixture(model_id, mixtures) returning the set-level embedding before the output head. Use the GraphConv variant from models.py to avoid torch-scatter. CPU works for a few thousand mixtures. The bundled checkpoint is for electrolyte conductivity and must not be used for rubber.

---

### 10. TransPolymer

- URL: https://github.com/ChangwenXu98/TransPolymer
- Лицензия MIT. Push 2023-11-17. Статья: npj Comput. Mater. 9, 64 (2023).
- Проверено по README и дереву: предобучение на ~5 млн последовательностей из PI1M, веса лежат в `ckpt/pretrain.pt/` (`pytorch_model.bin` размером 134 байта в дереве, то есть указатель Git LFS). Скрипты `Pretrain.py`, `Downstream.py`, собственный токенизатор `PolymerSmilesTokenization.py`. Окружение старое: Python 3.9, torch 1.12, transformers 4.20.1.

Инструменты:

| Имя | Вход | Выход |
|---|---|---|
| `embed_polymer` | `{"psmiles": ["*CC=C(C)C*"], "pooling": "cls" или "mean"}` | `{"embeddings": [[...]], "dim": 768}` (размерность не проверена) |
| `embed_blend` | `{"components": [{"psmiles": "...", "phr": 70}, {"psmiles": "...", "phr": 30}]}` | `{"embedding": [...]}` |
| `polymer_similarity` | `{"a": "...", "b": "..."}` | `{"cosine": 0.93}` |
| `tokenize` | `{"psmiles": "..."}` | `{"tokens": [...]}` |

Польза. Единственная найденная языковая модель полимеров с весами под MIT, то есть законная замена polyBERT в публичном образе. Оговорка: эмбеддинги polyBERT уже не помогли, а в наборе примерно 10 разных каучуков. Ждать прироста на отложенных патентах от другого энкодера оснований мало. Ценность в демо: воспроизводимая проверка отрицательного результата на лицензионно чистой модели.

Риски. Клонирование требует `git lfs`. Старые версии transformers могут не встать на Python 3.11+, нужно пробовать загрузку весов новой версией `RobertaModel`. Сополимеры (SBR, NBR) одной PSMILES описываются плохо, состав стирол/бутадиен теряется.

Hint:

> Expose the pretrained TransPolymer RoBERTa encoder as a polymer embedding server. Clone with git lfs so that ckpt/pretrain.pt/pytorch_model.bin is the real weight file. Load with transformers RobertaModel.from_pretrained("ckpt/pretrain.pt") and the repo's PolymerSmilesTokenizer. Tools: embed_polymer(psmiles list, pooling in {cls, mean}) returning float vectors; embed_blend(components with psmiles and phr) returning the phr-weighted mean embedding; polymer_similarity(a, b) returning cosine similarity; tokenize(psmiles). Inference only, CPU is sufficient. Try current transformers first and fall back to transformers==4.20.1 with torch 1.12 if loading fails.

---

## Отклонённые кандидаты

| Репозиторий | Факты (GitHub API, 2026-09-17) | Причина |
|---|---|---|
| Ramprasad-Group/polyBERT | push 2026-05-18, лицензия NOASSERTION | README: только академическое использование, распространение запрещено, код по запросу |
| Ramprasad-Group/polygnn, Ramprasad-Group/polygnn_kit, rishigurnani/polygnn | 404 | Не существуют под этими именами. `rishigurnani/polygnn_trainer` (push 2024-02-15) и `rishigurnani/polygnn_kit` без лицензии. Другие `polygnn` на GitHub относятся к реконструкции зданий |
| Ramprasad-Group/canonicalize_psmiles | push 2024-09-03, NOASSERTION | Лицензия не определена. Замена: `kuennethgroup/psmiles` (MIT, push 2026-04-13), но его отпечатки polyBERT зависят от закрытой модели |
| HKQiu/PolyNC | 404 на GitHub | На HuggingFace `hkqiu/PolyNC` есть, Apache-2.0, изменён 2024-01-11. Это T5-модель «текст в свойство» для гомополимеров, к рецептам не подходит. Код на GitHub не найден |
| coleygroup/polymer-chemprop (wD-MPNN) | MIT, push 2022-10-12, 369 МБ | Код рабочий (`chemprop_train --polymer`), готовых весов нет. Вход требует стехиометрию и веса связей мономеров. При ~10 каучуках в наборе обучать не на чем. Резерв |
| learningmatter-mit/Chem-prop-pred | MIT, push 2024-07-29 | Подмодуль ссылается на `github.mit.edu` (внутренний сервер MIT), снаружи не соберётся. Задача: проводимость полимерных электролитов |
| chemcognition-lab/chemixhub | MIT, push 2026-02-27, 41 звезда | Бенчмарк и наборы данных по жидким смесям. Полезен как образец разбиения «невиданные компоненты». Как сервер инструментов даёт мало |
| GLAD-RUC/GeoMix | MIT, push 2026-01-12 | Закреплён `torch==2.1.0+cu118`, e3nn, torch_sparse. Нужен GPU, данные не включены, задача: электролиты |
| DiffMix (BattModels/DiffMix) | 404 | Репозиторий под этим именем не найден. Не проверено, где лежит код |
| NU-CUCIS/CheMixNet | push 2019-11-21, лицензия «other» | Это модель для одной молекулы с несколькими представлениями. К смесям не относится. Старый Keras |
| IBM/polymer_property_prediction | BSD-3-Clause, push 2022-05-06, в архиве | Архивирован |
| lamalab-org/PolyMetriX | MIT, push 2026-07-15, PyPI 0.2.0 | Рабочий `pip install polymetrix`, признаки «основная цепь / боковые группы» по PSMILES, набор данных по Tg. Для ~10 каучуков даёт ~10 уникальных строк признаков. Резерв для п. 10 |
| RadonPy/RadonPy | BSD-3-Clause, push 2026-08-07, 281 звезда | Полная автоматизация МД (LAMMPS, Psi4). Часы счёта на полимер, для MCP-инструмента слишком тяжело |
| PriorLabs/TabPFN | код Apache-2.0, push 2026-09-17, 7974 звезды | Веса по умолчанию (3.5) некоммерческие и требуют вход или `TABPFN_TOKEN`. Веса V2 идут под Prior Labs License с атрибуцией (HF: `license:other`). В образ можно класть только V2 через `TabPFNRegressor.create_default_for_version(ModelVersion.V2)`. Условно годен, лицензию весов нужно прочитать до публикации |
| adapt-python/adapt | BSD-2-Clause, push 2025-12-02 | Жёсткая зависимость от tensorflow, README советует `tensorflow==2.15.0`. Заменён на skada |
| mirandi1/pyRheo | GPL-3.0, push 2026-02-03, на PyPI нет | Подгонка дробных вязкоупругих моделей к ползучести, релаксации, SAOS. В наборе нет частотных развёрток, только tan δ в двух точках. Кривые вулканизации пакет не описывает |
| jorge-ramirez-upm/RepTate | GPL-3.0, push 2026-09-10 | GUI-приложение для реологии расплавов. API для MCP неудобен |
| adtzlr/hyperelastic, adtzlr/matadi | GPL-3.0 | Библиотеки моделей для FElupe. Подгонка живёт в FElupe (п. 7) |
| Chongran-Zhao/Hyperelastic-fitting | MIT, push 2026-06-07 | MATLAB и Optimization Toolbox |
| LucMarechal/Soft-Robotics-Materials-Database | ODbL-1.0, push 2024-08-19, 112 звёзд | Кривые растяжения силиконов и один скрипт подгонки. Полезен как тестовые данные для п. 7 |
| mjbog/curekinetics | GPL-3.0, push 2019-08-06, 0 звёзд, README нет | Класс `CureKinetics` (Аррениус, автокатализ, изотерма и линейный нагрев) и чтение DSC. Данные по полиэфирной смоле. Заброшен, но это единственный найденный лицензированный код кинетики отверждения. Резерв |
| wedyer9/Curekinetics | MIT, размер 1 КБ | Почти пустой |
| EmilKristjansson/heat-cure-solver | без лицензии, push 2026-04-22 | Один учебный ноутбук: теплопроводность плюс кинетика вулканизации в пресс-форме |
| Vanguer/rubber-mechanical-properties-prediction | без лицензии, push 2024-05-05, 4 звезды | Три файла `.h5` (прочность, удлинение, усталость резин с техуглеродом) и Excel с фронтом Парето. Нет кода обучения, нет данных, нет описания входных признаков |
| andyk99/FEA-Driven-Bayesian-Optimization-of-Nanoparticle-Reinforced-Tire-Compounds | без лицензии, push 2026-03-19 | Один ноутбук. Данные получены от суррогата ViscoNet с ручным копированием результатов |
| karyakorkmazyigit/EPDM-Project, muraterdemaydin1981/ml-compounder, jayanththalla/Rubber, thomilin/RubberFormulations, niteshrajeshsoni/rubber-compound | без лицензии, 0 звёзд | README по 72-155 байт либо пустой репозиторий |
| ElsevierSoftwareX/SOFTX-D-16-00029 (GURU v2.0) | без лицензии в API, push 2016-05-04 | MATLAB GUI для подгонки реометрических кривых |
| Duke-MatSci/nanomine, Duke-MatSci/ChemProps | без лицензии, push 2023-05-01 и 2021-06-24 | Код веб-портала, вызываемого API нет |
| b-shields/edbo, doyle-lab-ucla/edboplus | MIT, push 2026-03-31 и 2026-09-03 | Рабочие, заточены под условия реакций. BayBE и BoFire покрывают то же и лучше описывают смеси |
| sustainable-processes/summit | MIT, push 2024-09-03 | Два года без обновлений, старые зависимости |
| the-matter-lab/olympus, the-matter-lab/atlas | MIT, push 2024-11-24 и 2025-05-21 | Olympus является бенчмарком. Atlas обновляется редко. Дублируют п. 2 и п. 6 |
| meta-pytorch/botorch, facebook/Ax | MIT, push 2026-09-08 и 2026-09-15 | Отличные библиотеки нижнего уровня. Для автоматической конвертации слишком общий API, п. 2 и п. 6 дают готовые обёртки над BoTorch |
| MSDLLCpapers/obsidian | GPL-3.0, push 2026-08-03 | Дублирует п. 2 при более строгой лицензии |
| henrikbostrom/crepes | BSD-3-Clause, push 2026-07-08, 582 звезды | Годная лёгкая альтернатива MAPIE с условной (Мондриановой) калибровкой. Резерв для п. 3 |
| datamol-io/molfeat | Apache-2.0, push 2026-09-09 | Хаб признаков, тянет много необязательных зависимостей. п. 1 и п. 8 проще |

## Открытые наборы данных

Прямого аналога (рецепты резиновых смесей в phr с механическими и динамическими свойствами) в открытом доступе не найдено. Проверены Zenodo API (7 запросов), HuggingFace API (5 запросов), веб-поиск по Mendeley Data и figshare.

| Набор | URL | Размер | Лицензия | Замечание |
|---|---|---|---|---|
| CheMixHub | https://github.com/chemcognition-lab/chemixhub | 13 задач, ~500 тыс. точек (по README и arXiv:2506.12231) | MIT (репозиторий), у исходных наборов свои условия | Жидкие смеси, электролиты, топлива. Резины нет. Полезны готовые разбиения «невиданные компоненты» |
| MolSets data | https://github.com/Henrium/MolSets (`data/data_compiled.csv`, 172 КБ) | не подсчитано | MIT (репозиторий), источник: ACS Cent. Sci. 2023, 9, 206 | Электролиты, смесь растворителей плюс соль |
| PI1M | https://github.com/RUIMINMA1996/PI1M | ~1 млн сгенерированных PSMILES, репозиторий 30 МБ | MIT | Без свойств. Только для предобучения |
| POINT2 | https://github.com/Jiaxin-Xu/POINT2 | репозиторий 134 МБ | MIT | Бенчмарк свойств гомополимеров на базе PI1M. Состав не проверен |
| Soft Robotics Materials Database | https://github.com/LucMarechal/Soft-Robotics-Materials-Database | репозиторий 6.7 МБ | ODbL-1.0 | Кривые растяжения силиконов и полиуретанов. Тест для подгонки гиперупругих моделей |
| Fatigue lifetime of carbon black-filled polychloroprene | https://zenodo.org/records/15224564 | 10 КБ | CC-BY-4.0 | Усталость одной смеси CR. Очень мал |
| Tensile fatigue, microstructure of filled rubber (Dryad) | https://zenodo.org/records/4994403 | 403 КБ | CC0 | Одна система, рецептов нет. Содержание не проверено |
| Thermal conductivity of natural rubber | https://zenodo.org/records/7240288 | 72 КБ | CC-BY-4.0 | Одно свойство, один материал |
| S98 TIRECHEM | https://zenodo.org/records/11185511 | 147 КБ | CC-BY-4.0 | Список химикатов, связанных с шинами, из литературы по экологии. Может дать SMILES для шинных добавок (не проверено) |
| Asphalt mixed with vulcanized natural rubber | https://data.mendeley.com/datasets/wnwykdkwx3/2 | не проверено | не проверено | Влияние дозировки серы, но объект исследования асфальт |
| NanoMine / MaterialsMine | https://materialsmine.org | не проверено | не проверено | Курируемые данные по полимерным нанокомпозитам, включая наполненные эластомеры. Открытого пакетного доступа не найдено |
| PoLyInfo (NIMS) | https://polymer.nims.go.jp | не проверено | условия NIMS запрещают массовую выгрузку (не проверено в этой сессии) | Для образов и перераспространения не годится |

Работы с закрытыми данными, полезные для раздела related work: «Machine learning assisted analysis and prediction of rubber formulation using existing databases» (Artificial Intelligence Chemistry, 2024, https://www.sciencedirect.com/science/article/pii/S2949747724000125) и «Data-Driven Exploration of Polymer Processing Effects on the Mechanical Properties in Carbon Black-Reinforced Rubber Composites» (Chinese J. Polym. Sci., 2024, https://link.springer.com/article/10.1007/s10118-024-3216-3, модели лежат в `Vanguer/rubber-mechanical-properties-prediction`). Ссылок на открытые данные в найденных описаниях нет.

## Рекомендуемая связка для демо

1. `mordred-community` и `scikit-fingerprints` переводят ингредиенты в химические признаки и функциональные классы.
2. `skada` (`domain_shift_report`) отвечает, где сидит сдвиг между патентами.
3. `MAPIE` с калибровкой по патентам даёт интервалы и честное покрытие на отложенных патентах.
4. `felupe` сворачивает M100, M300, прочность и удлинение в физические параметры.
5. `pymoo` или `BayBE` ищет рецепт по нескольким целям со штрафом за ширину интервала.

Физику наполнителя (Гут-Голд, Краус) и кинетику вулканизации (Камал-Суру, Исаев-Денг) стоит оформить своим маленьким репозиторием: готового лицензированного кода не найдено.
