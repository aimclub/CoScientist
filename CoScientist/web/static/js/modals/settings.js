// =========================================================================
// Settings Modal
// =========================================================================
// The form is rendered from SETTINGS_SECTIONS: every field names the
// appSettings path it edits, when a change takes effect and what it depends
// on. The modal edits a draft copy; nothing reaches the server until Save.

    const SETTINGS_SCOPES = {
      instant: 'bolt',
      session: 'restart_alt',
      browser: 'devices',
      reload: 'refresh',
    };

    const OPENROUTER_POPULAR_PROVIDERS = [
      'DeepInfra', 'Together', 'Fireworks', 'Groq', 'Lepton', 'Novita',
      'Chutes', 'Cerebras', 'SambaNova', 'Nebius', 'Mistral',
    ];

    // In "orchestrator plans" mode the PlannerAgent is not built at all, so its
    // own switches have nothing to act on.
    function plannerInactive(d) {
      return getSettingPath(d, 'general.startMode') === 'orchestrator_planner'
        ? { key: 'settings.inactive.noPlanner' } : null;
    }

    const SETTINGS_SECTIONS = [
      {
        id: 'research', icon: 'science',
        groups: [
          {
            fields: [
              {
                id: 'startMode', path: 'general.startMode', type: 'cards', scope: 'session', env: 'START_MODE',
                options: [
                  { value: 'planner', icon: 'account_tree' },
                  { value: 'orchestrator', icon: 'bolt' },
                  { value: 'orchestrator_planner', icon: 'alt_route' },
                ],
              },
              { id: 'contextInit', path: 'general.contextInitEnabled', type: 'toggle', scope: 'session', env: 'RESEARCH_FRAME' },
              { id: 'maxHypotheses', path: 'hypothesesAgent.maxActiveHypotheses', type: 'number', min: 1, max: 5, scope: 'session', env: 'HYPOTHESES__MAX_ACTIVE' },
            ],
          },
          {
            heading: 'planning',
            fields: [
              { id: 'critic', path: 'plannerAgent.criticEnabled', type: 'toggle', scope: 'session', env: 'PLANNER__CRITIC_ENABLED', inactive: plannerInactive },
              { id: 'criticRounds', path: 'plannerAgent.criticRounds', type: 'number', min: 1, max: 5, scope: 'session', parent: 'critic', env: 'PLANNER__CRITIC_ROUNDS', inactive: plannerInactive },
              { id: 'mergeTasks', path: 'plannerAgent.mergeTasksEnabled', type: 'toggle', scope: 'instant', env: 'PLANNER__MERGE_TASKS' },
              { id: 'plannerRetrieval', path: 'plannerAgent.retrievalEnabled', type: 'toggle', scope: 'session', env: 'PLANNER__RETRIEVAL_ENABLED', inactive: plannerInactive },
              {
                id: 'plannerGraph', path: 'plannerAgent.graphEnabled', type: 'toggle', scope: 'session', env: 'PLANNER__GRAPH_ENABLED',
                inactive: d => plannerInactive(d) || (getSettingPath(d, 'general.knowledgeGraphEnabled')
                  ? null : { key: 'settings.inactive.knowledgeGraph', section: 'graphs' }),
              },
            ],
          },
        ],
      },
      {
        id: 'interface', icon: 'palette',
        groups: [{
          fields: [
            { id: 'language', type: 'language', scope: 'browser' },
            { id: 'autoNaming', path: 'general.autoNamingEnabled', type: 'toggle', scope: 'instant', env: 'AUTO_NAMING__ENABLED' },
            { id: 'showInternal', type: 'browserToggle', scope: 'browser', env: 'SHOW_INTERNAL__ENABLED' },
          ],
        }],
      },
      {
        id: 'approvals', icon: 'verified_user',
        groups: [{
          fields: [
            { id: 'hitl', path: 'general.hitlEnabled', type: 'toggle', scope: 'session', env: 'HITL__ENABLED' },
            // -1 = no deadline, wait for the human; N > 0 = approved after N seconds.
            { id: 'hitlTimeout', path: 'general.hitlAutoApproveTimeout', type: 'timeout', fallback: 300, scope: 'instant', parent: 'hitl', env: 'HITL_AUTO_APPROVE_TIMEOUT' },
            { id: 'workOrder', path: 'general.workOrderEnabled', type: 'toggle', scope: 'session', parent: 'hitl', env: 'WORK_ORDER__ENABLED' },
            { id: 'workOrderVeto', path: 'general.workOrderVetoSeconds', type: 'timeout', fallback: 60, scope: 'instant', parent: 'workOrder', env: 'WORK_ORDER__VETO_SECONDS' },
          ],
        }],
      },
      {
        id: 'tools', icon: 'construction',
        groups: [
          {
            heading: 'search',
            fields: [
              { id: 'maxSearches', path: 'researchAgent.maxSearches', type: 'number', min: 0, max: 20, scope: 'session', env: 'RESEARCH_AGENT_SEARCHES' },
            ],
          },
          {
            heading: 'code',
            fields: [
              { id: 'coderMode', path: 'coderAgent.mode', type: 'segmented', options: ['local', 'openhands'], scope: 'session', env: 'CODER__MODE' },
              {
                id: 'sandboxUrl', path: 'coderAgent.sandboxUrl', type: 'text', mono: true, placeholder: 'http://localhost:8884', scope: 'instant', env: 'SANDBOX_URL',
                validate: d => {
                  const url = String(getSettingPath(d, 'coderAgent.sandboxUrl') || '').trim();
                  if (url && !/^https?:\/\/\S+$/i.test(url)) return { key: 'settings.err.url' };
                  if (!url && getSettingPath(d, 'coderAgent.mode') === 'openhands') return { key: 'settings.err.sandboxRequired' };
                  return null;
                },
              },
              { id: 'workspaceId', path: 'coderAgent.workspaceId', type: 'text', mono: true, placeholderKey: 'settings.f.workspaceId.placeholder', scope: 'instant', advanced: true, env: 'CODER_WORKSPACE_ID' },
            ],
          },
          {
            heading: 'toolSelection',
            fields: [
              { id: 'keepScore', path: 'taskExecutorAgent.keepScore', type: 'number', float: true, min: 0, max: 1, step: 0.05, scope: 'instant', advanced: true, env: 'EXECUTOR_TOOL_KEEP_SCORE' },
              {
                id: 'abstainScore', path: 'taskExecutorAgent.abstainScore', type: 'number', float: true, min: 0, max: 1, step: 0.05, scope: 'instant', advanced: true, env: 'EXECUTOR_TOOL_ABSTAIN_SCORE',
                validate: d => {
                  const keep = getSettingPath(d, 'taskExecutorAgent.keepScore');
                  const abstain = getSettingPath(d, 'taskExecutorAgent.abstainScore');
                  if (typeof keep === 'number' && typeof abstain === 'number' && abstain > keep) {
                    return { key: 'settings.err.abstainAboveKeep', vars: { keep } };
                  }
                  return null;
                },
              },
            ],
          },
        ],
      },
      {
        id: 'models', icon: 'memory',
        groups: [{
          fields: [
            { id: 'providerSort', path: 'general.openrouterProviderSort', type: 'segmented', options: ['default', 'price', 'latency', 'throughput'], scope: 'session', env: 'OPENROUTER_PROVIDER_SORT' },
            { id: 'providerOrder', path: 'general.openrouterProviderOrder', type: 'chips', suggestions: OPENROUTER_POPULAR_PROVIDERS, scope: 'session', env: 'OPENROUTER_PROVIDER_ORDER' },
            { id: 'maxRetries', path: 'general.maxRetries', type: 'number', min: 0, max: 10, scope: 'instant', advanced: true, env: 'LLM_MAX_RETRIES' },
          ],
        }],
      },
      {
        id: 'graphs', icon: 'hub',
        groups: [
          {
            fields: [
              { id: 'knowledgeGraph', path: 'general.knowledgeGraphEnabled', type: 'toggle', scope: 'session', env: 'GRAPH__ENABLED' },
              { id: 'researchGraph', path: 'general.researchGraphEnabled', type: 'toggle', scope: 'session' },
            ],
          },
          { heading: 'danger', fields: [{ id: 'dangerZone', type: 'danger' }] },
        ],
      },
      {
        id: 'system', icon: 'dns',
        groups: [
          {
            fields: [
              { id: 'defaultUsername', path: 'general.coscientistUsername', type: 'text', placeholderKey: 'settings.f.defaultUsername.placeholder', scope: 'reload', env: 'COSCIENTIST_USERNAME' },
              { id: 'opik', path: 'general.opikEnabled', type: 'toggle', scope: 'session', env: 'OPIK__ENABLED' },
            ],
          },
          {
            heading: 'envOnly',
            fields: [
              { id: 'useProxy', path: 'general.useProxy', type: 'env', env: 'USE_PROXY' },
              { id: 'autoClearGraph', path: 'general.autoClearGraphEnabled', type: 'env', env: 'GRAPH__AUTO_CLEAR' },
            ],
          },
        ],
      },
    ];

    const SETTINGS_FIELDS = SETTINGS_SECTIONS.flatMap(section =>
      section.groups.flatMap(group => group.fields.map(field => ({ ...field, section: section.id }))));
    const SETTINGS_FIELD_BY_ID = Object.fromEntries(SETTINGS_FIELDS.map(f => [f.id, f]));
    // Fields whose value is sent on Save (read-only .env values are not).
    const EDITABLE_TYPES = new Set(['toggle', 'number', 'text', 'cards', 'segmented', 'chips', 'timeout']);
    const TIMEOUT_MAX_SECONDS = 86400;
    // Seconds last typed into a timeout field, restored when "wait" is switched back to auto.
    const settingsLastTimeout = {};
    const EDITABLE_FIELDS = SETTINGS_FIELDS.filter(f => f.path && EDITABLE_TYPES.has(f.type));

    let settingsSaved = null;      // last values confirmed by the server
    let settingsDraft = null;      // what the form currently shows
    let settingsDefaults = null;   // values the server was launched with
    let settingsSection = 'research';
    let settingsQuery = '';
    let settingsLoadFailed = false;
    let settingsStatus = null;     // { key, vars, kind } shown in the footer
    const settingsAdvancedOpen = new Set();
    // pending: null | 'session' | 'memory' (inline confirm) | 'memory-final' (second dialog)
    const settingsDanger = { pending: null, busy: false, message: '', kind: '' };

    // ── helpers ─────────────────────────────────────────────────────────────
    function getSettingPath(obj, path) {
      return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
    }

    function setSettingPath(obj, path, value) {
      const keys = path.split('.');
      const last = keys.pop();
      const target = keys.reduce((o, k) => (o[k] = o[k] || {}), obj);
      target[last] = value;
    }

    function cloneSettings(obj) {
      return JSON.parse(JSON.stringify(obj));
    }

    function tf(key, vars) {
      let text = t(key);
      Object.entries(vars || {}).forEach(([name, value]) => {
        text = text.split(`{${name}}`).join(String(value));
      });
      return text;
    }

    function sameValue(a, b) {
      return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
    }

    function settingsModalOpen() {
      const modal = document.getElementById('settings-modal');
      return !!modal && !modal.classList.contains('hidden');
    }

    function formatSettingValue(field, value) {
      if (field.type === 'toggle' || field.type === 'env') return t(value ? 'settings.value.on' : 'settings.value.off');
      if (field.type === 'timeout') {
        return typeof value === 'number' && value > 0 ? tf('settings.timeout.after', { n: value }) : t('settings.timeout.wait');
      }
      if (value === '' || value == null) return t('settings.value.empty');
      if (field.type === 'cards' || field.type === 'segmented') {
        return t(`settings.f.${field.id}.opt.${value}`, String(value));
      }
      return String(value);
    }

    function fieldError(field, draft) {
      const value = getSettingPath(draft, field.path);
      if (field.type === 'number') {
        const bad = typeof value !== 'number' || Number.isNaN(value)
          || value < field.min || value > field.max
          || (!field.float && !Number.isInteger(value));
        if (bad) {
          return { key: field.float ? 'settings.err.rangeFloat' : 'settings.err.rangeInt', vars: { min: field.min, max: field.max } };
        }
      }
      if (field.type === 'timeout' && value !== -1) {
        if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > TIMEOUT_MAX_SECONDS) {
          return { key: 'settings.err.rangeInt', vars: { min: 1, max: TIMEOUT_MAX_SECONDS } };
        }
      }
      return field.validate ? field.validate(draft) : null;
    }

    // Children are only meaningful while their parent switch (and its parents) is on.
    function parentOff(field, draft) {
      if (!field.parent) return false;
      const parent = SETTINGS_FIELD_BY_ID[field.parent];
      return !getSettingPath(draft, parent.path) || parentOff(parent, draft);
    }

    // The switch that hides this field: the outermost parent that is off.
    function blockingParent(field, draft) {
      let blocker = null;
      for (let f = field; f.parent; ) {
        f = SETTINGS_FIELD_BY_ID[f.parent];
        if (!getSettingPath(draft, f.path)) blocker = f;
      }
      return blocker;
    }

    function dirtyFields() {
      if (!settingsDraft || !settingsSaved) return [];
      return EDITABLE_FIELDS.filter(f => !sameValue(getSettingPath(settingsDraft, f.path), getSettingPath(settingsSaved, f.path)));
    }

    function erroredFields() {
      if (!settingsDraft) return [];
      return EDITABLE_FIELDS.filter(f => !parentOff(f, settingsDraft) && fieldError(f, settingsDraft));
    }

    function fieldMatchesQuery(field, query) {
      const haystack = [
        t(`settings.f.${field.id}.label`), t(`settings.f.${field.id}.desc`), field.env || '',
      ].join(' ').toLowerCase();
      return haystack.includes(query);
    }

    // ── server sync ─────────────────────────────────────────────────────────
    function mergeServerSettings(data) {
      Object.keys(appSettings).forEach(group => {
        if (!data[group] || typeof data[group] !== 'object') return;
        Object.keys(appSettings[group]).forEach(key => {
          if (data[group][key] !== undefined && data[group][key] !== null) appSettings[group][key] = data[group][key];
        });
      });
      if (data.defaults) settingsDefaults = data.defaults;
    }

    async function loadSettings() {
      try {
        const resp = await fetch('/api/settings');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        mergeServerSettings(await resp.json());
        settingsLoadFailed = false;
        if (showInternalStored === null) setShowInternal(appSettings.general.showInternal, { remember: false });
      } catch (e) {
        settingsLoadFailed = true;
        console.warn('Failed to load settings from server:', e);
      }
      if (!activeSandboxWatchUrl) {
        updateCoderSandboxButton(null);
      }
      return !settingsLoadFailed;
    }

    // ── open / close ────────────────────────────────────────────────────────
    async function openSettings(sectionId) {
      const modal = document.getElementById('settings-modal');
      if (sectionId && SETTINGS_SECTIONS.some(s => s.id === sectionId)) settingsSection = sectionId;
      settingsQuery = '';
      document.getElementById('settings-search').value = '';
      settingsDanger.pending = null;
      settingsDanger.message = '';
      settingsStatus = { key: 'settings.status.loading', kind: 'muted' };
      settingsDraft = null;
      modal.classList.remove('hidden');
      applyLanguage();
      renderSettings();

      await loadSettings();
      settingsSaved = cloneSettings(appSettings);
      settingsDraft = cloneSettings(appSettings);
      settingsStatus = settingsLoadFailed ? { key: 'settings.status.loadFailed', kind: 'error' } : null;
      renderSettings();
    }

    function closeSettings(force = false) {
      if (!force && dirtyFields().length && !confirm(t('settings.confirmDiscard'))) return;
      document.getElementById('settings-modal').classList.add('hidden');
      settingsDraft = null;
    }

    function discardSettingsChanges() {
      if (!settingsSaved) return;
      settingsDraft = cloneSettings(settingsSaved);
      settingsStatus = null;
      renderSettings();
    }

    function resetSettingsSection(sectionId) {
      if (!settingsDefaults || !settingsDraft) return;
      EDITABLE_FIELDS.filter(f => f.section === sectionId).forEach(f => {
        const value = getSettingPath(settingsDefaults, f.path);
        if (value !== undefined) setSettingPath(settingsDraft, f.path, cloneSettings(value));
      });
      settingsStatus = null;
      renderSettings();
    }

    function selectSettingsSection(sectionId) {
      settingsSection = sectionId;
      settingsQuery = '';
      document.getElementById('settings-search').value = '';
      renderSettings();
      document.getElementById('settings-body').scrollTop = 0;
    }

    function onSettingsSearch(value) {
      settingsQuery = value.trim().toLowerCase();
      renderSettings();
    }

    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape' || !settingsModalOpen()) return;
      if (settingsDanger.pending === 'memory-final') {
        if (!settingsDanger.busy) { settingsDanger.pending = null; renderSettings(); }
        return;
      }
      closeSettings();
    });

    // ── rendering ───────────────────────────────────────────────────────────
    function renderSettings() {
      if (!settingsModalOpen()) return;
      renderSettingsNav();
      const body = document.getElementById('settings-body');
      body.innerHTML = settingsDraft
        ? (settingsQuery ? renderSettingsSearch() : renderSettingsSection(SETTINGS_SECTIONS.find(s => s.id === settingsSection)))
        : `<p class="text-xs text-outline-variant">${escHtml(t('settings.status.loading'))}</p>`;
      decorateSettings();
      renderSettingsDialog();
    }

    function renderSettingsNav() {
      const nav = document.getElementById('settings-nav');
      nav.innerHTML = SETTINGS_SECTIONS.map(section => {
        const active = !settingsQuery && section.id === settingsSection;
        return `
          <button type="button" data-action="section" data-section="${section.id}"
            class="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-left text-xs transition-colors
              ${active ? 'bg-primary/10 text-primary font-semibold' : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'}">
            <span class="material-symbols-outlined text-base">${section.icon}</span>
            <span class="flex-1 truncate">${escHtml(t(`settings.section.${section.id}`))}</span>
            <span data-nav-marker="${section.id}" class="w-1.5 h-1.5 rounded-full hidden"></span>
          </button>`;
      }).join('');
    }

    function renderSettingsSection(section) {
      const hasEditable = EDITABLE_FIELDS.some(f => f.section === section.id);
      const resetBtn = hasEditable && settingsDefaults ? `
        <button type="button" data-action="reset-section" data-section="${section.id}" title="${escHtml(t('settings.resetHint'))}"
          class="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] text-on-surface-variant border border-outline-variant/20 hover:text-on-surface hover:bg-surface-container-high transition-colors">
          <span class="material-symbols-outlined text-sm">settings_backup_restore</span>${escHtml(t('settings.reset'))}
        </button>` : '';
      return `
        <div class="flex items-start justify-between gap-4 mb-1">
          <div>
            <h4 class="font-headline text-base font-bold text-on-surface">${escHtml(t(`settings.section.${section.id}`))}</h4>
            <p class="text-xs text-on-surface-variant/80 mt-0.5">${escHtml(t(`settings.section.${section.id}.desc`))}</p>
          </div>
          ${resetBtn}
        </div>
        <p class="flex items-center gap-1.5 text-[11px] text-outline-variant/80 mb-5">
          <span class="material-symbols-outlined text-sm">info</span>${escHtml(t('settings.banner'))}
        </p>
        <div class="space-y-6">
          ${section.groups.map((group, i) => renderSettingsGroup(group, `${section.id}:${i}`)).join('')}
        </div>`;
    }

    function renderSettingsGroup(group, groupKey) {
      const visible = group.fields.filter(f => !parentOff(f, settingsDraft));
      const basic = visible.filter(f => !f.advanced);
      const advanced = visible.filter(f => f.advanced);
      // Keep the advanced block open while one of its fields needs fixing.
      const open = settingsAdvancedOpen.has(groupKey) || advanced.some(f => fieldError(f, settingsDraft));
      const heading = group.heading ? `
        <div class="mb-2">
          <h5 class="text-[11px] font-bold uppercase tracking-widest font-headline ${group.heading === 'danger' ? 'text-error' : 'text-outline-variant'}">
            ${escHtml(t(`settings.group.${group.heading}`))}</h5>
          ${i18n[`settings.group.${group.heading}.desc`] ? `<p class="text-[11px] text-outline-variant/80 mt-0.5">${escHtml(t(`settings.group.${group.heading}.desc`))}</p>` : ''}
        </div>` : '';
      const advancedBlock = advanced.length ? `
        <button type="button" data-action="toggle-advanced" data-group="${groupKey}"
          class="flex items-center gap-1 px-4 py-2.5 w-full text-left text-[11px] font-semibold text-outline-variant hover:text-on-surface transition-colors ${basic.length ? 'border-t border-outline-variant/10' : ''}">
          <span class="material-symbols-outlined text-sm">${open ? 'expand_less' : 'expand_more'}</span>
          ${escHtml(tf('settings.advanced', { n: advanced.length }))}
        </button>
        ${open ? advanced.map(f => renderSettingRow(f)).join('') : ''}` : '';
      if (group.heading === 'danger') {
        return `<section>${heading}${renderDangerZone()}</section>`;
      }
      return `
        <section>
          ${heading}
          <div class="bg-surface-container-lowest rounded-lg border border-outline-variant/10 divide-y divide-outline-variant/10">
            ${basic.map(f => renderSettingRow(f)).join('')}
            ${advancedBlock}
          </div>
        </section>`;
    }

    function renderSettingsSearch() {
      const blocks = SETTINGS_SECTIONS.map(section => {
        const matches = SETTINGS_FIELDS.filter(f => f.section === section.id && f.type !== 'danger' && fieldMatchesQuery(f, settingsQuery));
        if (!matches.length) return '';
        return `
          <section>
            <button type="button" data-action="section" data-section="${section.id}"
              class="mb-2 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest font-headline text-outline-variant hover:text-primary">
              <span class="material-symbols-outlined text-sm">${section.icon}</span>${escHtml(t(`settings.section.${section.id}`))}
            </button>
            <div class="bg-surface-container-lowest rounded-lg border border-outline-variant/10 divide-y divide-outline-variant/10">
              ${matches.map(f => renderSettingRow(f, { search: true })).join('')}
            </div>
          </section>`;
      }).join('');
      return blocks
        ? `<div class="space-y-6">${blocks}</div>`
        : `<p class="text-xs text-outline-variant py-8 text-center">${escHtml(t('settings.noResults'))}</p>`;
    }

    function renderSettingRow(field, opts = {}) {
      let inactive = field.inactive ? field.inactive(settingsDraft) : null;
      if (!inactive && opts.search && parentOff(field, settingsDraft)) {
        const parent = blockingParent(field, settingsDraft);
        inactive = { key: 'settings.inactive.parentOff', vars: { parent: t(`settings.f.${parent.id}.label`) }, section: parent.section };
      }
      const disabled = !!inactive;
      const label = escHtml(t(`settings.f.${field.id}.label`));
      const desc = i18n[`settings.f.${field.id}.desc`] ? t(`settings.f.${field.id}.desc`) : '';
      const wide = field.type === 'cards' || field.type === 'chips';
      const scopeHint = field.scope ? `${t(`settings.scope.${field.scope}`)} — ${t(`settings.scope.${field.scope}.hint`)}` : '';
      const scope = field.scope ? `
        <span class="material-symbols-outlined text-[14px] text-outline-variant/70 cursor-help"
          role="img" aria-label="${escHtml(scopeHint)}" title="${escHtml(scopeHint)}">${SETTINGS_SCOPES[field.scope]}</span>` : '';
      let envHint = field.env ? tf('settings.envVar', { name: field.env }) : '';
      if (envHint && i18n[`settings.f.${field.id}.envValues`]) {
        envHint += '\n' + t('settings.envValues') + '\n' + t(`settings.f.${field.id}.envValues`);
      }
      const envInfo = field.env && field.type !== 'env' ? `
        <span class="material-symbols-outlined text-[14px] text-outline-variant/60 cursor-help"
          role="img" aria-label="${escHtml(envHint)}" title="${escHtml(envHint)}">info</span>` : '';
      const inactiveNote = inactive ? `
        <p class="text-[11px] text-tertiary/90 mt-1.5 flex items-center gap-1 flex-wrap">
          <span class="material-symbols-outlined text-sm">block</span>${escHtml(tf(inactive.key, inactive.vars))}
          ${inactive.section ? `<button type="button" data-action="section" data-section="${inactive.section}" class="underline hover:text-on-surface">${escHtml(t('settings.goto'))}</button>` : ''}
        </p>` : '';
      const control = renderSettingControl(field, disabled);
      return `
        <div data-row="${field.id}" class="relative px-4 py-3.5 border-l-2 border-l-transparent ${field.parent && !opts.search ? 'pl-8' : ''}">
          <div class="${wide ? 'space-y-3' : 'flex items-start justify-between gap-6'}">
            <div class="min-w-0 ${disabled ? 'opacity-60' : ''}">
              <div class="flex items-center gap-2 flex-wrap">
                <label for="sf-${field.id}" class="text-[13px] font-semibold text-on-surface">${label}</label>
                <span data-default-marker class="hidden w-1.5 h-1.5 rounded-full bg-primary/70"></span>
                ${scope}${envInfo}
              </div>
              ${desc ? `<p class="text-[11.5px] text-on-surface-variant/75 mt-1 leading-relaxed">${desc}</p>` : ''}
              ${inactiveNote}
              <p data-error class="hidden text-[11px] text-error mt-1.5 flex items-center gap-1"></p>
            </div>
            <div class="${wide ? '' : 'shrink-0 pt-0.5'} ${disabled ? 'opacity-50 pointer-events-none' : ''}">${control}</div>
          </div>
        </div>`;
    }

    function renderSettingControl(field, disabled) {
      const value = field.path ? getSettingPath(settingsDraft, field.path) : undefined;
      const dis = disabled ? 'disabled' : '';
      const inputCls = 'bg-surface-container-high border border-outline-variant/20 text-on-surface text-xs rounded-md px-3 py-2 focus:ring-1 focus:ring-primary/40 focus:border-primary/40 disabled:cursor-not-allowed';
      switch (field.type) {
        case 'toggle':
          return `
            <label class="relative inline-flex items-center cursor-pointer">
              <input id="sf-${field.id}" type="checkbox" data-field="${field.id}" class="sr-only peer" ${value ? 'checked' : ''} ${dis} />
              <span class="w-10 h-6 rounded-full bg-surface-variant border border-outline-variant/30 peer-checked:bg-primary peer-checked:border-primary transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-primary/50"></span>
              <span class="absolute left-1 top-1 w-4 h-4 rounded-full bg-on-surface-variant peer-checked:bg-on-primary peer-checked:translate-x-4 transition-transform"></span>
            </label>`;
        case 'timeout': {
          const auto = value !== -1;
          return `
            <div class="flex flex-col items-end gap-2">
              <div id="sf-${field.id}" role="radiogroup" class="inline-flex gap-0.5 p-0.5 rounded-md bg-surface-container-high border border-outline-variant/20">
                ${[['wait', !auto], ['auto', auto]].map(([mode, selected]) => `
                  <button type="button" role="radio" aria-checked="${selected}" data-action="timeout-mode" data-field="${field.id}" data-mode="${mode}" ${dis}
                    class="px-3 py-1.5 rounded text-[11px] font-semibold transition-colors ${selected ? 'bg-primary text-on-primary' : 'text-on-surface-variant hover:text-on-surface'}">
                    ${escHtml(t(`settings.timeout.mode.${mode}`))}
                  </button>`).join('')}
              </div>
              ${auto ? `
                <label class="flex items-center gap-2 text-[11px] text-on-surface-variant">
                  ${escHtml(t('settings.timeout.after.label'))}
                  <input type="number" inputmode="numeric" data-field="${field.id}" data-timeout-seconds min="1" max="${TIMEOUT_MAX_SECONDS}" step="1"
                    value="${escHtml(value ?? '')}" ${dis} aria-label="${escHtml(t('settings.timeout.after.label'))}"
                    class="${inputCls} font-mono w-24 text-center" />
                  ${escHtml(t('settings.timeout.seconds'))}
                </label>` : ''}
            </div>`;
        }
        case 'number':
          return `<input id="sf-${field.id}" type="number" inputmode="${field.float ? 'decimal' : 'numeric'}" data-field="${field.id}"
            min="${field.min}" max="${field.max}" step="${field.step || 1}" value="${escHtml(value ?? '')}" ${dis}
            class="${inputCls} font-mono w-24 text-center" />`;
        case 'text':
          return `<input id="sf-${field.id}" type="text" data-field="${field.id}" value="${escHtml(value ?? '')}" ${dis}
            placeholder="${escHtml(field.placeholderKey ? t(field.placeholderKey) : (field.placeholder || ''))}"
            class="${inputCls} ${field.mono ? 'font-mono' : ''} w-64" />`;
        case 'segmented':
          return `
            <div id="sf-${field.id}" role="radiogroup" class="inline-flex flex-wrap gap-0.5 p-0.5 rounded-md bg-surface-container-high border border-outline-variant/20">
              ${field.options.map(opt => `
                <button type="button" role="radio" aria-checked="${value === opt}" data-action="choose" data-field="${field.id}" data-value="${opt}" ${dis}
                  class="px-3 py-1.5 rounded text-[11px] font-semibold transition-colors ${value === opt ? 'bg-primary text-on-primary' : 'text-on-surface-variant hover:text-on-surface'}">
                  ${escHtml(t(`settings.f.${field.id}.opt.${opt}`, opt))}
                </button>`).join('')}
            </div>`;
        case 'cards':
          return `
            <div id="sf-${field.id}" role="radiogroup" class="grid grid-cols-1 sm:grid-cols-3 gap-2">
              ${field.options.map(opt => {
                const selected = value === opt.value;
                return `
                  <button type="button" role="radio" aria-checked="${selected}" data-action="choose" data-field="${field.id}" data-value="${opt.value}" ${dis}
                    class="text-left p-3 rounded-lg border transition-colors ${selected ? 'border-primary bg-primary/10' : 'border-outline-variant/20 hover:border-outline-variant/50 hover:bg-surface-container-high'}">
                    <span class="flex items-center gap-2">
                      <span class="material-symbols-outlined text-base ${selected ? 'text-primary' : 'text-outline-variant'}">${opt.icon}</span>
                      <span class="text-xs font-semibold text-on-surface">${escHtml(t(`settings.f.${field.id}.opt.${opt.value}`))}</span>
                    </span>
                    <span class="block text-[11px] text-on-surface-variant/75 mt-1.5 leading-snug">${escHtml(t(`settings.f.${field.id}.opt.${opt.value}.desc`))}</span>
                    <span class="block text-[10px] font-mono text-outline-variant mt-2">${escHtml(t(`settings.f.${field.id}.opt.${opt.value}.flow`))}</span>
                  </button>`;
              }).join('')}
            </div>`;
        case 'chips': {
          const items = String(value || '').split(',').map(s => s.trim()).filter(Boolean);
          const listId = `sf-${field.id}-suggestions`;
          return `
            <div class="flex flex-wrap items-center gap-1.5 p-1.5 rounded-md bg-surface-container-high border border-outline-variant/20 focus-within:border-primary/40">
              ${items.map((item, i) => `
                <span class="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded bg-primary/10 border border-primary/20 text-[11px] text-on-surface">
                  <span class="text-[10px] text-outline-variant font-mono">${i + 1}</span>${escHtml(item)}
                  <button type="button" data-action="chip-remove" data-field="${field.id}" data-index="${i}" aria-label="remove"
                    class="material-symbols-outlined text-sm text-outline-variant hover:text-error">close</button>
                </span>`).join('')}
              <input id="sf-${field.id}" type="text" data-chips="${field.id}" list="${listId}" ${dis}
                placeholder="${escHtml(t('settings.f.providerOrder.placeholder'))}"
                class="flex-1 min-w-[10rem] bg-transparent border-0 text-xs text-on-surface px-1 py-1 focus:ring-0" />
              <datalist id="${listId}">
                ${field.suggestions.filter(s => !items.includes(s)).map(s => `<option value="${escHtml(s)}"></option>`).join('')}
              </datalist>
            </div>`;
        }
        case 'browserToggle':
          return `
            <label class="relative inline-flex items-center cursor-pointer">
              <input id="sf-${field.id}" type="checkbox" data-browser-toggle="${field.id}" class="sr-only peer" ${showInternal ? 'checked' : ''} />
              <span class="w-10 h-6 rounded-full bg-surface-variant border border-outline-variant/30 peer-checked:bg-primary peer-checked:border-primary transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-primary/50"></span>
              <span class="absolute left-1 top-1 w-4 h-4 rounded-full bg-on-surface-variant peer-checked:bg-on-primary peer-checked:translate-x-4 transition-transform"></span>
            </label>`;
        case 'language':
          return `
            <div role="radiogroup" class="inline-flex gap-0.5 p-0.5 rounded-md bg-surface-container-high border border-outline-variant/20">
              ${['ru', 'en'].map(lang => `
                <button type="button" role="radio" aria-checked="${currentLang === lang}" data-action="language" data-lang="${lang}"
                  class="px-3 py-1.5 rounded text-[11px] font-semibold transition-colors ${currentLang === lang ? 'bg-primary text-on-primary' : 'text-on-surface-variant hover:text-on-surface'}">
                  ${lang === 'ru' ? 'Русский' : 'English'}
                </button>`).join('')}
            </div>`;
        case 'env':
          return `
            <div class="text-right">
              <span class="inline-block px-2 py-1 rounded text-[11px] font-semibold ${value ? 'bg-secondary/10 text-secondary' : 'bg-surface-container-high text-outline-variant'}">
                ${escHtml(formatSettingValue(field, value))}</span>
              <p class="text-[10px] font-mono text-outline-variant mt-1">${escHtml(field.env)}</p>
            </div>`;
        default:
          return '';
      }
    }

    // Markers that change while typing — updated in place so inputs keep focus.
    function decorateSettings() {
      const body = document.getElementById('settings-body');
      if (settingsDraft) {
        body.querySelectorAll('[data-row]').forEach(row => {
          const field = SETTINGS_FIELD_BY_ID[row.dataset.row];
          if (!field.path || !EDITABLE_TYPES.has(field.type)) return;
          const draftValue = getSettingPath(settingsDraft, field.path);
          const dirty = !sameValue(draftValue, getSettingPath(settingsSaved, field.path));
          row.classList.toggle('border-l-primary', dirty);
          row.classList.toggle('bg-primary/[0.03]', dirty);

          const marker = row.querySelector('[data-default-marker]');
          const defaultValue = settingsDefaults ? getSettingPath(settingsDefaults, field.path) : undefined;
          const differs = defaultValue !== undefined && !sameValue(draftValue, defaultValue);
          marker.classList.toggle('hidden', !differs);
          marker.title = differs ? tf('settings.differsDefault', { value: formatSettingValue(field, defaultValue) }) : '';

          const errorEl = row.querySelector('[data-error]');
          const error = fieldError(field, settingsDraft);
          errorEl.classList.toggle('hidden', !error);
          errorEl.innerHTML = error ? `<span class="material-symbols-outlined text-sm">error</span>${escHtml(tf(error.key, error.vars))}` : '';
        });
      }

      const dirty = dirtyFields();
      const errors = erroredFields();
      SETTINGS_SECTIONS.forEach(section => {
        const marker = document.querySelector(`[data-nav-marker="${section.id}"]`);
        if (!marker) return;
        const hasError = errors.some(f => f.section === section.id);
        const hasDirty = dirty.some(f => f.section === section.id);
        marker.classList.toggle('hidden', !hasError && !hasDirty);
        marker.classList.toggle('bg-error', hasError);
        marker.classList.toggle('bg-primary', !hasError && hasDirty);
      });

      const status = document.getElementById('settings-status');
      let message;
      let kind;
      if (errors.length) {
        message = tf('settings.status.errors', { n: errors.length });
        kind = 'error';
      } else if (dirty.length) {
        message = tf('settings.status.dirty', { n: dirty.length });
        kind = 'primary';
      } else if (settingsStatus) {
        message = tf(settingsStatus.key, settingsStatus.vars);
        kind = settingsStatus.kind;
      } else {
        message = t('settings.status.clean');
        kind = 'muted';
      }
      status.textContent = message;
      status.className = 'text-[11px] flex-1 min-w-0 truncate ' + ({
        error: 'text-error', primary: 'text-primary', success: 'text-secondary', muted: 'text-outline-variant',
      }[kind] || 'text-outline-variant');

      document.getElementById('settings-save-btn').disabled = !settingsDraft || !dirty.length || errors.length > 0;
      document.getElementById('settings-discard-btn').disabled = !dirty.length;
    }

    // ── editing ─────────────────────────────────────────────────────────────
    function updateSettingDraft(field, value, rerender) {
      setSettingPath(settingsDraft, field.path, value);
      settingsStatus = null;
      if (rerender) renderSettings();
      else decorateSettings();
    }

    function parseSettingNumber(raw) {
      if (String(raw).trim() === '') return '';
      const num = Number(raw);
      return Number.isNaN(num) ? String(raw) : num;
    }

    function addProviderChip(field, input) {
      const name = input.value.replace(/,/g, ' ').trim();
      if (!name) return;
      const items = String(getSettingPath(settingsDraft, field.path) || '').split(',').map(s => s.trim()).filter(Boolean);
      if (!items.some(item => item.toLowerCase() === name.toLowerCase())) items.push(name);
      updateSettingDraft(field, items.join(', '), true);
      document.getElementById(`sf-${field.id}`)?.focus();
    }

    function initSettingsEvents() {
      const modal = document.getElementById('settings-modal');
      if (!modal || modal.dataset.bound) return;
      modal.dataset.bound = '1';
      const body = document.getElementById('settings-body');

      modal.addEventListener('click', (e) => {
        if (e.target === modal) { closeSettings(); return; }
        const btn = e.target.closest('[data-action]');
        if (!btn || btn.disabled) return;
        const field = SETTINGS_FIELD_BY_ID[btn.dataset.field];
        switch (btn.dataset.action) {
          case 'section': selectSettingsSection(btn.dataset.section); break;
          case 'reset-section': resetSettingsSection(btn.dataset.section); break;
          case 'toggle-advanced': {
            const key = btn.dataset.group;
            if (settingsAdvancedOpen.has(key)) settingsAdvancedOpen.delete(key); else settingsAdvancedOpen.add(key);
            renderSettings();
            break;
          }
          case 'choose': updateSettingDraft(field, btn.dataset.value, true); break;
          case 'timeout-mode': {
            const current = getSettingPath(settingsDraft, field.path);
            if (btn.dataset.mode === 'wait') {
              if (current !== -1) settingsLastTimeout[field.id] = current;
              updateSettingDraft(field, -1, true);
            } else if (current === -1) {
              updateSettingDraft(field, settingsLastTimeout[field.id] ?? field.fallback, true);
              body.querySelector(`[data-field="${field.id}"][data-timeout-seconds]`)?.focus();
            }
            break;
          }
          case 'chip-remove': {
            const items = String(getSettingPath(settingsDraft, field.path) || '').split(',').map(s => s.trim()).filter(Boolean);
            items.splice(Number(btn.dataset.index), 1);
            updateSettingDraft(field, items.join(', '), true);
            break;
          }
          case 'language': applyLanguage(btn.dataset.lang); break;
          case 'danger-ask': settingsDanger.pending = btn.dataset.target; settingsDanger.message = ''; renderSettings(); break;
          case 'danger-cancel': settingsDanger.pending = null; renderSettings(); break;
          case 'danger-confirm':
            if (settingsDanger.pending === 'memory') { settingsDanger.pending = 'memory-final'; renderSettings(); }
            else deleteGraphData(settingsDanger.pending);
            break;
          case 'danger-final': deleteGraphData('memory'); break;
        }
      });

      body.addEventListener('change', (e) => {
        // Browser-only switches apply at once, like the language: no draft, no Save.
        if (e.target.dataset.browserToggle === 'showInternal') {
          setShowInternal(e.target.checked);
          return;
        }
        const field = SETTINGS_FIELD_BY_ID[e.target.dataset.field];
        if (field && field.type === 'toggle') updateSettingDraft(field, e.target.checked, true);
      });

      body.addEventListener('input', (e) => {
        const el = e.target;
        const field = SETTINGS_FIELD_BY_ID[el.dataset.field];
        if (!field) return;
        if (field.type === 'number' || field.type === 'timeout') updateSettingDraft(field, parseSettingNumber(el.value), false);
        else if (field.type === 'text') updateSettingDraft(field, el.value, false);
      });

      body.addEventListener('keydown', (e) => {
        const field = SETTINGS_FIELD_BY_ID[e.target.dataset.chips];
        if (!field) return;
        if (e.key === 'Enter' || e.key === ',') {
          e.preventDefault();
          addProviderChip(field, e.target);
        } else if (e.key === 'Backspace' && !e.target.value) {
          const items = String(getSettingPath(settingsDraft, field.path) || '').split(',').map(s => s.trim()).filter(Boolean);
          if (!items.length) return;
          items.pop();
          updateSettingDraft(field, items.join(', '), true);
          document.getElementById(`sf-${field.id}`)?.focus();
        }
      });

      // Picking a suggestion from the datalist fires no keydown — add it on blur.
      body.addEventListener('focusout', (e) => {
        const field = SETTINGS_FIELD_BY_ID[e.target.dataset.chips];
        if (field && e.target.value.trim()) addProviderChip(field, e.target);
      });
    }

    // ── saving ──────────────────────────────────────────────────────────────
    async function saveSettings() {
      if (!settingsDraft || erroredFields().length) return;
      const changed = dirtyFields();
      if (!changed.length) return;

      const payload = {};
      EDITABLE_FIELDS.forEach(f => {
        let value = getSettingPath(settingsDraft, f.path);
        if (typeof value === 'string') value = value.trim();
        setSettingPath(payload, f.path, value);
      });

      const saveBtn = document.getElementById('settings-save-btn');
      saveBtn.disabled = true;
      const status = document.getElementById('settings-status');
      status.textContent = t('settings.status.saving');
      status.className = 'text-[11px] flex-1 min-w-0 truncate text-primary/70 animate-pulse';

      try {
        const resp = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error(await fetchErrorMessage(resp));
        mergeServerSettings(await resp.json());
        settingsSaved = cloneSettings(appSettings);
        settingsDraft = cloneSettings(appSettings);
        addTelemetry('SETTINGS :: saved ' + changed.map(f => f.id).join(', '));
        if (!activeSandboxWatchUrl) updateCoderSandboxButton(null);

        let key = 'settings.status.saved';
        if (changed.some(f => f.scope === 'session')) key = 'settings.status.savedSession';
        else if (changed.some(f => f.scope === 'reload')) key = 'settings.status.savedReload';
        settingsStatus = { key, kind: 'success' };
      } catch (e) {
        settingsStatus = { key: 'settings.status.saveFailed', vars: { error: e.message || e }, kind: 'error' };
      }
      renderSettings();
      // An error status would otherwise be hidden behind the unsaved-changes count.
      if (settingsStatus.kind === 'error') {
        status.textContent = tf(settingsStatus.key, settingsStatus.vars);
        status.className = 'text-[11px] flex-1 min-w-0 truncate text-error';
      }
    }

    // ── danger zone ─────────────────────────────────────────────────────────
    function renderDangerZone() {
      const session = activeSession ? (activeSession.title || activeSession.id) : '';
      const noSession = !activeUser || !activeSession;
      const btnCls = 'shrink-0 px-3 py-2 rounded-md text-[11px] font-bold uppercase tracking-wider border border-error/30 text-error hover:bg-error/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5';
      const row = (target, icon) => {
        const pending = settingsDanger.pending === target || (target === 'memory' && settingsDanger.pending === 'memory-final');
        let confirmBlock = '';
        if (pending) {
          confirmBlock = `
            <div class="mt-3 p-3 rounded-md bg-error-container/20 border border-error/20 space-y-2">
              <p class="text-[11.5px] text-on-surface">${escHtml(tf(`settings.danger.${target}.confirm`, { name: session }))}</p>
              <div class="flex flex-wrap items-center gap-2">
                <button type="button" id="settings-danger-confirm" data-action="danger-confirm" ${settingsDanger.busy ? 'disabled' : ''}
                  class="px-3 py-1.5 rounded-md text-[11px] font-bold bg-error text-on-error hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed">
                  ${escHtml(t('settings.danger.confirmBtn'))}</button>
                <button type="button" data-action="danger-cancel" ${settingsDanger.busy ? 'disabled' : ''}
                  class="px-3 py-1.5 rounded-md text-[11px] text-on-surface-variant hover:text-on-surface">${escHtml(t('settings.danger.cancel'))}</button>
              </div>
            </div>`;
        }
        return `
          <div class="px-4 py-3.5">
            <div class="flex items-start justify-between gap-6">
              <div class="min-w-0">
                <p class="text-[13px] font-semibold text-on-surface">${escHtml(t(`settings.danger.${target}.label`))}</p>
                <p class="text-[11.5px] text-on-surface-variant/75 mt-1 leading-relaxed">${escHtml(t(`settings.danger.${target}.desc`))}</p>
                ${noSession ? `<p class="text-[11px] text-tertiary/90 mt-1.5">${escHtml(t('settings.danger.noSession'))}</p>` : ''}
              </div>
              <button type="button" data-action="danger-ask" data-target="${target}" ${noSession || pending || settingsDanger.busy ? 'disabled' : ''} class="${btnCls}">
                <span class="material-symbols-outlined text-sm">${icon}</span>${escHtml(t(`settings.danger.${target}.btn`))}
              </button>
            </div>
            ${confirmBlock}
          </div>`;
      };
      const message = settingsDanger.message ? `
        <p class="px-4 py-2.5 text-[11px] font-mono ${settingsDanger.kind === 'error' ? 'text-error' : settingsDanger.kind === 'busy' ? 'text-primary/70 animate-pulse' : 'text-secondary'}">
          ${escHtml(settingsDanger.message)}</p>` : '';
      return `
        <div class="rounded-lg border border-error/25 divide-y divide-error/15 bg-surface-container-lowest">
          ${row('session', 'layers_clear')}
          ${row('memory', 'delete_forever')}
          ${message}
        </div>`;
    }

    // The global memory takes a second, separate "are you sure" window: it is
    // gone for every session at once, so one misclick must not be enough.
    function renderSettingsDialog() {
      const dialog = document.getElementById('settings-dialog');
      const open = settingsModalOpen() && settingsDanger.pending === 'memory-final';
      dialog.classList.toggle('hidden', !open);
      if (!open) { dialog.innerHTML = ''; return; }
      dialog.innerHTML = `
        <div role="alertdialog" aria-modal="true" aria-labelledby="settings-dialog-title" aria-describedby="settings-dialog-text"
          class="w-full max-w-md mx-4 rounded-xl border border-error/30 bg-surface-container shadow-2xl p-5">
          <div class="flex items-start gap-3">
            <span class="material-symbols-outlined text-error text-2xl">warning</span>
            <div class="min-w-0">
              <h4 id="settings-dialog-title" class="font-headline text-sm font-bold text-on-surface">${escHtml(t('settings.danger.memory.finalTitle'))}</h4>
              <p id="settings-dialog-text" class="text-xs text-on-surface-variant mt-2 leading-relaxed">${escHtml(t('settings.danger.memory.finalText'))}</p>
            </div>
          </div>
          <div class="flex justify-end gap-2 mt-5">
            <button type="button" data-action="danger-cancel" ${settingsDanger.busy ? 'disabled' : ''}
              class="px-4 py-2 rounded-md text-[11px] font-bold bg-surface-container-high border border-outline-variant/20 text-on-surface hover:bg-surface-variant/40">
              ${escHtml(t('settings.danger.cancel'))}</button>
            <button type="button" id="settings-dialog-confirm" data-action="danger-final" ${settingsDanger.busy ? 'disabled' : ''}
              class="px-4 py-2 rounded-md text-[11px] font-bold bg-error text-on-error hover:brightness-110 disabled:opacity-40">
              ${escHtml(t('settings.danger.memory.finalBtn'))}</button>
          </div>
        </div>`;
      // Safe default: Enter/Space on the focused button cancels.
      dialog.querySelector('[data-action="danger-cancel"]').focus();
    }

    function describeGraphDeletion(deleted) {
      return Object.entries(deleted || {}).map(([name, info]) => {
        if (info && info.error) return `${name} failed (${info.error})`;
        if (name === 'memory') {
          return `${name} (${info.entities || 0} entities, ${info.relations || 0} relations)`;
        }
        return name;
      }).join(', ');
    }

    // "session" wipes both per-session graphs; "memory" is the installation-wide
    // knowledge memory. Each view is its own DELETE so a failure names which one.
    async function deleteGraphData(target) {
      const views = target === 'memory' ? ['memory'] : ['execution', 'research'];
      settingsDanger.busy = true;
      settingsDanger.message = t('settings.danger.deleting');
      settingsDanger.kind = 'busy';
      renderSettings();
      const done = [];
      try {
        for (const view of views) {
          const response = await fetch(sessionApi(`/graph?view=${encodeURIComponent(view)}`), { method: 'DELETE' });
          let data = {};
          try { data = await response.json(); } catch (_) { /* empty response */ }
          if (!response.ok) {
            throw new Error(data.detail || describeGraphDeletion(data.deleted) || `HTTP ${response.status}`);
          }
          const described = describeGraphDeletion(data.deleted);
          if (described) done.push(described);
        }
        settingsDanger.message = tf('settings.danger.done', { what: done.join(', ') || t('settings.danger.nothing') });
        settingsDanger.kind = 'success';
        addTelemetry(`GRAPHS :: deleted ${views.join(', ')}`);
      } catch (error) {
        const prefix = done.length ? tf('settings.danger.done', { what: done.join(', ') }) + ' ' : '';
        settingsDanger.message = prefix + tf('settings.danger.failed', { error: error.message || error });
        settingsDanger.kind = 'error';
      } finally {
        settingsDanger.busy = false;
        settingsDanger.pending = null;
        renderSettings();
      }
    }

    initSettingsEvents();
