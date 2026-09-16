    // =========================================================================
    // i18n – lightweight translation system
    // =========================================================================
    // Текущий язык: 'ru' по умолчанию (или из localStorage).
    // state.js is absent on the standalone pages (graph/builds), so every
    // cross-module reference below is guarded — this file must load alone.
    const I18N_LANG_KEY = (typeof LANG_STORAGE_KEY !== 'undefined') ? LANG_STORAGE_KEY : 'coscientist.lang';
    let currentLang = localStorage.getItem(I18N_LANG_KEY) || 'ru';

    const i18n = {
      // ── Navigation & Sidebar ──
      'nav.agents': { en: 'Agents', ru: 'Агенты' },
      'nav.user': { en: 'User', ru: 'Пользователь' },
      'nav.session': { en: 'Session', ru: 'Сессия' },
      'nav.noUser': { en: 'No user selected', ru: 'Пользователь не выбран' },
      'nav.connected': { en: 'Connected', ru: 'Подключено' },
      'nav.disconnected': { en: 'Disconnected', ru: 'Отключено' },
      'nav.orchestrator': { en: 'ORCHESTRATOR', ru: 'ОРКЕСТРАТОР' },

      // Agent descriptions in side nav
      'agent.OrchestratorAgent.desc': { en: 'Master Orchestrator', ru: 'Главный оркестратор' },
      'agent.PlannerAgent.desc': { en: 'Roadmap Planner', ru: 'Планировщик задач' },
      'agent.ToolsViewer.desc': { en: 'Tools Viewer', ru: 'Просмотр инструментов' },
      'agent.KnowledgeGraph.desc': { en: 'Knowledge Graph', ru: 'Граф знаний' },
      'agent.MCPBuilder.desc': { en: 'MCP Builder', ru: 'Сборщик MCP' },
      'agent.CoderSandbox.desc': { en: 'CoderSandbox', ru: 'Песочница кода' },
      'agent.__settings__.desc': { en: 'Settings', ru: 'Настройки' },

      // Chat controls & Header
      'chat.missionControl': { en: 'Mission Control', ru: 'Центр управления' },
      'chat.online': { en: 'Online', ru: 'Онлайн' },
      'chat.offline': { en: 'Offline', ru: 'Офлайн' },
      'chat.sendQuery': { en: 'Send a query to begin orchestration', ru: 'Отправьте запрос для начала работы' },
      'chat.placeholder': { en: 'Send system command…  (Enter — send, Shift+Enter — new line)', ru: 'Введите запрос… (Enter — отправить, Shift+Enter — новая строка)' },
      'telemetry.header': { en: 'Telemetry Output', ru: 'Лог телеметрии' },
      'usage.header': { en: 'Usage & Cost', ru: 'Использование и стоимость' },

      // ── Activity Rail HUD ──
      'rail.agents': { en: 'Agents', ru: 'Агенты' },
      'rail.tools': { en: 'Tools', ru: 'Инструменты' },
      'rail.standby': { en: 'Standby — awaiting tool invocation', ru: 'Ожидание вызова инструментов…' },
      'rail.noTools': { en: 'No tool calls yet', ru: 'Инструменты ещё не вызывались' },
      'rail.toggle': { en: 'Show/hide agent activity', ru: 'Показать/скрыть активность агентов' },

      // ── Settings modal header ──
      'settings.title': { en: 'Settings', ru: 'Настройки' },
      'settings.subtitle': { en: 'System Configuration', ru: 'Конфигурация системы' },
      'settings.language.label': { en: 'Language (interface and report)', ru: 'Язык (интерфейс и отчёт)' },

      // ── General section ──
      'settings.general': { en: 'General', ru: 'Общие' },
      'settings.general.hint': {
        en: '(Default values are set in .env or settings.py)',
        ru: '(Значения по умолчанию задаются в .env или settings.py)'
      },

      'settings.startMode.label': { en: 'Session Start Mode', ru: 'Режим запуска сессии' },
      'settings.startMode.desc': {
        en: 'Choose which agent starts the session. <strong>PlannerAgent</strong> runs PlannerAgent first, then OrchestratorAgent. <strong>OrchestratorAgent</strong> starts directly with the orchestrator. <strong>Orchestrator as a planner</strong> gives Orchestrator the plan tool and disables PlannerAgent.',
        ru: 'Выберите, какой агент запускает сессию. <strong>PlannerAgent</strong> сначала запускает PlannerAgent, затем OrchestratorAgent. <strong>OrchestratorAgent</strong> запускает оркестратор напрямую. <strong>Orchestrator as a planner</strong> даёт оркестратору инструмент планирования и отключает PlannerAgent.'
      },
      'settings.startMode.planner': { en: 'PlannerAgent', ru: 'PlannerAgent' },
      'settings.startMode.orchestrator': { en: 'OrchestratorAgent', ru: 'OrchestratorAgent' },
      'settings.startMode.orchestratorPlanner': { en: 'Orchestrator as a planner', ru: 'Orchestrator в роли планировщика' },

      'settings.maxRetries.label': { en: 'Max LLM Retries', ru: 'Макс. повторов LLM' },
      'settings.maxRetries.desc': {
        en: 'Number of LLM call retry attempts on transient network or upstream API errors.',
        ru: 'Количество повторных попыток вызова LLM при временных сбоях сети или API.'
      },

      'settings.hitl.label': { en: 'HITL Enabled', ru: 'Включить HITL (подтверждения)' },
      'settings.hitl.desc': {
        en: 'Toggle Human-in-the-Loop approval for dangerous or outward-facing actions.',
        ru: 'Включить подтверждение человеком (Human-in-the-Loop) для опасных или внешних действий.'
      },
      'settings.hitlTimeout.label': { en: 'HITL Auto-Approve Timeout (s)', ru: 'Автоподтверждение HITL (сек)' },
      'settings.hitlTimeout.desc': {
        en: 'Seconds before auto-approving HITL requests (-1 for no timeout / wait for human).',
        ru: 'Секунды до автоподтверждения HITL (-1 — без тайм-аута, ждать человека).'
      },

      // ── HITL research-frame form (rendered at runtime, keyed by currentLang) ──
      'hitl.form.sidebarTitle': { en: 'Research Frame', ru: 'Рамка исследования' },
      'hitl.form.sidebarHint': {
        en: 'Fill in the form in the chat. The agent fills the empty fields itself.',
        ru: 'Заполните форму в чате. Пустые поля агент заполнит сам.'
      },
      'hitl.form.title': { en: 'Research Frame', ru: 'Рамка исследования' },
      'hitl.form.notSet': { en: 'not set', ru: 'не задано' },
      'hitl.form.placeholderFallback': {
        en: 'Leave empty and the agent will fill in a working value',
        ru: 'Оставьте пустым, чтобы агент подставил рабочее значение'
      },
      'hitl.form.save': { en: 'Save Frame', ru: 'Сохранить рамку' },
      'hitl.form.skip': { en: 'Skip (agent decides)', ru: 'Пропустить (агент решит)' },
      'hitl.form.saved': {
        en: '✓ Frame saved ({n} fields set by the operator)',
        ru: '✓ Рамка сохранена ({n} поле(й) заданы оператором)'
      },
      'hitl.form.skipped': {
        en: '→ Frame skipped — the agent will fill in the values',
        ru: '→ Рамка пропущена — агент подставит значения'
      },

      // Internal-loop review request (agent name replaces {agent}).
      'hitl.internalLoop': {
        en: "Agent '{agent}' proposes its result. Please review.",
        ru: "Агент '{agent}' предлагает свой результат. Проверьте его."
      },

      'settings.usePlanner.label': { en: 'Use Planner', ru: 'Использовать планировщик' },
      'settings.usePlanner.note': {
        en: '(disabled when using PlannerAgent mode)',
        ru: '(отключено в режиме PlannerAgent)'
      },
      'settings.usePlanner.desc': {
        en: 'Whether the orchestrator delegates to PlannerAgent for task decomposition.',
        ru: 'Делегирует ли оркестратор декомпозицию задач компоненту PlannerAgent.'
      },

      'settings.contextInit.label': { en: 'Research Frame', ru: 'Рамка исследования' },
      'settings.contextInit.desc': {
        en: 'Draft research frame and seed it into the research graph before the orchestrator runs.',
        ru: 'Формировать фрейм исследования и добавлять его в граф исследований до запуска оркестратора.'
      },

      'settings.useProxy.label': { en: 'Use Corporate Proxy', ru: 'Корпоративный прокси' },
      'settings.useProxy.note': { en: '(set only in env)', ru: '(задаётся в .env)' },
      'settings.useProxy.desc': {
        en: 'Route LLM model calls through corporate proxy (SERVICES__PROXY_URL).',
        ru: 'Маршрутизировать вызовы моделей LLM через корпоративный прокси (SERVICES__PROXY_URL).'
      },

      'settings.opik.label': { en: 'Enable Opik Tracing', ru: 'Включить трассировку Opik' },
      'settings.opik.desc': {
        en: 'Send execution logs and agent traces to your Opik dashboard.',
        ru: 'Отправлять логи выполнения и трассировки агентов в дашборд Opik.'
      },

      'settings.autoNaming.label': { en: 'Auto-name Sessions', ru: 'Авто-наименование сессий' },
      'settings.autoNaming.desc': {
        en: 'Automatically generate session titles based on the first prompt.',
        ru: 'Автоматически генерировать названия сессий на основе первого запроса.'
      },

      'settings.defaultUsername.label': { en: 'Default Username', ru: 'Имя пользователя по умолчанию' },
      'settings.defaultUsername.desc': {
        en: 'Auto-selects user on startup (can also be set via COSCIENTIST_USERNAME in .env).',
        ru: 'Автоматически выбирает пользователя при старте (задаётся также через COSCIENTIST_USERNAME в .env).'
      },
      'settings.defaultUsername.placeholder': {
        en: 'e.g. COSCIENTIST_USERNAME in .env',
        ru: 'например COSCIENTIST_USERNAME в .env'
      },

      // ── Graphs section ──
      'settings.graphs': { en: 'Graphs', ru: 'Графы' },
      'settings.knowledgeGraph.label': { en: 'Knowledge Graph', ru: 'Граф знаний' },
      'settings.knowledgeGraph.desc': {
        en: 'Records the execution graph of every run and lets agents read it (<span class="font-mono">get_graph_history</span>, <span class="font-mono">get_agents_info</span>, <span class="font-mono">search_knowledge_memory</span>). When off, nothing is recorded, the Graph view stays empty, and the tools disappear from every agent and from their prompts.',
        ru: 'Записывает граф выполнения каждого запуска и позволяет агентам читать его (<span class="font-mono">get_graph_history</span>, <span class="font-mono">get_agents_info</span>, <span class="font-mono">search_knowledge_memory</span>). Когда выключен, ничего не записывается, вкладка графа пуста, а инструменты убираются у всех агентов.'
      },

      'settings.researchGraph.label': { en: 'Research Graph', ru: 'Граф исследований' },
      'settings.researchGraph.desc': {
        en: 'The typed research blackboard agents commit findings to (<span class="font-mono">research_commit</span>, <span class="font-mono">research_context_slice</span>, orchestrator triggers). When off, the whole feature — tools and prompt sections — drops out and agents pass context through their answers only.',
        ru: 'Доска исследований, куда агенты записывают результаты (<span class="font-mono">research_commit</span>, <span class="font-mono">research_context_slice</span>, триггеры оркестратора). Когда выключен, инструменты и секции промптов отключаются, контекст передается только в ответах.'
      },

      'settings.graphs.sessionNote': {
        en: 'Applies to new sessions — the agent system is built once per session.',
        ru: 'Применяется к новым сессиям — система агентов инициализируется при создании сессии.'
      },

      'settings.deleteGraph.label': { en: 'Delete Graph Data', ru: 'Удалить данные графов' },
      'settings.deleteGraph.desc': {
        en: 'Wipe what the graphs have recorded. The execution and research graphs belong to the <strong>current session</strong>; the knowledge memory is installation-wide and disappears for every session at once. The research graph and the knowledge memory are archived next to their files first; the execution graph keeps only the agent roster.',
        ru: 'Очистить записанные данными графов. Графы выполнения и исследований относятся к <strong>текущей сессии</strong>; память знаний распространяется на всю систему. Граф исследований и память знаний архивируются; граф выполнения сохраняет только список агентов.'
      },
      'settings.deleteGraph.optExecution': { en: 'Execution (session)', ru: 'Выполнение (сессия)' },
      'settings.deleteGraph.optResearch': { en: 'Research (session)', ru: 'Исследования (сессия)' },
      'settings.deleteGraph.optMemory': { en: 'Knowledge memory (global)', ru: 'Память знаний (глобальная)' },
      'settings.deleteGraph.optAll': { en: 'All of the above', ru: 'Всё вышеперечисленное' },
      'settings.deleteGraph.btn': { en: 'Delete', ru: 'Удалить' },

      'settings.autoClearGraph.label': { en: 'Auto-clear Graph Before Session', ru: 'Автоочистка графов перед сессией' },
      'settings.autoClearGraph.note': { en: '(set only in env)', ru: '(задаётся в .env)' },
      'settings.autoClearGraph.desc': {
        en: 'Automatically clear graph data before each session starts.',
        ru: 'Автоматически очищать данные графов перед началом каждой сессии.'
      },

      // ── PlannerAgent section ──
      'settings.planner.retrieval.label': { en: 'Retrieval Tools', ru: 'Инструменты поиска' },
      'settings.planner.retrieval.desc': {
        en: 'Let the planner search the MCP registry (<span class="font-mono">retrieve_tools</span>, <span class="font-mono">get_server_info</span>) before writing the roadmap. When off, it plans by outcome and never names concrete tools or server ids.',
        ru: 'Разрешить планировщику искать в реестре MCP (<span class="font-mono">retrieve_tools</span>, <span class="font-mono">get_server_info</span>) перед созданием плана. Когда выключено, планирование происходит без указания конкретных инструментов.'
      },

      'settings.planner.graph.label': { en: 'Graph Tools', ru: 'Инструменты графа' },
      'settings.planner.graph.note': { en: '(disabled — Knowledge Graph is off)', ru: '(отключено — Граф знаний выключен)' },
      'settings.planner.graph.desc': {
        en: 'Let the planner read the shared knowledge graph (history, agent roster, knowledge memory) so it does not re-plan finished work.',
        ru: 'Разрешить планировщику читать общий граф знаний (историю, список агентов, память знаний), чтобы не планировать заново выполненную работу.'
      },

      'settings.planner.critic.label': { en: 'Plan Critic', ru: 'Критик плана' },
      'settings.planner.critic.desc': {
        en: 'Have an LLM critic review the registered roadmap (assignees, coverage, dependencies) before it is executed, and send it back to the planner if it objects. Runs whether or not HITL is on, before a human sees the plan. Costs one extra LLM call per planning run.',
        ru: 'Проверять созданный план с помощью LLM-критика (исполнители, покрытие, зависимости) перед выполнением и возвращать планировщику при наличии замечаний. Добавляет 1 вызов LLM на запуск планирования.'
      },

      'settings.planner.rounds.label': { en: 'Revision Rounds', ru: 'Раунды доработки' },
      'settings.planner.rounds.desc': {
        en: 'How many times the critic may send the roadmap back. <span class="font-mono">1</span> — it gets a single say and the rewrite then stands. Each extra round is a full replan, and a critic that never approves would otherwise keep the planner going.',
        ru: 'Сколько раз критик может возвращать план на доработку. <span class="font-mono">1</span> — одна проверка, после чего версия утверждается. Каждый доп. раунд — полный переутверждённый план.'
      },

      'settings.planner.mergeTasks.label': { en: 'Merge Tasks', ru: 'Объединение задач' },
      'settings.planner.mergeTasks.desc': {
        en: 'Automatically merge consecutive tasks assigned to the same executor (CoderAgent / TaskExecutorAgent) into a single task. Turn off to keep every task the planner wrote as a separate unit of work.',
        ru: 'Автоматически объединять последовательные задачи, назначенные одному исполнителю (CoderAgent / TaskExecutorAgent), в одну задачу.'
      },

      // ── ResearchAgent section ──
      'settings.research.maxSearches.label': { en: 'Per-turn — max searches', ru: 'Макс. поисков за ход' },
      'settings.research.maxSearches.desc': {
        en: 'Maximum number of web search tool calls per agent turn. After this limit, the agent must synthesize from existing results.',
        ru: 'Максимальное количество вызовов поиска в сети за один ход агента. После превышения лимита агент должен отвечать из имеющихся данных.'
      },

      // ── HypothesesAgent section ──
      'settings.hypotheses.maxActive.label': { en: 'Max Active Hypotheses', ru: 'Макс. активных гипотез' },
      'settings.hypotheses.maxActive.desc': {
        en: 'How many hypotheses are kept as active (<span class="font-mono">formulated</span>) simultaneously for parallel verification. <span class="font-mono">1</span> — the classic "one at a time" mode: the agent picks the single best hypothesis and postpones the rest. Higher values let the orchestrator verify several branches in parallel.',
        ru: 'Сколько гипотез одновременно сохраняются активными (<span class="font-mono">formulated</span>) для параллельной проверки. <span class="font-mono">1</span> — режим "по одной": выбирается 1 лучшая гипотеза. Более высокие значения позволяют проверять несколько веток параллельно.'
      },

      // ── CoderAgent section ──
      'settings.coder.mode.label': { en: 'Coder Execution Mode', ru: 'Режим выполнения Coder' },
      'settings.coder.mode.note': { en: '(no Sandbox URL set — OpenHands mode requires a Sandbox URL)', ru: '(не задан URL песочницы — для режима OpenHands требуется URL песочницы)' },
      'settings.coder.mode.desc': {
        en: 'Choose execution mode: <strong>local</strong> uses in-process tools (<span class="font-mono">execute_bash</span>, file edits, git); <strong>openhands</strong> relays tasks to the remote OpenHands sandbox agent.',
        ru: 'Выберите режим выполнения: <strong>local</strong> использует локальные инструменты (<span class="font-mono">execute_bash</span>, правка файлов, git); <strong>openhands</strong> передаёт задачи удалённому агенту в песочнице OpenHands.'
      },

      'settings.coder.sandboxUrl.label': { en: 'Sandbox Remote URL', ru: 'Удалённый URL песочницы' },
      'settings.coder.sandboxUrl.desc': {
        en: 'The endpoint URL of the isolated code-execution sandbox server.',
        ru: 'URL-адрес изолированного сервера-песочницы для выполнения кода.'
      },

      'settings.coder.workspaceId.label': { en: 'Coder Workspace ID', ru: 'ID рабочей области Coder' },
      'settings.coder.workspaceId.desc': {
        en: 'Pin a custom persistent workspace folder name to save code state across delegations. Leave empty to auto-generate.',
        ru: 'Указать имя папки рабочей области для сохранения состояния кода между вызовами. Оставьте пустым для автогенерации.'
      },
      'settings.coder.workspaceId.placeholder': { en: 'e.g. workspace_1', ru: 'например workspace_1' },

      // ── TaskExecutorAgent section ──
      'settings.taskExec.keepScore.label': { en: 'Tool Keep Threshold', ru: 'Порог релевантности инструментов' },
      'settings.taskExec.keepScore.desc': {
        en: 'Minimum relevance score (0.0 to 1.0) for a retrieved MCP tool to be loaded into context.',
        ru: 'Минимальный балл релевантности (от 0.0 до 1.0) для загрузки найденного инструмента MCP в контекст.'
      },

      'settings.taskExec.abstainScore.label': { en: 'Tool Abstain Threshold', ru: 'Порог отказа от инструментов' },
      'settings.taskExec.abstainScore.desc': {
        en: 'Threshold below which the tool pipeline completely abstains, so the executor re-routes the task to the CoderAgent.',
        ru: 'Порог, ниже которого пайплайн инструментов отказывается от выполнения, и исполнитель перенаправляет задачу в CoderAgent.'
      },

      // ── Empty / Common sections ──
      'settings.noConfig': { en: 'No configurable parameters yet.', ru: 'Пока нет настраиваемых параметров.' },
      'settings.cancel': { en: 'Cancel', ru: 'Отмена' },
      'settings.save': { en: 'Save Settings', ru: 'Сохранить настройки' },

      // ── Settings modal runtime messages ──
      'settings.saving': { en: 'Saving…', ru: 'Сохранение…' },
      'settings.saved': { en: 'Settings saved.', ru: 'Настройки сохранены.' },
      'settings.saveError': { en: 'Error saving settings: {error}', ru: 'Ошибка сохранения настроек: {error}' },
      'settings.deleteGraph.targetExecution': { en: "this session's execution graph", ru: 'граф выполнения этой сессии' },
      'settings.deleteGraph.targetResearch': { en: "this session's research graph", ru: 'граф исследований этой сессии' },
      'settings.deleteGraph.targetMemory': { en: 'the GLOBAL knowledge memory (shared by every session)', ru: 'ГЛОБАЛЬНУЮ память знаний (общую для всех сессий)' },
      'settings.deleteGraph.targetAll': { en: "this session's execution and research graphs AND the GLOBAL knowledge memory", ru: 'графы выполнения и исследований этой сессии И ГЛОБАЛЬНУЮ память знаний' },
      'settings.deleteGraph.confirm': { en: 'Delete {target}?\n\nThis cannot be undone from the UI.', ru: 'Удалить {target}?\n\nЭто действие нельзя отменить из интерфейса.' },
      'settings.deleteGraph.deleting': { en: 'Deleting…', ru: 'Удаление…' },
      'settings.deleteGraph.nothing': { en: 'nothing', ru: 'ничего' },
      'settings.deleteGraph.deleted': { en: 'Deleted {details}.', ru: 'Удалено: {details}.' },
      'settings.deleteGraph.error': { en: 'Error deleting graphs: {error}', ru: 'Ошибка удаления графов: {error}' },

      // ── Common ──
      'common.close': { en: 'Close', ru: 'Закрыть' },
      'common.loading': { en: 'Loading…', ru: 'Загрузка…' },
      'common.showMore': { en: 'Show more', ru: 'Показать больше' },
      'common.showLess': { en: 'Show less', ru: 'Скрыть' },
      'common.errorPrefix': { en: 'Error: {error}', ru: 'Ошибка: {error}' },

      // ── Top bar ──
      'topbar.idle': { en: 'Status: Idle', ru: 'Статус: ожидание' },
      'topbar.processing': { en: 'Status: Processing', ru: 'Статус: выполняется' },
      'topbar.events': { en: 'Events: {count}', ru: 'События: {count}' },

      // ── Tooltips (sidebar & header) ──
      'nav.registerUser': { en: 'Register user', ru: 'Зарегистрировать пользователя' },
      'nav.renameSession': { en: 'Rename session', ru: 'Переименовать сессию' },
      'nav.saveSession': { en: 'Save session to disk', ru: 'Сохранить сессию на диск' },
      'nav.exportSession': { en: 'Export session (.zip)', ru: 'Экспорт сессии (.zip)' },
      'nav.importSession': { en: 'Import session', ru: 'Импорт сессии' },
      'nav.restoreSession': { en: 'Restore saved session', ru: 'Восстановить сохранённую сессию' },
      'nav.newSession': { en: 'New session', ru: 'Новая сессия' },
      'nav.sidebarShow': { en: 'Show sidebar', ru: 'Показать панель' },
      'nav.sidebarHide': { en: 'Hide sidebar', ru: 'Скрыть панель' },
      'chat.clearView': { en: 'Clear current view (history is preserved)', ru: 'Очистить текущий вид (история сохраняется)' },
      'chat.attach': { en: 'Add context', ru: 'Добавить контекст' },
      'chat.stop': { en: 'Stop agents', ru: 'Остановить агентов' },

      // ── Chat runtime ──
      'chat.system': { en: 'System', ru: 'Система' },
      'chat.you': { en: 'You', ru: 'Вы' },
      'chat.result': { en: 'Result', ru: 'Результат' },
      'chat.showFull': { en: 'Show full output', ru: 'Показать полностью' },
      'chat.collapse': { en: 'Collapse', ru: 'Свернуть' },
      'chat.sandboxOpenActive': { en: 'Open Active CoderSandbox: {url}', ru: 'Открыть активную песочницу: {url}' },
      'chat.sandboxActive': { en: 'Sandbox active: {url}', ru: 'Песочница активна: {url}' },
      'chat.sandboxOpen': { en: 'Open CoderSandbox: {url}', ru: 'Открыть песочницу: {url}' },
      'chat.sandboxStandby': { en: 'Sandbox standby: {url}', ru: 'Песочница в ожидании: {url}' },
      'chat.detachDataset': { en: 'Detach dataset', ru: 'Открепить датасет' },

      // ── Telemetry & metrics ──
      'telemetry.waiting': { en: 'Waiting for connection…', ru: 'Ожидание подключения…' },
      'telemetry.live': { en: 'Live', ru: 'Live' },
      'metrics.noCalls': { en: 'no model calls yet', ru: 'вызовов модели пока не было' },
      'metrics.calls': { en: 'calls', ru: 'выз.' },
      'metrics.tokens': { en: 'tok', ru: 'ток.' },
      'metrics.unpriced': {
        en: '{count} call(s) on a model with no known price — total is a floor',
        ru: '{count} вызов(а) модели без известной цены — итог занижен'
      },

      // ── Activity rail runtime hints ──
      'rail.hintCalls': { en: '{count} tool call(s)', ru: 'вызовов инструментов: {count}' },
      'rail.hintDelegated': { en: 'delegated', ru: 'делегировано' },
      'rail.hintRunning': { en: 'Running', ru: 'Выполняется' },
      'rail.toolFinished': { en: '{done}/{calls} finished', ru: 'завершено {done}/{calls}' },
      'rail.toolErrors': { en: '{count} error(s)', ru: 'ошибок: {count}' },
      'rail.delegatedTitle': { en: 'Delegated', ru: 'Делегировано' },

      // ── HITL ──
      'hitl.sidebarHint': { en: 'Answer in the chat card.', ru: 'Ответьте в карточке в чате.' },
      'hitl.required': { en: 'HITL Required', ru: 'Требуется подтверждение' },
      'hitl.requiredLong': { en: 'Human-In-The-Loop Required', ru: 'Требуется подтверждение человеком' },
      'hitl.proposedOutput': { en: 'Proposed output', ru: 'Предложенный результат' },
      'hitl.accept': { en: 'Accept', ru: 'Принять' },
      'hitl.reject': { en: 'Reject', ru: 'Отклонить' },
      'hitl.revise': { en: 'Revise', ru: 'На доработку' },
      'hitl.send': { en: 'Send', ru: 'Отправить' },
      'hitl.reply': { en: 'Reply', ru: 'Ответить' },
      'hitl.openRoadmap': { en: 'Open Roadmap', ru: 'Открыть план' },
      'hitl.placeholderInput': { en: 'Enter instructions for the agent…', ru: 'Введите инструкции для агента…' },
      'hitl.placeholderAnswer': { en: 'Your answer to the question — then "Reply"', ru: 'Ваш ответ на вопрос — затем «Ответить»' },
      'hitl.placeholderRevise': { en: 'Edits for the agent — then Revise', ru: 'Правки для агента — затем «На доработку»' },
      'hitl.emptyEdits': { en: 'Enter your edits in the field above, then press Revise.', ru: 'Введите правки в поле выше, затем нажмите «На доработку».' },
      'hitl.empty': { en: '(empty)', ru: '(пусто)' },
      'hitl.inputSent': { en: '💬 HITL Input: {feedback}', ru: '💬 HITL ввод: {feedback}' },
      'hitl.approved': { en: '✓ HITL Approved', ru: '✓ HITL подтверждено' },
      'hitl.rejected': { en: '✗ HITL Rejected', ru: '✗ HITL отклонено' },
      'hitl.revisionRequested': { en: '✎ HITL Revision requested: {feedback}', ru: '✎ HITL: запрошена доработка: {feedback}' },
      'hitl.timeoutMsg': {
        en: '⏱ HITL: no answer for {seconds} s — the proposal of agent {agent} was auto-approved, the pipeline continues.',
        ru: '⏱ HITL: нет ответа {seconds} с — предложение агента {agent} автоподтверждено, пайплайн продолжен.'
      },

      // ── WebSocket system messages ──
      'ws.datasetAttached': {
        en: 'Dataset attached: {url}\nThe coder agent will pass it to the sandbox when a step needs that data.',
        ru: 'Датасет прикреплён: {url}\nАгент Coder передаст его в песочницу, когда шагу понадобятся эти данные.'
      },
      'ws.datasetDetached': { en: 'Dataset link detached.', ru: 'Ссылка на датасет откреплена.' },
      'ws.datasetRejected': { en: 'Dataset link rejected: {message}', ru: 'Ссылка на датасет отклонена: {message}' },
      'ws.reportLangRejected': { en: 'Report language rejected: {message}', ru: 'Язык отчёта отклонён: {message}' },

      // ── Identity modal ──
      'identity.title': { en: 'Local user', ru: 'Локальный пользователь' },
      'identity.subtitle': { en: 'Users and sessions are cleared when the service restarts.', ru: 'Пользователи и сессии очищаются при перезапуске сервиса.' },
      'identity.continueAs': { en: 'Continue as', ru: 'Продолжить как' },
      'identity.open': { en: 'Open', ru: 'Открыть' },
      'identity.registerLabel': { en: 'Register a new Nick', ru: 'Регистрация нового ника' },
      'identity.register': { en: 'Register', ru: 'Зарегистрировать' },
      'identity.nickPlaceholder': { en: 'User', ru: 'Пользователь' },
      'identity.enterNick': { en: 'Enter a nick.', ru: 'Введите ник.' },
      'identity.noUsers': { en: 'No local users', ru: 'Нет локальных пользователей' },
      'identity.noSessions': { en: 'No sessions', ru: 'Нет сессий' },

      // ── Session operations ──
      'sessions.titlePrompt': { en: 'Session title:', ru: 'Название сессии:' },
      'sessions.renamePrompt': { en: 'New session title:', ru: 'Новое название сессии:' },
      'sessions.createError': { en: 'Could not create session: {error}', ru: 'Не удалось создать сессию: {error}' },
      'sessions.renameError': { en: 'Could not rename session: {error}', ru: 'Не удалось переименовать сессию: {error}' },
      'sessions.initError': { en: 'Failed to initialize local sessions: {error}', ru: 'Не удалось загрузить локальные сессии: {error}' },
      'sessions.noActiveExport': { en: 'No active session to export.', ru: 'Нет активной сессии для экспорта.' },
      'sessions.exporting': { en: '📥 Exporting session…', ru: '📥 Экспорт сессии…' },
      'sessions.exported': { en: '✅ Session exported: {filename}', ru: '✅ Сессия экспортирована: {filename}' },
      'sessions.exportFailed': { en: '❌ Export failed: {error}', ru: '❌ Ошибка экспорта: {error}' },
      'sessions.noActiveSave': { en: 'No active session to save.', ru: 'Нет активной сессии для сохранения.' },
      'sessions.saving': { en: '💾 Saving session to disk…', ru: '💾 Сохранение сессии на диск…' },
      'sessions.saved': { en: '✅ Session saved: {filename}', ru: '✅ Сессия сохранена: {filename}' },
      'sessions.saveFailed': { en: '❌ Save failed: {error}', ru: '❌ Ошибка сохранения: {error}' },
      'sessions.importing': { en: '📤 Importing session from {filename}…', ru: '📤 Импорт сессии из {filename}…' },
      'sessions.imported': { en: '✅ Session imported: {title}', ru: '✅ Сессия импортирована: {title}' },
      'sessions.mcpRebuilds': { en: ' (MCP rebuilds launched)', ru: ' (запущена пересборка MCP)' },
      'sessions.importFailed': { en: '❌ Import failed: {error}', ru: '❌ Ошибка импорта: {error}' },
      'sessions.restoring': { en: '📂 Restoring session from {filename}…', ru: '📂 Восстановление сессии из {filename}…' },
      'sessions.restored': { en: '✅ Session restored: {title}', ru: '✅ Сессия восстановлена: {title}' },
      'sessions.restoreFailed': { en: '❌ Restore failed: {error}', ru: '❌ Ошибка восстановления: {error}' },
      'sessions.downloadFailed': { en: '❌ Download failed: {error}', ru: '❌ Ошибка скачивания: {error}' },
      'sessions.deleteConfirm': { en: 'Delete saved session "{filename}"?', ru: 'Удалить сохранённую сессию «{filename}»?' },
      'sessions.deleted': { en: '🗑 Saved session deleted: {filename}', ru: '🗑 Сохранённая сессия удалена: {filename}' },
      'sessions.deleteFailed': { en: '❌ Delete failed: {error}', ru: '❌ Ошибка удаления: {error}' },
      'sessions.savedBy': { en: ' · by {nick}', ru: ' · от {nick}' },
      'sessions.loadFailed': { en: 'Failed to load saved sessions: {error}', ru: 'Не удалось загрузить сохранённые сессии: {error}' },

      // ── Saved sessions modal ──
      'saved.title': { en: 'Saved Sessions', ru: 'Сохранённые сессии' },
      'saved.subtitle': { en: 'Restore or manage previously saved sessions', ru: 'Восстановление и управление сохранёнными сессиями' },
      'saved.empty': { en: 'No saved sessions found.', ru: 'Сохранённые сессии не найдены.' },
      'saved.restore': { en: 'Restore', ru: 'Восстановить' },
      'saved.download': { en: 'Download', ru: 'Скачать' },
      'saved.delete': { en: 'Delete', ru: 'Удалить' },

      // ── MCP rebuild modal ──
      'mcpRebuild.title': { en: 'MCP Servers Found', ru: 'Найдены серверы MCP' },
      'mcpRebuild.subtitle': { en: 'This session contains MCP tool server builds', ru: 'Эта сессия содержит сборки MCP-серверов' },
      'mcpRebuild.explain': {
        en: '<strong>Rebuild</strong> will launch Docker builds for each server (takes ~10–30 min per server). <strong>Skip</strong> will import the session without starting the servers — build logs and metadata will still be available.',
        ru: '<strong>Пересборка</strong> запустит Docker-сборку каждого сервера (~10–30 минут на сервер). <strong>Пропустить</strong> импортирует сессию без запуска серверов — логи сборки и метаданные останутся доступными.'
      },
      'mcpRebuild.skip': { en: 'Skip', ru: 'Пропустить' },
      'mcpRebuild.rebuild': { en: 'Rebuild', ru: 'Пересобрать' },

      // ── Dataset modal & upload widget ──
      'dataset.menuItem': { en: 'Dataset link (.zip)', ru: 'Ссылка на датасет (.zip)' },
      'dataset.title': { en: 'Dataset link (for openhands)', ru: 'Ссылка на датасет (для openhands)' },
      'dataset.desc': {
        en: 'A direct http(s) URL of a .zip archive. The coder agent sees it and sends it to the sandbox, where it is unpacked, when a step needs that data.',
        ru: 'Прямая http(s) ссылка на .zip архив. Агент Coder видит её и отправляет в песочницу, где архив распаковывается, когда шагу нужны эти данные.'
      },
      'dataset.remove': { en: 'Remove', ru: 'Удалить' },
      'dataset.attach': { en: 'Attach', ru: 'Прикрепить' },
      'dataset.errEmpty': { en: 'Enter a link to a .zip archive.', ru: 'Введите ссылку на .zip архив.' },
      'dataset.errInvalid': { en: 'That is not a valid URL.', ru: 'Это недопустимый URL.' },
      'dataset.errProtocol': { en: 'The link must be an http(s) URL.', ru: 'Ссылка должна быть http(s) URL.' },
      'dataset.errNotZip': { en: 'The link must point to a .zip archive.', ru: 'Ссылка должна указывать на .zip архив.' },
      'dataset.notConnected': { en: 'Not connected — reconnect and try again.', ru: 'Нет подключения — переподключитесь и попробуйте снова.' },
      'dataset.upload.title': { en: 'DATASET UPLOAD', ru: 'ЗАГРУЗКА ДАТАСЕТА' },
      'dataset.upload.details': { en: 'Details', ru: 'Подробности' },
      'dataset.upload.filename': { en: 'Filename:', ru: 'Файл:' },
      'dataset.upload.speed': { en: 'Speed:', ru: 'Скорость:' },
      'dataset.upload.eta': { en: 'ETA:', ru: 'Осталось:' },
      'dataset.upload.status': { en: 'Status:', ru: 'Статус:' },
      'dataset.uploading': { en: 'Uploading', ru: 'Загрузка' },
      'dataset.uploadingSandbox': { en: 'Uploading dataset to sandbox…', ru: 'Загрузка датасета в песочницу…' },

      // ── Roadmap modal ──
      'roadmap.title': { en: 'Roadmap & Execution Plan', ru: 'План и этапы выполнения' },
      'roadmap.subtitle': { en: 'Execution steps for the current session', ru: 'Этапы выполнения текущей сессии' },
      'roadmap.addTask': { en: 'Add Task', ru: 'Добавить задачу' },
      'roadmap.filter.all': { en: 'All', ru: 'Все' },
      'roadmap.searchPlaceholder': { en: 'Search tasks…', ru: 'Поиск задач…' },
      'roadmap.expandAllDesc': { en: 'Expand all descriptions', ru: 'Развернуть все описания' },
      'roadmap.collapseAllDesc': { en: 'Collapse all descriptions', ru: 'Свернуть все описания' },
      'roadmap.empty.none': { en: 'No tasks found in roadmap', ru: 'В плане нет задач' },
      'roadmap.empty.noMatch': { en: 'No tasks match current filter/search', ru: 'Нет задач по текущему фильтру/поиску' },
      'roadmap.empty.hint': { en: 'PlannerAgent generates the plan, or click "Add Task" to create one manually.', ru: 'PlannerAgent создаёт план автоматически, либо нажмите «Добавить задачу», чтобы создать её вручную.' },
      'roadmap.feedbackLabel': { en: 'Feedback / Revision Instructions for Planner', ru: 'Замечания / инструкции по доработке для планировщика' },
      'roadmap.feedbackPlaceholder': { en: 'Specify what should be changed or added (e.g. Add validation against off-targets, split task 2)…', ru: 'Укажите, что изменить или добавить (например: добавить проверку по офф-таргетам, разбить задачу 2)…' },
      'roadmap.saveChanges': { en: 'Save Changes', ru: 'Сохранить изменения' },
      'roadmap.revisePlan': { en: 'Revise Plan', ru: 'Отправить на доработку' },
      'roadmap.saveConfirm': { en: 'Save & Confirm', ru: 'Сохранить и подтвердить' },
      'roadmap.status.done': { en: 'Completed', ru: 'Завершено' },
      'roadmap.status.in_progress': { en: 'In Progress', ru: 'В работе' },
      'roadmap.status.error': { en: 'Failed', ru: 'Ошибка' },
      'roadmap.status.todo': { en: 'Pending', ru: 'Ожидает' },
      'roadmap.progress': { en: '{done} of {total} completed ({percent}%)', ru: 'Завершено {done} из {total} ({percent}%)' },
      'roadmap.tasksCount': { en: '{count} task(s)', ru: 'задач: {count}' },
      'roadmap.statTotal': { en: 'Total: {count}', ru: 'Всего: {count}' },
      'roadmap.statActive': { en: 'In progress: {count}', ru: 'В работе: {count}' },
      'roadmap.statDone': { en: 'Done: {count}', ru: 'Готово: {count}' },
      'roadmap.noPrereq': { en: 'No prerequisite', ru: 'Без зависимости' },
      'roadmap.dependsOn': { en: 'Depends on: {id}', ru: 'Зависит от: {id}' },
      'roadmap.deleteTask': { en: 'Delete task', ru: 'Удалить задачу' },
      'roadmap.editTask': { en: 'Edit task', ru: 'Редактировать задачу' },
      'roadmap.moveUp': { en: 'Move up', ru: 'Переместить вверх' },
      'roadmap.moveDown': { en: 'Move down', ru: 'Переместить вниз' },
      'roadmap.toggleStatus': { en: 'Click to toggle status', ru: 'Нажмите, чтобы изменить статус' },
      'roadmap.jumpToPrereq': { en: 'Jump to prerequisite task', ru: 'Перейти к задаче-зависимости' },
      'roadmap.fieldTitle': { en: 'Task Title', ru: 'Название задачи' },
      'roadmap.titlePlaceholder': { en: 'Enter task title…', ru: 'Введите название задачи…' },
      'roadmap.fieldDesc': { en: 'Description', ru: 'Описание' },
      'roadmap.descPlaceholder': { en: 'Specific instructions or details for this task…', ru: 'Конкретные инструкции или детали для этой задачи…' },
      'roadmap.fieldNotes': { en: 'Notes / Parameters (Optional)', ru: 'Заметки / параметры (необязательно)' },
      'roadmap.notesPlaceholder': { en: 'e.g. Max iterations: 3, temperature: 0.2', ru: 'например: макс. итераций: 3, температура: 0.2' },
      'roadmap.doneEditing': { en: 'Done', ru: 'Готово' },
      'roadmap.untitled': { en: 'Untitled task', ru: 'Задача без названия' },
      'roadmap.errEmptyTitle': { en: 'Task title cannot be empty.', ru: 'Название задачи не может быть пустым.' },
      'roadmap.errNoPrereq': { en: "Prerequisite task '{id}' not found in the plan.", ru: 'Задача-зависимость «{id}» не найдена в плане.' },
      'roadmap.confirmDelete': { en: 'Delete task {id}?', ru: 'Удалить задачу {id}?' },
      'roadmap.errNoPending': { en: 'No pending roadmap confirmation request found.', ru: 'Нет ожидающего запроса на подтверждение плана.' },
      'roadmap.syncing': { en: 'Syncing roadmap…', ru: 'Синхронизация плана…' },
      'roadmap.synced': { en: 'Roadmap synced.', ru: 'План синхронизирован.' },
      'roadmap.syncError': { en: 'Error syncing roadmap: {error}', ru: 'Ошибка синхронизации плана: {error}' },
      'roadmap.savingChanges': { en: 'Saving changes…', ru: 'Сохранение изменений…' },
      'roadmap.savedOk': { en: 'Roadmap saved successfully.', ru: 'План сохранён.' },
      'roadmap.saveError': { en: 'Error saving roadmap: {error}', ru: 'Ошибка сохранения плана: {error}' },
      'roadmap.errSave': { en: 'Failed to save roadmap', ru: 'Не удалось сохранить план' },
      'roadmap.errUnknown': { en: 'Unknown error', ru: 'Неизвестная ошибка' },
      'roadmap.sendingRevision': { en: 'Sending revision request…', ru: 'Отправка запроса на доработку…' },
      'roadmap.revisionSent': { en: 'Revision requested.', ru: 'Доработка запрошена.' },
      'roadmap.sentForRevision': { en: '✗ HITL Sent for Revision', ru: '✗ HITL отправлен на доработку' },
      'roadmap.savingConfirming': { en: 'Saving and confirming plan…', ru: 'Сохранение и подтверждение плана…' },
      'roadmap.savedConfirmed': { en: 'Roadmap saved and confirmed.', ru: 'План сохранён и подтверждён.' },

      // ── Experiment viewer ──
      'experiments.title': { en: 'Experiment Viewer', ru: 'Просмотр эксперимента' },
      'experiments.subtitle': { en: 'Live Tool Activity Feed', ru: 'Поток вызовов инструментов' },
      'experiments.expandAll': { en: 'Expand all', ru: 'Развернуть всё' },
      'experiments.collapseAll': { en: 'Collapse all', ru: 'Свернуть всё' },
      'experiments.clearFeed': { en: 'Clear feed', ru: 'Очистить ленту' },
      'experiments.empty': { en: 'No tool activity yet', ru: 'Вызовов инструментов пока нет' },
      'experiments.emptyHint': { en: 'Tool calls and results from agents will appear here in real time', ru: 'Вызовы инструментов и их результаты будут появляться здесь в реальном времени' },
      'experiments.calls': { en: 'calls', ru: 'вызовов' },
      'experiments.running': { en: 'running', ru: 'в работе' },
      'experiments.failed': { en: 'failed', ru: 'с ошибкой' },
      'experiments.delegates': { en: 'delegates', ru: 'делегирует' },
      'experiments.runningDots': { en: 'running…', ru: 'выполняется…' },
      'experiments.args': { en: 'Arguments', ru: 'Аргументы' },
      'experiments.output': { en: 'Output', ru: 'Результат' },
      'experiments.error': { en: 'Error', ru: 'Ошибка' },
      'experiments.callNotRecorded': { en: '(the call itself was not recorded)', ru: '(сам вызов не был записан)' },
      'experiments.noArgs': { en: '(no arguments)', ru: '(нет аргументов)' },
      'experiments.emptyValue': { en: '(empty)', ru: '(пусто)' },
      'experiments.noValue': { en: '(none)', ru: '(нет)' },
      'experiments.emptyList': { en: '(empty list)', ru: '(пустой список)' },
      'experiments.waiting': { en: 'waiting for the result…', ru: 'ожидание результата…' },
      'experiments.truncated': { en: '… truncated (server preview cap)', ru: '… обрезано (лимит предпросмотра сервера)' },
      'experiments.retry': { en: 'Retry — {error}', ru: 'Повторить — {error}' },
      'experiments.loadFailed': { en: 'failed to load full result', ru: 'не удалось загрузить полный результат' },

      // ── Standalone graph page ──
      'graph.title': { en: 'CoScientist — Research Graph', ru: 'CoScientist — Граф исследований' },
      'graph.brand': { en: 'Graph', ru: 'Граф' },
      'graph.connecting': { en: 'connecting…', ru: 'подключение…' },
      'graph.live': { en: 'live', ru: 'live' },
      'graph.refresh': { en: 'refresh', ru: 'обновить' },
      'graph.backTrace': { en: '← session trace', ru: '← трасса сессии' },
      'graph.view.label': { en: 'view', ru: 'вид' },
      'graph.view.research': { en: 'research', ru: 'исследования' },
      'graph.view.slide': { en: 'research · slide', ru: 'исследования · слайд' },
      'graph.view.execution': { en: 'execution log', ru: 'лог выполнения' },
      'graph.turn.study': { en: 'study', ru: 'исследование' },
      'graph.turn.request': { en: 'request', ru: 'запрос' },
      'graph.choice.live': { en: 'live', ru: 'live' },
      'graph.choice.archived': { en: 'archived', ru: 'архивное' },
      'graph.choice.study': { en: 'study', ru: 'исследование' },
      'graph.status': { en: '{nodes} nodes · {edges} edges', ru: 'узлов: {nodes} · рёбер: {edges}' },
      'graph.age.justNow': { en: ' · last written just now', ru: ' · обновлено только что' },
      'graph.age.min': { en: ' · last written {mins} min ago', ru: ' · обновлено {mins} мин назад' },
      'graph.age.hours': { en: ' · last written {hours} h ago', ru: ' · обновлено {hours} ч назад' },
      'graph.age.date': { en: ' · last written {date}', ru: ' · обновлено {date}' },
      'graph.error': { en: 'error: {error}', ru: 'ошибка: {error}' },
      'graph.noSession': { en: 'Open the graph from an active CoScientist session.', ru: 'Откройте граф из активной сессии CoScientist.' },
      'graph.callNotFound': { en: 'call {call} not found in this session', ru: 'вызов {call} не найден в этой сессии' },
      'graph.count.calls': { en: '{count} call(s)', ru: 'вызовов: {count}' },
      'graph.count.item': { en: '{count} item(s)', ru: 'элементов: {count}' },
      'graph.count.field': { en: '{count} field(s)', ru: 'полей: {count}' },
      'graph.chars': { en: '{count} chars', ru: '{count} симв.' },
      // Research node type names (fallback for data without a server type_word)
      'graph.type.researchquestion': { en: 'Question', ru: 'Вопрос' },
      'graph.type.hypothesis': { en: 'Hypothesis', ru: 'Гипотеза' },
      'graph.type.evidence': { en: 'Evidence', ru: 'Данные' },
      'graph.type.conclusion': { en: 'Conclusion', ru: 'Вывод' },
      'graph.type.verificationmethod': { en: 'Method', ru: 'Метод' },
      'graph.type.confirmationcriteria': { en: 'Criteria', ru: 'Критерии' },
      'graph.type.tool': { en: 'Tool', ru: 'Инструмент' },
      'graph.type.resource': { en: 'Resource', ru: 'Ресурс' },
      'graph.type.empiricalbase': { en: 'Data source', ru: 'Источник данных' },
      'graph.type.constraint': { en: 'Constraint', ru: 'Ограничение' },
      'graph.type.codeartifact': { en: 'Code', ru: 'Код' },
      'graph.type.generateddata': { en: 'Dataset', ru: 'Набор данных' },
      'graph.type.report': { en: 'Report', ru: 'Отчёт' },
      'graph.type.publication': { en: 'Publication', ru: 'Публикация' },
      'graph.type.spec': { en: 'Spec', ru: 'Спецификация' },
      'graph.type.efficiencyjustification': { en: 'Efficiency', ru: 'Эффективность' },
      'graph.type.costmodel': { en: 'Cost model', ru: 'Модель стоимости' },
      'graph.type.efficiencymetric': { en: 'Metric', ru: 'Метрика' },
      // Research edge labels
      'graph.edge.motivates': { en: 'motivates', ru: 'мотивирует' },
      'graph.edge.tested_by': { en: 'tested by', ru: 'проверяется' },
      'graph.edge.requires': { en: 'requires', ru: 'требует' },
      'graph.edge.uses': { en: 'uses', ru: 'использует' },
      'graph.edge.consumes': { en: 'consumes', ru: 'потребляет' },
      'graph.edge.produces': { en: 'produces', ru: 'производит' },
      'graph.edge.supports': { en: 'supports', ru: 'поддерживает' },
      'graph.edge.refutes': { en: 'refutes', ru: 'опровергает' },
      'graph.edge.refines': { en: 'refines', ru: 'уточняет' },
      'graph.edge.based_on': { en: 'based on', ru: 'основано на' },
      'graph.edge.determines_sufficiency': { en: 'sufficiency for', ru: 'достаточность для' },
      'graph.edge.formulated_for': { en: 'criterion for', ru: 'критерий для' },
      'graph.edge.regulates': { en: 'regulates', ru: 'регулирует' },
      'graph.edge.constrains': { en: 'constrains', ru: 'ограничивает' },
      'graph.edge.derived_from': { en: 'derived from', ru: 'получено из' },
      'graph.edge.contextualizes': { en: 'frames', ru: 'контекст для' },
      'graph.edge.defines_scope': { en: 'scope of', ru: 'область' },
      'graph.edge.relates_to': { en: 'relates to', ru: 'относится к' },
      'graph.edge.applies_to': { en: 'applies to', ru: 'применяется к' },
      'graph.edge.via': { en: 'via', ru: 'через' },
      // Execution node kinds (panel subtitle)
      'graph.kind.goal': { en: 'request', ru: 'запрос' },
      'graph.kind.result': { en: 'answer', ru: 'ответ' },
      'graph.kind.agent': { en: 'agent', ru: 'агент' },
      'graph.kind.agent_call': { en: 'agent', ru: 'агент' },
      'graph.kind.tool_call': { en: 'tool call', ru: 'вызов инструмента' },
      'graph.kind.system': { en: 'system', ru: 'система' },
      // Node hover tooltip (plain text, one line per item)
      'graph.tooltip.type': { en: 'type: {kind}', ru: 'тип: {kind}' },
      'graph.tooltip.source': { en: 'source: {agent}', ru: 'источник: {agent}' },
      'graph.tooltip.status': { en: 'status: {status}', ru: 'статус: {status}' },
      'graph.tooltip.toolCalls': { en: 'tool calls: {count}', ru: 'вызовов инструментов: {count}' },
      // Detail / inspector panel
      'graph.detail.provenance': { en: 'provenance — produced by', ru: 'происхождение — получено из' },
      'graph.detail.openInLog': { en: 'open this call in the execution log', ru: 'открыть этот вызов в логе выполнения' },
      'graph.detail.execLog': { en: '↗ execution log', ru: '↗ лог выполнения' },
      'graph.detail.says': { en: 'what this says', ru: 'содержание' },
      'graph.detail.details': { en: 'details', ru: 'детали' },
      'graph.detail.by': { en: 'by {agent}', ru: 'от {agent}' },
      'graph.detail.truncated': {
        en: 'recorded up to {kept} characters · {dropped} more were not kept',
        ru: 'записано {kept} символов · ещё {dropped} не сохранено'
      },
      'graph.detail.cutShort': {
        en: 'recorded value was cut short · shown up to the last complete field',
        ru: 'записанное значение обрезано · показано до последнего целого поля'
      },
      'graph.detail.arguments': { en: 'arguments', ru: 'аргументы' },
      'graph.detail.none': { en: 'none', ru: 'нет' },
      'graph.detail.result': { en: 'result', ru: 'результат' },
      'graph.detail.files': { en: 'files', ru: 'файлы' },
      'graph.detail.call': { en: 'call', ru: 'вызов' },
      'graph.detail.artifacts': { en: 'artifacts', ru: 'артефакты' },
      'graph.detail.agent': { en: 'agent', ru: 'агент' },
      'graph.detail.request': { en: 'request', ru: 'запрос' },
      'graph.detail.answer': { en: 'answer', ru: 'ответ' },
      'graph.detail.whatAsked': { en: 'what was asked', ru: 'что было запрошено' },
      'graph.detail.report': { en: 'report', ru: 'отчёт' },
      'graph.detail.task': { en: 'task', ru: 'задача' },
      'graph.detail.ioDelegation': {
        en: 'task and report come from the delegation that started this run',
        ru: 'задача и отчёт взяты из делегирования, запустившего этот запуск'
      },
      'graph.detail.ioRequest': {
        en: 'task and report come from the request this agent served and its answer',
        ru: 'задача и отчёт взяты из запроса, который обслуживал агент, и его ответа'
      },
      'graph.detail.taskReport': { en: 'task · report', ru: 'задача · отчёт' },
      'graph.detail.notRecorded': { en: 'not recorded for this agent', ru: 'для этого агента ничего не записано' },
      'graph.detail.toolCalls': { en: 'tool calls', ru: 'вызовы инструментов' },
      'graph.detail.failedCount': { en: ' · {count} failed', ru: ' · ошибок: {count}' },
      'graph.detail.noneRecorded': { en: 'none recorded', ru: 'не записано' },
      'graph.detail.empty': { en: 'nothing recorded yet', ru: 'пока ничего не записано' },
      'graph.detail.runOf': { en: 'run {run} of {runs}', ru: 'запуск {run} из {runs}' },
      'graph.detail.started': { en: 'started {at}', ru: 'начат в {at}' },

    };

    /** Применяет текущий язык ко всем элементам с data-i18n / data-i18n-placeholder */
    function applyLanguage(lang) {
      // The server rejects a language change while a run is active, so ignore
      // the request here too. The buttons are disabled for the run anyway.
      if (lang && typeof runActive !== 'undefined' && runActive) return;
      const prevLang = currentLang;
      if (lang) currentLang = lang;
      localStorage.setItem(I18N_LANG_KEY, currentLang);
      document.documentElement.lang = currentLang;

      // The indicator builds its phrases in JS, not from data-i18n attributes.
      if (window.StatusIndicator) StatusIndicator.setLang(currentLang);

      document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        const entry = i18n[key];
        if (entry && entry[currentLang]) el.innerHTML = entry[currentLang];
      });
      document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const key = el.getAttribute('data-i18n-placeholder');
        const entry = i18n[key];
        if (entry && entry[currentLang]) el.placeholder = entry[currentLang];
      });
      document.querySelectorAll('[data-i18n-title]').forEach(el => {
        const key = el.getAttribute('data-i18n-title');
        const entry = i18n[key];
        if (entry && entry[currentLang]) el.title = entry[currentLang];
      });

      // Динамические элементы статуса и пользователя
      const user = (typeof activeUser !== 'undefined') ? activeUser : null;
      const nicknameEl = document.getElementById('active-nickname');
      if (nicknameEl) {
        if (user && user.nickname) {
          nicknameEl.textContent = user.nickname;
        } else {
          const entry = i18n['nav.noUser'];
          nicknameEl.textContent = (entry && entry[currentLang]) || 'No user selected';
        }
      }
      const isWsOpen = typeof ws !== 'undefined' && ws && ws.readyState === 1;
      const connStatusEl = document.getElementById('conn-status');
      if (connStatusEl) {
        const key = isWsOpen ? 'nav.connected' : 'nav.disconnected';
        const entry = i18n[key];
        connStatusEl.textContent = (entry && entry[currentLang]) || (isWsOpen ? 'Connected' : 'Disconnected');
      }
      const badgeEl = document.getElementById('active-badge');
      if (badgeEl) {
        const key = isWsOpen ? 'chat.online' : 'chat.offline';
        const entry = i18n[key];
        badgeEl.textContent = (entry && entry[currentLang]) || (isWsOpen ? 'Online' : 'Offline');
      }

      // Dynamic HUD labels JS writes outside the data-i18n pass.
      const statusBadgeEl = document.getElementById('status-badge');
      if (statusBadgeEl && typeof runActive !== 'undefined') {
        statusBadgeEl.textContent = t(runActive ? 'topbar.processing' : 'topbar.idle');
      }
      if (typeof renderEventCount === 'function') renderEventCount();
      const metricsSummaryEl = document.getElementById('metrics-summary');
      if (metricsSummaryEl && metricsSummaryEl.dataset.empty === '1') {
        metricsSummaryEl.textContent = t('metrics.noCalls');
      }

      // Обновляем кнопки переключателя языка
      const btnEn = document.getElementById('lang-btn-en');
      const btnRu = document.getElementById('lang-btn-ru');
      if (btnEn) {
        btnEn.classList.toggle('bg-primary', currentLang === 'en');
        btnEn.classList.toggle('text-on-primary', currentLang === 'en');
      }
      if (btnRu) {
        btnRu.classList.toggle('bg-primary', currentLang === 'ru');
        btnRu.classList.toggle('text-on-primary', currentLang === 'ru');
      }

      if (typeof renderActivityRail === 'function' && typeof activityAgents !== 'undefined' && activityAgents.size) {
        renderActivityRail();
      }

      // One control sets both the interface language and the report language.
      // Send only on an explicit change with a live session. A re-render call
      // (no argument) must not replay the message.
      if (lang && lang !== prevLang && typeof activeSession !== 'undefined' && activeSession && typeof sendReportLanguage === 'function') {
        sendReportLanguage(currentLang);
      }
    }

    /** Хелпер для получения перевода по ключу. Подставляет {placeholder} из vars. */
    function t(key, vars = null, fallback = '') {
      if (typeof vars === 'string') { fallback = vars; vars = null; }
      const entry = i18n[key];
      let text = (entry && entry[currentLang]) || fallback || key;
      if (vars) {
        Object.keys(vars).forEach(name => {
          text = text.split('{' + name + '}').join(String(vars[name]));
        });
      }
      return text;
    }
    window.t = t;

    // Применяем язык при загрузке страницы (после того как DOM построится)
    document.addEventListener('DOMContentLoaded', () => applyLanguage());


