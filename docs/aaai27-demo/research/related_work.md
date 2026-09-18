# Related work для демо-статьи AAAI-27 (CoScientist + Alembic)

Собрано 17 сентября 2026 года. Продолжает обзор `papers/aaai27-main-draft/research/prior_work.md`.
BibTeX лежит рядом: `related_work.bib`.

Пометки в таблицах:

- **[V]** факт проверен в этой сессии по статье, arXiv, Crossref или README репозитория.
- **[U]** факт взят из памяти или из пересказа поисковика, по первоисточнику в этой сессии проверить не удалось.

Метаданные (авторы, журнал, год, DOI) проверены через arXiv API и Crossref для всех записей, кроме помеченных в разделе 6.

## 0. Что изменилось с прошлого обзора

Прошлый обзор устарел в четырёх местах. Эти правки нужно перенести и в `references.bib` основной статьи.

1. **Paper2Agent вышел в Nature 16 сентября 2026 года** (DOI 10.1038/s41586-026-11044-y, название «Reimagining research papers as interactive and reliable AI agents»). Авторов пять: Miao, Davis, Zhang, Pritchard, Zou. В старом bib указаны только Miao и Zou, это ошибка.
2. **Google AI co-scientist вышел в Nature** (том 655, с. 487-496, 19 мая 2026, DOI 10.1038/s41586-026-10644-y) под названием «Accelerating scientific discovery with Co-Scientist». Название совпадает с нашим почти дословно, в тексте стоит писать «Co-Scientist (Google)».
3. **AI Scientist (Sakana) вышел в Nature** (том 651, с. 914-919, 25 марта 2026, DOI 10.1038/s41586-026-10265-5, «Towards end-to-end automation of AI research»).
4. Новые места публикации: Code2MCP принят на KDD 2026 (с. 3835-3846); Agent Laboratory вышел в Findings of EMNLP 2025; AI-Researcher и RepoMaster вышли на NeurIPS 2025; LLaMP вышел на EMNLP 2025 (main); ToolMaker имеет страницы в ACL 2025 (26092-26130). ToolUniverse сменил название на «ToolUniverse: An open platform for democratizing AI scientists» и вырос до 2700+ инструментов (версия v3 на arXiv).

Ещё одно наблюдение для позиционирования. В 2026 году появилась отдельная линия работ про артефакты агентного исследования: Agent-Native Research Artifacts (arXiv 2604.24658), ScienceClaw + Infinite (2603.14312), El Agente Gráfico (2602.17902), EviGraph (2608.04738). Тезис «после прогона остаются артефакты, включая неудачные ветки» у нас уже не уникален сам по себе. Уникальной остаётся связка: артефактом служит работающий контейнер с инструментом в публичном каталоге.

## 1. Сравнительная таблица

### 1A. AI-scientist и co-scientist системы

| System | Task-solving approach | Tools: fixed or grown | Artifacts left after a run | Reusable by others? | Open? |
|---|---|---|---|---|---|
| Co-Scientist (Google), Gottweis et al., Nature 2026 | Multi-agent generate, critique, refine loop with a tournament that ranks hypotheses; asynchronous task framework for test-time compute [V] | Fixed (web search and specialised models); runs no experiments itself [V] | Research overview and ranked hypotheses or proposals [V] | Text only; wet-lab validation done by human partners [V] | Closed; access through a tester programme [U] |
| The AI Scientist v1, Lu et al. 2024 / Nature 2026 | Idea generation inside a code template, experiments edited by a coding assistant, LaTeX write-up, LLM reviewer [V] | No tool library; coder writes experiment code per idea [V] | Per-idea folder: paper PDF, experiment code, run data and logs, `review.json` [V] | Code and logs can be rerun by hand; nothing is packaged as a tool | Source-available under a RAIL-derived licence [V] |
| The AI Scientist v2, Yamada et al. 2025 | Agentic tree search over experiment nodes, template-free, VLM feedback on figures [V] | No tool library | `experiments/<timestamp_idea>/`: paper PDF, logs, tree visualisation HTML, idea JSON [V] | Same as v1; sandboxing left to the user [V] | Source-available, same licence [V] |
| Agent Laboratory, Schmidgall et al., Findings EMNLP 2025 | Three phases (literature review, experimentation, report) with role agents and optional human feedback [V] | No tool library; code written per task | Report, LaTeX source, experiment code, state checkpoints (`state_saves`) that allow resuming [V] | Checkpoints resume the same run; AgentRxiv shares reports between agent labs [V] | MIT [V] |
| AI-Researcher, Tang et al., NeurIPS 2025 | Literature review and idea, algorithm implementation with iterative refinement, paper writing [V] | No tool library | Manuscript, code implementation, experiment results; runs inside Docker [V] | Code and paper; no tool packaging | Open on GitHub; licence not confirmed [U] |
| Coscientist, Boiko et al., Nature 2023 | GPT-4 planner with modules for web search, documentation search, code execution and robotic lab automation [V] | Fixed small module set [V] | Experimental data and run transcripts in the SI repository [V] | Data only; full system withheld, simplified example released [V] | Partial; Apache 2.0 with Commons Clause [V] |
| ChemCrow, Bran et al., Nat. Mach. Intell. 2024 | ReAct-style LLM agent over expert-designed chemistry tools [V] | Fixed: 18 tools in the paper; public package has fewer because of API restrictions [V] | Agent answer and trace; runs of the paper published in a separate repo [V] | Tools reusable as a Python package | MIT (reduced tool set) [V] |
| Virtual Lab, Swanson et al., Nature 2025 | PI agent and specialist agents hold team and individual meetings; humans give the agenda; agents write scripts for ESM, AlphaFold-Multimer, Rosetta [V] | Fixed per project; pipeline scripted during meetings | Meeting discussions and generated pipeline scripts in the repo [U for exact files] | Nanobody pipeline can be rerun from the notebook [V] | MIT [V] |
| Robin, Ghareeb et al. 2025 | Orchestrates literature agents (Crow, Falcon) and a data-analysis agent (Finch) in a hypothesis, experiment, analysis loop; lab work done by humans [V] | Fixed agents on the Edison/FutureHouse platform [V] | Timestamped folder: hypothesis reports, literature reviews, pairwise ranking CSVs, summaries, optional analysis output [V] | Text and CSV outputs; analysis part needs platform access [V] | Apache 2.0, platform API required [V] |
| Kosmos, Mitchener et al. 2025 | Structured world model shared by parallel data-analysis and literature agents; up to 12 h, about 200 agent rollouts, about 42,000 lines of code, about 1,500 papers per run [V] | Fixed agent set; code written per analysis | Report in which every statement cites code or primary literature; 79.4% of statements judged accurate [V] | Report is auditable on the platform | Commercial platform (credits) [V]; a self-hosted open implementation is mentioned in search results [U] |
| Biomni, Huang et al., bioRxiv 2025 | Generalist agent: retrieval-augmented planning plus code execution over a unified biomedical environment [V] | Large curated environment (tools, databases, software, about 11 GB data lake); users can attach custom MCP servers and know-how documents [V] | Conversation history with code and execution trace, exportable as PDF [V] | Environment is shared by all users; a run adds nothing to it | Apache 2.0, some bundled tools with stricter licences [V] |
| ToolUniverse, Gao et al. 2025 | Platform for building AI scientists: Tool Finder, Tool Caller, Tool Composer; any LLM connects through MCP [V] | Grown by the community: 2,700+ tools (v3); Tool Discoverer generates a tool from a text description; remote tools register over MCP [V] | For a generated tool: JSON config, source file, dependency info [V] | Yes, after maintainer review (tests, expert check of traces, quality thresholds); a run adds nothing automatically [V] | Apache 2.0 [V] |
| Denario, Villaescusa-Navarro et al. 2025 | Modules for idea, methods, results, paper; AG2 and LangGraph agents with cmbagent as analysis backend [V] | No tool library; code written per project | Project folder: input files, `idea.md`, `methods.md`, `results.md`, plots, LaTeX and PDF paper [V] | Project folder can be continued module by module [V] | GPLv3, Docker image available [V] |
| InternAgent (NovelSeek), 2025 | Closed loop from idea generation to experiment execution and feedback across 12 research tasks [V] | No tool library; evolves baseline code | Ideas JSON, experiment code and logs under `results/` and `logs/` [V] | Idea files can seed a new run (`--skip_idea_generation`) [V] | Open on GitHub; licence not confirmed [U] |
| ARA, Liu et al. 2026 (arXiv 2604.24658) | Packaging format: scientific logic, executable code, exploration graph with failed branches, evidence grounding [V] | n/a | The artifact itself; reproduction success 57.4% to 64.4% with ARA [V] | Yes, designed for agent reuse [V] | Preprint [V] |
| ScienceClaw + Infinite, Wang et al. 2026 (arXiv 2603.14312) | Decentralised agents chain skills and exchange immutable artifacts [V] | Extensible registry of 300+ skills [V] | Artifact DAG with typed metadata and parent lineage [V] | Yes, shared artifact index [V] | Preprint; code status not checked [U] |
| El Agente Gráfico, Bai et al. 2026 (arXiv 2602.17902) | LLM decisions embedded in typed execution graphs for chemistry workflows [V] | Fixed typed operations | Provenance and typed state that persist across sessions [V] | Within the runtime [U] | Preprint [V] |
| **CoScientist + Alembic (ours)** | Multi-agent system with a typed research graph, literature search, coder agent; Alembic converts repositories to MCP servers on demand | Grown during the run: local lookup, then hub lookup, then build from a repository | Validated MCP servers as container images in a public Docker Hub namespace, `validation.json` per server, exported session, research graph | Yes: `docker pull` and start; session import | Open source |

### 1B. Инженерные агентные системы

| System | Task-solving approach | Tools: fixed or grown | Artifacts left after a run | Reusable by others? | Open? |
|---|---|---|---|---|---|
| MechAgents, Ni & Buehler, Extreme Mech. Lett. 2024 | Agent teams (planner, formulator, coder, executor, critic) write, run and self-correct FEniCS finite-element code for elasticity problems [V] | No library; code per problem | FE code and solution fields [U for file layout] | Code reusable by hand | Code status not checked [U] |
| ChatMOF, Kang & Kim, Nat. Commun. 2024 | Agent plans, toolkits execute, evaluator formats the answer; searcher, predictor (ML), generator (genetic algorithm) [V] | Fixed three toolkits [V] | Answer with predicted values or generated MOF structures [V] | Package reusable; a query leaves no tool | MIT [V] |
| LLaMP, Chiang et al., EMNLP 2025 | Hierarchical ReAct agents query the Materials Project API and can launch atomistic simulations (ASE, atomate2, MACE) [V] | Fixed API wrappers [V] | Grounded answer, retrieved records, optional simulation output [V] | Package and Docker web app [V] | BSD-style (LBNL) [V] |
| MatAgent, Takahara et al., Cell Rep. Phys. Sci. 2025 | LLM proposes compositions, diffusion model estimates crystal structure, property predictor gives feedback; memory, periodic table and knowledge base as cognitive tools [V] | Fixed [V] | Candidate compositions with structures and predicted properties [V] | Code release not confirmed [U] | [U] |
| MatSciAgent (modular agents), Chaudhari et al., Commun. Mater. 2026 | Master agent routes to task agents: data retrieval, continuum simulation, crystal generation, molecular dynamics [U: from search summary] | Fixed | Simulation results and structures [U] | [U] | [U] |
| Polymer-Agent, Nigam et al., JCIM 2026 | LLM agent with tools for polymer property prediction, property-guided generation and structure modification [U: from search summary] | Fixed | Candidate polymer structures with predicted properties [U] | [U] | [U] |
| S1-MatAgent, Wang et al. 2025 (arXiv 2509.14542) | Planner-driven multi-agent system for material discovery [V title only] | [U] | [U] | [U] | [U] |
| ML for rubber compounds (Wan 2024a,b; Hu 2024; Deng 2024; Roy Choudhury 2025) | Supervised models from recipe and process to properties; no agents (see section 5) | n/a | Trained model, sometimes code and data | Wan 2024 has open code (per project plan) [U]; Hu 2024 has no open code (per project plan) [U] | Mixed |

Наблюдение по блоку B. Среди найденных агентных систем для материалов нет ни одной про рецептуры резины или шинные смеси. Поиск по arXiv, Crossref и вебу дал только классические ML-работы. Формулировка для статьи: «we found no published agent system for rubber compound formulation». Утверждать полное отсутствие таких систем нельзя.

### 1C. Repo-to-tool и системы, создающие инструменты

| System | Task-solving approach | Tools: fixed or grown | Artifacts left after a run | Reusable by others? | Open? |
|---|---|---|---|---|---|
| ToolMaker, Wölflein et al., ACL 2025 | Input: GitHub URL, task description, argument list with an example call. Agent installs dependencies, writes the tool, fixes it in a closed loop. 80% of 15 tasks, 100+ unit tests [V] | Grown, one tool per task definition | Environment definition (bash or Dockerfile lines) and a Python function; Docker checkpointing used for resets [V] | Portable by hand; paper describes no registry [V] | Open source [V] |
| Code2MCP, Ouyang et al., KDD 2026 | Seven agents: download, environment, analysis, generation, Run-Review-Fix loop, finalisation. Success means server starts and at least 3 functions respond. 32 of 50 repos (64%) [V] | Grown, one server per repository | `mcp_service.py`, `adapter.py`, tests, merge-ready pull request [V] | Through a pull request to the source repo; no hub described [V] | Code link in paper [V] |
| ToolRosella, Di et al. 2026 | Tool-search agent finds repos on GitHub, MCP-construction agent converts them in 8 stages with a repair loop, planning agent calls the tools. 75 of 122 repos (61.5%), 1,580 tools, 84.0% downstream task success [V] | Grown on demand, search included [V] | Standardised repositories with MCP services, published on Hugging Face and GitHub [V] | Yes, as converted repositories [V]; container images not mentioned [U] | Open [V] |
| Paper2Agent, Miao et al., Nature 2026 | Input: paper and its repo. Coding agent (Claude Code or Codex) extracts tools from tutorials, tests them in a loop, drops functions that keep failing [V] | Grown, one MCP server per paper | MCP server with tools, resources, prompts; tested environment spec; test suite; `USAGE.md`; ZIP bundle. AlphaGenome: 22 tools in about 3 h, 100% on 30 queries [V] | Yes: several servers hosted on Hugging Face Spaces; several MCPs can be attached to one chat agent. No central catalogue described [V] | MIT [V] |
| RepoMaster, Wang et al., NeurIPS 2025 | Builds call graphs, dependency graphs and code trees of a repo, feeds the core parts to the LLM, solves the task with the repo code. GitTaskBench pass 40.7% to 62.9% [V] | Uses repos directly; no tool is produced | Task output only [V] | No reusable tool | Open [V] |
| AutoMCP, Mastouri et al. 2025 | Compiles OpenAPI specifications into MCP servers; 80 real APIs, 76% of tools work out of the box, 94.2% after repair [V] | Grown from REST specs; scientific code repositories are out of scope | MCP server code [V] | Yes, as code | Open [U] |
| LATM, Cai et al., ICLR 2024 | Strong LLM writes a Python function as a tool, a weaker LLM reuses it on later instances [V metadata; method from prior review] | Grown, cached functions | Python functions | Inside one deployment | Open [V] |
| CRAFT, Yuan et al., ICLR 2024 | Builds a toolset of abstracted, validated code snippets and retrieves from it at inference [V metadata; method from prior review] | Grown offline | Tool library (code) | Yes, as a code library | Open [V] |
| BioContextAI, Kuehl et al., Nat. Biotechnol. 2025 | Community registry of biomedical MCP servers plus a knowledgebase MCP [V] | Grown by community submissions; servers written by people | `meta.yaml` per server, validated against a schema; submitters declare that tools were tested [V] | Yes. Registry stores metadata that points to repositories; it hosts no containers [V] | BSD-3-Clause registry, OSI licence required for servers [V] |
| ToolUniverse | see 1A | | | | |

## 2. Позиционирование (без завышенных заявлений)

**Что уже сделано другими.**

- Преобразование репозитория в проверенный MCP-сервер есть у Paper2Agent, Code2MCP и ToolRosella. ToolMaker делает то же для одной функции. Новизну на слове «конвертируем репозитории» строить нельзя.
- Поиск репозиториев под задачу с автоматической конверсией и последующим вызовом инструментов есть у ToolRosella (связка tool-search, MCP-construction, planning). Заявление «впервые агент сам находит и конвертирует репозитории» будет ложным.
- Общие каталоги инструментов для науки есть: ToolUniverse (2700+ инструментов, рецензируемый вклад сообщества), BioContextAI (реестр метаданных MCP-серверов), Hugging Face Spaces у Paper2Agent, Hugging Face у ToolRosella. Biomni принимает сторонние MCP-серверы.
- Сохранение хода исследования с неудачными ветками описано в ARA (exploration graph), в ScienceClaw + Infinite (DAG артефактов), в El Agente Gráfico (типизированные графы исполнения с сохранением между сессиями). Возобновление прогона есть у Agent Laboratory (checkpoints) и Denario (папка проекта по модулям).
- Отчёт с привязкой каждого утверждения к коду или источнику есть у Kosmos.

**Где CoScientist + Alembic отличается.** Формулировать как сочетание свойств, каждое из которых проверяемо:

1. Инструменты создаются внутри исследовательского прогона. Агент идёт по каскаду: локальный сервер, затем хаб, затем сборка из репозитория. У Paper2Agent, Code2MCP и ToolMaker конверсию запускает человек для выбранного репозитория. У ToolRosella каскад похожий, но исследовательского цикла (гипотезы, литература, граф) вокруг него нет.
2. Артефакт конверсии: контейнерный образ с рабочим окружением в публичном пространстве Docker Hub. Получатель выполняет `docker pull` и запускает сервер без повторной сборки окружения. У остальных систем артефактом служит код, Dockerfile, pull request, ZIP или запись в реестре метаданных. Сборка окружения научного репозитория остаётся самой хрупкой частью воспроизведения (см. SUPER, CORE-Bench, ResearchEnvBench в старом bib), поэтому готовый образ даёт практическую разницу. В статье это подать как инженерное решение.
3. Каталог пополняется побочным продуктом работы агента. В ToolUniverse и BioContextAI инструмент попадает в общий набор через заявку и проверку людьми. У нас загрузка идёт автоматически с защитными проверками либо вручную. Оборотная сторона: качество каталога держится на автоматической валидации. Наш собственный аудит показал слабые места (пустая проверка на заглушках, неполные конверсии), и рецензенты EMNLP это уже отмечали. В демо-статье нужно прямо написать, что именно проверяет `validation.json`.
4. После прогона остаются три связанных артефакта: серверы в хабе, экспортированная сессия, типизированный граф исследования. Отрицательный результат (часть репозиториев не запустилась, готового метода расчёта рецептуры нет) сохраняется вместе с работающими инструментами, и другая группа может продолжить с этого места. Ближайшие аналоги по идее: ARA и ScienceClaw. У них артефактом служат данные и код, у нас к ним добавлены работающие серверы.
5. Инженерный кейс. В блоке B нет агентных систем для рецептур резины. Кейс с шинными смесями показывает систему на задаче, где открытый код редкий и наполовину заброшенный, и где честный итог может быть отрицательным.

**Чего заявлять нельзя.**

- «Первый каталог научных MCP-инструментов» (есть ToolUniverse, BioContextAI).
- «Первая система, которая выращивает инструменты по ходу работы» (ToolRosella, Tool Discoverer в ToolUniverse, LATM, CRAFT, Voyager).
- Превосходство по качеству конверсии без сравнения на одной модели. В статье опираться только на прогон TM-Bench на glm-5.2, описанный в `discussion/task.md`.
- «Воспроизводимость» в сильном смысле. Точнее писать «reuse and continuation»: повторный вызов тех же инструментов в том же окружении. Недетерминированность LLM-части прогона остаётся.
- Сравнение с Paper2Agent нужно писать аккуратно: это статья в Nature от 16.09.2026, рецензенты её знают. Отличие: у Paper2Agent вход состоит из статьи и репозитория с обучающими примерами, проверка идёт по воспроизведению этих примеров. Alembic работает с произвольным репозиторием и запускается агентом изнутри задачи.

## 3. Черновик абзаца Related Work (English, около 150 слов)

> **Related work.** AI-scientist systems automate the path from idea to manuscript. The AI Scientist \cite{lu2026aiscientist,yamada2025aiscientistv2}, Agent Laboratory \cite{schmidgall2025agentlab}, AI-Researcher \cite{tang2025airesearcher} and Denario \cite{villaescusa2025denario} end a run with a paper, code and logs. Co-Scientist \cite{gottweis2026coscientist} and Robin \cite{ghareeb2025robin} return ranked hypotheses, and Kosmos \cite{mitchener2025kosmos} returns a report whose statements cite code or literature. Domain agents such as ChemCrow \cite{bran2024chemcrow}, ChatMOF \cite{kang2024chatmof}, LLaMP \cite{chiang2025llamp} and MechAgents \cite{ni2024mechagents} call tools fixed by their developers. Biomni \cite{huang2025biomni}, ToolUniverse \cite{gao2025tooluniverse} and BioContextAI \cite{kuehl2025biocontextai} maintain curated tool collections that grow through human review. Converters turn a repository into a validated tool or MCP server \cite{wolflein2025toolmaker,ouyang2026code2mcp,di2026toolrosella,miao2026paper2agent}; their output is code or a hosted endpoint. CoScientist joins these lines: its agents convert the repositories a task needs during the run, and the validated servers are published as container images in a public catalogue. The images, the exported session and the typed research graph \cite{typedgraph_TODO} let another group continue the study after a negative result. Our case study is tyre compound design, where ML predictors exist \cite{wan2024coco,hu2024jmi} and we found no agent system.

Длина: около 170 слов с командами цитирования. Для сокращения до 150 убрать Denario, LLaMP и BioContextAI.

Запасной вариант последнего предложения, если места мало: «We demonstrate it on tyre rubber compound design \cite{wan2024coco,hu2024jmi}.»

## 4. Наши предыдущие работы (блок D)

| Работа | Статус проверки | Данные |
|---|---|---|
| MADD: Multi-Agent Drug Discovery Orchestra | [V] Crossref + arXiv | Solovev G. V., Zhidkovskaya A. B., Orlova A., Gubina N., Vepreva A., Golovinskii R., Tonkii I., Dubrovsky I., Gurev I., Gilemkhanov D., Chistiakov D., Aliev T. A., Poddiakov I., Zubkova G., Skorb E. V., Vinogradov V., Boukhanovsky A., Nikitin N., Dmitrenko A., Kalyuzhnaya A., Savchenko A. Findings of ACL: EMNLP 2025, с. 6956-6998. DOI 10.18653/v1/2025.findings-emnlp.367. arXiv 2511.08217 |
| ChemCoScientist: LLM-Based Multi-Agent Assistant for Automated Solving of Chemical Tasks Using Data-Driven Tools | [V] Crossref + OpenAlex | Solovev G. V., Gurev I., Vepreva A., Dubrovsky I., Zhidkovskaya A., Fatkhiev K., Lutsenko E., Orlova A., Gubina N., Nikitin N. O., Dmitrenko A., Kalyuzhnaya A. V. 2025 IEEE International Conference on Data Mining Workshops (ICDMW), с. 2569-2572. DOI 10.1109/ICDMW69685.2025.00325. Версии на arXiv не нашлось |
| A Typed Research Graph for Verifiable Multi-Agent Scientific Workflows | **[U] не найдена** | Поиск по arXiv API, Crossref, OpenAlex, вебу и локальным репозиториям ничего не дал. Вероятно, статья на рецензии или ещё не выложена. Авторов, место и год нужно взять у Глеба или Николая Никитина. В bib стоит заглушка `typedgraph_TODO` |

Попутно найдено в профиле Глеба Соловьёва на alphaXiv: «MedCoScientist: A Multi-Agent LLM Framework for Clinical Decision Support» (AAMAS 2026) [U, по первоисточнику не проверено]. Может пригодиться как пример переноса CoScientist в другую область.

## 5. ML для резиновых смесей (блок E)

Все DOI проверены через Crossref. Содержательные описания первых шести работ взяты из `tyre-case/project_plan_gdoc.txt` и в этой сессии по текстам статей не перепроверялись [U].

| Key | Работа | Что делает |
|---|---|---|
| `wan2024coco` | Wan, Chen, Feng, Sun. Composites Communications 51, 102072 (2024) | Прогноз свойств резины с техуглеродом по параметрам процесса; добавление микроструктурных признаков поднимает R² с 0.763 до 0.878; multi-task DNN; по плану проекта код открыт |
| `wan2024cjps` | Wan и др. (12 авторов). Chinese J. Polymer Science 42(12), 2038-2047 (2024) | Влияние параметров смешения на механические свойства, 215 точек |
| `hu2024jmi` | Hu, Liu, Chen, Zhan, Li, Cui, Liu. J. Materials Informatics 4(3) (2024), DOI 10.20517/jmi.2024.11 | Малые данные по натуральному каучуку (86 точек): VAE-аугментация, разметка кригингом, градиентный бустинг, проверка молекулярной динамикой; по плану проекта открытого кода нет |
| `roychoudhury2025jrr` | Roy Choudhury, Senthilkumar, Ebin, Thangarasu. J. Rubber Research 28(5), 705-718 (2025) | RF, DT, XGBoost, ANN на рецептурах NR с экспериментальной проверкой; XGBoost R² до 0.96. В плане проекта стоит 2026 год, по Crossref выпуск датирован ноябрём 2025 |
| `kuenneth2023polybert` | Kuenneth, Ramprasad. Nature Communications 14, 4099 (2023) | polyBERT: химическая языковая модель для полимеров, 29 свойств |
| `queen2023polymergnn` | Queen и др. npj Computational Materials 9, 90 (2023) | PolymerGNN: многозадачная GNN для Tg и IV полиэфиров |
| `deng2024aichem` | Deng, Zhao, Zheng, Yin, Huan, Liu, Wang. Artificial Intelligence Chemistry 2(1), 100054 (2024); есть corrigendum 2025 | ML по существующим базам рецептур: восстановление пропусков, поиск ошибочных записей, прогноз свойств [U, по аннотации из поиска] |
| `burkhart2023tread` | Burkhart и др. Tire Science and Technology 51(2), 114-131 (2023) | Обзорная работа Goodyear и Northwestern о многомасштабном data-driven подходе к протекторным смесям; ближайшее к обзору по теме. Есть версия-глава 2020 года в Springer Series in Materials Science [V метаданные] |
| `zhang2022mooney`, `zheng2020softsensor` | Polymers 14(5), 1018 (2022); Sensors 20(3), 695 (2020) | Виртуальные датчики вязкости по Муни в процессе смешения |

Отдельного обзора «ML for rubber compounding» в рецензируемом журнале найти не удалось. Работа по обратной задаче (подбор рецептуры под заданные свойства) для шинных смесей с открытым кодом тоже не нашлась. В выдаче есть патент WO2023095008A1 (метод на ML для протекторных смесей) и статья о многокритериальной оптимизации композитов NR в J. Harbin Inst. Technol. 2023, её метаданные не проверены [U]. Для демо-статьи это аргумент в пользу кейса: открытых инструментов мало, и итог прогона честно может быть отрицательным.

## 6. Что осталось непроверенным

- Статья про Typed Research Graph: нет ни одного следа в открытых источниках.
- Режим доступа к Co-Scientist (Google): в аннотации не указан; сведения о программе тестировщиков взяты из памяти.
- Открытая самостоятельная реализация Kosmos: упомянута только в пересказе поисковика.
- Лицензии AI-Researcher и InternAgent: в README не названы.
- Точный состав файлов, которые Virtual Lab и MechAgents оставляют после прогона.
- MatSciAgent, Polymer-Agent, S1-MatAgent: проверены только метаданные, описание метода взято из пересказа поисковика.
- «MatAgent» существует в двух вариантах. Takahara и др. (Cell Rep. Phys. Sci. 2025) проверен и включён в bib. Репозиторий adibgpt/MatAgent ссылается на анонимную подачу ICLR 2025, в bib он не включён.
- RepoMaster: на arXiv 14 авторов, в записи Crossref для NeurIPS 11. В bib стоит список Crossref с пометкой.
- LATM, CRAFT, Voyager: метаданные проверены, описание метода перенесено из прошлого обзора.

## 7. Источники

- arXiv API и страницы: 2502.18864, 2408.06292, 2504.08066, 2501.04227, 2304.05376, 2505.13400, 2509.23426 (v3, HTML), 2505.18705, 2511.02824, 2510.26887, 2505.16938, 2311.08166, 2308.01423, 2401.17244, 2504.00741, 2502.11705 (v2, HTML), 2509.05941 (v4, HTML), 2603.09290 (v5, HTML), 2509.06917 (v2, HTML), 2505.21577, 2507.16044, 2305.17126, 2309.17428, 2511.08217, 2604.24658, 2603.14312, 2602.17902, 2608.04738, 2509.14542.
- Crossref API: все DOI из `related_work.bib`.
- OpenAlex API: ChemCoScientist.
- README репозиториев на GitHub: SakanaAI/AI-Scientist, SakanaAI/AI-Scientist-v2, SamuelSchmidgall/AgentLaboratory, snap-stanford/Biomni, mims-harvard/ToolUniverse, jmiao24/Paper2Agent, Future-House/robin, AstroPilot-AI/Denario, Alpha-Innovator/InternAgent, HKUDS/AI-Researcher, biocontext-ai/registry, zou-group/virtual-lab, ur-whitelab/chemcrow-public, gomesgroup/coscientist, Yeonghun1675/ChatMOF, chiang-yuan/llamp, adibgpt/MatAgent.
- Профиль https://www.alphaxiv.org/@gleb-solovev.
- Сведения о доступе к Kosmos: https://edisonscientific.com/news/announcing-kosmos и выдача поиска (цена 200 долларов за прогон, первые шесть прогонов для академических пользователей бесплатны) [U по первоисточнику].
