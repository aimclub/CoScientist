// =========================================================================
// i18n – lightweight translation system
// =========================================================================
// Текущий язык: 'ru' по умолчанию (или из localStorage)
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
  'nav.orchestrator': { en: 'Orchestrator', ru: 'Оркестратор' },

  // ── Composer: report language (NOT the interface language) ──
  'composer.reportLang.ru': { en: 'Report: RU', ru: 'Отчёт: RU' },
  'composer.reportLang.en': { en: 'Report: EN', ru: 'Отчёт: EN' },

  // Agent descriptions in side nav
  'agent.OrchestratorAgent.desc': { en: 'Master Orchestrator', ru: 'Главный оркестратор' },
  'agent.PlannerAgent.desc': { en: 'Roadmap Planner', ru: 'Планировщик задач' },
  'agent.ToolsViewer.desc': { en: 'Tools Viewer', ru: 'Вызовы инструментов' },
  'agent.KnowledgeGraph.desc': { en: 'Knowledge Graph', ru: 'Граф знаний' },
  'agent.SessionTrace.desc': { en: 'Session Trace', ru: 'Трассировка сессии' },
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
  'usage.duration': { en: 'Run duration', ru: 'Время выполнения' },
  'usage.durationRunning': { en: 'Running', ru: 'Выполняется' },
  'usage.durationFinished': { en: 'Completed in', ru: 'Выполнено за' },

  // ── Plan tracker (right sidebar) ──
  'plan.header': { en: 'Plan', ru: 'План' },
  'plan.open': { en: 'Open roadmap', ru: 'Открыть план' },
  'plan.untitled': { en: 'Untitled task', ru: 'Задача без названия' },
  'plan.status.todo': { en: 'Pending', ru: 'Ожидает' },
  'plan.status.in_progress': { en: 'In progress', ru: 'В работе' },
  'plan.status.done': { en: 'Completed', ru: 'Выполнена' },
  'plan.status.error': { en: 'Failed', ru: 'Ошибка' },

  // ── Activity Rail HUD ──
  'rail.agents': { en: 'Agents', ru: 'Агенты' },
  'rail.tools': { en: 'Tools', ru: 'Инструменты' },
  'rail.standby': { en: 'Standby — awaiting tool invocation', ru: 'Ожидание вызова инструментов…' },
  'rail.noTools': { en: 'No tool calls yet', ru: 'Инструменты ещё не вызывались' },
  'rail.toggle': { en: 'Show/hide agent activity', ru: 'Показать/скрыть активность агентов' },

  // ── Settings modal (rendered by modals/settings.js) ───────────────────────
  'settings.title': { en: 'Settings', ru: 'Настройки' },
  'settings.search': { en: 'Search settings', ru: 'Поиск настроек' },
  'settings.noResults': { en: 'Nothing found', ru: 'Ничего не найдено' },
  'settings.banner': {
    en: 'Shared by every user of this server and reset when it restarts. Permanent values live in .env.',
    ru: 'Настройки общие для всех пользователей сервера и сбрасываются при его перезапуске. Постоянные значения задаются в .env.'
  },
  'settings.reset': { en: 'Reset to defaults', ru: 'По умолчанию' },
  'settings.resetHint': {
    en: 'Restore the values the server was started with (.env). Saved only after you press Save.',
    ru: 'Вернуть значения, с которыми запущен сервер (.env). Сохраняются только после нажатия «Сохранить».'
  },
  'settings.advanced': { en: 'Advanced ({n})', ru: 'Расширенные ({n})' },
  'settings.differsDefault': { en: 'Differs from default: {value}', ru: 'Отличается от значения по умолчанию: {value}' },
  'settings.envVar': { en: 'Default comes from .env: {name}', ru: 'Значение по умолчанию задаётся в .env: {name}' },
  'settings.envValues': { en: 'Allowed values:', ru: 'Допустимые значения:' },
  'settings.timeout.mode.wait': { en: 'Wait for me', ru: 'Ждать решения' },
  'settings.timeout.mode.auto': { en: 'Approve after', ru: 'Одобрить через' },
  'settings.timeout.after.label': { en: 'after', ru: 'через' },
  'settings.timeout.seconds': { en: 's', ru: 'с' },
  'settings.timeout.wait': { en: 'wait for a human', ru: 'ждать решения' },
  'settings.timeout.after': { en: 'after {n} s', ru: 'через {n} с' },
  'settings.goto': { en: 'Open section', ru: 'Перейти' },
  'settings.value.on': { en: 'On', ru: 'Вкл' },
  'settings.value.off': { en: 'Off', ru: 'Выкл' },
  'settings.value.empty': { en: 'empty', ru: 'пусто' },
  'settings.discard': { en: 'Discard changes', ru: 'Отменить изменения' },
  'settings.close': { en: 'Close', ru: 'Закрыть' },
  'settings.save': { en: 'Save', ru: 'Сохранить' },
  'settings.confirmDiscard': {
    en: 'You have unsaved changes. Close without saving?',
    ru: 'Есть несохранённые изменения. Закрыть без сохранения?'
  },

  // When a change takes effect
  'settings.scope.instant': { en: 'Immediately', ru: 'Сразу' },
  'settings.scope.instant.hint': {
    en: 'Takes effect right after saving, including sessions that are already running.',
    ru: 'Действует сразу после сохранения, в том числе в уже запущенных сессиях.'
  },
  'settings.scope.session': { en: 'New sessions', ru: 'Новые сессии' },
  'settings.scope.session.hint': {
    en: 'Agents are built when a session first runs — sessions that already ran keep the previous value.',
    ru: 'Агенты собираются при первом запуске сессии — уже запускавшиеся сессии сохранят прежнее значение.'
  },
  'settings.scope.browser': { en: 'This browser', ru: 'Этот браузер' },
  'settings.scope.browser.hint': {
    en: 'Stored in this browser and applied at once; not saved on the server.',
    ru: 'Хранится в этом браузере и применяется сразу; на сервер не сохраняется.'
  },
  'settings.scope.reload': { en: 'On page reload', ru: 'После перезагрузки' },
  'settings.scope.reload.hint': {
    en: 'Takes effect the next time the page is opened.',
    ru: 'Действует при следующем открытии страницы.'
  },

  // Why a field is greyed out
  'settings.inactive.noPlanner': {
    en: 'Not used: in "Orchestrator plans" mode there is no separate planner.',
    ru: 'Не действует: в режиме «Оркестратор планирует сам» отдельного планировщика нет.'
  },
  'settings.inactive.knowledgeGraph': {
    en: 'Not used: the knowledge graph is off.',
    ru: 'Не действует: граф знаний выключен.'
  },
  'settings.inactive.parentOff': {
    en: 'Works only while "{parent}" is on.',
    ru: 'Действует, только когда включено «{parent}».'
  },

  // Validation
  'settings.err.rangeInt': { en: 'Enter a whole number from {min} to {max}', ru: 'Введите целое число от {min} до {max}' },
  'settings.err.rangeFloat': { en: 'Enter a number from {min} to {max}', ru: 'Введите число от {min} до {max}' },
  'settings.err.abstainAboveKeep': {
    en: 'Must not exceed the keep threshold ({keep})',
    ru: 'Не может быть больше порога отбора ({keep})'
  },
  'settings.err.sandboxRequired': {
    en: 'Required: without a URL the OpenHands mode cannot run code',
    ru: 'Укажите адрес: без него режим OpenHands не сможет выполнять код'
  },
  'settings.err.url': { en: 'The URL must start with http:// or https://', ru: 'Адрес должен начинаться с http:// или https://' },

  // Footer status
  'settings.status.loading': { en: 'Loading…', ru: 'Загрузка…' },
  'settings.status.loadFailed': {
    en: 'Could not load settings from the server — showing the last known values.',
    ru: 'Не удалось загрузить настройки с сервера — показаны последние известные значения.'
  },
  'settings.status.clean': { en: 'No unsaved changes', ru: 'Нет несохранённых изменений' },
  'settings.status.dirty': { en: 'Unsaved changes: {n}', ru: 'Несохранённых изменений: {n}' },
  'settings.status.errors': { en: 'Fix errors to save: {n}', ru: 'Исправьте ошибки, чтобы сохранить: {n}' },
  'settings.status.saving': { en: 'Saving…', ru: 'Сохранение…' },
  'settings.status.saved': { en: 'Saved.', ru: 'Сохранено.' },
  'settings.status.savedSession': {
    en: 'Saved. Some changes take effect in new sessions.',
    ru: 'Сохранено. Часть изменений вступит в силу в новых сессиях.'
  },
  'settings.status.savedReload': {
    en: 'Saved. The change takes effect after a page reload.',
    ru: 'Сохранено. Изменение вступит в силу после перезагрузки страницы.'
  },
  'settings.status.saveFailed': { en: 'Could not save: {error}', ru: 'Не удалось сохранить: {error}' },

  // Sections
  'settings.section.interface': { en: 'Interface', ru: 'Интерфейс' },
  'settings.section.interface.desc': { en: 'How the web interface looks and behaves.', ru: 'Как выглядит и ведёт себя веб-интерфейс.' },
  'settings.section.research': { en: 'Research flow', ru: 'Ход исследования' },
  'settings.section.research.desc': {
    en: 'How a session starts and how the work gets planned.',
    ru: 'С чего начинается сессия и как планируется работа.'
  },
  'settings.section.approvals': { en: 'Approvals', ru: 'Подтверждения' },
  'settings.section.approvals.desc': {
    en: 'When the system stops and waits for your decision.',
    ru: 'Когда система останавливается и ждёт вашего решения.'
  },
  'settings.section.tools': { en: 'Tools & code', ru: 'Инструменты и код' },
  'settings.section.tools.desc': {
    en: 'Web search, code execution and MCP tool selection.',
    ru: 'Поиск в сети, выполнение кода и подбор MCP-инструментов.'
  },
  'settings.section.models': { en: 'Models', ru: 'Модели' },
  'settings.section.models.desc': {
    en: 'How requests to language models are routed through OpenRouter.',
    ru: 'Как запросы к языковым моделям распределяются через OpenRouter.'
  },
  'settings.section.graphs': { en: 'Graphs & memory', ru: 'Графы и память' },
  'settings.section.graphs.desc': {
    en: 'What the system records about runs and research.',
    ru: 'Что система запоминает о запусках и исследовании.'
  },
  'settings.section.system': { en: 'System', ru: 'Система' },
  'settings.section.system.desc': {
    en: 'Server-level options and values that are set only in .env.',
    ru: 'Параметры сервера и значения, которые задаются только в .env.'
  },

  // ── Experiment plan review card (CoScientist/experiments/plan_view.py) ──
  'plan.title': { en: 'Experiment plan', ru: 'План эксперимента' },
  'plan.sidebarTitle': { en: 'Experiment plan', ru: 'План эксперимента' },
  'plan.sidebarHint': {
    en: 'Read the plan in the chat: the design matrix, then each task. Revise sends your corrections back to the planner.',
    ru: 'План — в карточке в чате: матрица плана, затем задачи. «Доработать» отправит ваши правки планировщику.'
  },
  'plan.revision': { en: 'revision {n}', ru: 'ревизия {n}' },
  'plan.tasks': { en: '{n} task(s)', ru: 'задач: {n}' },
  'plan.tasksTitle': { en: 'Tasks', ru: 'Задачи' },
  'plan.min': { en: 'min', ru: 'мин' },
  'plan.goal': { en: 'Goal', ru: 'Цель' },
  'plan.hypothesis': { en: 'Hypothesis', ru: 'Гипотеза' },
  'plan.hypotheses': { en: 'Hypotheses', ru: 'Гипотезы' },
  'plan.methods': { en: 'Methods', ru: 'Методы' },
  'plan.matrix': {
    en: 'Design matrix — hypothesis → experiment → data → baseline → metrics',
    ru: 'Матрица плана — гипотеза → эксперимент → данные → базлайн → метрики'
  },
  'plan.col.task': { en: 'Task', ru: 'Задача' },
  'plan.col.hypothesis': { en: 'Hypothesis', ru: 'Гипотеза' },
  'plan.col.question': { en: 'Question', ru: 'Вопрос' },
  'plan.col.dataset': { en: 'Dataset', ru: 'Данные' },
  'plan.col.baselines': { en: 'Baselines', ru: 'Базлайны' },
  'plan.col.metrics': { en: 'Metrics', ru: 'Метрики' },
  'plan.col.tools': { en: 'Tools', ru: 'Инструменты' },
  'plan.col.artifacts': { en: 'Analysis', ru: 'Анализ' },
  'plan.col.route': { en: 'Route', ru: 'Маршрут' },
  'plan.task.question': { en: 'Question', ru: 'Вопрос' },
  'plan.task.dataset': { en: 'Dataset', ru: 'Данные' },
  'plan.task.baselines': { en: 'Baselines', ru: 'Базлайны' },
  'plan.task.metrics': { en: 'Metrics', ru: 'Метрики' },
  'plan.task.analysis': { en: 'Analysis', ru: 'Анализ' },
  'plan.task.description': { en: 'What runs', ru: 'Что выполняется' },
  'plan.task.rationale': { en: 'Why', ru: 'Зачем' },
  'plan.task.tools': { en: 'MCP / tools', ru: 'MCP / инструменты' },
  'plan.task.repo': { en: 'Repository', ru: 'Репозиторий' },
  'plan.task.params': { en: 'Launch params', ru: 'Параметры запуска' },
  'plan.task.inputs': { en: 'Inputs', ru: 'Входные данные' },
  'plan.task.criteria': { en: 'Success criteria', ru: 'Критерии успеха' },
  'plan.task.expected': { en: 'Expected artifacts', ru: 'Ожидаемые артефакты' },
  'plan.task.warnings': { en: 'Warnings', ru: 'Предупреждения' },
  'plan.task.optional': { en: 'optional', ru: 'необязательная' },
  'plan.task.after': { en: 'after', ru: 'после' },
  'plan.optionalTool': { en: 'optional', ru: 'необязательный' },
  'plan.noInputs': { en: 'no inputs — the task starts from its own launch params', ru: 'входных данных нет — задача стартует со своих параметров' },
  'plan.noTools': { en: 'no MCP tools — this route does not use them', ru: 'MCP-инструменты не используются этим маршрутом' },
  'plan.risks': { en: 'Risks', ru: 'Риски' },
  'plan.assumptions': { en: 'Assumptions', ru: 'Допущения' },
  'plan.critique': { en: 'Automatic review', ru: 'Автоматическая проверка' },
  'plan.critique.approve': {
    en: 'The deterministic critic found no blocking issue.',
    ru: 'Детерминированная проверка не нашла блокирующих проблем.'
  },
  'plan.critique.revise': {
    en: 'The deterministic critic asked for a revision.',
    ru: 'Детерминированная проверка потребовала доработки.'
  },
  'plan.expandAll': { en: 'Expand all', ru: 'Раскрыть все' },
  'plan.collapseAll': { en: 'Collapse all', ru: 'Свернуть все' },
  'plan.accept': { en: 'Approve', ru: 'Утвердить' },
  'plan.revise': { en: 'Revise', ru: 'Доработать' },
  'plan.reject': { en: 'Reject', ru: 'Отклонить' },
  'plan.feedbackPlaceholder': {
    en: 'Corrections for the planner — then Revise',
    ru: 'Правки для планировщика — затем «Доработать»'
  },


  // Groups inside sections
  'settings.group.planning': { en: 'Planning', ru: 'Планирование' },
  'settings.group.search': { en: 'Web search', ru: 'Поиск в сети' },
  'settings.group.code': { en: 'Code execution', ru: 'Выполнение кода' },
  'settings.group.toolSelection': { en: 'Tool selection', ru: 'Подбор инструментов' },
  'settings.group.toolSelection.desc': {
    en: 'How TaskExecutorAgent decides which of the found MCP tools to use.',
    ru: 'Как TaskExecutorAgent решает, какие из найденных MCP-инструментов использовать.'
  },
  'settings.group.danger': { en: 'Delete data', ru: 'Удаление данных' },
  'settings.group.danger.desc': {
    en: 'These actions run immediately and are not affected by Save or Discard.',
    ru: 'Эти действия выполняются сразу и не зависят от кнопок «Сохранить» и «Отменить».'
  },
  'settings.group.envOnly': { en: 'Set only in .env', ru: 'Задаётся только в .env' },
  'settings.group.envOnly.desc': {
    en: 'To change these, edit .env and restart the server.',
    ru: 'Чтобы изменить, отредактируйте .env и перезапустите сервер.'
  },

  // Allowed .env values, shown in the ⓘ tooltip where the format is not obvious
  'settings.f.startMode.envValues': {
    en: 'planner — plan first\norchestrator — straight to work\norchestrator_planner — orchestrator plans',
    ru: 'planner — сначала план\norchestrator — сразу к делу\norchestrator_planner — оркестратор планирует сам'
  },
  'settings.f.maxSearches.envValues': { en: '0–20 (integer). 0 — web search is off.', ru: '0–20 (целое). 0 — поиск запрещён.' },
  'settings.f.coderMode.envValues': {
    en: 'local — locally\nopenhands — OpenHands sandbox',
    ru: 'local — локально\nopenhands — песочница OpenHands'
  },
  'settings.f.sandboxUrl.envValues': {
    en: 'http(s)://host:port, e.g. http://localhost:8884. Empty — not set.',
    ru: 'http(s)://хост:порт, например http://localhost:8884. Пусто — не задан.'
  },
  'settings.f.workspaceId.envValues': {
    en: 'Folder name, e.g. workspace_1. Empty — created automatically.',
    ru: 'Имя папки, например workspace_1. Пусто — создаётся автоматически.'
  },
  'settings.f.keepScore.envValues': { en: 'Number from 0 to 1, e.g. 0.3', ru: 'Число от 0 до 1, например 0.3' },
  'settings.f.abstainScore.envValues': {
    en: 'Number from 0 to 1, not above the keep threshold, e.g. 0.2',
    ru: 'Число от 0 до 1, не больше порога отбора, например 0.2'
  },
  'settings.f.providerSort.envValues': {
    en: 'default — balanced\nprice — price\nlatency — latency\nthroughput — throughput',
    ru: 'default — баланс\nprice — цена\nlatency — отклик\nthroughput — скорость'
  },
  'settings.f.providerOrder.envValues': {
    en: 'Comma-separated provider names in priority order, e.g. Together, DeepInfra. Empty — any.',
    ru: 'Названия провайдеров через запятую в порядке приоритета, например Together, DeepInfra. Пусто — любые.'
  },
  'settings.f.maxRetries.envValues': { en: '0–10 (integer). 0 — do not retry.', ru: '0–10 (целое). 0 — не повторять.' },
  'settings.f.defaultUsername.envValues': {
    en: 'User nickname, e.g. alice. Also read from DEFAULT_USERNAME. Empty — not set.',
    ru: 'Никнейм пользователя, например alice. Читается также из DEFAULT_USERNAME. Пусто — не задан.'
  },

  // Fields — Interface
  'settings.f.language.label': { en: 'Language (interface and report)', ru: 'Язык (интерфейс и отчёт)' },
  'settings.f.language.desc': {
    en: 'One choice for the interface and the report. Locked while a run is active: switch before you start the session.',
    ru: 'Один выбор для интерфейса и отчёта. Во время выполнения запуска заблокировано: переключите язык до начала сессии.'
  },
  'settings.f.autoNaming.label': { en: 'Auto-name sessions', ru: 'Автоназвание сессий' },
  'settings.f.autoNaming.desc': {
    en: 'Title a new session after its first request.',
    ru: 'Придумывать название новой сессии по первому запросу.'
  },
  'settings.f.showInternal.label': { en: 'Show internal agents and tools', ru: 'Показывать служебных агентов и инструменты' },
  'settings.f.showInternal.desc': {
    en: 'Pipeline stages, wrappers and system tools (marked internal in the system config) appear in the activity rail, the trace tree and Work Order cards. Useful for debugging.',
    ru: 'Этапы пайплайна, обёртки и системные инструменты (помечены internal в конфиге системы) появляются в панели активности, дереве вызовов и карточках плана работы. Полезно для отладки.'
  },

  // Fields — Research flow
  'settings.f.startMode.label': { en: 'How a session starts', ru: 'С чего начинается сессия' },
  'settings.f.startMode.desc': { en: 'Who picks up your request first.', ru: 'Кто первым берётся за ваш запрос.' },
  'settings.f.startMode.opt.planner': { en: 'Plan first', ru: 'Сначала план' },
  'settings.f.startMode.opt.planner.desc': {
    en: 'The planner writes a roadmap, then the orchestrator carries it out step by step.',
    ru: 'Планировщик составляет план, затем оркестратор выполняет его по шагам.'
  },
  'settings.f.startMode.opt.planner.flow': { en: 'Planner → Orchestrator', ru: 'Планировщик → Оркестратор' },
  'settings.f.startMode.opt.orchestrator': { en: 'Straight to work', ru: 'Сразу к делу' },
  'settings.f.startMode.opt.orchestrator.desc': {
    en: 'The orchestrator starts right away, without an upfront roadmap.',
    ru: 'Оркестратор начинает работу сразу, без предварительного плана.'
  },
  'settings.f.startMode.opt.orchestrator.flow': { en: 'Orchestrator', ru: 'Оркестратор' },
  'settings.f.startMode.opt.orchestrator_planner': { en: 'Orchestrator plans', ru: 'Оркестратор планирует сам' },
  'settings.f.startMode.opt.orchestrator_planner.desc': {
    en: 'The orchestrator writes the roadmap itself; the separate planner is switched off.',
    ru: 'Оркестратор сам составляет план; отдельный планировщик отключён.'
  },
  'settings.f.startMode.opt.orchestrator_planner.flow': { en: 'Orchestrator + plan', ru: 'Оркестратор + план' },
  'settings.f.contextInit.label': { en: 'Research frame', ru: 'Рамка исследования' },
  'settings.f.contextInit.desc': {
    en: 'Before the run, an agent drafts the question, constraints and success criteria and records them in the research graph. With approvals on, you can edit the frame in a form.',
    ru: 'Перед стартом агент формулирует вопрос, ограничения и критерии успеха и заносит их в граф исследования. При включённых подтверждениях рамку можно поправить в форме.'
  },
  'settings.f.maxHypotheses.label': { en: 'Hypotheses queued for testing', ru: 'Гипотез в очереди на проверку' },
  'settings.f.maxHypotheses.desc': {
    en: 'How many of the hypotheses proposed in one batch go straight into the testing queue; the rest are set aside, and the orchestrator can bring them back later. Testing itself still goes one hypothesis at a time: the next one starts after the current one has a verdict.',
    ru: 'Сколько гипотез из одной порции, предложенной генератором, сразу попадают в очередь на проверку; остальные откладываются, и оркестратор может вернуть их позже. Сама проверка всё равно идёт по одной: следующая гипотеза начинается, когда у текущей есть вердикт.'
  },
  'settings.f.maxHypotheses.envValues': {
    en: '1–5 (integer). 1 — only the best hypothesis is queued.',
    ru: '1–5 (целое). 1 — в очередь попадает только лучшая гипотеза.'
  },
  'settings.f.critic.label': { en: 'Review the plan with a critic', ru: 'Проверять план критиком' },
  'settings.f.critic.desc': {
    en: 'Before execution a separate model checks the roadmap (assignees, coverage, dependencies) and sends it back if it objects. One extra model call per review.',
    ru: 'Перед выполнением отдельная модель проверяет план (исполнители, полнота, зависимости) и при замечаниях возвращает его на доработку. +1 вызов модели на проверку.'
  },
  'settings.f.criticRounds.label': { en: 'Times the plan can be sent back', ru: 'Сколько раз можно вернуть план' },
  'settings.f.criticRounds.desc': {
    en: '1 — a single review, after which the revised plan stands. Every extra round is a full replan.',
    ru: '1 — одна проверка, после доработки план принимается. Каждый дополнительный раунд — полное перепланирование.'
  },
  'settings.f.criticRounds.envValues': { en: '1–5 (integer)', ru: '1–5 (целое)' },
  'settings.f.mergeTasks.label': { en: 'Merge adjacent tasks', ru: 'Объединять соседние задачи' },
  'settings.f.mergeTasks.desc': {
    en: 'Consecutive tasks for the same executor run as one. Turn off to run every planned task separately.',
    ru: 'Идущие подряд задачи одного исполнителя выполняются как одна. Выключите, чтобы каждая задача плана шла отдельно.'
  },
  'settings.f.plannerRetrieval.label': { en: 'Planner sees the tool catalog', ru: 'Планировщик видит каталог инструментов' },
  'settings.f.plannerRetrieval.desc': {
    en: 'The planner looks up suitable MCP tools and names them in tasks. When off, the plan describes only the expected outcome.',
    ru: 'Планировщик ищет подходящие MCP-инструменты и называет их в задачах. Если выключено — план описывает только ожидаемый результат.'
  },
  'settings.f.plannerGraph.label': { en: 'Planner reads the knowledge graph', ru: 'Планировщик читает граф знаний' },
  'settings.f.plannerGraph.desc': {
    en: 'The planner takes past runs into account and does not re-plan work that is already done.',
    ru: 'Планировщик учитывает прошлые запуски и не планирует заново уже сделанную работу.'
  },

  // Fields — Approvals
  'settings.f.hitl.label': { en: 'Ask for my approval', ru: 'Спрашивать моё подтверждение' },
  'settings.f.hitl.desc': {
    en: 'Before risky actions (outward-facing requests, irreversible commands) and at key steps, agents stop and wait for your decision in the chat.',
    ru: 'Перед рискованными действиями (внешние запросы, необратимые команды) и на ключевых шагах агенты останавливаются и ждут вашего решения в чате.'
  },
  'settings.f.workOrder.label': { en: "Show the agent's work plan", ru: 'Показывать план работы агента' },
  'settings.f.workOrder.desc': {
    en: 'Before starting, an executor agent shows its goal, steps, tools and assumptions. You can accept, correct or reject the plan.',
    ru: 'Перед началом агент-исполнитель показывает цель, шаги, инструменты и допущения. План можно принять, поправить или отклонить.'
  },
  'settings.f.hitlTimeout.label': { en: 'If nobody answers', ru: 'Если никто не ответил' },
  'settings.f.hitlTimeout.desc': {
    en: 'What happens to an approval request left unanswered. "Approve after" — once the time is up, the action runs as if you had approved it.',
    ru: 'Что делать с запросом подтверждения, на который никто не ответил. «Одобрить через» — по истечении времени действие выполняется так, будто вы его одобрили.'
  },
  'settings.f.hitlTimeout.envValues': {
    en: '-1 — wait for a human (no auto-approval)\nN > 0 — approve automatically after N seconds',
    ru: '-1 — ждать решения человека (без автоодобрения)\nN > 0 — одобрить автоматически через N секунд'
  },
  'settings.f.workOrderVeto.label': { en: 'Search and computation plans without an answer', ru: 'Планы поиска и вычислений без ответа' },
  'settings.f.workOrderVeto.desc': {
    en: 'Work plans in which the agent only searches, reads or runs computations can start automatically after this time unless you pause them. Plans with external side effects follow the rule above.',
    ru: 'Планы работы, в которых агент только ищет, читает или выполняет вычисления, могут стартовать автоматически через это время, если вы не поставили их на паузу. Планы с внешними последствиями подчиняются правилу выше.'
  },
  'settings.f.workOrderVeto.envValues': {
    en: '-1 — wait for a human (no auto-start)\nN > 0 — start automatically after N seconds',
    ru: '-1 — ждать решения человека (без автостарта)\nN > 0 — стартовать автоматически через N секунд'
  },

  // Fields — Tools & code
  'settings.f.maxSearches.label': { en: 'Web searches per turn', ru: 'Поисков в сети за один ход' },
  'settings.f.maxSearches.desc': {
    en: 'How many times an agent may search the web before it must answer from what it found. 0 — web search is off.',
    ru: 'Сколько раз агент может искать в интернете, прежде чем отвечать по найденному. 0 — поиск запрещён.'
  },
  'settings.f.coderMode.label': { en: 'Where code runs', ru: 'Где выполняется код' },
  'settings.f.coderMode.desc': {
    en: 'Locally — the agent runs commands and edits files on this server. OpenHands — tasks go to an agent in a remote sandbox.',
    ru: 'Локально — агент сам запускает команды и правит файлы на этом сервере. OpenHands — задачи передаются агенту в удалённой песочнице.'
  },
  'settings.f.coderMode.opt.local': { en: 'Locally', ru: 'Локально' },
  'settings.f.coderMode.opt.openhands': { en: 'OpenHands sandbox', ru: 'Песочница OpenHands' },
  'settings.f.sandboxUrl.label': { en: 'Sandbox URL', ru: 'Адрес песочницы' },
  'settings.f.sandboxUrl.desc': {
    en: 'Server that executes code in isolation. Required in OpenHands mode.',
    ru: 'Сервер изолированного выполнения кода. Обязателен в режиме OpenHands.'
  },
  'settings.f.workspaceId.label': { en: 'Persistent workspace', ru: 'Постоянная рабочая папка' },
  'settings.f.workspaceId.desc': {
    en: 'Folder name where code is kept between tasks. Empty — a folder is created automatically.',
    ru: 'Имя папки, в которой код сохраняется между задачами. Пусто — папка создаётся автоматически.'
  },
  'settings.f.workspaceId.placeholder': { en: 'e.g. workspace_1', ru: 'например, workspace_1' },
  'settings.f.keepScore.label': { en: 'Keep threshold', ru: 'Порог отбора' },
  'settings.f.keepScore.desc': {
    en: 'A found tool is given to the agent if its relevance to the task is at least this value (0–1).',
    ru: 'Найденный инструмент передаётся агенту, если его релевантность задаче не ниже этого значения (0–1).'
  },
  'settings.f.abstainScore.label': { en: 'Hand-off threshold', ru: 'Порог передачи в CoderAgent' },
  'settings.f.abstainScore.desc': {
    en: 'If no tool reaches the keep threshold: the best is at least this value — the top two are used anyway; below it — the task goes to CoderAgent.',
    ru: 'Если ни один инструмент не прошёл порог отбора: лучший не ниже этого значения — берутся два лучших; ниже — задача передаётся CoderAgent.'
  },

  // Fields — Models
  'settings.f.providerSort.label': { en: 'Provider priority', ru: 'Приоритет при выборе провайдера' },
  'settings.f.providerSort.desc': {
    en: 'OpenRouter picks which host runs the model. Applies only to models served through OpenRouter.',
    ru: 'OpenRouter выбирает, у какого хостера запускать модель. Действует только для моделей через OpenRouter.'
  },
  'settings.f.providerSort.opt.default': { en: 'Balanced', ru: 'Баланс' },
  'settings.f.providerSort.opt.price': { en: 'Price', ru: 'Цена' },
  'settings.f.providerSort.opt.latency': { en: 'Latency', ru: 'Отклик' },
  'settings.f.providerSort.opt.throughput': { en: 'Throughput', ru: 'Скорость' },
  'settings.f.providerOrder.label': { en: 'Preferred providers', ru: 'Предпочтительные провайдеры' },
  'settings.f.providerOrder.desc': {
    en: 'These hosts are tried first, in the order shown. Empty — any host.',
    ru: 'Эти хостеры пробуются первыми, в указанном порядке. Пусто — любые.'
  },
  'settings.f.providerOrder.placeholder': { en: 'Type a name and press Enter', ru: 'Введите название и нажмите Enter' },
  'settings.f.maxRetries.label': { en: 'Retries on failures', ru: 'Повторы при сбоях' },
  'settings.f.maxRetries.desc': {
    en: 'How many times to retry a model call after a temporary network or API error. 0 — do not retry.',
    ru: 'Сколько раз повторять запрос к модели при временной ошибке сети или API. 0 — не повторять.'
  },

  // Fields — Graphs & memory
  'settings.f.knowledgeGraph.label': { en: 'Knowledge graph', ru: 'Граф знаний' },
  'settings.f.knowledgeGraph.desc': {
    en: 'Records how each run went so agents can build on past work, and the Knowledge Graph view shows it. When off, nothing is recorded and agents work without history.',
    ru: 'Записывает ход каждого запуска: агенты опираются на прошлую работу, а вкладка «Граф знаний» её показывает. Если выключить — ничего не записывается, и агенты работают без истории.'
  },
  'settings.f.researchGraph.label': { en: 'Research graph', ru: 'Граф исследования' },
  'settings.f.researchGraph.desc': {
    en: 'A shared board where agents record findings, hypotheses and conclusions. When off, agents pass context only through their answers.',
    ru: 'Общая доска, куда агенты заносят находки, гипотезы и выводы. Если выключить — агенты передают контекст только через свои ответы.'
  },
  'settings.danger.session.label': { en: "Clear this session's graphs", ru: 'Очистить графы этой сессии' },
  'settings.danger.session.desc': {
    en: 'Removes the execution and research graphs of the open session. The research graph is archived first; the execution graph keeps only the agent list.',
    ru: 'Удаляет граф выполнения и граф исследования открытой сессии. Граф исследования сначала архивируется; в графе выполнения остаётся только список агентов.'
  },
  'settings.danger.session.btn': { en: 'Clear', ru: 'Очистить' },
  'settings.danger.session.confirm': {
    en: 'Clear the graphs of session "{name}"? This cannot be undone from the interface.',
    ru: 'Очистить графы сессии «{name}»? Отменить это из интерфейса нельзя.'
  },
  'settings.danger.memory.label': { en: 'Delete the shared knowledge memory', ru: 'Удалить общую память знаний' },
  'settings.danger.memory.desc': {
    en: 'There is one knowledge memory for the whole server — it disappears for every session at once. An archive is made first.',
    ru: 'Память знаний одна на весь сервер — она исчезнет во всех сессиях сразу. Перед удалением создаётся архив.'
  },
  'settings.danger.memory.btn': { en: 'Delete', ru: 'Удалить' },
  'settings.danger.memory.confirm': {
    en: 'Delete the knowledge memory for all sessions of this server?',
    ru: 'Удалить память знаний для всех сессий этого сервера?'
  },
  'settings.danger.memory.finalTitle': {
    en: 'Are you sure you want to delete the knowledge memory?',
    ru: 'Вы уверены, что хотите удалить память знаний?'
  },
  'settings.danger.memory.finalText': {
    en: 'It disappears for every session and every user of this server at once. It cannot be restored from the interface.',
    ru: 'Она исчезнет сразу во всех сессиях у всех пользователей этого сервера. Восстановить её из интерфейса нельзя.'
  },
  'settings.danger.memory.finalBtn': { en: 'Delete memory', ru: 'Удалить память' },
  'settings.danger.noSession': { en: 'Open a session first.', ru: 'Сначала откройте сессию.' },
  'settings.danger.confirmBtn': { en: 'Yes, delete', ru: 'Да, удалить' },
  'settings.danger.cancel': { en: 'Cancel', ru: 'Отмена' },
  'settings.danger.deleting': { en: 'Deleting…', ru: 'Удаление…' },
  'settings.danger.done': { en: 'Deleted: {what}.', ru: 'Удалено: {what}.' },
  'settings.danger.nothing': { en: 'nothing', ru: 'ничего' },
  'settings.danger.failed': { en: 'Deletion failed: {error}', ru: 'Ошибка удаления: {error}' },

  // Fields — System
  'settings.f.defaultUsername.label': { en: 'Default user', ru: 'Пользователь по умолчанию' },
  'settings.f.defaultUsername.desc': {
    en: 'Selected automatically when the interface opens; created if it does not exist yet.',
    ru: 'Выбирается автоматически при открытии интерфейса; если такого нет — создаётся.'
  },
  'settings.f.defaultUsername.placeholder': { en: 'not set', ru: 'не задан' },
  'settings.f.opik.label': { en: 'Opik tracing', ru: 'Трассировка в Opik' },
  'settings.f.opik.desc': {
    en: 'Send agent logs and traces to the Opik dashboard for debugging.',
    ru: 'Отправлять логи и трассы агентов в дашборд Opik для отладки.'
  },
  'settings.f.useProxy.label': { en: 'Corporate proxy', ru: 'Корпоративный прокси' },
  'settings.f.useProxy.desc': {
    en: 'Model calls go through the proxy from SERVICES__PROXY_URL.',
    ru: 'Запросы к моделям идут через прокси из SERVICES__PROXY_URL.'
  },
  'settings.f.autoClearGraph.label': { en: 'Clear graphs before a session', ru: 'Очищать графы перед сессией' },
  'settings.f.autoClearGraph.desc': {
    en: "A session's graphs are cleared before its agents are first built.",
    ru: 'Графы сессии очищаются перед первой сборкой её агентов.'
  },

  // ── Work Order cards (hitl.js) ──
  'hitl.msg.workOrder': {
    en: "Agent {agent} declares its work order. Review the plan and the assumptions.",
    ru: "Агент {agent} представил план работы. Проверьте план, условия и ограничения."
  },
  'hitl.msg.workOrderAmendment': {
    en: "Agent {agent} wants to amend its work order.",
    ru: "Агент {agent} хочет изменить свой план работы."
  },
  'hitl.via.workOrder': { en: 'work order (plan before acting)', ru: 'план работы агента (план до действий)' },
  'hitl.via.workOrderAmendment': { en: 'work order amendment', ru: 'поправка к плану работы' },
  'workOrder.title': { en: 'Work Order', ru: 'План работы агента' },
  'workOrder.amendTitle': { en: 'Work Order Amendment', ru: 'Поправка к плану работы' },
  'workOrder.noticeTitle': { en: 'Work Order (for information)', ru: 'План работы агента' },
  'workOrder.tier.read': { en: 'read', ru: 'чтение' },
  'workOrder.tier.compute': { en: 'compute', ru: 'вычисления' },
  'workOrder.tier.side_effect': { en: 'side effects', ru: 'побочные эффекты' },
  'workOrder.goal': { en: 'Goal', ru: 'Цель' },
  'workOrder.done': { en: 'Done when', ru: 'Критерий готовности' },
  'workOrder.assumptions': { en: 'Assumptions', ru: 'Условия и ограничения' },
  'workOrder.assumptionsHint': {
    en: 'Uncheck the assumptions you reject — the agent must not rely on them.',
    ru: 'Снимите галочку с условий, которые вы отклоняете, — агент не должен на них опираться.'
  },
  'workOrder.steps': { en: 'Steps', ru: 'Шаги' },
  'workOrder.tools': { en: 'Tools', ru: 'Инструменты' },
  'workOrder.sideEffects': { en: 'Side effects', ru: 'Побочные эффекты' },
  'workOrder.expected': { en: 'Expected outcome', ru: 'Ожидаемый результат' },
  'workOrder.fallback': { en: 'If it fails', ru: 'Если не получится' },
  'workOrder.reason': { en: 'Reason', ru: 'Обоснование' },
  'workOrder.added': { en: 'Requested changes', ru: 'Запрошенные изменения' },
  'workOrder.countdown': { en: 'Starts automatically in {s} s', ru: 'Автоматический старт через {s} с' },
  'workOrder.paused': { en: 'Paused — waiting for your decision', ru: 'Пауза — ждём вашего решения' },
  'workOrder.blocking': { en: 'Waiting for your decision', ru: 'Ждём вашего решения' },
  'workOrder.btn.pause': { en: 'Pause', ru: 'Пауза' },
  'workOrder.ph.notes': {
    en: 'Notes or corrections for the agent (optional for Accept, required for Revise)',
    ru: 'Заметки или правки для агента (для «Принять» — необязательно, для «Доработать» — обязательно)'
  },
  'workOrder.approved': { en: '✓ Work order approved', ru: '✓ План работы одобрен' },
  'workOrder.rejectedAssumptions': { en: '{n} assumption(s) rejected', ru: 'отклонено условий: {n}' },
  'workOrder.deviation': { en: 'Blocked', ru: 'Заблокировано' },
  'workOrder.reason.no_work_order': { en: 'no work order declared yet', ru: 'план работы ещё не объявлен' },
  'workOrder.reason.rejected': { en: 'work order was rejected', ru: 'план работы отклонён' },
  'workOrder.reason.undeclared_tool': { en: 'tool not in the work order', ru: 'инструмента нет в плане работы' },

  // ── Work Report cards (hitl.js) ──
  'hitl.msg.workReport': {
    en: 'Agent {agent} reports what it did. Check the findings against its work order.',
    ru: 'Агент {agent} отчитался о работе. Сверьте находки с планом работы.'
  },
  'hitl.via.workReport': { en: 'work report (result after acting)', ru: 'отчёт агента (результат после работы)' },
  'workReport.title': { en: 'Work Report', ru: 'Отчёт агента' },
  'workReport.round': { en: 'round {n}', ru: 'раунд {n}' },
  'workReport.summary': { en: 'Summary', ru: 'Итог' },
  'workReport.finalAnswer': {
    en: 'The agent finished without a report — its final answer:',
    ru: 'Агент завершил работу без отчёта — его итоговый ответ:'
  },
  'workReport.findings': { en: 'Findings', ru: 'Находки' },
  'workReport.findingsHint': {
    en: 'Tick the findings that are wrong — the agent will recheck them on rework.',
    ru: 'Отметьте неверные находки — при доработке агент перепроверит их.'
  },
  'workReport.markWrong': { en: 'Wrong', ru: 'Неверно' },
  'workReport.noEvidence': { en: 'no evidence given', ru: 'нет подтверждения' },
  'workReport.confidence.high': { en: 'high confidence', ru: 'высокая уверенность' },
  'workReport.confidence.medium': { en: 'medium confidence', ru: 'средняя уверенность' },
  'workReport.confidence.low': { en: 'low confidence', ru: 'низкая уверенность' },
  'workReport.verdict.met': { en: 'met', ru: 'выполнен' },
  'workReport.verdict.partial': { en: 'partially met', ru: 'выполнен частично' },
  'workReport.verdict.not_met': { en: 'not met', ru: 'не выполнен' },
  'workReport.outcome': { en: 'Expected vs actual', ru: 'Ожидание и факт' },
  'workReport.actual': { en: 'Actual outcome', ru: 'Фактический результат' },
  'workReport.steps': { en: 'Steps: plan vs done', ru: 'Шаги: план и факт' },
  'workReport.artifacts': { en: 'Artifacts', ru: 'Артефакты' },
  'workReport.kind.file': { en: 'file', ru: 'файл' },
  'workReport.kind.dataset': { en: 'dataset', ru: 'датасет' },
  'workReport.kind.graph_node': { en: 'graph node', ru: 'узел графа' },
  'workReport.kind.link': { en: 'link', ru: 'ссылка' },
  'workReport.kind.other': { en: 'other', ru: 'другое' },
  'workReport.journal': { en: 'Journal (recorded by the system)', ru: 'Журнал (записан системой)' },
  'workReport.sideEffectsDone': { en: 'Side effects performed:', ru: 'Выполненные побочные эффекты:' },
  'workReport.amendments': { en: 'Amendments', ru: 'Поправки к плану' },
  'workReport.deviations': { en: 'Blocked calls', ru: 'Заблокированные вызовы' },
  'workReport.warn.no_report': {
    en: 'The agent finished without a report: only its answer and the journal are shown.',
    ru: 'Агент завершил работу без отчёта: показаны только его ответ и журнал.'
  },
  'workReport.warn.open_steps': { en: 'Steps not closed: {steps}', ru: 'Незакрытые шаги: {steps}' },
  'workReport.warn.done_not_met': { en: 'Done criteria: {verdict}', ru: 'Критерий готовности: {verdict}' },
  'workReport.warn.findings_without_evidence': {
    en: 'Findings without evidence: {findings}', ru: 'Находки без подтверждения: {findings}'
  },
  'workReport.warn.deviations': { en: 'Blocked calls during the run: {count}', ru: 'Заблокированных вызовов за работу: {count}' },
  'workReport.countdown': { en: 'Accepted automatically in {s} s', ru: 'Автоматическое принятие через {s} с' },
  'workReport.btn.rework': { en: 'Send back for rework', ru: 'На доработку' },
  'workReport.btn.returnParent': { en: 'Return to parent', ru: 'Вернуть родителю' },
  'workReport.ph.notes': {
    en: 'What is wrong or missing (optional for Accept, required for rework)',
    ru: 'Что неверно или чего не хватает (для «Принять» — необязательно, для доработки — обязательно)'
  },
  'workReport.accepted': { en: '✓ Work report accepted', ru: '✓ Отчёт принят' },
  'workReport.sentBack': { en: '↺ Sent back for rework', ru: '↺ Отправлено на доработку' },
  'workReport.rejected': { en: '✗ Work report rejected', ru: '✗ Отчёт отклонён' },
  'workReport.disputedCount': { en: '{n} finding(s) marked wrong', ru: 'неверных находок: {n}' },

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
    en: "Agent {agent} proposes its result. Please review.",
    ru: "Агент {agent} предлагает свой результат. Проверьте его."
  },

  // ── HITL request card (built at render time from agent_name / invoked_via / trigger) ──
  'hitl.title': { en: 'Human-In-The-Loop Required', ru: 'Требуется решение человека' },
  'hitl.titleShort': { en: 'HITL Required', ru: 'Нужно решение' },
  'hitl.viaLabel': { en: 'Invoked via', ru: 'Причина вызова' },
  'hitl.msg.beforeTool': {
    en: "Agent {agent} is about to execute tool {tool}. Approve execution?",
    ru: "Агент {agent} собирается выполнить инструмент {tool}. Разрешить выполнение?"
  },
  'hitl.msg.afterAgent': {
    en: "Agent {agent} proposes the following output. Please review.",
    ru: "Агент {agent} предлагает следующий результат. Проверьте его."
  },
  'hitl.msg.beforeAgent': {
    en: "Agent {agent} is about to start. Approve?",
    ru: "Агент {agent} собирается начать работу. Разрешить?"
  },
  'hitl.msg.bashCommand': {
    en: "Agent {agent} wants to run a command that is outward-facing or hard to reverse. Approve execution?",
    ru: "Агент {agent} хочет выполнить команду с внешними или необратимыми последствиями. Разрешить выполнение?"
  },
  'hitl.via.beforeTool': {
    en: 'confirmation before running tool «{tool}»',
    ru: 'подтверждение запуска инструмента «{tool}»'
  },
  'hitl.via.afterAgent': {
    en: 'agent output review',
    ru: 'проверка результата агента'
  },
  'hitl.via.beforeAgent': {
    en: 'confirmation before agent start',
    ru: 'подтверждение запуска агента'
  },
  'hitl.via.bashCommand': {
    en: 'system command check (rule: {rule})',
    ru: 'проверка системной команды (правило: {rule})'
  },
  'hitl.via.callback': { en: 'automatic check', ru: 'автоматическая проверка' },
  'hitl.via.tool': { en: 'direct request from agent «{tool}»', ru: 'агент запрашивает подтверждение' },
  'hitl.via.internalLoop': { en: 'intermediate result review', ru: 'согласование промежуточного результата' },
  'hitl.via.requestInput': { en: 'request for user input', ru: 'запрос данных от пользователя' },
  'hitl.via.downloadCancel': { en: 'dataset download cancelled', ru: 'отмена загрузки датасета' },
  'hitl.via.unknown': { en: 'not specified', ru: 'не указан' },
  'hitl.block.toolCall': { en: 'Tool call', ru: 'Вызов инструмента' },
  'hitl.block.command': { en: 'Command', ru: 'Команда' },
  'hitl.block.userQuery': { en: 'User query', ru: 'Запрос пользователя' },
  'hitl.block.output': { en: 'Proposed output', ru: 'Предлагаемый результат' },
  'hitl.reviseEmpty': {
    en: 'Enter your corrections in the field above, then press Revise.',
    ru: 'Введите правки в поле выше, затем нажмите «Доработать».'
  },
  'hitl.btn.accept': { en: 'Accept', ru: 'Принять' },
  'hitl.btn.reject': { en: 'Reject', ru: 'Отклонить' },
  'hitl.btn.revise': { en: 'Revise', ru: 'Доработать' },
  'hitl.btn.reply': { en: 'Reply', ru: 'Ответить' },
  'hitl.btn.send': { en: 'Send', ru: 'Отправить' },
  'hitl.btn.openRoadmap': { en: 'Open Roadmap', ru: 'Открыть план' },
  'hitl.answerInChat': { en: 'Answer in the chat card.', ru: 'Ответьте в карточке в чате.' },
  'hitl.ph.input': { en: 'Enter instructions for the agent...', ru: 'Введите инструкции для агента...' },
  'hitl.ph.reply': { en: 'Your answer to the question, then «Reply»', ru: 'Ваш ответ на вопрос — затем «Ответить»' },
  'hitl.ph.revise': { en: 'Corrections for the agent, then Revise', ru: 'Введите правки для агента, затем нажмите «Доработать»' },

  // ── Keys from feat/report-links-artifacts-i18n (unified language switch,
  //    graph pages, dataset upload, saved sessions, roadmaps) ──
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
  'dataset.upload.title': { en: 'Dataset upload', ru: 'Загрузка датасета' },
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
  'graph.type.framing': { en: 'Framing', ru: 'Постановка' },
  'graph.type.outcome': { en: 'Outcome', ru: 'Итог' },
  'graph.type.planstep': { en: 'Plan step', ru: 'Шаг плана' },
  'graph.plan.title': { en: 'Research plan', ru: 'План исследования' },
  'graph.plan.experiments': { en: 'Experiment plan', ru: 'План экспериментов' },
  'graph.type.experimenttask': { en: 'Experiment task', ru: 'Задача эксперимента' },
  'graph.card.elaborates': { en: 'for step:', ru: 'к шагу:' },
  'graph.edge.elaborates': { en: 'details', ru: 'детализирует' },
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
  'graph.kind.decision': { en: 'decision', ru: 'решение' },
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
  'graph.detail.plan': { en: 'plan', ru: 'план' },
  'graph.detail.decision': { en: 'decision', ru: 'решение' },
  'graph.detail.outcome': { en: 'outcome', ru: 'итог' },
  'graph.detail.note': { en: 'note', ru: 'примечание' },
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

  // ── Research graph: the story a card tells ──
  // Everything below is written into the page by JS after load, so each one is
  // fetched with t(...) rather than data-i18n (applyLanguage runs once, on
  // DOMContentLoaded). The server sends CODES for these, never sentences —
  // otherwise an English reader gets Russian banners.
  'graph.why.title': { en: 'why', ru: 'почему' },
  'graph.why.missing': {
    en: 'no reason was recorded for this outcome',
    ru: 'причина этого исхода не записана'
  },
  'graph.card.criterion': { en: 'criterion:', ru: 'критерий:' },
  // What a method answers. Without it a reader counts four method cards
  // and cannot tell why there are four.
  'graph.card.tests': { en: 'tests:', ru: 'проверяет:' },
  'graph.origin.question': { en: 'the question as first stated', ru: 'исходная формулировка вопроса' },
  'graph.origin.modified': { en: 'modified: {reason}', ru: 'модификация: {reason}' },
  'graph.origin.refined': { en: 'refined: {reason}', ru: 'уточнение: {reason}' },
  'graph.origin.retried': { en: 'retried: {reason}', ru: 'повторная проверка: {reason}' },
  'graph.origin.other': { en: 'replaces an earlier hypothesis', ru: 'заменяет прежнюю гипотезу' },
  'graph.count.attached': { en: '{count} attached', ru: 'вложений: {count}' },
  'graph.chips.tools': { en: 'tools', ru: 'инструменты' },
  'graph.attach.title': { en: 'attached', ru: 'вложения' },
  'graph.history.title': { en: 'how it got here', ru: 'как дошло до этого' },
  'graph.history.initial': { en: 'created as {status}', ru: 'создан(а) как {status}' },
  'graph.history.entry': { en: '{from} → {to} · {source}', ru: '{from} → {to} · {source}' },
  'graph.links.title': { en: 'connections', ru: 'связи' },
  'graph.edge.realises': { en: 'carries out', ru: 'выполняет шаг' },
  'graph.edge.supersedes.refuted': { en: '✗ refuted → modified', ru: '✗ опровергнута → модифицирована' },
  'graph.edge.supersedes.confirmed': { en: '✓ confirmed → refined', ru: '✓ подтверждена → уточнена' },
  'graph.edge.supersedes.inconclusive': { en: '≈ unsettled → retried', ru: '≈ без ответа → перепроверена' },
  'graph.edge.supersedes.other': { en: 'superseded by', ru: 'заменена на' },
  'graph.edge.frames': { en: 'frames', ru: 'задаёт рамку' },
  'graph.edge.concludes': { en: 'sums up', ru: 'подводит итог' },
  'graph.edge.via': { en: 'via {node}', ru: 'через {node}' },
  'graph.counters.confirmed': { en: 'confirmed', ru: 'подтверждено' },
  'graph.counters.refuted': { en: 'refuted', ru: 'опровергнуто' },
  'graph.counters.under_verification': { en: 'under verification', ru: 'на проверке' },
  'graph.counters.formulated': { en: 'formulated', ru: 'сформулировано' },
  'graph.counters.inconclusive': { en: 'inconclusive', ru: 'без ответа' },
  'graph.counters.postponed': { en: 'postponed', ru: 'отложено' },
  'graph.header.meta': {
    en: '{branches} branch(es) · {iterations} iteration(s)',
    ru: 'веток: {branches} · итераций: {iterations}'
  },
  // Shown instead of the branch tally while a study has no hypotheses to
  // branch: when the record was written, and over how long.
  'graph.header.span': {
    en: 'recorded from {from}, over {mins} min',
    ru: 'записано с {from}, за {mins} мин'
  },
  // Node attribute codes. The server sends the code (see store._fields) and the
  // panel captions it here, so one record reads correctly in both languages.
  // Keys are the attribute names from schema.NODE_TYPES.attr_docs.
  'graph.field.formulation': { en: 'Statement', ru: 'Формулировка' },
  'graph.field.rationale': { en: 'Why', ru: 'Обоснование' },
  'graph.field.priority': { en: 'Priority', ru: 'Приоритет' },
  'graph.field.content': { en: 'Finding', ru: 'Результат' },
  'graph.field.subtype': { en: 'Kind', ru: 'Вид' },
  'graph.field.reliability': { en: 'Confidence', ru: 'Достоверность' },
  'graph.field.source_ref': { en: 'Source', ru: 'Источник' },
  'graph.field.measured_on': { en: 'Measured on', ru: 'На чём измерено' },
  'graph.field.synthesis': { en: 'Conclusion', ru: 'Вывод' },
  'graph.field.validity_bounds': { en: 'Limits of validity', ru: 'Границы применимости' },
  'graph.field.new_question': { en: 'Opens next', ru: 'Открывает вопрос' },
  'graph.field.procedure': { en: 'Procedure', ru: 'Процедура' },
  'graph.field.limits': { en: 'Limits', ru: 'Ограничения' },
  'graph.field.limitations': { en: 'Known weaknesses', ru: 'Известные слабости' },
  'graph.field.threshold': { en: 'Threshold', ru: 'Порог' },
  'graph.field.tools': { en: 'Tools', ru: 'Инструменты' },
  'graph.field.how_established': { en: 'How it was established', ru: 'Как установлено' },
  'graph.field.against_criteria': { en: 'Against the criteria', ru: 'По критериям' },
  'graph.field.open_questions': { en: 'What remains', ru: 'Что осталось' },
  'graph.field.title': { en: 'Step', ru: 'Шаг' },
  'graph.field.reproducibility': { en: 'Reproducibility', ru: 'Воспроизводимость' },
  'graph.field.confirmations_needed': { en: 'Confirmations needed', ru: 'Нужно подтверждений' },
  'graph.field.metric': { en: 'Metric', ru: 'Метрика' },
  'graph.field.criterion': { en: 'Criterion', ru: 'Критерий' },
  'graph.field.value': { en: 'Value', ru: 'Значение' },
  'graph.field.name': { en: 'Name', ru: 'Название' },
  'graph.field.location': { en: 'Where', ru: 'Где' },
  'graph.field.tool_type': { en: 'Type', ru: 'Тип' },
  'graph.field.base_type': { en: 'Type', ru: 'Тип' },
  'graph.field.method_type': { en: 'Type', ru: 'Тип' },
  'graph.field.volume': { en: 'Size', ru: 'Объём' },
  'graph.field.resource_type': { en: 'Resource', ru: 'Ресурс' },
  'graph.field.remaining': { en: 'Remaining', ru: 'Осталось' },
  'graph.field.limit': { en: 'Total', ru: 'Всего' },
  'graph.field.domain': { en: 'Field', ru: 'Область' },
  'graph.field.gap': { en: 'Knowledge gap', ru: 'Пробел в знаниях' },
  'graph.field.question': { en: 'Question', ru: 'Вопрос' },
  'graph.field.statement': { en: 'Statement', ru: 'Утверждение' },
  'graph.field.description': { en: 'Description', ru: 'Описание' },
  'graph.field.inputs': { en: 'Needs', ru: 'Что нужно' },
  'graph.field.outputs': { en: 'Yields', ru: 'Что даёт' },
  'graph.field.cost': { en: 'Cost', ru: 'Стоимость' },
  'graph.field.path': { en: 'File', ru: 'Файл' },
  'graph.field.uri': { en: 'Address', ru: 'Адрес' },
  'graph.field.completion_criteria': { en: 'Stopping rule', ru: 'Правило остановки' },
  'graph.field.target_setting': { en: 'Answer sought', ru: 'Целевая постановка' },
  'graph.field.research_form': { en: 'Research form', ru: 'Форма исследования' },
  'graph.field.decomposition': { en: 'Decomposition', ru: 'Декомпозиция' },
  'graph.field.assignee': { en: 'Assigned to', ru: 'Исполнитель' },
  'graph.field.plan_task_id': { en: 'Plan step', ru: 'Шаг плана' },
  'graph.field.specificity': { en: 'Specificity', ru: 'Конкретизация' },
  'graph.field.trl': { en: 'TRL', ru: 'УГТ' },
  'graph.field.ai_application_model': { en: 'AI role', ru: 'Роль ИИ' },
  'graph.field.method': { en: 'Method', ru: 'Метод' },
  'graph.field.not_tested_reason': { en: 'Why untested', ru: 'Почему не проверялась' },
  'graph.field.failure_reason': { en: 'Why it failed', ru: 'Почему не удалось' },
  'graph.field.postponed_reason': { en: 'Why postponed', ru: 'Почему отложена' },
  'graph.field.inconclusive_reason': { en: 'What stayed unsettled', ru: 'Что осталось неясным' },
  // The bands the research canvas is read down, top to bottom. A card sits in
  // the band of the stage that produced it, so the picture says where the study
  // has got to before any card is read. The hypothesis band holds the claim and
  // the bar written for it; what tests the claim stands in the band below.
  'graph.stage.framing': { en: 'Framing', ru: 'Постановка' },
  'graph.stage.literature': { en: 'Literature review', ru: 'Анализ литературы' },
  'graph.stage.hypotheses': { en: 'Hypotheses', ru: 'Гипотезы' },
  'graph.stage.experiment': { en: 'Experiments', ru: 'Эксперименты' },
  'graph.stage.report': { en: 'Report', ru: 'Отчёт' },
  'graph.stage.empty': { en: 'not reached yet', ru: 'этап не начат' },
  // What the record is missing — said out loud, because an empty canvas looked
  // the same whether nobody wrote anything or every write was refused.
  'graph.gap.no_root': { en: 'no root question', ru: 'нет корневого вопроса' },
  'graph.gap.no_frame': { en: 'the research frame was never set', ru: 'рамка исследования не задана' },
  'graph.gap.no_hypotheses': { en: 'no hypotheses yet', ru: 'гипотез пока нет' },
  'graph.gap.no_methods': { en: '{count} hypothesis(es) with no method', ru: 'гипотез без метода: {count}' },
  'graph.gap.no_evidence': { en: 'methods ran, no observations recorded', ru: 'методы есть, наблюдений нет' },
  'graph.gap.unreasoned_failures': { en: '{count} outcome(s) with no reason', ru: 'исходов без причины: {count}' },
  'graph.gap.rejected_commits': { en: '{count} write(s) refused', ru: 'записей отклонено: {count}' },
  'graph.error.http': { en: 'HTTP {status}', ru: 'HTTP {status}' },
  'graph.error.server': { en: 'server: {error}', ru: 'сервер: {error}' },
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
  if (window.PlanTracker) PlanTracker.render();

  // Динамические элементы статуса и пользователя
  const nicknameEl = document.getElementById('active-nickname');
  const user = (typeof activeUser !== 'undefined') ? activeUser : null;
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

  // The settings modal builds its fields (and the language switch) in JS.
  if (typeof renderSettings === 'function') renderSettings();

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

  // HITL cards compose their header text in JS (agent / tool / trigger).
  if (typeof relocalizeHitlCards === 'function') relocalizeHitlCards();

  if (typeof renderActivityRail === 'function' && typeof activityAgents !== 'undefined' && activityAgents.size) {
    renderActivityRail();
  }

  if (typeof RunTimer !== 'undefined' && typeof RunTimer.reapplyLanguage === 'function') {
    RunTimer.reapplyLanguage();
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


