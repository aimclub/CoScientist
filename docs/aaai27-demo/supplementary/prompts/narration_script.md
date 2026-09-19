# Сценарий видео: AAAI-27 Demonstrations

Лимит 5:00. Цель по хронометражу 4:40. Закадровый текст на английском, озвучка через Qwen3-TTS (https://huggingface.co/spaces/Qwen/Qwen3-TTS), по одному абзацу на запрос. Темп расчёта: около 150 слов в минуту. Числа взяты из итогов прогона `tyre-main-2` (`runs/tyre-main-2_*.summary.md`, `.report.md`) и follow-up сессии `tyre-followup-1`.

Порядок работы: сначала озвучить все абзацы и записать длительности, потом снимать экран под длину каждого абзаца, потом монтаж.

## Раскадровка

| # | Время | Кадр | Слов |
|---|---|---|---|
| 1 | 0:00–0:40 | Титул, затем схема архитектуры (`paper/figures/architecture.pdf`) | 95 |
| 2 | 0:40–1:15 | Веб-интерфейс: новая сессия, вставка промпта, прикрепление датасета | 85 |
| 3 | 1:15–2:05 | Граф исследования (новая проекция): счётчики вердиктов, полосы Framing → Literature review → Hypotheses → Report, карточки гипотез с вердиктами, раскрытие свидетельства с вызовами инструментов | 120 |
| 4 | 2:05–2:50 | Лента событий `trial-polybert-3` или `tyre-main-1`: поиск по каталогу, вызовы `embed_blend`, `read_result`, передача кодеру | 110 |
| 5 | 2:50–3:25 | Ход 2 сессии `tyre-main-2`: запрос, два билда `rubber-mechanical-properties-prediction-1c872d` и `TransPolymer-acee03` на странице билдов, карточка инструмента, история вызовов | 90 |
| 6 | 3:25–4:00 | Отчёт: таблица R², кандидаты рецептур с оговорками | 90 |
| 7 | 4:00–4:35 | Страница Hub, Docker Hub в браузере (19 серверов), сессия `tyre-followup-1`: `retrieve_tools` находит сервер Wan, вызовы `predict_strength` и `predict_elongation` | 95 |
| 8 | 4:35–4:50 | Экспорт сессии, финальный титул со ссылками | 55 |

## Закадровый текст

**1. Overview**

> Language model agents can now run most stages of a computational study. But when the run ends, what is left is usually a report and some code. The environment where a published method finally worked is lost, and the next study sets it up again. This is CoScientist. It plans a study as a typed research graph, searches the literature, runs experiments, and turns research repositories into tool servers that stay in a public catalogue. In this video it takes on an industrial problem: designing tyre rubber compounds from open data and published methods.

**2. The task**

> Tyre makers keep their recipes secret. We give the system one prompt. It states the goal, lists eight published methods, and attaches a table of three thousand seven hundred compounds collected from patents. The prompt does not say how to solve the task and does not mention any tool. From here on, the system works without a human.

**3. The research graph**

> The orchestrator turns the request into a research question and a set of hypotheses, each with a verification method and a confirmation criterion. One of them the system proposed by itself: rows from the same patent are near copies, so a random split will overstate the accuracy. Every agent writes to the same graph. Evidence, code, and generated data are attached to the hypothesis they test, and a background validator sets the verdicts. The study ends with forty nodes and six hypotheses: one confirmed, one refuted, one inconclusive, three postponed. Every sentence of the final report points to a node.

**4. Reusing a tool**

> To use polyBERT, a language model for polymers, the system first searches its tool catalogue. It finds a server that Alembic built earlier from the model repository, calls it for the elastomer blends of the dataset, and hands the fingerprints to the coder agent as object references. No environment is installed and no model code is written. We checked this server against values that a chemist on our team had computed by hand before the study. They agree to six decimal places.

**5. Converting a repository**

> The system found the Wan et al. rubber models in an unlisted repository and got them to run. At the end of the session, one request turns the methods that ran into tool servers: Alembic converts the Wan repository and TransPolymer. Alembic builds the environment in a container, writes each tool as a plain function with tests, calls every tool on sample inputs, and serves the result over the Model Context Protocol. Each validation call is stored with its arguments and output, so you can see what validated means for this tool. Nine tools, all passing their tests and live calls, in about forty minutes. The TransPolymer image goes to the public catalogue.

**6. The result**

> The result is mostly negative, and the system says so. With a random split the recipe predicts M three hundred with an R squared of zero point nine. When whole patents are held out, it drops to zero, and for Mooney viscosity it goes below zero. The system named the cause itself: rows from one patent are near copies, and a random split rewards memorising them. Polymer fingerprints do not help; a paired test says so. The system refutes its own benchmark hypothesis, and still proposes five candidate recipes for the target window, with the warning that its uncertainty is optimistic and that every candidate needs a laboratory check.

**7. The catalogue**

> What remains after the run is the catalogue. On Docker Hub it now holds nineteen servers from chemistry, materials, climate, geoscience, physiology, and medical imaging. Anyone can pull one and call a tool in a minute, with no model calls. The next agent that needs the method finds it here: a new session asked for the properties of one candidate recipe, found the Wan server in the catalogue, and answered in four minutes for fourteen cents, with nothing installed.

**8. Closing**

> The whole run took one hundred and five minutes and three and a half dollars. The session exports as one file with the graph, the agent trajectory, and the builds. A follow-up study starts from running tools and from a record of what was already tried. Links to the catalogue and the code are in the paper.

## Кадры, которые нужно снять
1. Главная страница чата: новая сессия, промпт, окно прикрепления датасета.
2. `/graph?view=research` для импортированной сессии `tyre-main-2` (id в `shots/baked_session.txt`): общий вид сверху вниз (счётчики `1 confirmed · 1 refuted · 1 inconclusive · 3 postponed`, полосы стадий), клик по Hypothesis 2 (refuted, статус с причиной), клик по Evidence 2 (6 вызовов кодера, 2 вложения). Образец кадра: `shots/graph_proj_en_tall.png`, фрагмент в статье: `paper/figures/graph_hypotheses.png`.
3. `/trace` или лента чата: `retrieve_tools`, `embed_blend`, делегирование кодеру.
4. `/alembic/builds`: список, страница билда (инструменты, история вызовов, вызов инструмента со страницы).
5. `/alembic/hub`: список серверов, Pull & start.
6. Страница `hub.docker.com/u/peanutbuttermilk` в браузере.
7. Итоговый отчёт в чате: таблица R² и кандидаты.
8. Кнопка экспорта сессии.

## Замечания
- Интерфейс в кадре должен быть на английском: переключатель языка на главной странице в `en` (граф читает его же), язык отчёта `en`, заголовки сессий на английском.
- Сессии под пользователем `demo`. Остальные сессии в списке лучше скрыть.
- В кадр не должны попадать `.env`, ключи, адрес `10.32.1.36`.
- polyBERT в кадре показываем как локальный сервер. На странице Hub его нет.
- Сцена 3: граф берётся из импортированной сессии (`runs/tyre-main-2_*.cossession.zip`, текущий id в `shots/baked_session.txt`). После каждого перезапуска сервера бандл импортируется заново: `curl -X POST localhost:8000/api/users/x/import-session -F file=@runs/tyre-main-2_e7fa204e.cossession.zip`. Проекция показывает 18 карточек и 30 рёбер из 40 узлов записи, в шапке так и написано. Подписи карточек (тип, статус) следуют языку интерфейса, переключить на английский до записи; текст гипотез и методов внутри карточек агенты писали по-русски, свидетельства и выводы по-английски.
- Сцена 4: в `tyre-main-2` вызовов серверов не было, кодер всё считал сам. Повторное использование polyBERT показываем по сессии `trial-polybert-3` (вызовы `embed_blend`, `read_result`) без утверждения, что это часть основного прогона.
- Сцена 5: сборки запущены во втором ходе сессии по прямой просьбе пользователя. В тексте так и сказано («one request»).

## Автономная запись (19 сентября)
- `tts.py`: озвучка через Space `Qwen/Qwen3-TTS` (`/generate_custom_voice`, голос Ryan, модель 1.7B). Анонимная квота ZeroGPU кончилась после пяти сцен, поэтому сцены 6–8 сделаны `tts_local.py` на локальной модели `Qwen3-TTS-12Hz-0.6B-CustomVoice` (1.7B в 4 ГБ видеопамяти не входит). Полный набор 0.6B лежит в `audio_06b/` для сравнения на слух.
- `record.py`: восемь сцен в безголовом Chrome 1600×900, по одному webm на сцену, длительность по клипу озвучки. Сцены 2, 3, 5, 6, 8 показывают импортированные сессии (id в `shots/baked_session.txt`), сцена 4 показывает `/trace` сессии `trial-polybert-3`, сцена 7 хаб, Docker Hub и импортированную `tyre-followup-1`, начало сцены 5 берётся из исходной `tyre-main-2` (в бандле нет запроса второго хода).
- `montage.sh [audio_dir] [out.mp4]`: 1920×1080, 30 fps, h264 + aac, пауза 0,6 с после сцены; сцена 5 обрезана на 3,5 с в начале (лента чата успокаивается).
- Пересъёмка одной сцены: `python record.py --only 6 && ./montage.sh`.
