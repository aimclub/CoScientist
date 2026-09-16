// =========================================================================
// HITL UI
// =========================================================================
    // =========================================================================
    // HITL UI
    // =========================================================================
    // Internal-loop HITL requests arrive with a fixed English message
    // ("Agent 'X' proposes its result. Please review.", legacy ones carry an
    // "[INTERNAL_LOOP: ...]" prefix). Show a localized version instead.
    const INTERNAL_LOOP_RE = /^(?:\[INTERNAL_LOOP:[^\]]*\]\s*)?Agent '([^']+)' proposes its result\. Please review\.?\s*$/;
    function localizeHitlMessage(message) {
      const m = INTERNAL_LOOP_RE.exec(message || '');
      if (!m) return message;
      return t('hitl.internalLoop').replace('{agent}', m[1]);
    }

    function showHITL(data) {
      const panel = document.getElementById('hitl-panel');
      const feed = document.getElementById('chat-feed');

      // Structured intake (e.g. the research frame): render a per-field form
      // instead of the free-text review, then stop — the other HITL points keep
      // the free-text / option path below.
      if (data.form && Array.isArray(data.form.blocks)) {
        renderHitlForm(panel, feed, data);
        scrollChat();
        return;
      }

      // An experiment plan is not a paragraph to skim: it is a design matrix
      // and a task list, and it is what the human is being asked to approve.
      // The backend ships it structured next to the rendered Markdown, so it
      // gets a view of its own rather than a <pre> of pipe-separated rows.
      const plan = data.context && data.context.experiment_plan;
      if (plan && Array.isArray(plan.tasks)) {
        renderExperimentPlanReview(panel, data, plan);
        scrollChat();
        return;
      }

      let openRoadmapSidebarBtn = '';
      let openRoadmapChatBtn = '';
      if (data.agent_name === 'PlannerAgent') {
        openRoadmapSidebarBtn = `
      <button onclick="openRoadmapEditor()" class="w-full mt-2 flex items-center justify-center gap-2 bg-surface-variant border border-outline-variant/20 text-on-surface py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-high transition-all">
        <span class="material-symbols-outlined text-sm">map</span> Open Roadmap
      </button>
    `;
        openRoadmapChatBtn = `
      <div class="mt-4 pl-11">
        <button onclick="openRoadmapEditor()" class="flex items-center justify-center gap-2 bg-surface-variant border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-wider hover:bg-surface-container-high transition-all">
          <span class="material-symbols-outlined text-sm">map</span> Open Roadmap
        </button>
      </div>
    `;
      }

      const isProvideInput = data.action_type === 'provide_input';
      const hasOptions = !!(data.options && data.options.length);

      // Show in sidebar. For question windows (options present) or input requests the sidebar is
      // informational only — answer directly in the chat card.
      const sidebarButtons = (hasOptions || isProvideInput) ? `
        <p class="text-[10px] text-outline-variant leading-relaxed">Ответьте в карточке в чате.</p>` : `
        <div class="flex gap-3">
          <button onclick="respondHITL('${data.request_id}', true)" class="flex-1 flex items-center justify-center gap-2 bg-primary text-on-primary py-3 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
            <span class="material-symbols-outlined text-base">check_circle</span> Accept
          </button>
          <button onclick="respondHITL('${data.request_id}', false)" class="flex-1 flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error py-3 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-error/10 transition-all">
            <span class="material-symbols-outlined text-base">close</span> Reject
          </button>
        </div>`;
      panel.classList.remove('hidden');
      panel.innerHTML = `
    <div class="relative">
      <div class="absolute -inset-2 bg-gradient-to-r from-primary/10 via-transparent to-primary/10 blur-2xl opacity-40"></div>
      <div class="relative bg-surface-container-lowest p-6 rounded-xl border border-primary/30 shadow-2xl flex flex-col gap-4">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
            <span class="material-symbols-outlined text-on-primary text-sm">ads_click</span>
          </div>
          <h3 class="font-headline font-bold text-on-surface text-sm uppercase tracking-tight">HITL Required</h3>
        </div>
        <p class="text-xs text-on-surface-variant leading-relaxed">${escHtml(localizeHitlMessage(data.message))}</p>
        ${sidebarButtons}
        ${openRoadmapSidebarBtn}
      </div>
    </div>`;

      // Also show in chat: the proposed output itself + Accept / Revise controls.
      const proposedOutput = (data.context && data.context.output) ? String(data.context.output) : '';
      const outputBlock = proposedOutput ? `
        <div class="mt-3 pl-11">
          <p class="text-[10px] font-bold text-outline-variant uppercase tracking-wider mb-1">Proposed output</p>
          <pre class="font-mono text-[11px] leading-relaxed text-on-surface-variant whitespace-pre-wrap bg-surface-container-high p-3 rounded-lg border border-outline-variant/10 max-h-96 overflow-auto">${escHtml(proposedOutput)}</pre>
        </div>` : '';
      appendMsgToFeed(`
    <div class="my-6 relative msg-enter">
      <div class="absolute -inset-2 bg-gradient-to-r from-primary/10 via-transparent to-primary/10 blur-2xl opacity-40"></div>
      <div class="relative bg-surface-container-lowest p-6 rounded-xl border border-primary/30 shadow-2xl">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
            <span class="material-symbols-outlined text-on-primary text-sm">ads_click</span>
          </div>
          <h3 class="font-headline font-bold text-on-surface uppercase tracking-tight">Human-In-The-Loop Required</h3>
        </div>
        <p class="text-sm text-on-surface-variant leading-relaxed pl-11">${escHtml(localizeHitlMessage(data.message))}</p>
        <p class="text-[10px] text-outline-variant font-mono mt-2 pl-11">CTX: ${data.request_id.slice(0, 8)} · ${escHtml(data.agent_name || '')}</p>
        ${outputBlock}
        ${isProvideInput ? `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pl-11 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" placeholder="Введите инструкции для агента..."
            class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex">
            <button onclick="respondHITLInput('${data.request_id}')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">send</span> Отправить
            </button>
          </div>
        </div>` : hasOptions ? `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pl-11 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" placeholder="Ваш ответ на вопрос — затем «Ответить»"
            class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex flex-wrap gap-2">
            <button onclick="respondHITLEdit('${data.request_id}')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">reply</span> Ответить
            </button>
            ${data.options.map(o => `
            <button onclick="respondHITLOption('${data.request_id}', '${escJs(o)}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-highest transition-all">${escHtml(o)}</button>`).join('')}
          </div>
        </div>` : `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pl-11 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" placeholder="Правки для агента — затем Revise"
            class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex gap-3">
            <button onclick="respondHITL('${data.request_id}', true)" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">check_circle</span> Accept
            </button>
            <button onclick="respondHITLEdit('${data.request_id}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-highest transition-all">
              <span class="material-symbols-outlined text-base">edit_note</span> Revise
            </button>
            <button onclick="respondHITL('${data.request_id}', false)" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-error/10 transition-all">
              <span class="material-symbols-outlined text-base">close</span> Reject
            </button>
          </div>
        </div>`}
        ${openRoadmapChatBtn}
      </div>
    </div>`);
    }

    function disableHitlControls(requestId) {
      const box = document.getElementById('hitl-controls-' + requestId);
      if (!box) return;
      box.querySelectorAll('button, textarea').forEach(el => {
        el.disabled = true;
        el.classList.add('opacity-40', 'pointer-events-none');
      });
    }

    let currentPlannerHitlRequest = null;

    function sendHitlResponse(payload) {
      if (ws && ws.readyState === 1) {
        ws.send(JSON.stringify(payload));
      }
      if (window.StatusIndicator) {
        StatusIndicator.feed({ type: 'hitl_response', request_id: payload.request_id });
      }
    }

    function respondHITLInput(requestId) {
      const feedbackEl = document.getElementById('hitl-feedback-' + requestId);
      const feedback = feedbackEl ? feedbackEl.value.trim() : '';
      sendHitlResponse({
        type: 'hitl_response',
        request_id: requestId,
        action: 'provide_input',
        approved: true,
        instructions: feedback,
        free_input: feedback,
      });
      document.getElementById('hitl-panel').classList.add('hidden');
      disableHitlControls(requestId);
      addSystemMsg('💬 HITL Input: ' + (feedback || '(empty)'));

      if (currentPlannerHitlRequest && currentPlannerHitlRequest.request_id === requestId) {
        currentPlannerHitlRequest = null;
        updateRoadmapModalButtons();
      }
    }

    function respondHITL(requestId, approved) {
      const feedbackEl = document.getElementById('hitl-feedback-' + requestId);
      const feedback = feedbackEl ? feedbackEl.value.trim() : '';
      sendHitlResponse({
        type: 'hitl_response',
        request_id: requestId,
        action: approved ? 'approve' : 'reject',
        approved: approved,
        instructions: feedback || null,
        free_input: feedback || null,
      });
      document.getElementById('hitl-panel').classList.add('hidden');
      disableHitlControls(requestId);
      addSystemMsg(approved ? '✓ HITL Approved' : '✗ HITL Rejected' + (feedback ? ': ' + feedback : ''));

      if (currentPlannerHitlRequest && currentPlannerHitlRequest.request_id === requestId) {
        currentPlannerHitlRequest = null;
        updateRoadmapModalButtons();
      }
    }

    function respondHITLOption(requestId, option) {
      // A question-window option button: a complete answer by itself.
      sendHitlResponse({
        type: 'hitl_response',
        request_id: requestId,
        action: 'select',
        approved: true,
        selected_option: option,
        instructions: option,
        free_input: option,
      });
      document.getElementById('hitl-panel').classList.add('hidden');
      disableHitlControls(requestId);
      addSystemMsg('☑ ' + option);
    }

    function respondHITLEdit(requestId) {
      // Send the operator's corrections: the agent rewrites its output with them.
      const feedbackEl = document.getElementById('hitl-feedback-' + requestId);
      const feedback = feedbackEl ? feedbackEl.value.trim() : '';
      if (!feedback) {
        addSystemMsg('Введите правки в поле выше, затем нажмите Revise.');
        if (feedbackEl) feedbackEl.focus();
        return;
      }
      sendHitlResponse({
        type: 'hitl_response',
        request_id: requestId,
        action: 'edit',
        approved: false,
        instructions: feedback,
        free_input: feedback,
      });
      document.getElementById('hitl-panel').classList.add('hidden');
      disableHitlControls(requestId);
      addSystemMsg('✎ HITL Revision requested: ' + feedback);

      if (currentPlannerHitlRequest && currentPlannerHitlRequest.request_id === requestId) {
        currentPlannerHitlRequest = null;
        updateRoadmapModalButtons();
      }
    }

    // ── Structured frame form (research frame intake) ────────────────────────
    function renderHitlForm(panel, feed, data) {
      const form = data.form;
      const rid = data.request_id;
      // The backend sends {en, ru} dicts for the display strings. The canonical
      // Russian `title` / `name` stay the round-trip keys in data-block / data-field.
      const loc = (v, fallback) => {
        if (v && typeof v === 'object') return v[currentLang] || v.ru || v.en || fallback;
        return v || fallback;
      };
      const blocksHtml = form.blocks.map((b, bi) => {
        const fieldsHtml = (b.fields || []).map((f, fi) => {
          const openTag = f.open
            ? `<span class="text-[9px] text-error uppercase tracking-wider">${escHtml(t('hitl.form.notSet'))}</span>`
            : `<span class="text-[9px] text-outline-variant uppercase tracking-wider">${escHtml(f.status || '')}</span>`;
          const val = f.open ? '' : String(f.value || '');
          const label = loc(f.label, f.name);
          const placeholder = loc(f.placeholder, t('hitl.form.placeholderFallback'));
          return `
            <div class="flex flex-col gap-1">
              <div class="flex items-center justify-between">
                <label class="text-[11px] font-mono text-on-surface-variant">${escHtml(label)}</label>
                ${openTag}
              </div>
              <textarea id="frm-${rid}-${bi}-${fi}" data-block="${escJs(b.title)}" data-field="${escJs(f.name)}"
                rows="2" placeholder="${escHtml(placeholder)}"
                class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50">${escHtml(val)}</textarea>
            </div>`;
        }).join('');
        const blockTitle = loc(b.title_i18n, b.title);
        const blockUsage = loc(b.usage_i18n, b.usage);
        return `
          <div class="mt-3 border border-outline-variant/10 rounded-lg p-3 bg-surface-container-high/40">
            <p class="text-[11px] font-bold text-on-surface uppercase tracking-wider">${escHtml(blockTitle)}</p>
            ${blockUsage ? `<p class="text-[10px] text-outline-variant mb-2">${escHtml(blockUsage)}</p>` : '<div class="mb-2"></div>'}
            <div class="flex flex-col gap-2">${fieldsHtml}</div>
          </div>`;
      }).join('');

      panel.classList.remove('hidden');
      panel.innerHTML = `
        <div class="relative bg-surface-container-lowest p-4 rounded-xl border border-primary/30 shadow-2xl flex flex-col gap-2">
          <h3 class="font-headline font-bold text-on-surface text-sm uppercase tracking-tight">${escHtml(t('hitl.form.sidebarTitle'))}</h3>
          <p class="text-[11px] text-on-surface-variant">${escHtml(t('hitl.form.sidebarHint'))}</p>
        </div>`;

      const formTitle = loc(form.title_i18n, form.title || t('hitl.form.title'));
      const formIntro = loc(form.intro_i18n, form.intro || data.message || '');
      feed.innerHTML += `
        <div id="hitl-controls-${rid}" class="my-6 relative msg-enter">
          <div class="relative bg-surface-container-lowest p-6 rounded-xl border border-primary/30 shadow-2xl">
            <div class="flex items-center gap-3 mb-2">
              <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
                <span class="material-symbols-outlined text-on-primary text-sm">fact_check</span>
              </div>
              <h3 class="font-headline font-bold text-on-surface uppercase tracking-tight">${escHtml(formTitle)}</h3>
            </div>
            <p class="text-xs text-on-surface-variant leading-relaxed">${escHtml(formIntro)}</p>
            ${blocksHtml}
            <div class="flex flex-wrap gap-3 mt-4">
              <button onclick="respondHITLForm('${rid}', true)" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
                <span class="material-symbols-outlined text-base">check_circle</span> ${escHtml(t('hitl.form.save'))}
              </button>
              <button onclick="respondHITLForm('${rid}', false)" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-highest transition-all">
                <span class="material-symbols-outlined text-base">skip_next</span> ${escHtml(t('hitl.form.skip'))}
              </button>
            </div>
          </div>
        </div>`;
    }

    function respondHITLForm(requestId, collect) {
      // collect=true: gather every non-empty field into form_values so the agent
      // marks them operator-set; collect=false: submit nothing (soft gate — the
      // run proceeds with the agent's drafted values).
      let formValues = null;
      if (collect) {
        formValues = {};
        document.querySelectorAll(`#hitl-controls-${requestId} textarea[data-field]`).forEach(el => {
          const v = el.value.trim();
          if (!v) return;
          const block = el.getAttribute('data-block');
          const field = el.getAttribute('data-field');
          (formValues[block] = formValues[block] || {})[field] = v;
        });
      }
      sendHitlResponse({
        type: 'hitl_response',
        request_id: requestId,
        action: 'approve',
        approved: true,
        form_values: formValues,
      });
      document.getElementById('hitl-panel').classList.add('hidden');
      disableHitlControls(requestId);
      const n = formValues ? Object.values(formValues).reduce((s, o) => s + Object.keys(o).length, 0) : 0;
      addSystemMsg(collect ? t('hitl.form.saved').replace('{n}', n) : t('hitl.form.skipped'));
    }


    // ── Experiment plan review ───────────────────────────────────────────────
    // The plan the Experiment Module builds during a run is the one thing the
    // human is asked to approve, and it used to arrive as Markdown in a <pre>:
    // a design matrix written as pipe-separated rows, ten task sections under
    // it, the whole thing in a 24rem scroll box. Nobody approves that; they
    // approve whatever they can see in the first screen of it.
    //
    // The backend now ships the plan structured (context.experiment_plan, see
    // CoScientist/experiments/plan_view.py), so it is drawn as what it is: a
    // header with the goal and the totals, the design matrix as a real table,
    // and one foldable card per task carrying that task's whole design. The
    // answer is unchanged — Accept / Revise / Reject through the same handlers
    // as any other review — so nothing downstream has to know about this view.

    const planOpenTasks = new Set();   // "<request_id>:<task_id>" of unfolded cards
    // The plan a card was drawn from, so folding a task re-renders from data
    // rather than from the DOM it is about to replace.
    const planByRequest = new Map();

    const PLAN_ROUTE_TONE = {
      fedot_mas: 'text-primary border-primary/30 bg-primary/5',
      react_tools: 'text-primary border-primary/30 bg-primary/5',
      coder: 'text-tertiary border-tertiary/30 bg-tertiary/5',
      alembic_build: 'text-secondary border-secondary/30 bg-secondary/5',
      research: 'text-outline-variant border-outline-variant/30 bg-outline-variant/5',
      medical: 'text-outline-variant border-outline-variant/30 bg-outline-variant/5',
    };
    const PLAN_CHIP_TONE = 'text-on-surface-variant border-outline-variant/20 bg-surface-container-high';

    // A slot the planner left empty is shown as empty. Printing its placeholder
    // text ("unspecified", "n/a") made an unfilled design look filled in.
    function planDash() { return '<span class="text-outline-variant/60">—</span>'; }

    function planText(value) {
      const text = (value === 0 || value) ? String(value).trim() : '';
      return text ? escHtml(text) : planDash();
    }

    // A list reads as a list, not as one comma-glued line: a task's metrics,
    // baselines and tools are each several short names and run together badly.
    function planItems(items, empty) {
      const rows = (items || []).filter(x => x !== null && x !== undefined && String(x).trim());
      if (!rows.length) return empty === undefined ? planDash() : escHtml(empty);
      return rows.map(x => `<span class="inline-block bg-surface-container-high border border-outline-variant/10 rounded px-1.5 py-0.5 mr-1 mb-1 text-[10px] font-mono">${escHtml(String(x))}</span>`).join('');
    }

    function planChip(label, value, tone) {
      const name = label ? `<span class="opacity-60 uppercase tracking-wider">${escHtml(label)}</span>` : '';
      return `<span class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-mono ${tone || PLAN_CHIP_TONE}">${name}${escHtml(String(value))}</span>`;
    }

    function planRouteChip(route) {
      return `<span class="inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-mono ${PLAN_ROUTE_TONE[route] || PLAN_CHIP_TONE}">${escHtml(route || '')}</span>`;
    }

    function planField(label, valueHtml) {
      return `<div class="grid grid-cols-[minmax(92px,max-content)_1fr] gap-x-3 py-1 border-b border-outline-variant/5 last:border-0">
        <span class="text-[10px] uppercase tracking-wider text-outline-variant pt-0.5">${escHtml(label)}</span>
        <span class="text-[11px] text-on-surface-variant leading-relaxed break-words min-w-0">${valueHtml}</span>
      </div>`;
    }

    function planSection(title, bodyHtml) {
      if (!bodyHtml) return '';
      return `<div class="mt-3">
        <p class="text-[10px] font-bold text-outline-variant uppercase tracking-wider mb-1">${escHtml(title)}</p>
        ${bodyHtml}</div>`;
    }

    const PLAN_MATRIX_COLUMNS = [
      'plan.col.task', 'plan.col.hypothesis', 'plan.col.question', 'plan.col.dataset',
      'plan.col.baselines', 'plan.col.metrics', 'plan.col.tools', 'plan.col.artifacts',
      'plan.col.route',
    ];

    function planMatrix(plan) {
      if (!Array.isArray(plan.matrix) || !plan.matrix.length) return '';
      const head = PLAN_MATRIX_COLUMNS
        .map(key => `<th class="text-left font-bold uppercase tracking-wider text-[9px] text-outline-variant px-2 py-1.5 whitespace-nowrap">${escHtml(t(key))}</th>`)
        .join('');
      const rows = plan.matrix.map(r => `
        <tr class="border-t border-outline-variant/10 align-top">
          <td class="px-2 py-1.5 font-mono text-[10px] text-primary whitespace-nowrap">${escHtml(r.task_id || '')}</td>
          <td class="px-2 py-1.5 font-mono text-[10px] whitespace-nowrap">${planText(r.hypothesis)}</td>
          <td class="px-2 py-1.5 text-[11px] min-w-[220px]">${planText(r.question)}</td>
          <td class="px-2 py-1.5 text-[11px]">${planText(r.dataset)}</td>
          <td class="px-2 py-1.5">${planItems(r.baselines)}</td>
          <td class="px-2 py-1.5">${planItems(r.metrics)}</td>
          <td class="px-2 py-1.5">${planItems(r.tools)}</td>
          <td class="px-2 py-1.5">${planItems(r.artifacts)}</td>
          <td class="px-2 py-1.5 whitespace-nowrap">${planRouteChip(r.route)}</td>
        </tr>`).join('');
      return planSection(t('plan.matrix'), `
        <div class="overflow-x-auto rounded-lg border border-outline-variant/10 bg-surface-container-high/30">
          <table class="w-full border-collapse text-on-surface-variant"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>
        </div>`);
    }

    function planTools(task) {
      const servers = task.mcp_servers || [];
      if (!servers.length) return planItems([], t('plan.noTools'));
      return servers.map(s => {
        const where = s.url ? ` <span class="text-outline-variant/70 break-all">${escHtml(s.url)}</span>` : '';
        const names = (s.tools || []).map(x => x.name + (x.required ? '' : ' (' + t('plan.optionalTool') + ')'));
        return `<div class="mb-1"><span class="font-mono text-[11px] text-on-surface">${escHtml(s.name || '')}</span>${where}
          <div class="mt-0.5">${planItems(names)}</div></div>`;
      }).join('');
    }

    function planCriteria(task) {
      const rows = task.success_criteria || [];
      if (!rows.length) return planDash();
      return rows.map(c => `<div class="mb-1.5">
        <span class="font-mono text-[10px] text-primary">${escHtml(c.criterion_id || '')}</span>
        <span class="text-[9px] uppercase tracking-wider text-outline-variant ml-1">${escHtml(c.kind || '')}</span>
        ${c.threshold ? `<span class="ml-1 font-mono text-[10px] text-tertiary">${escHtml(c.threshold)}</span>` : ''}
        <div class="text-[11px]">${planText(c.description)}</div>
        ${c.verification ? `<div class="text-[10px] text-outline-variant">${escHtml(c.verification)}</div>` : ''}
      </div>`).join('');
    }

    function planInputs(task) {
      const rows = task.input_data || [];
      if (!rows.length) return `<span class="text-outline-variant/60">${escHtml(t('plan.noInputs'))}</span>`;
      return rows.map(d => `<div class="mb-1">
        <span class="font-mono text-[10px] text-on-surface">${escHtml(d.data_id || '')}</span>
        <span class="text-[9px] uppercase tracking-wider text-outline-variant ml-1">${escHtml(d.kind || '')}</span>
        ${d.location ? `<div class="font-mono text-[10px] text-outline-variant break-all">${escHtml(d.location)}</div>` : ''}
        ${d.description ? `<div class="text-[11px]">${escHtml(d.description)}</div>` : ''}
      </div>`).join('');
    }

    function planDatasetCell(dataset) {
      if (!dataset || !dataset.name) return planDash();
      const ref = dataset.ref ? ` <span class="font-mono text-[10px] text-outline-variant break-all">${escHtml(dataset.ref)}</span>` : '';
      const notes = dataset.notes ? `<div class="text-[10px] text-outline-variant">${escHtml(dataset.notes)}</div>` : '';
      return escHtml(dataset.name) + ref + notes;
    }

    function planTaskCard(rid, task, index) {
      const open = planOpenTasks.has(rid + ':' + task.id);
      const design = task.design || {};
      const params = Object.entries(task.launch_params || {});
      const body = !open ? '' : `
        <div class="px-3 pb-3">
          ${planField(t('plan.task.question'), planText(design.question))}
          ${planField(t('plan.task.dataset'), planDatasetCell(design.dataset))}
          ${planField(t('plan.task.baselines'), planItems((design.baselines || []).map(b => b.name + ' (' + b.kind + ')')))}
          ${planField(t('plan.task.metrics'), planItems((design.metrics || []).map(m =>
            m.name + ' ' + m.direction + (m.threshold ? ' ' + m.threshold : '') + (m.test ? ' [' + m.test + ']' : ''))))}
          ${planField(t('plan.task.analysis'), planItems((design.analysis_artifacts || []).map(a => a.name + ' [' + a.role + '/' + a.prepare_via + ']')))}
          ${planField(t('plan.task.description'), planText(task.description))}
          ${task.rationale ? planField(t('plan.task.rationale'), planText(task.rationale)) : ''}
          ${planField(t('plan.task.tools'), planTools(task))}
          ${task.repo_url ? planField(t('plan.task.repo'), `<span class="font-mono text-[10px] break-all">${escHtml(task.repo_url)}</span>`) : ''}
          ${params.length ? planField(t('plan.task.params'), planItems(params.map(p => p[0] + '=' + p[1]))) : ''}
          ${planField(t('plan.task.inputs'), planInputs(task))}
          ${planField(t('plan.task.criteria'), planCriteria(task))}
          ${planField(t('plan.task.expected'), planItems((task.expected_artifacts || []).map(a => a.name + ' [' + a.role + ']')))}
          ${(task.warnings || []).length ? planField(t('plan.task.warnings'),
            `<span class="text-tertiary">${escHtml(task.warnings.join(' · '))}</span>`) : ''}
        </div>`;
      return `<div class="rounded-lg border border-outline-variant/10 bg-surface-container-high/30 mb-2">
        <button type="button" onclick="togglePlanTask('${escJs(rid)}','${escJs(task.id)}')"
          class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-container-high/60 rounded-lg transition-colors">
          <span class="material-symbols-outlined text-sm text-outline-variant">${open ? 'expand_more' : 'chevron_right'}</span>
          <span class="font-mono text-[10px] text-primary">${escHtml(task.id || ('#' + (index + 1)))}</span>
          <span class="text-[11px] text-on-surface truncate flex-1">${escHtml(task.name || '')}</span>
          ${task.optional ? planChip('', t('plan.task.optional')) : ''}
          ${(task.depends_on || []).length ? planChip(t('plan.task.after'), task.depends_on.join(', ')) : ''}
          ${planChip('', (task.est_duration_min || 0) + ' ' + t('plan.min'))}
          ${planRouteChip(task.route)}
        </button>
        ${body}</div>`;
    }

    function repaintPlanTasks(rid) {
      const box = document.getElementById('plan-tasks-' + rid);
      const plan = planByRequest.get(rid);
      if (!box || !plan) return;
      box.innerHTML = plan.tasks.map((task, i) => planTaskCard(rid, task, i)).join('');
      const toggle = document.getElementById('plan-toggle-all-' + rid);
      if (toggle) {
        const allOpen = plan.tasks.every(task => planOpenTasks.has(rid + ':' + task.id));
        toggle.textContent = allOpen ? t('plan.collapseAll') : t('plan.expandAll');
      }
    }

    function togglePlanTask(rid, taskId) {
      const key = rid + ':' + taskId;
      if (planOpenTasks.has(key)) planOpenTasks.delete(key); else planOpenTasks.add(key);
      repaintPlanTasks(rid);
    }

    function togglePlanAllTasks(rid) {
      const plan = planByRequest.get(rid);
      if (!plan) return;
      const allOpen = plan.tasks.every(task => planOpenTasks.has(rid + ':' + task.id));
      plan.tasks.forEach(task => {
        if (allOpen) planOpenTasks.delete(rid + ':' + task.id);
        else planOpenTasks.add(rid + ':' + task.id);
      });
      repaintPlanTasks(rid);
    }

    function planCritiqueBlock(plan) {
      const critique = plan.critique;
      if (!critique) return '';
      const approved = critique.verdict === 'approve';
      const issues = (critique.issues || []).map(i => `<div class="mb-1">
        <span class="text-[9px] uppercase tracking-wider ${i.severity === 'blocker' ? 'text-error' : 'text-tertiary'}">${escHtml(i.severity || '')}</span>
        <span class="text-[9px] uppercase tracking-wider text-outline-variant ml-1">${escHtml(i.category || '')}</span>
        ${i.task_id ? `<span class="font-mono text-[10px] text-primary ml-1">${escHtml(i.task_id)}</span>` : ''}
        <div class="text-[11px]">${planText(i.message)}</div>
        ${i.suggestion ? `<div class="text-[10px] text-outline-variant">${escHtml(i.suggestion)}</div>` : ''}
      </div>`).join('');
      return planSection(t('plan.critique'),
        `<p class="text-[11px] ${approved ? 'text-secondary' : 'text-tertiary'} mb-1">${escHtml(approved ? t('plan.critique.approve') : t('plan.critique.revise'))}</p>${issues}`);
    }

    function planBullets(list) {
      return (list || []).length
        ? `<ul class="list-disc list-inside text-[11px] text-on-surface-variant space-y-0.5">${list.map(x => `<li>${escHtml(x)}</li>`).join('')}</ul>`
        : '';
    }

    function renderExperimentPlanReview(panel, data, plan) {
      const rid = data.request_id;
      planByRequest.set(rid, plan);

      panel.classList.remove('hidden');
      panel.innerHTML = `
        <div class="relative bg-surface-container-lowest p-4 rounded-xl border border-primary/30 shadow-2xl flex flex-col gap-3">
          <h3 class="font-headline font-bold text-on-surface text-sm uppercase tracking-tight">${escHtml(t('plan.sidebarTitle'))}</h3>
          <p class="text-[11px] text-on-surface-variant">${escHtml(t('plan.revision').replace('{n}', plan.revision))} · ${escHtml(t('plan.tasks').replace('{n}', plan.task_count))}</p>
          <p class="text-[10px] text-outline-variant leading-relaxed">${escHtml(t('plan.sidebarHint'))}</p>
          <div class="flex gap-3">
            <button onclick="respondHITL('${escJs(rid)}', true)" class="flex-1 flex items-center justify-center gap-2 bg-primary text-on-primary py-3 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">check_circle</span> ${escHtml(t('plan.accept'))}
            </button>
            <button onclick="respondHITL('${escJs(rid)}', false)" class="flex-1 flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error py-3 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-error/10 transition-all">
              <span class="material-symbols-outlined text-base">close</span> ${escHtml(t('plan.reject'))}
            </button>
          </div>
        </div>`;

      const hypotheses = (plan.hypotheses || []).map(h =>
        `<div class="mb-1"><span class="font-mono text-[10px] text-primary">${escHtml(h.id || '')}</span>
          <span class="text-[11px] ml-1">${planText(h.statement)}</span></div>`).join('');

      appendMsgToFeed(`
    <div class="my-6 relative msg-enter">
      <div class="absolute -inset-2 bg-gradient-to-r from-primary/10 via-transparent to-primary/10 blur-2xl opacity-40"></div>
      <div class="relative bg-surface-container-lowest p-6 rounded-xl border border-primary/30 shadow-2xl">
        <div class="flex items-center gap-3 mb-2">
          <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
            <span class="material-symbols-outlined text-on-primary text-sm">science</span>
          </div>
          <h3 class="font-headline font-bold text-on-surface uppercase tracking-tight">${escHtml(t('plan.title'))}</h3>
        </div>
        <p class="text-[10px] text-outline-variant font-mono mb-2">CTX: ${escHtml(String(rid).slice(0, 8))} · ${escHtml(data.agent_name || '')}</p>
        <div class="flex flex-wrap gap-1.5 mb-3">
          ${planChip('', t('plan.revision').replace('{n}', plan.revision), 'text-primary border-primary/30 bg-primary/5')}
          ${planChip('', t('plan.tasks').replace('{n}', plan.task_count))}
          ${planChip('', (plan.total_est_duration_min || 0) + ' ' + t('plan.min'))}
          ${(plan.routes || []).map(planRouteChip).join('')}
          ${plan.plan_id ? planChip('id', plan.plan_id) : ''}
        </div>
        ${planField(t('plan.goal'), planText(plan.goal))}
        ${plan.hypothesis ? planField(t('plan.hypothesis'), planText(plan.hypothesis)) : ''}
        ${planField(t('plan.methods'), planItems(plan.methods))}
        ${hypotheses ? planSection(t('plan.hypotheses'), hypotheses) : ''}
        ${planCritiqueBlock(plan)}
        ${planMatrix(plan)}
        <div class="mt-3 flex items-center justify-between">
          <p class="text-[10px] font-bold text-outline-variant uppercase tracking-wider">${escHtml(t('plan.tasksTitle'))}</p>
          <button type="button" id="plan-toggle-all-${escHtml(rid)}" onclick="togglePlanAllTasks('${escJs(rid)}')"
            class="text-[10px] uppercase tracking-wider text-primary hover:underline">${escHtml(t('plan.expandAll'))}</button>
        </div>
        <div id="plan-tasks-${escHtml(rid)}" class="mt-1">${plan.tasks.map((task, i) => planTaskCard(rid, task, i)).join('')}</div>
        ${planSection(t('plan.risks'), planBullets(plan.risks))}
        ${planSection(t('plan.assumptions'), planBullets(plan.assumptions))}
        <!-- Only the answer is disabled once this review is over (timeout, or
             the operator has answered): the plan stays readable and its task
             cards stay foldable, which is the whole point of drawing it. -->
        <div id="hitl-controls-${escHtml(rid)}" class="mt-4 flex flex-col gap-2">
          <textarea id="hitl-feedback-${escHtml(rid)}" rows="2" placeholder="${escHtml(t('plan.feedbackPlaceholder'))}"
            class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex flex-wrap gap-3">
            <button onclick="respondHITL('${escJs(rid)}', true)" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">check_circle</span> ${escHtml(t('plan.accept'))}
            </button>
            <button onclick="respondHITLEdit('${escJs(rid)}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-highest transition-all">
              <span class="material-symbols-outlined text-base">edit_note</span> ${escHtml(t('plan.revise'))}
            </button>
            <button onclick="respondHITL('${escJs(rid)}', false)" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-error/10 transition-all">
              <span class="material-symbols-outlined text-base">close</span> ${escHtml(t('plan.reject'))}
            </button>
          </div>
        </div>
      </div>
    </div>`);
    }
