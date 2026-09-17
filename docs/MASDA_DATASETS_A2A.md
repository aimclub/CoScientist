# Экспериментальный provider MASDA_Datasets

## Маршруты и граница интеграции

```text
                           OrchestratorAgent
                                  |
             +--------------------+--------------------+
             |                                         |
     builtin (default)                         masda (explicit)
             |                                         |
     TaskExecutorAgent                         MasdaDatasetsAgent
             |                              deterministic ADK BaseAgent
         CoderAgent                                     |
             |                             MASDA SendMessage adapter
   DatasetCollectorAgent                                |
     shared sandbox                         configured MASDA RPC endpoint
                                                       |
                                          embedded CSV -> same local workspace
```

`DatasetCollectorAgent` остаётся дочерним агентом `CoderAgent` в режиме
`builtin`: он получает данные из внешних источников и пишет файлы с manifest в
общий sandbox. Он не удалён и не требует MASDA. В режиме `masda` конфигурация
подключает `MasdaDatasetsAgent` к Orchestrator, снимает встроенный collector с
маршрута Coder и добавляет специальное правило делегирования. Ошибка MASDA
возвращается Orchestrator текстом; автоматического fallback нет.

Новый агент — детерминированный `BaseAgent` с небольшим `httpx` adapter в
`CoScientist/a2a/masda.py`. Он не запускает LLM, planner или отдельный HTTP
framework. `AgentTool` по-прежнему передаёт результат Orchestrator. Generic
`RemoteA2aAgent` для остальных агентов не изменён.


## MASDA Integration Boundary v1

MASDA интегрируется в CoScientist как альтернативный provider **только для стадии
dataset acquisition**. Orchestrator решает, требуется ли получение внешнего
набора данных; выбор backend (`builtin` или `masda`) остаётся конфигурационным
решением и не передаётся LLM.

Для `provider=masda` граница v1 формулируется так:

- MASDA получает внешний табличный датасет, которого ещё нет в local workspace
  или среди user uploads;
- наиболее проверенный путь v1 — explicit exact direct CSV URL;
- после acquisition downstream-агенты должны использовать возвращённый
  CoScientist workspace path;
- analysis, preprocessing, feature engineering, ML, visualization и synthetic
  data generation **не** относятся к ответственности MasdaDatasetsAgent;
- description-only / ambiguous discovery допускается как экспериментальный путь,
  но `TASK_STATE_COMPLETED` не подтверждает semantic correctness;
- при ошибке MASDA автоматического fallback на `DatasetCollectorAgent` нет.

Граница ответственности:

```text
MASDA responsibility
external source
    -> acquisition
    -> dataset bytes
    -> acquisition metadata / provenance
    -> task status

------------- integration boundary -------------

CoScientist responsibility
    -> validate/decode remote result
    -> materialize physical workspace artifact
    -> expose local workspace path
    -> semantic validation when required
    -> downstream analysis / preprocessing / ML / reporting
```

MASDA-local путь вроде `output/jobs/a2a/<task>/dataset.csv` не пересекает эту
границу сам по себе. Передаваемым объектом становится только embedded artifact,
который adapter проверил, декодировал и записал в workspace CoScientist.

Поддерживаемая область v1:

| Категория | Сценарии |
| --- | --- |
| **Validated / supported** | внешний табличный dataset; exact direct CSV URL; `SendMessage`; embedded CSV; physical workspace materialization; provenance metadata; explicit provider selection; no fallback |
| **Experimental** | dataset-name-only lookup; natural-language description discovery; ambiguous HuggingFace/discovery сценарии |
| **Not validated** | Parquet на `:9999`; ZIP; arbitrary archives; non-tabular datasets; large-file behavior; remote code-exec visibility при отсутствии общего диска |


## Фактический wire contract

Текущий AgentCard MASDA заявляет `protocolVersion: "0.3"` и
`preferredTransport: "JSONRPC"`, но endpoint принимает другой контракт:

- `POST` на настроенный RPC URL;
- заголовки `Content-Type: application/json`, `A2A-Version: 1.0`;
- JSON-RPC method `SendMessage`, роль `ROLE_USER`;
- `configuration.return_immediately: false`.

Версия A2A задаётся `DATASET__MASDA_A2A_VERSION` (default `1.0`).
`DATASET__MASDA_A2A_RPC_URL` задаёт RPC endpoint прямо. Для совместимости с
первым вариантом интеграции можно оставить только
`DATASET__MASDA_A2A_CARD_URL`: adapter прочитает стандартное поле `url` из
AgentCard, но **не** возьмёт из него заявленную protocolVersion как wire
contract. Одновременно задавать card необязательно, когда RPC URL известен.

Стандартный ADK `RemoteA2aAgent` + `a2a-sdk 0.3.26` здесь не подходит:
наблюдаемый endpoint требует `SendMessage` вместо `message/send`, а также
другую версию заголовка и enum-представление роли/состояния. Обновление всего
`a2a-sdk` не входит в эксперимент. Diagnostic compatibility proxy помог
установить это расхождение, но для работы native adapter больше не нужен.

## Результат и физический CSV

Adapter проверяет HTTP и JSON-RPC ошибки, наличие `result.task`, terminal
state `TASK_STATE_COMPLETED`, `harvest_result.record_count` и единственный
embedded CSV artifact. CSV выбирается по `raw` вместе с `.csv` filename либо
`mediaType: text/csv`, независимо от позиции artifact. `dataset_report.json`
датасетом не считается. Base64 декодируется строго; CSV должен иметь строки,
согласованные с `record_count`. `COMPLETED` без корректного CSV — ошибка, а не
успех.

Workspace берётся из уже закреплённого `coder_workspace_id` в состоянии
публичной web-session. Это тот же идентификатор, который используют Coder и
workspace sync; временный `ctx.session.id` дочернего `AgentTool` не используется.
Файл записывается атомарно в:

```text
<CODE_EXEC__WORKSPACE_ROOT>/ws_<public-session>/data/masda/<task-id>-<hash>/dataset.csv
```

Имя файла проверяется, а каталог задачи отделяет несколько запросов друг от
друга. Ответ Orchestrator содержит успех, число записей, реальный абсолютный
путь, MASDA task id и source URL, если он однозначно найден в `harvest_result`.
Путь MASDA `output/jobs/a2a/.../dataset.csv` не выдаётся за локальный файл.
FilePart/inline_data из удалённого A2A не сохраняется как ADK artifact:
физический CSV в существующем local workspace является доставляемым объектом.

Это локальная workspace materialization. Если `CODE_EXEC__URL` отправляет
Coder на отдельный сервер без общего диска, ему понадобится отдельная передача
этого файла через уже существующий механизм vault/S3. Этот сценарий здесь не
проверен и не должен считаться автоматически работающим.

## Запуск без diagnostic proxy

PowerShell, встроенный provider (или вообще не задавать переменную):

```powershell
$env:DATASET__PROVIDER = 'builtin'
uv run --no-sync python -m CoScientist web --host 127.0.0.1 --port 8000
```

PowerShell, MASDA по текущему RPC endpoint:

```powershell
$env:DATASET__PROVIDER = 'masda'
$env:DATASET__MASDA_A2A_RPC_URL = 'http://77.234.216.102:9999'
$env:DATASET__MASDA_A2A_VERSION = '1.0'
uv run --no-sync python -m CoScientist web --host 127.0.0.1 --port 8000
```

Вместо RPC URL можно задать
`DATASET__MASDA_A2A_CARD_URL=http://77.234.216.102:9999/.well-known/agent-card.json`.
Provider выбирается при старте процесса. Текущий внешний endpoint использует
plain HTTP; для production размещения предпочтителен HTTPS.

Ручной запрос для проверки: «Получи табличный датасет по точной ссылке
https://raw.githubusercontent.com/JohnMount/Penguins/main/penguins.csv через
настроенный MASDA dataset service. После успешного получения ничего больше не
делай: не анализируй данные и не запускай дополнительную обработку. Сообщи
только результат получения датасета».

Полный web E2E с этим exact URL пройден 17 сентября 2026 без proxy:
User → ContextInitAgent → OrchestratorAgent → MasdaDatasetsAgent → native
adapter → MASDA `:9999` → embedded CSV → workspace → Orchestrator. MASDA
вернул `TASK_STATE_COMPLETED`, task id
`5f92312f-9af6-4bab-abff-f61e98e82c59` и `record_count = 344`. Физический
артефакт публичной web-session:

```text
C:\Users\Home\PycharmProjects\CoScientist\workspace\ws_session_2ec2bdfbddc14649952fd3b96d2b9857\data\masda\5f92312f-9af6-4bab-abff-f61e98e82c59-2f795f8b0ead\dataset.csv
```

Файл проверен вручную: 50 736 байт, 344 строки `Import-Csv`, SHA256
`358D01E8F46DCA541FB715DE825C41685562B3A6CC1C82B9C07EB556A5E3BF7E`.
Он содержит добавленные MASDA provenance-поля `title`, `source`, `url`,
`source_file`. Доказательством доставки служит именно этот workspace-файл;
Parquet/ZIP на endpoint `:9999` не проверялись.


## Acceptance matrix Boundary v1

После уточнения routing contract проверены следующие сценарии. Для строк с
`prompt contract` защита означает однозначную инструкцию Orchestrator и
регрессионный unit test; это не runtime-guard против любого возможного решения LLM.

| Сценарий | Ожидаемый routing | Защита / результат |
| --- | --- | --- |
| Exact external CSV URL, `provider=masda` | `MasdaDatasetsAgent` | PASS — validated v1 route |
| Exact external CSV URL, `provider=builtin` | builtin acquisition path | PASS — `builtin` остаётся default |
| Already-local CSV | не выполнять MASDA acquisition | PASS — prompt contract |
| Uploaded CSV | использовать существующий artifact | PASS — prompt contract |
| Анализ dataset | downstream execution | PASS — prompt contract |
| Preprocessing / cleaning | downstream execution | PASS — prompt contract |
| ML / train model | downstream execution | PASS — prompt contract |
| Synthetic dataset generation | execution/generation path | PASS — prompt contract |
| Description-only discovery | MASDA допустима, но результат experimental | PASS — semantic correctness явно не гарантируется |
| MASDA unavailable | явная MASDA error без builtin fallback | PASS |
| `COMPLETED` без embedded CSV | adapter error | PASS |

После boundary-fix P0/P1 gaps относительно Integration Boundary v1 не
обнаружены. Оставшиеся follow-up относятся к semantic validation, повторному
task id, runtime-поведению LLM routing и remote code-exec artifact visibility,
а не к базовой native MASDA integration.


## Отдельный риск отчётности и смысловой проверки

`ResultAggregator` способен независимо скачать исходный CSV из URL в
`ResearchQuestion` через `find_artifact_urls()` → `collect_artifacts()`. В
контрольном запуске отчёт показал две таблицы: `dataset.csv` соответствует
MASDA workspace artifact с provenance-полями, а
`MasdaDatasetsAgent_penguins.csv`, вероятно, получена reporting-слоем напрямую
из исходного URL. Последняя **не доказывает доставку MASDA artifact**. Для E2E
проверять файл из `Workspace artifact` с MASDA task id; reporting здесь не
меняется.

В том же запуске Orchestrator после acquisition пытался записать Evidence, а
ResultAggregator создал отчёт, хотя пользователь просил остановиться после
получения. `CC1` остался `not_met`, `Q1` — `open`. Это известное ограничение
жизненного цикла operational task и research graph; данный adapter его не
исправляет.

Даже `TASK_STATE_COMPLETED` и существующий CSV сами по себе не доказывают,
что сервис выбрал семантически нужный датасет. Ранее поиск только по описанию
давал semantic false-success. Exact direct CSV URL для Palmer Penguins
надёжнее, но содержание и provenance результата всё равно нужно проверять.


## Экспериментальная версия ветки

Проверенная реализация находится в ветке:

```text
experiment/masda-datasets-a2a
```

Два логических commit:

```text
b39ee96b0c82e568fbeaba38729c78c93071fa88
Add native MASDA dataset provider and workspace CSV delivery

cdb04418cb2fee1d96faf99d2c4ed6057c4ba0c6
Clarify MASDA dataset acquisition routing boundary
```

Первый commit вводит native MASDA adapter и физическую доставку CSV в workspace.
Второй сужает routing boundary до dataset acquisition, отделяет exact CSV от
экспериментального discovery и фиксирует исключения для local/uploaded данных,
analysis, preprocessing, ML и synthetic generation.

На момент фиксации второго commit ветка была `ahead 2` относительно
`origin/main`, working tree — clean; push и PR ещё не выполнялись.


## Follow-up вне scope v1

Следующие задачи целесообразно вести отдельными change set:

1. semantic validation результата, включая сопоставление requested exact URL с
   возвращённым `source_url`;
2. runtime/behavioral routing tests без реального LLM либо с контролируемым
   harness;
3. политика повторного использования одного `task id`;
4. передача materialized CSV в remote code-exec при отсутствии общего диска;
5. отдельная проверка description-only discovery;
6. Parquet/ZIP и другие форматы;
7. operational-task lifecycle (`Evidence`, `CC1`, `Q1`, ResultAggregator).

Эти пункты не являются блокерами для текущей MASDA Integration Boundary v1.
