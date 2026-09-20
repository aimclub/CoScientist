// =========================================================================
// i18n – lightweight translation system
// =========================================================================
// Текущий язык: 'ru' по умолчанию (или из localStorage)
let currentLang = localStorage.getItem(LANG_STORAGE_KEY) || 'ru';

const i18n = {
  // ── Navigation & Sidebar ──
  'nav.agents': { en: 'Agents', ru: 'Агенты' },
  'nav.user': { en: 'User', ru: 'Пользователь' },
  'nav.session': { en: 'Session', ru: 'Сессия' },
  'nav.noUser': { en: 'No user selected', ru: 'Пользователь не выбран' },
  'nav.connected': { en: 'Connected', ru: 'Подключено' },
  'nav.disconnected': { en: 'Disconnected', ru: 'Отключено' },
  'nav.orchestrator': { en: 'ORCHESTRATOR', ru: 'ОРКЕСТРАТОР' },

  // ── Composer: report language (NOT the interface language) ──
  'composer.reportLang.ru': { en: 'Report: RU', ru: 'Отчёт: RU' },
  'composer.reportLang.en': { en: 'Report: EN', ru: 'Отчёт: EN' },

  // Agent descriptions in side nav
  'agent.OrchestratorAgent.desc': { en: 'Master Orchestrator', ru: 'Главный оркестратор' },
  'agent.PlannerAgent.desc': { en: 'Roadmap Planner', ru: 'Планировщик задач' },
  'agent.TZSpecAgent.desc': { en: 'Technical Spec', ru: 'Техническое задание' },
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
  'settings.f.language.label': { en: 'Interface language', ru: 'Язык интерфейса' },
  'settings.f.language.desc': {
    en: 'Language of menus and hints. The report language is chosen separately, next to the message box.',
    ru: 'Язык меню и подсказок. Язык отчёта выбирается отдельно — рядом с полем ввода запроса.'
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
  'workOrder.reason.no_active_step': { en: 'no step marked in progress', ru: 'ни один шаг не отмечен как выполняемый' },
  'workStep.title': { en: 'Step check', ru: 'Проверка шага' },
  'workStep.step': { en: 'Step', ru: 'Шаг' },
  'workStep.sends': { en: 'sends', ru: 'отправит' },
  'workStep.expects': { en: 'expects', ru: 'ожидает' },
  'workStep.found': { en: 'found', ru: 'найдено' },
  'workStep.sent': { en: 'Sent', ru: 'Отправлено' },
  'workStep.expected': { en: 'Expected', ru: 'Ожидалось' },
  'workStep.foundTitle': { en: 'Found', ru: 'Найдено' },
  'workStep.calls': { en: 'Calls (recorded by the system)', ru: 'Вызовы (записаны системой)' },
  'workStep.noCalls': {
    en: 'No tool calls were recorded for this step',
    ru: 'Для этого шага не записано ни одного вызова инструмента',
  },
  'workStep.callError': { en: 'error', ru: 'ошибка' },
  'workStep.history': { en: 'Earlier rounds', ru: 'Предыдущие раунды' },
  'workStep.review.accepted': { en: 'step accepted', ru: 'шаг принят' },
  'workStep.review.revise': { en: 'sent back', ru: 'на доработке' },
  'workStep.review.rejected': { en: 'stopped', ru: 'остановлено' },
  'workStep.countdown': { en: 'Accepted automatically in {s} s', ru: 'Автоматическое принятие через {s} с' },
  'workStep.btn.redo': { en: 'Redo the step', ru: 'Переделать шаг' },
  'workStep.btn.stop': { en: 'Stop the work', ru: 'Остановить работу' },
  'workStep.ph.notes': {
    en: 'What to fix or check (required to redo the step)…',
    ru: 'Что исправить или проверить (обязательно, чтобы переделать шаг)…',
  },
  'workStep.accepted': { en: '✓ Step {step} accepted', ru: '✓ Шаг {step} принят' },
  'workStep.sentBack': { en: '↺ Step {step} sent back', ru: '↺ Шаг {step} отправлен на доработку' },
  'workStep.stopped': { en: '✗ Work stopped at step {step}', ru: '✗ Работа остановлена на шаге {step}' },

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
  'workReport.warn.unreviewed_steps': {
    en: 'Steps finished without your check: {steps}',
    ru: 'Шаги, завершённые без вашей проверки: {steps}',
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
};

/** Применяет текущий язык ко всем элементам с data-i18n / data-i18n-placeholder */
function applyLanguage(lang) {
  if (lang) currentLang = lang;
  localStorage.setItem(LANG_STORAGE_KEY, currentLang);
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
  if (nicknameEl) {
    if (activeUser && activeUser.nickname) {
      nicknameEl.textContent = activeUser.nickname;
    } else {
      const entry = i18n['nav.noUser'];
      nicknameEl.textContent = (entry && entry[currentLang]) || 'No user selected';
    }
  }
  const isWsOpen = ws && ws.readyState === 1;
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

  // The settings modal builds its fields (and the language switch) in JS.
  if (typeof renderSettings === 'function') renderSettings();

  // HITL cards compose their header text in JS (agent / tool / trigger).
  if (typeof relocalizeHitlCards === 'function') relocalizeHitlCards();

  if (typeof renderActivityRail === 'function' && typeof activityAgents !== 'undefined' && activityAgents.size) {
    renderActivityRail();
  }

  if (typeof RunTimer !== 'undefined' && typeof RunTimer.reapplyLanguage === 'function') {
    RunTimer.reapplyLanguage();
  }
}

/** Хелпер для получения перевода по ключу */
function t(key, fallback = '') {
  const entry = i18n[key];
  if (entry && entry[currentLang]) return entry[currentLang];
  return fallback || key;
}
window.t = t;

// Применяем язык при загрузке страницы (после того как DOM построится)
document.addEventListener('DOMContentLoaded', () => applyLanguage());


