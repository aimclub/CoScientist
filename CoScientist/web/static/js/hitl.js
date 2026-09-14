// =========================================================================
// HITL UI
// =========================================================================
    // =========================================================================
    // HITL UI
    // =========================================================================
    // The card header is built on the client from agent_name / invoked_via /
    // trigger, so it follows the UI language. Older requests (and replays of
    // them) carry the trigger only as an English "[CALLBACK: X]" message prefix;
    // internal-loop ones as a fixed English message.
    const INTERNAL_LOOP_RE = /^(?:\[INTERNAL_LOOP:[^\]]*\]\s*)?Agent '([^']+)' proposes its result\. Please review\.?\s*$/;
    const LEGACY_PREFIX_RE = /^\[(CALLBACK|INTERNAL_LOOP):\s*([A-Z_]*)[^\]]*\]\s*/;
    const TRIGGER_KEYS = {
      before_tool: 'beforeTool',
      after_agent: 'afterAgent',
      before_agent: 'beforeAgent',
      bash_command: 'bashCommand',
    };
    const hitlCards = new Map();  // request_id -> payload, re-rendered on language switch

    function fillHitl(key, params) {
      return t(key).replace(/\{(\w+)\}/g, (m, k) => (params[k] != null ? params[k] : m));
    }

    function hitlTrigger(data) {
      if (data.trigger) return data.trigger;
      const m = LEGACY_PREFIX_RE.exec(data.message || '');
      return m && m[1] === 'CALLBACK' ? m[2].toLowerCase() : null;
    }

    function hitlParams(data) {
      const ctx = data.context || {};
      return {
        agent: data.agent_name || '?',
        tool: ctx.tool || data.trigger || '?',
        rule: ctx.matched_rule || '?',
      };
    }

    function localizeHitlMessage(data) {
      const trigger = hitlTrigger(data);
      const key = TRIGGER_KEYS[trigger];
      // A legacy before_agent message embeds the user query, which the template would drop.
      if (key && !(trigger === 'before_agent' && !data.trigger)) {
        return fillHitl('hitl.msg.' + key, hitlParams(data));
      }
      const message = data.message || '';
      const m = INTERNAL_LOOP_RE.exec(message);
      if (m) return t('hitl.internalLoop').replace('{agent}', m[1]);
      return message.replace(LEGACY_PREFIX_RE, '');
    }

    function describeHitlVia(data) {
      const params = hitlParams(data);
      const key = TRIGGER_KEYS[hitlTrigger(data)];
      if (key) return fillHitl('hitl.via.' + key, params);
      switch (data.invoked_via) {
        case 'tool': return fillHitl('hitl.via.tool', params);
        case 'callback': return t('hitl.via.callback');
        case 'internal_loop': return t('hitl.via.internalLoop');
        case 'request_input': return t('hitl.via.requestInput');
        case 'sandbox_download_cancel': return t('hitl.via.downloadCancel');
      }
      if (INTERNAL_LOOP_RE.test(data.message || '')) return t('hitl.via.internalLoop');
      return data.invoked_via && data.invoked_via !== 'unspecified' ? data.invoked_via : t('hitl.via.unknown');
    }

    // The single place the request details (tool arguments, output, command) are shown.
    function hitlDetailBlock(data) {
      const ctx = data.context || {};
      if (ctx.output) {
        const isToolCall = hitlTrigger(data) === 'before_tool';
        return { labelKey: isToolCall ? 'hitl.block.toolCall' : 'hitl.block.output', text: String(ctx.output) };
      }
      if (ctx.command) return { labelKey: 'hitl.block.command', text: String(ctx.command) };
      if (ctx.user_query) return { labelKey: 'hitl.block.userQuery', text: String(ctx.user_query) };
      return null;
    }

    function hitlDynamic(data, part, text) {
      return `<span data-hitl-part="${part}" data-hitl-rid="${escHtml(data.request_id || '')}">${escHtml(text)}</span>`;
    }

    function hitlLabel(key) {
      return `<span data-i18n="${key}">${escHtml(t(key))}</span>`;
    }

    function relocalizeHitlCards() {
      document.querySelectorAll('[data-hitl-part]').forEach(el => {
        const data = hitlCards.get(el.dataset.hitlRid);
        if (!data) return;
        el.textContent = el.dataset.hitlPart === 'via' ? describeHitlVia(data) : localizeHitlMessage(data);
      });
    }
    window.relocalizeHitlCards = relocalizeHitlCards;

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

      hitlCards.set(data.request_id || '', data);
      const messageHtml = hitlDynamic(data, 'message', localizeHitlMessage(data));
      const viaHtml = hitlDynamic(data, 'via', describeHitlVia(data));
      const agentHtml = `<span class="font-bold text-on-surface">${escHtml(data.agent_name || '—')}</span>`;

      let openRoadmapSidebarBtn = '';
      let openRoadmapChatBtn = '';
      if (data.agent_name === 'PlannerAgent') {
        openRoadmapSidebarBtn = `
      <button onclick="openRoadmapEditor()" class="w-full mt-2 flex items-center justify-center gap-2 bg-surface-variant border border-outline-variant/20 text-on-surface py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-high transition-all">
        <span class="material-symbols-outlined text-sm">map</span> ${hitlLabel('hitl.btn.openRoadmap')}
      </button>
    `;
        openRoadmapChatBtn = `
      <div class="mt-4 pl-11">
        <button onclick="openRoadmapEditor()" class="flex items-center justify-center gap-2 bg-surface-variant border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-wider hover:bg-surface-container-high transition-all">
          <span class="material-symbols-outlined text-sm">map</span> ${hitlLabel('hitl.btn.openRoadmap')}
        </button>
      </div>
    `;
      }

      const isProvideInput = data.action_type === 'provide_input';
      const hasOptions = !!(data.options && data.options.length);

      // Show in sidebar. For question windows (options present) or input requests the sidebar is
      // informational only — answer directly in the chat card.
      const sidebarButtons = (hasOptions || isProvideInput) ? `
        <p class="text-[10px] text-outline-variant leading-relaxed">${hitlLabel('hitl.answerInChat')}</p>` : `
        <div class="flex gap-3">
          <button onclick="respondHITL('${data.request_id}', true)" class="flex-1 flex items-center justify-center gap-2 bg-primary text-on-primary py-3 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
            <span class="material-symbols-outlined text-base">check_circle</span> ${hitlLabel('hitl.btn.accept')}
          </button>
          <button onclick="respondHITL('${data.request_id}', false)" class="flex-1 flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error py-3 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-error/10 transition-all">
            <span class="material-symbols-outlined text-base">close</span> ${hitlLabel('hitl.btn.reject')}
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
          <h3 class="font-headline font-bold text-on-surface text-sm uppercase tracking-tight">${hitlLabel('hitl.titleShort')}</h3>
        </div>
        <p class="text-xs text-on-surface-variant leading-relaxed">${messageHtml}</p>
        <div class="flex flex-col gap-1 text-[11px] leading-relaxed">
          <p><span class="text-outline-variant">${hitlLabel('hitl.agentLabel')}:</span> ${agentHtml}</p>
          <p><span class="text-outline-variant">${hitlLabel('hitl.viaLabel')}:</span> <span class="text-primary">${viaHtml}</span></p>
        </div>
        ${sidebarButtons}
        ${openRoadmapSidebarBtn}
      </div>
    </div>`;

      // Also show in chat: the request details + Accept / Revise controls.
      const detail = hitlDetailBlock(data);
      const outputBlock = detail ? `
        <div class="mt-3 pl-11">
          <p class="text-[10px] font-bold text-outline-variant uppercase tracking-wider mb-1">${hitlLabel(detail.labelKey)}</p>
          <pre class="font-mono text-[11px] leading-relaxed text-on-surface-variant whitespace-pre-wrap bg-surface-container-high p-3 rounded-lg border border-outline-variant/10 max-h-96 overflow-auto">${escHtml(detail.text)}</pre>
        </div>` : '';
      appendMsgToFeed(`
    <div class="my-6 relative msg-enter">
      <div class="absolute -inset-2 bg-gradient-to-r from-primary/10 via-transparent to-primary/10 blur-2xl opacity-40"></div>
      <div class="relative bg-surface-container-lowest p-6 rounded-xl border border-primary/30 shadow-2xl">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
            <span class="material-symbols-outlined text-on-primary text-sm">ads_click</span>
          </div>
          <h3 class="font-headline font-bold text-on-surface uppercase tracking-tight">${hitlLabel('hitl.title')}</h3>
        </div>
        <p class="text-sm text-on-surface-variant leading-relaxed pl-11">${messageHtml}</p>
        <div class="mt-2 pl-11 flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[11px]">
          <span><span class="text-outline-variant">${hitlLabel('hitl.agentLabel')}:</span> ${agentHtml}</span>
          <span><span class="text-outline-variant">${hitlLabel('hitl.viaLabel')}:</span> <span class="text-primary">${viaHtml}</span></span>
          <span class="font-mono text-[10px] text-outline-variant">CTX: ${escHtml((data.request_id || '').slice(0, 8))}</span>
        </div>
        ${outputBlock}
        ${isProvideInput ? `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pl-11 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" data-i18n-placeholder="hitl.ph.input" placeholder="${escHtml(t('hitl.ph.input'))}"
            class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex">
            <button onclick="respondHITLInput('${data.request_id}')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">send</span> ${hitlLabel('hitl.btn.send')}
            </button>
          </div>
        </div>` : hasOptions ? `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pl-11 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" data-i18n-placeholder="hitl.ph.reply" placeholder="${escHtml(t('hitl.ph.reply'))}"
            class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex flex-wrap gap-2">
            <button onclick="respondHITLEdit('${data.request_id}')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">reply</span> ${hitlLabel('hitl.btn.reply')}
            </button>
            ${data.options.map(o => `
            <button onclick="respondHITLOption('${data.request_id}', '${escJs(o)}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-highest transition-all">${escHtml(o)}</button>`).join('')}
          </div>
        </div>` : `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pl-11 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" data-i18n-placeholder="hitl.ph.revise" placeholder="${escHtml(t('hitl.ph.revise'))}"
            class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex gap-3">
            <button onclick="respondHITL('${data.request_id}', true)" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">check_circle</span> ${hitlLabel('hitl.btn.accept')}
            </button>
            <button onclick="respondHITLEdit('${data.request_id}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-highest transition-all">
              <span class="material-symbols-outlined text-base">edit_note</span> ${hitlLabel('hitl.btn.revise')}
            </button>
            <button onclick="respondHITL('${data.request_id}', false)" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-error/10 transition-all">
              <span class="material-symbols-outlined text-base">close</span> ${hitlLabel('hitl.btn.reject')}
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
        addSystemMsg(t('hitl.reviseEmpty'));
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

