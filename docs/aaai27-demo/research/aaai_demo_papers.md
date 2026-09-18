# Принятые статьи AAAI Demonstration Track (AAAI-24, 25, 26): разбор и выводы для нашей заявки на AAAI-27

Дата сбора: 2026-09-17. Источники: страницы выпусков ojs.aaai.org, PDF статей с ojs.aaai.org, страница вызова AAAI-27, архив AuthorKit27.

Как проверялось. Списки статей взяты из разделов "AAAI Demonstration Track" выпусков Vol. 38 No. 21 (AAAI-24, 30 статей), Vol. 39 No. 28 (issue 651, AAAI-25, 41 статья) и выпуска issue 732 (AAAI-26, 71 статья). 13 PDF скачаны и переведены в текст через `pdftotext`. 10 статей прочитаны целиком, у трёх (AutoMV, MANDREL, SciSpace Copilot) прочитаны аннотация, заголовки, вклад, демо-раздел и заключение. Доли разделов оценены по объёму текста, рисунки в долях не учтены. Такие оценки помечены знаком "~". Вёрстку страниц (размер рисунков) я глазами не смотрел: всё, что касается площади рисунков, помечено как непроверенное.

Срочно: крайний срок подачи на AAAI-27 Demo стоит на 18 сентября 2026, 23:59 AoE (UTC-12). Это завтра относительно даты сбора.

---

## 1. Требования AAAI-27 Demonstrations (проверено по странице вызова)

Страница: https://aaai.org/conference/aaai/aaai-27/demonstration-call/

| Пункт | Требование |
|---|---|
| Объём | "Two-page short paper describing their system, plus one page of references only" |
| Формат | двухколоночный стиль AAAI (AuthorKit27) |
| Содержание | статья должна включать "technical details of the demonstration, discuss related work, and describe the significance" |
| Видео | до 5 минут, видео предпочтительнее слайдов, загружается в OpenReview как supplementary |
| Код | загрузка необязательна, поощряется |
| Анонимность | на выбор авторов: single-blind (имена в статье) или double-blind |
| Reproducibility checklist | для демо-трека не требуется |
| Площадка | OpenReview: https://openreview.net/group?id=AAAI.org/2027/Demonstration_Program |
| Срок подачи | 18 сентября 2026, 23:59 AoE. До этого рекомендована регистрация на площадке |
| Уведомление | 6 ноября 2026 |
| Camera-ready | 20 ноября 2026 |
| Демо-сессии | 18-21 февраля 2027 (конференция 16-23 февраля 2027, Монреаль) |
| Присутствие | минимум один автор регистрируется и показывает демо очно |
| Критерии рецензии | "clarity, the significance of the proposed demonstration, and its relevance to the AI community, as well as the ability to engage audiences" |

Страница вызова получена через автоматическое извлечение текста. Цитаты стоит сверить глазами перед подачей, особенно пункт про анонимность.

### AuthorKit27 (проверено по архиву https://aaai.org/authorkit27/)

Состав архива: `AnonymousSubmission2027.tex/.pdf`, `CameraReady2027.tex/.pdf`, `aaai2027.sty`, `aaai2027.bst`, `aaai2027.bib`, `ReproducibilityChecklist.tex/.pdf`, папка `Word/` с .docx.

- Преамбула: `\documentclass[letterpaper]{article}` и `\usepackage[submission]{aaai2027}` для анонимной версии, `\usepackage{aaai2027}` для версии с именами. Строки с `url`, `graphicx`, `natbib`, `caption` менять нельзя, опции к `natbib` и `caption` добавлять нельзя.
- Бумага US Letter 8.5 x 11 дюймов, две колонки по 3.3 дюйма. Поля: верх 1.25 дюйма на первой странице и 0.75 на остальных, левое и правое 0.75, нижнее 1.25.
- Шрифт Times-подобный, его подключает стиль. Пакеты `times`, `helvet`, `courier` подключать нельзя.
- Запрещённые пакеты (часть списка): `authblk`, `balance`, `CJK`, `float`, `flushend`, `fullpage`, `geometry`, `hyperref`, `titlesec`. Запрещены команды, меняющие поля, интервалы и кегль (`\columnsep`, `\topmargin`, `\textheight` и подобные).
- В PDF нет встроенных ссылок и закладок, нет номеров страниц. Все шрифты встроены, Type 3 запрещён.
- Таблицы 10 pt, допускается 9 pt. Мельче 9 pt нельзя.
- Ссылки на код и данные оформляются окружением `\begin{links} \link{Code}{...} \end{links}` после аннотации. В анонимной версии ссылки не должны раскрывать авторов.
- Для анонимной версии: автор "Anonymous Submission", пустые аффилиации, очищенные метаданные PDF, обезличенные самоцитирования, без копирайта в подвале.

---

## 2. Разобранные статьи

Все статьи занимают 3 страницы в сборнике: 2 страницы текста и страница ссылок. Это совпадает с правилом AAAI-27.

### 2.1 DFAgent: From Natural Language Data Interactions to Reusable Agent-Ready Tools (AAAI-26)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/42347 (IBM Research India)
- Самая близкая к нам работа: код из диалогов превращается в каталог MCP-инструментов.
- Разделы: Abstract (113 слов), Introduction and Background (~35%), DataFoundry Agent (DFAgent) (~40%), Related Work (~15%), Conclusion (~10%).
- Вклад: "DFAgent (i) translates NL prompts and direct data manipulations into executable code for inspection, transformation, and visualization, (ii) logs generated snippets together with provenance metadata, and (iii) abstracts and synthesizes those snippets into a governed catalog of MCP-exposed tools." Дальше: "Our contribution is threefold. First, we demonstrate a working pipeline ... Second, we show automated synthesis of parameterized agentic tools from the code artifacts. Third, we highlight governance by enabling catalog curation and lineage".
- Оценка: нет. Ни чисел, ни пользовательского исследования. Есть примеры запросов ("plot income versus age").
- Related work: отдельный раздел из двух абзацев, 6 ссылок на всю статью.
- Рисунки: 3 (взаимодействие пользователя, общая схема, генерация инструментов). Таблиц нет.
- Демо и видео: в тексте ссылки на видео нет. Одна сноска на github MCP.
- Ограничения: нет.

### 2.2 ToolSmith: A Multi-Agent Framework for Enterprise Tool Creation (AAAI-26)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/42388 (IIT Delhi, IBM Research)
- Разделы: Abstract (122 слова), Introduction (~20%), Prior Work (~17%), Our Contributions (~18%), Framework (~37%), Discussion and Conclusion (~8%).
- Вклад: отдельный раздел "Our Contributions" с тремя именованными пунктами жирным: "Context Grounded Test Generation", "Agent-Centric Verification & State Validation", "Autonomous Self-Correction Loop". Ключевая фраза аннотации: "We present ToolSmith, a framework for autonomously generating and validating agent-compatible tools."
- Оценка: нет. В заключении оценка отнесена в будущее: "Future work includes benchmarking the framework to determine the best LLMs to use under cost constraints."
- Related work: отдельный раздел "Prior Work" с критикой двух подходов (генерация кода на лету, LATM). 15 ссылок.
- Рисунки: 1 (схема из четырёх агентов). Таблиц нет.
- Демо и видео: ссылки на видео и код в тексте нет, только сноски на Swagger, LangGraph, PEP 257.
- Ограничения: явного раздела нет, есть планы работ.

### 2.3 GenMatLab: A Generative Platform for Inverse Materials Design (AAAI-26)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/42374 (A*STAR)
- Близко к нашему кейсу по домену: материалы, обратный дизайн по целевым свойствам.
- Разделы: Abstract (95 слов), Introduction (~40%, внутри сравнение с Materials Project, JARVIS, Open MatSci ML Toolkit), Functionality of GenMatLab (~52%, абзацы с жирными вводными: User Interface, Inverse Design with Multiple Target Properties, Backend Conditional Generative Model Training, Data Augmentation), Conclusion (~8%).
- Вклад: "To the best of our knowledge, GenMatLab is the first platform that provides an integrated, user-friendly environment for inverse materials design." И про аналоги: "none of them directly support interactive inverse materials design workflows".
- Оценка: нет. Качество моделей подкреплено ссылкой на собственную статью (PCDiff).
- Related work: встроен во введение. 9 ссылок.
- Рисунки: 1 большой скриншот интерфейса на ширину страницы. Таблиц нет.
- Демо и видео: ссылок нет, статья называет себя "this demo" и "technical demo".
- Ограничения: нет.

### 2.4 Wikatoni: An Agentic AI System for Energy Engineering Workflows (AAAI-26)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/42375 (Robert Gordon University, Katoni Engineering)
- Разделы: Abstract (136 слов), Introduction (~25%), Embedding Model Fine-tuning (~15%), System Overview (~35%: Supervisor Agent, Retrieval Agents, Other Sub-agents), Evaluation (~18%), Conclusion (~7%).
- Вклад: "we present Wikatoni, an agentic AI system for energy engineering workflows. It incorporates a novel embedding model fine-tuned on a domain-specific dataset, both openly released."
- Оценка: самая плотная из выборки. Recall@K для 6 моделей эмбеддингов (рисунок), таблица с Context Recall, Faithfulness, Answer Accuracy на 300 реальных запросах с экспертной разметкой через RAGAS. Числа вынесены в аннотацию: "improves recall by 10% ... increases answer accuracy by 14%".
- Related work: встроен во введение. 18 ссылок.
- Рисунки и таблицы: 2 рисунка (архитектура, график Recall@K) и 1 таблица.
- Демо и видео: блок ссылок после аннотации на модель и датасеты на Hugging Face. Видео в тексте не упомянуто.
- Ограничения: нет.

### 2.5 KnowThyself: An Agentic Assistant for LLM Interpretability (AAAI-26)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/42373, arXiv:2511.03948
- Разделы: Abstract (106 слов), Introduction (~25%), System Overview (~25%: Orchestrator LLM, Agent Router, Specialized Agents, Conversational Interface), Implementation (~18%), Use Cases (~20%), Conclusion and Future Work (~12%).
- Вклад: нумерованный список внутри абзаца: "Our main contributions include: (i) a multi-agent orchestration framework ... (ii) a modular architecture that encapsulates different methods as independent agents ... (iii) an interactive visualization interface".
- Оценка: чисел нет. Два сквозных сценария в одном сеансе (внимание по токенам, гендерное смещение) с примерами ответов системы на рисунке.
- Related work: встроен во введение. 23 ссылки.
- Рисунки: 1 рисунок на всю ширину: конвейер агентов на двух примерах.
- Демо и видео: "Code — https://github.com/spygaurad/KnowThyself" после аннотации. В Implementation названы конкретные модели (Gemma3-27B, nomic-embed-text, Ollama) и возможность локального запуска.
- Ограничения: есть, в заключении: "the current implementation integrates only a limited set of tools, requires additional engineering to adapt non-modular libraries, and supports text inputs exclusively."

### 2.6 CausalPulse: Agentic Copilot for Root Cause Analysis in Smart Manufacturing (AAAI-26)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/42381 (Univ. of South Carolina, Bosch)
- Разделы: Abstract (158 слов), Introduction (~25%), System Overview (~40%: четыре слоя UI, Agent, Utility, Data), Demonstration (~35%: User Interfaces and Interactivity, Workflow Execution and Observability, Adaptability and Extensibility). Раздела Conclusion нет.
- Вклад: "we present CausalPulse, an intelligent copilot that unifies anomaly detection to RCA within a modular, agentic framework." Упор на стандартные протоколы: MCP, A2A, LangGraph.
- Оценка: в аннотации сказано "evaluated using both an academic public dataset ... and an industrial proprietary dataset ... outperforms traditional baselines". В теле статьи чисел нет.
- Related work: встроен во введение. 10 ссылок, из них 3 на собственные работы.
- Рисунки: 2. Архитектура и составной рисунок (a) слои, (b) поток данных между агентами, (c) скриншот интерфейса.
- Демо и видео: строка "Demo Video — https://tinyurl.com/yc4mrd6s" сразу после аннотации.
- Ограничения: нет. Есть абзац про расширяемость с перечнем шагов добавления агента.

### 2.7 OrcheCause Agent: From Textual Knowledge to End-to-End Causal Inference (AAAI-26)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/42397 (LG AI Research)
- Разделы: Abstract (137 слов), Introduction (~25%, с маркированным списком вклада), System Design and Implementation (~50%: четыре модуля и Interactive UX), Demonstration (~18%), Conclusions & Future Works (~7%).
- Вклад: маркированный список из трёх пунктов с жирными названиями. Первый: "Causal task orchestration – We introduce, for the first time, an LLM-based module that dynamically adapts to user queries". В заключении: "the first causal AI agent that performs composite causal task orchestration and integrates textual knowledge".
- Оценка: таблица абляции на двух открытых датасетах (Alarm, Sachs), метрики SHD, Precision, Recall, F1 для четырёх конфигураций. Раздел с числами назван "Demonstration".
- Related work: встроен во введение, названы прямые конкуренты (Causal-Copilot). Около 17 ссылок (не пересчитано построчно).
- Рисунки и таблицы: 1 рисунок (общий поток), 1 таблица.
- Демо и видео: ссылок нет.
- Ограничения: косвенно через планы (многомерные данные с малой выборкой, временные ряды, реальные документы).

### 2.8 KnowPilot: Your Knowledge-Driven Copilot for Domain Tasks (AAAI-26)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/42394 (Zhejiang University, NUS)
- Разделы: Abstract (~85 слов), Introduction (~40%), Design and Implementation (~55%: Task-specific Priors, Explicit Knowledge, Experiential Knowledge, Knowledge Fusion), Conclusion (~5%, два предложения).
- Вклад: "we propose KnowPilot, a framework designed to systematically endow large language models with domain specific knowledge by combining textual knowledge injection with interactive experience learning". Повторное использование названо прямо: "transforming these valuable interactive processes into reusable knowledge assets". Плюс обещание поддержки: "We have open-sourced the project code and will provide long-term maintenance."
- Оценка: нет. Один пример (написание кодекса больницы) на рисунке.
- Related work: встроен во введение, много ссылок пачками. Около 25 ссылок (оценка).
- Рисунки: 2 (концепция, архитектура с примером).
- Демо и видео: сноски на первой странице: "Video: https://zjunlp.github.io/project/KnowPilot/video" и "Project: https://github.com/XeeKee/KnowPilot".
- Ограничения: нет.

### 2.9 Agentic AI for Digital Twin (AAAI-25)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/35373 (Imperial College, Konnecta, IBM Research Europe)
- Разделы: Abstract (~150 слов), Introduction (~15%), System Overview (~50%, два маркированных списка: функции цифрового двойника и инструменты агента), два сценария применения (~30%), заключительный абзац без заголовка (~5%).
- Вклад: "In this demonstration, we present an interactive agentic digital twin designed to enhance scalability, flexibility, and efficiency in managing the extensive and intricate decision-making requirements of the shipping industry."
- Оценка: нет. Два сценария: поиск аномалий в главном двигателе с выпуском наряда на ремонт, сборка и развёртывание модели на борту (Docker, Open Horizon).
- Related work: отдельного обсуждения почти нет. 6 ссылок, большинство на свои компоненты.
- Рисунки: 1 (агентный поток: планирование, рефлексия, инструменты).
- Демо и видео: ссылок нет. Сноски на LangGraph и Open Horizon.
- Ограничения: нет.

### 2.10 Agent Trajectory Explorer: Visualizing and Providing Feedback on Agent Trajectories (AAAI-25)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/35350 (IBM Research)
- Разделы: Abstract (~85 слов), Introduction (~25%), Agent Trajectory Explorer (~10%), Formatting (~12%), The Visual Paradigm (~18%), Feedback (~8%), Discussion (~20%), Conclusion (~7%).
- Вклад: "we developed the Agent Trajectory Explorer, a tool designed to help agent developers and researchers to examine, annotate, and demonstrate agent behavior in a convenient manner."
- Оценка: нет.
- Related work: встроен во введение и в Discussion. 11 ссылок.
- Рисунки: 2 (место инструмента в рабочем процессе, скриншот).
- Демо и видео: "Video — https://youtu.be/tosCdzT4MFE" после аннотации. Сноска: "We plan to open source the tool upon internal approval."
- Ограничения: есть, в тексте: "While this feedback modality is limited ..." и признание, что линейная схема Thought/Action/Observation подходит не всем агентам.

### 2.11 AutoMV: An Autonomous Agent Framework for Real Estate Marketing Video Generation (AAAI-25)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/35377 (Yep AI). Прочитана частично.
- Разделы: Abstract, Introduction, System Architecture (Agent Planning, Object Extraction, Resolution Promotion, Video Generation, Video Post-Processing), Demonstration, Conclusion.
- Вклад: "we introduce AutoMV, an autonomous agent framework designed for generating real estate marketing videos. The framework integrates a diverse set of existing models into a tool library, allowing the agent to intelligently select and execute the appropriate tools."
- Оценка: в прочитанных частях чисел нет (не проверено по всему тексту).
- Рисунки: 1 составной: "System architecture and demo website (screenshot)".
- Демо и видео: сноска "Demo website: https://automv.yepai.com.au. More generated video showcases here: https://youtu.be/aChD6FHVFK4" и фраза "please watch the video in the supplementary materials".
- Ограничения: нет, есть одна фраза про планы (расширить библиотеку инструментов).

### 2.12 MANDREL: Modular Reinforcement Learning Pipelines for Material Discovery (AAAI-24)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/30565 (IBM Research UKI, STFC Hartree Centre). Прочитана частично.
- Разделы: Abstract, Introduction, Framework Components (Environment Module, Agent Component, Reward Component, Featurisation Component), Interface, Discussion.
- Вклад: "we present MANDREL ...: an integrative, modular Python framework" и "Our contribution can be summarised as follows: MANDREL presents a standardised form of the material discovery problem."
- Оценка: качественная проверка воспроизведением: "we recover the QED results presented in Zhou et al. (2019) within MANDREL". Таблиц нет.
- Рисунки: 1 схема. Около 14 ссылок.
- Демо и видео: "An overview of this interface can be found in the video submission." Интерфейс на Dash.

### 2.13 SciSpace Copilot: Empowering Researchers through Intelligent Reading Assistance (AAAI-24)

- URL: https://ojs.aaai.org/index.php/AAAI/article/view/30578. Прочитана частично.
- Разделы: Abstract (125 слов), Introduction, Methodology, Core Functionalities (Question Answering, Features on Text Selection, Regional Language Support), Conclusion.
- Вклад через масштаб использования: "Thousands of users use SciSpace Copilot on a daily basis", "280 million corpus", "75+ languages". Ссылка на продукт стоит прямо в аннотации: "Our tool can be accessed at this link: https://typeset.io."
- Оценка: формальной нет, доказательством служит число пользователей.
- Рисунки: 4 скриншота. Около 10 ссылок.

### Сводная таблица

| Статья | Год | Рис. / табл. | Ссылок | Оценка | Related work | Видео или ссылка в тексте | Ограничения |
|---|---|---|---|---|---|---|---|
| DFAgent | 26 | 3 / 0 | 6 | нет | отдельный раздел | нет | нет |
| ToolSmith | 26 | 1 / 0 | 15 | нет, отнесена в планы | отдельный раздел | нет | нет |
| GenMatLab | 26 | 1 / 0 | 9 | нет | во введении | нет | нет |
| Wikatoni | 26 | 2 / 1 | 18 | числа, 300 запросов | во введении | модель и данные на HF | нет |
| KnowThyself | 26 | 1 / 0 | 23 | сценарии | во введении | GitHub | да |
| CausalPulse | 26 | 2 / 0 | 10 | заявлена без чисел | во введении | видео после аннотации | нет |
| OrcheCause | 26 | 1 / 1 | ~17 | абляция, 2 датасета | во введении | нет | через планы |
| KnowPilot | 26 | 2 / 0 | ~25 | один пример | во введении | видео и GitHub в сносках | нет |
| Agentic AI for DT | 25 | 1 / 0 | 6 | два сценария | почти нет | нет | нет |
| Trajectory Explorer | 25 | 2 / 0 | 11 | нет | введение и Discussion | YouTube после аннотации | да |
| AutoMV | 25 | 1 / 0 | не подсчитано | не найдена | во введении | сайт и YouTube | нет |
| MANDREL | 24 | 1 / 0 | ~14 | воспроизведение результата | во введении | "video submission" | не проверено |
| SciSpace Copilot | 24 | 4 / 0 | ~10 | число пользователей | не проверено | URL продукта в аннотации | не проверено |

---

## 3. Синтез

### 3.1 Типовая структура и бюджет места на 2 страницы

Текст без ссылок занимает от 1000 до 1450 слов (замерено: GenMatLab 1019, CausalPulse 1076, SciSpace 1000, MANDREL 1383, Agentic DT 1400, Wikatoni 1446 вместе с числами таблицы). Чем больше рисунков, тем меньше слов.

Типовой порядок:

1. Abstract, 85-160 слов, медиана около 115.
2. Introduction, 20-40% текста. Схема: домен и боль, два-три пробела у существующих решений, фраза "we present X", вклад. У 9 статей из 13 обзор аналогов живёт здесь.
3. System Overview / Architecture / Framework, 35-55%. Подразделы оформлены жирным вводным словом в начале абзаца (run-in heading), что экономит строки.
4. Demonstration / Use Cases / Evaluation, 15-35%. Сквозной сценарий от запроса пользователя до результата.
5. Conclusion, 5-12%, два-пять предложений, часто с планами.
6. Страница 3: ссылки, иногда благодарности (Wikatoni, KnowThyself, GenMatLab поставили благодарности на третью страницу).

Отклонения, которые прошли рецензию: нет заключения (CausalPulse), отдельный раздел Related Work (DFAgent, ToolSmith), отдельный раздел вклада (ToolSmith), раздел Discussion с ограничениями (Trajectory Explorer).

Первая страница почти всегда несёт рисунок с архитектурой в правой колонке или на всю ширину (DFAgent, Wikatoni, CausalPulse, OrcheCause, KnowThyself, Agentic DT, Trajectory Explorer). Площадь рисунков я не измерял.

### 3.2 Как позиционируют вклад

- Формула "We present X, a system that ..." в аннотации и повтор в конце введения. Встречается у всех 13.
- Три пункта вклада. Варианты оформления: "(i) ... (ii) ... (iii)" внутри абзаца (DFAgent, KnowThyself), маркированный список с жирными названиями (OrcheCause), отдельный раздел (ToolSmith).
- Заявка на первенство: "To the best of our knowledge ... the first platform" (GenMatLab), "for the first time" и "the first causal AI agent" (OrcheCause).
- Пробел формулируется как список: "First ... Second ... Third ..." (DFAgent), "Domain Knowledge Gap", "Native testing" (ToolSmith).
- Открытые артефакты как часть вклада: модель и данные (Wikatoni), код (KnowThyself, KnowPilot), живой сайт (AutoMV, SciSpace).
- Опора на стандарты как довод расширяемости: MCP, A2A, LangGraph (CausalPulse, DFAgent).
- Идея переиспользования уже занята двумя работами AAAI-26: DFAgent ("agents not only execute tasks but also forge reusable tools that evolve into a shared catalog") и KnowPilot ("reusable knowledge assets"). Плюс ToolSmith про проверку сгенерированных инструментов. Это наши ближайшие соседи, на них нужно сослаться и показать отличие.

### 3.3 Какой уровень оценки достаточен

- 7 из 13 статей приняты без единого числа (DFAgent, ToolSmith, GenMatLab, KnowPilot, Agentic DT, Trajectory Explorer, KnowThyself). Им хватило схемы и сценария.
- 2 из 13 дают таблицу с метриками (Wikatoni, OrcheCause). У обеих числа занимают 15-18% текста и вынесены в аннотацию или в демо-раздел.
- 1 статья заявляет превосходство над базовыми методами без чисел в теле (CausalPulse). Приём рискованный.
- MANDREL подтверждает корректность воспроизведением известного результата. SciSpace опирается на число пользователей.
- Пользовательских исследований в выборке нет.
- Вывод: для демо-трека достаточно одного сквозного сценария с конкретными входом и выходом. Небольшая таблица или два-три числа выделяют статью на фоне соседей. Критерии вызова AAAI-27 про числа не говорят, они говорят про ясность, значимость, релевантность и способность вовлечь аудиторию.

### 3.4 Стилистические конвенции

- Заголовок: "Имя: описательная фраза" у 11 из 13. Имя системы короткое и произносимое. В описательной части стоит тип системы ("An Agentic AI System for ...", "A Multi-Agent Framework for ...", "A Generative Platform for ...") или формула "From X to Y" (DFAgent, OrcheCause).
- Аннотация: один абзац, 85-160 слов. Схема: проблема (1-2 предложения), "We present X", механизм (2-3 предложения), результат или значимость.
- Ссылки на видео, код, данные: строкой после аннотации ("Video — URL", "Code — URL", "Demo Video — URL"), что соответствует окружению `links` из AuthorKit. Второй вариант: сноска на первой странице.
- Подзаголовки внутри раздела системы: жирное вводное слово в начале абзаца.
- Маркированные списки используются для перечня инструментов и компонентов (Agentic DT, OrcheCause). Это экономит место.
- Ссылок: от 6 до 25, медиана около 11. Страница ссылок редко заполнена целиком.
- Ограничения упомянуты в 2 статьях из 13, оба раза одной-двумя фразами в заключении или Discussion.
- Названы конкретные технологии и модели (LangGraph, Streamlit, FastAPI, Gemma3-27B, llama-3.1-8b), что отвечает требованию "technical details".

### 3.5 Рекомендации для нашей статьи

Рабочая позиция: автономный мультиагентный со-учёный, который решает научно-инженерную задачу и оставляет после себя переиспользуемые артефакты (MCP-серверы в открытом каталоге Docker Hub, экспорт сеансов, граф исследования). Кейс: рецептуры шинных резин.

Рекомендации:

1. Заголовок по схеме "Имя: тип системы + отличительный признак". Пример: "CoScientist: A Multi-Agent Co-Scientist That Leaves Reusable MCP Tools Behind". Имя и формулировку нужно выбрать авторам.
2. В аннотации дать 2-3 числа: сколько репозиториев превращено в MCP-серверы, сколько инструментов в каталоге, итог кейса по резинам. Числа брать только из проверенных прогонов.
3. Отличие от DFAgent, ToolSmith, KnowPilot сформулировать одной фразой. Возможная линия: у них инструменты рождаются из диалогов с данными или из спецификаций API внутри предприятия, у нас из научных репозиториев, с проверкой и публикацией в открытый каталог контейнеров, откуда их берёт любой следующий агент. Сослаться также на LATM (Cai et al. 2024) и на работы про AI co-scientist.
4. Related work сделать отдельным коротким абзацем в конце введения или мини-разделом на 90-120 слов. Вызов AAAI-27 прямо требует "discuss related work", у DFAgent и ToolSmith отдельный раздел прошёл.
5. Один рисунок на всю ширину на первой или второй странице: слева архитектура (оркестратор, агенты, конвейер repo→MCP, каталог), справа скриншот интерфейса с кейсом. Составной рисунок по образцу CausalPulse (a, b, c).
6. Одна компактная таблица на 4-6 строк: артефакты кейса или результаты по репозиториям. Таблица отличит нас от семи статей без чисел.
7. Раздел "Demonstration" писать как сценарий для посетителя стенда: что он вводит, что видит за 3-5 минут, что может потрогать (каталог на Docker Hub, Pull & start, граф исследования, экспорт сеанса). Это прямо работает на критерий "ability to engage audiences".
8. Строка ссылок после аннотации через `\begin{links}`: Video, Code, Hub. При double-blind ссылки нужно обезличить, поэтому при открытом Docker Hub и GitHub проще выбрать single-blind, который вызов разрешает.
9. Одна-две фразы про ограничения в заключении: стоимость и время прогона, зависимость от качества исходного репозитория, проверка инструментов на примерах авторов репозитория.
10. Видео до 5 минут загрузить в OpenReview как supplementary. В тексте на него сослаться.

Предлагаемый план с бюджетом слов (цель: около 1150 слов текста, 1 составной рисунок, 1 таблица, 12-18 ссылок):

| Раздел | Слов | Содержание |
|---|---|---|
| Abstract | 120-140 | проблема, "We present X", механизм, артефакты, 2-3 числа, кейс |
| Links | 1 строка | Video, Code, Hub |
| Introduction | 230-260 | боль: результаты агентных прогонов одноразовые; три пробела; "We present"; вклад (i)-(iii) внутри абзаца |
| Related Work (абзац или мини-раздел) | 90-120 | со-учёные на LLM, создание инструментов (LATM, ToolSmith, DFAgent), MCP; одно предложение об отличии |
| System Overview | 330-380 | 4 абзаца с жирными вводными: Orchestration, Repo-to-MCP pipeline, Validation and hub, Session export and research graph; конкретные технологии |
| Case Study: Tyre Rubber Compounds | 200-240 | задача, какие инструменты собраны и переиспользованы, итог, таблица |
| Demonstration | 90-110 | сценарий стенда, что интерактивно, что останется посетителю |
| Conclusion and Limitations | 60-80 | итог, 1-2 ограничения, планы |
| References | стр. 3 | 12-18 записей, можно добавить Acknowledgments |

Вклад (i)-(iii) лучше писать внутри абзаца: маркированный список из трёх пунктов стоит 6-8 строк колонки.

### 3.6 Ловушки

- Превышение объёма. Правило AAAI-27: на третьей странице только ссылки. Текст, рисунок или таблица на третьей странице ведут к отказу без рецензии (последствие не проверено, правило проверено). Благодарности на третьей странице встречаются в сборниках AAAI-26, но это camera-ready: для подачи разрешение не проверено.
- Нарушения стиля AAAI: `hyperref`, `geometry`, `float`, `titlesec`, изменение полей и кегля, `\vspace` для сжатия. Стиль это запрещает.
- Заявка на превосходство без чисел (как у CausalPulse). Рецензент может спросить, где результаты.
- Слова "first" и "novel" при наличии DFAgent, ToolSmith и KnowPilot. Формулировать первенство можно только в узкой, проверяемой рамке.
- Раскрытие авторов при double-blind: ссылки на GitHub, Docker Hub, имя организации на скриншотах, метаданные PDF, самоцитирование.
- Нечитаемый скриншот. При ширине колонки 3.3 дюйма мелкий интерфейс превращается в серое пятно. Нужен обрезанный фрагмент с крупным шрифтом или рисунок на всю ширину.
- Статья как рекламный текст без технических деталей. Вызов требует "technical details", принятые статьи называют модели, фреймворки, протоколы.
- Отсутствие сквозного сценария. У всех принятых статей без чисел есть конкретный пример запроса и результата.
- Отсутствие видео. Вызов называет видео сильно предпочтительным вариантом.
- Ссылки, которые умрут к февралю (tinyurl, временные стенды). Лучше постоянный адрес.
- Очное участие обязательно: один автор должен зарегистрироваться и приехать в Монреаль.

---

## 4. Что осталось непроверенным

- Площадь рисунков и точные доли разделов: оценки по объёму текста.
- Полные тексты AutoMV, MANDREL, SciSpace Copilot прочитаны частично.
- Число ссылок у OrcheCause, KnowPilot, MANDREL, SciSpace: оценка, у AutoMV не подсчитано.
- Правила демо-трека AAAI-24, 25, 26 отдельно не открывались. Совпадение формата (2 страницы + ссылки) выведено из того, что все 13 статей занимают по 3 страницы.
- Процент принятия в демо-трек не найден.
- arXiv-версии найдены только для KnowThyself (arXiv:2511.03948, по данным поиска в ней 5 страниц и 1 рисунок, то есть она длиннее версии в сборнике).
