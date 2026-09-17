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
  work_order: 'workOrder',
  work_order_amendment: 'workOrderAmendment',
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

// A card is keyed by its request id: a request the server redelivers (a
// reconnect while it is still open) replaces its disabled history copy in
// place instead of appearing twice.
function placeHitlCard(rid, html) {
  const existing = rid ? document.querySelector(`[data-hitl-card="${CSS.escape(rid)}"]`) : null;
  if (existing) {
    existing.outerHTML = html;
  } else {
    appendMsgToFeed(html);
  }
}

// history=true renders a card from the session transcript (reload, import):
// no sidebar panel, no countdown, controls disabled until the server
// redelivers the request as still open.
function showHITL(data, { history = false } = {}) {
  const panel = history ? null : document.getElementById('hitl-panel');
  hitlCards.set(data.request_id || '', data);

  // Structured intake (e.g. the research frame): render a per-field form
  // instead of the free-text review, then stop — the other HITL points keep
  // the free-text / option path below.
  if (data.form && Array.isArray(data.form.blocks)) {
    renderHitlForm(panel, data);
  } else if (String(data.trigger || '').startsWith('work_order')) {
    // Work Order (the agent's contract before it acts): its own card with
    // assumptions to uncheck, a veto countdown and a Pause button.
    renderWorkOrderCard(panel, data);
  } else {
    renderHitlCard(panel, data);
  }
  if (history) disableHitlControls(data.request_id);
  scrollChat();
}

function renderHitlCard(panel, data) {
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
  if (panel) {
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
          <p><span class="text-outline-variant">${hitlLabel('hitl.viaLabel')}:</span> <span class="text-primary">${viaHtml}</span></p>
        </div>
        ${sidebarButtons}
        ${openRoadmapSidebarBtn}
      </div>
    </div>`;
  }

  // Also show in chat: the request details + Accept / Revise controls.
  const detail = hitlDetailBlock(data);
  const outputBlock = detail ? `
        <div class="mt-3 pl-11">
          <p class="text-[10px] font-bold text-outline-variant uppercase tracking-wider mb-1">${hitlLabel(detail.labelKey)}</p>
          <pre class="font-mono text-[11px] leading-relaxed text-on-surface-variant whitespace-pre-wrap bg-surface-container-high p-3 rounded-lg border border-outline-variant/10 max-h-96 overflow-auto">${escHtml(detail.text)}</pre>
        </div>` : '';
  placeHitlCard(data.request_id, `
    <div class="my-6 relative msg-enter" data-hitl-card="${escHtml(data.request_id || '')}">
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
          <span><span class="text-outline-variant">${hitlLabel('hitl.viaLabel')}:</span> <span class="text-primary">${viaHtml}</span></span>
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
  stopWorkOrderCountdown(requestId);
  const box = document.getElementById('hitl-controls-' + requestId);
  if (!box) return;
  box.querySelectorAll('button, textarea').forEach(el => {
    el.disabled = true;
    el.classList.add('opacity-40', 'pointer-events-none');
  });
}

let currentPlannerHitlRequest = null;

// The chat line recording an answer. One place for both the live click and
// the transcript replay, so a reloaded session reads the same as the live one.
function hitlResponseSummary(response) {
  const request = hitlCards.get(response.request_id || '') || {};
  const feedback = String(response.instructions || response.free_input || '').trim();
  const action = response.action;
  if (request.form && Array.isArray(request.form.blocks)) {
    const values = response.form_values;
    const n = values ? Object.values(values).reduce((s, o) => s + Object.keys(o || {}).length, 0) : 0;
    return values ? t('hitl.form.saved').replace('{n}', n) : t('hitl.form.skipped');
  }
  if (String(request.trigger || '').startsWith('work_order') && action === 'approve') {
    const rejected = ((response.form_values || {}).rejected_assumption_ids || []).length;
    return t('workOrder.approved')
      + (rejected ? ' — ' + t('workOrder.rejectedAssumptions').replace('{n}', rejected) : '')
      + (feedback ? ': ' + feedback : '');
  }
  if (action === 'provide_input') return '💬 HITL Input: ' + (feedback || '(empty)');
  if (action === 'select') return '☑ ' + (response.selected_option || feedback);
  if (action === 'edit') return '✎ HITL Revision requested: ' + feedback;
  return response.approved ? '✓ HITL Approved' : '✗ HITL Rejected' + (feedback ? ': ' + feedback : '');
}

function hitlTimeoutSummary(data) {
  return t('hitl.timeoutMsg', { seconds: (data.timeout_seconds || 300), agent: (data.agent_name || '') });
}
window.hitlTimeoutSummary = hitlTimeoutSummary;

// Replay of a recorded outcome onto its card: what the operator typed or
// unchecked is put back, then the card is locked.
function applyHitlOutcome(event) {
  const rid = event.request_id || '';
  if (event.type === 'hitl_response') {
    const card = rid ? document.querySelector(`[data-hitl-card="${CSS.escape(rid)}"]`) : null;
    const feedbackEl = document.getElementById('hitl-feedback-' + rid);
    const feedback = event.instructions || event.free_input;
    if (feedbackEl && feedback && event.action !== 'select') feedbackEl.value = feedback;
    const values = event.form_values || {};
    if (card) {
      card.querySelectorAll('textarea[data-field]').forEach(el => {
        const block = values[el.getAttribute('data-block')];
        const value = block && block[el.getAttribute('data-field')];
        if (value != null) el.value = value;
      });
      const rejected = values.rejected_assumption_ids || [];
      card.querySelectorAll('input[data-wo-assumption]').forEach(el => {
        el.checked = !rejected.includes(el.dataset.woAssumption);
        el.disabled = true;
      });
    }
    disableHitlControls(rid);
    addSystemMsg(hitlResponseSummary(event), event.timestamp);
  } else if (event.type === 'hitl_timeout') {
    disableHitlControls(rid);
    addSystemMsg(hitlTimeoutSummary(event), event.timestamp);
  } else if (event.type === 'hitl_cancelled') {
    disableHitlControls(rid);
  }
}
window.applyHitlOutcome = applyHitlOutcome;

function sendHitlResponse(payload) {
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify(payload));
  }
  if (window.StatusIndicator) {
    StatusIndicator.feed({ type: 'hitl_response', request_id: payload.request_id });
  }
  addSystemMsg(hitlResponseSummary(payload));
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

  if (currentPlannerHitlRequest && currentPlannerHitlRequest.request_id === requestId) {
    currentPlannerHitlRequest = null;
    updateRoadmapModalButtons();
  }
}

// ── Structured frame form (research frame intake) ────────────────────────
function renderHitlForm(panel, data) {
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

  if (panel) {
    panel.classList.remove('hidden');
    panel.innerHTML = `
        <div class="relative bg-surface-container-lowest p-4 rounded-xl border border-primary/30 shadow-2xl flex flex-col gap-2">
          <h3 class="font-headline font-bold text-on-surface text-sm uppercase tracking-tight">${escHtml(t('hitl.form.sidebarTitle'))}</h3>
          <p class="text-[11px] text-on-surface-variant">${escHtml(t('hitl.form.sidebarHint'))}</p>
        </div>`;
  }

  const formTitle = loc(form.title_i18n, form.title || t('hitl.form.title'));
  const formIntro = loc(form.intro_i18n, form.intro || data.message || '');
  // insertAdjacentHTML, not `innerHTML +=`: re-parsing the whole feed would
  // wipe whatever the operator is typing into the earlier cards.
  placeHitlCard(rid, `
        <div id="hitl-controls-${rid}" data-hitl-card="${escHtml(rid || '')}" class="my-6 relative msg-enter">
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
        </div>`);
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
}

// ── Work Order cards ─────────────────────────────────────────────────────
const WO_TIER_STYLE = {
  read: 'text-primary border-primary/30 bg-primary/10',
  compute: 'text-tertiary border-tertiary/30 bg-tertiary/10',
  side_effect: 'text-error border-error/30 bg-error/10',
};
const WO_STEP_MARK = { pending: '○', in_progress: '◐', done: '✓', skipped: '–' };
const woTimers = new Map();  // request_id -> interval id

function woChip(text, cls = 'text-on-surface-variant border-outline-variant/20 bg-surface-container-high') {
  return `<span class="inline-block text-[10px] font-mono px-2 py-0.5 rounded border ${cls}">${escHtml(text)}</span>`;
}

// Internal tools the agent named: always rendered, shown only while the viewer
// has "Show internal agents and tools" on (CSS on .wo-internal).
const WO_INTERNAL_CHIP = 'wo-internal text-outline-variant border-dashed border-outline-variant/30 bg-transparent';

function woToolChips(tools, internal) {
  return [
    ...(tools || []).map(tn => woChip(tn)),
    ...(internal || []).map(tn => woChip(tn, WO_INTERNAL_CHIP)),
  ].join(' ');
}

function woSection(labelKey, inner) {
  if (!inner) return '';
  return `
        <div class="mt-3">
          <p class="text-[10px] font-bold text-outline-variant uppercase tracking-wider mb-1">${hitlLabel(labelKey)}</p>
          ${inner}
        </div>`;
}

function woStepRow(step) {
  const status = step.status || 'pending';
  const tools = woToolChips(step.tools, step.internal_tools);
  return `
        <li data-wo-step="${escHtml(step.id)}" data-wo-status="${escHtml(status)}" class="flex flex-col gap-0.5">
          <div class="flex items-baseline gap-2">
            <span data-wo-mark class="font-mono text-primary w-4 text-center">${WO_STEP_MARK[status] || '○'}</span>
            <span class="font-mono text-[10px] text-outline-variant">${escHtml(step.id)}</span>
            <span class="text-on-surface">${escHtml(step.title || '')}</span>
            <span class="flex flex-wrap gap-1">${tools}</span>
          </div>
          ${step.expected_outcome ? `<p class="pl-6 text-[11px] text-outline-variant">→ ${escHtml(step.expected_outcome)}</p>` : ''}
          <p data-wo-note class="pl-6 text-[11px] text-on-surface-variant italic">${escHtml(step.note || '')}</p>
        </li>`;
}

// The contract itself. interactive=true renders assumptions as checkboxes.
function workOrderBody(order, rid, interactive) {
  const assumptions = (order.assumptions || []).map(a => {
    if (interactive) {
      return `
            <label class="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" checked data-wo-assumption="${escHtml(a.id)}" class="mt-0.5 accent-primary" />
              <span><span class="font-mono text-[10px] text-outline-variant">${escHtml(a.id)}</span> ${escHtml(a.text)}</span>
            </label>`;
    }
    const struck = a.rejected ? 'line-through text-outline-variant' : '';
    return `<p class="${struck}"><span class="font-mono text-[10px] text-outline-variant">${escHtml(a.id)}</span> ${escHtml(a.text)}</p>`;
  }).join('');
  const effects = (order.side_effects || []).map(e =>
    woChip((e.kind || e) + (e.detail ? ': ' + e.detail : ''), WO_TIER_STYLE.side_effect)).join(' ');
  const tools = woToolChips(order.planned_tools, order.internal_tools);
  // Only internal tools: the whole section hides with them.
  const toolsOnlyInternal = !(order.planned_tools || []).length;
  return `
        <div class="text-xs text-on-surface-variant leading-relaxed">
          ${woSection('workOrder.goal', `<p class="text-on-surface">${escHtml(order.goal || '')}</p>`)}
          ${woSection('workOrder.done', order.done_criteria ? `<p>${escHtml(order.done_criteria)}</p>` : '')}
          ${woSection('workOrder.assumptions', assumptions
    ? (interactive ? `<p class="text-[10px] text-outline-variant mb-1">${hitlLabel('workOrder.assumptionsHint')}</p>` : '')
    + `<div class="flex flex-col gap-1">${assumptions}</div>`
    : '')}
          ${woSection('workOrder.steps', (order.steps || []).length
      ? `<ol data-wo-steps class="flex flex-col gap-1.5">${order.steps.map(woStepRow).join('')}</ol>` : '')}
          ${tools ? `<div class="${toolsOnlyInternal ? 'wo-internal' : ''}">${woSection('workOrder.tools', `<div class="flex flex-wrap gap-1">${tools}</div>`)}</div>` : ''}
          ${woSection('workOrder.sideEffects', effects ? `<div class="flex flex-wrap gap-1">${effects}</div>` : '')}
          ${woSection('workOrder.expected', order.expected_outcome ? `<p>${escHtml(order.expected_outcome)}</p>` : '')}
          ${woSection('workOrder.fallback', order.fallback ? `<p>${escHtml(order.fallback)}</p>` : '')}
          <div data-wo-deviations class="mt-2 flex flex-col gap-1"></div>
        </div>`;
}

function workOrderDiff(ctx) {
  const diff = ctx.diff || {};
  const rows = [];
  (diff.added_tools || []).forEach(tn => rows.push('+ ' + tn));
  (diff.added_side_effects || []).forEach(e => rows.push('+ ' + e.kind + (e.detail ? ': ' + e.detail : '')));
  (diff.added_steps || []).forEach(st => rows.push('+ ' + st.id + '. ' + st.title));
  const reason = ctx.reason ? woSection('workOrder.reason', `<p class="text-on-surface">${escHtml(ctx.reason)}</p>`) : '';
  const changes = rows.length ? woSection('workOrder.added',
    `<pre class="font-mono text-[11px] text-secondary whitespace-pre-wrap bg-surface-container-high p-2 rounded border border-outline-variant/10">${escHtml(rows.join('\n'))}</pre>`) : '';
  return reason + changes;
}

function woHeader(icon, titleKey, tier, agent, revision) {
  const tierCls = WO_TIER_STYLE[tier] || WO_TIER_STYLE.compute;
  return `
        <div class="flex items-center gap-3 flex-wrap">
          <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
            <span class="material-symbols-outlined text-on-primary text-sm">${icon}</span>
          </div>
          <h3 class="font-headline font-bold text-on-surface uppercase tracking-tight">${hitlLabel(titleKey)}</h3>
          ${tier ? `<span class="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${tierCls}">${hitlLabel('workOrder.tier.' + tier)}</span>` : ''}
          <span class="text-[11px] font-bold text-on-surface">${escHtml(agent || '—')}</span>
          <span class="font-mono text-[10px] text-outline-variant">rev ${escHtml(String(revision || 1))}</span>
        </div>`;
}

function renderWorkOrderCard(panel, data) {
  const rid = data.request_id;
  const ctx = data.context || {};
  const order = ctx.work_order || {};
  const tier = ctx.tier || order.tier || 'compute';
  const isAmendment = data.trigger === 'work_order_amendment';
  // A history card (no panel) never counts down: its window has closed.
  const timeout = panel ? (Number(data.timeout_seconds) || 0) : 0;
  const messageHtml = hitlDynamic(data, 'message', localizeHitlMessage(data));

  if (panel) {
    panel.classList.remove('hidden');
    panel.innerHTML = `
        <div class="relative bg-surface-container-lowest p-4 rounded-xl border border-primary/30 shadow-2xl flex flex-col gap-2">
          <h3 class="font-headline font-bold text-on-surface text-sm uppercase tracking-tight">${hitlLabel(isAmendment ? 'workOrder.amendTitle' : 'workOrder.title')}</h3>
          <p class="text-[11px] text-on-surface-variant">${messageHtml}</p>
          <p class="text-[10px] text-outline-variant leading-relaxed">${hitlLabel('hitl.answerInChat')}</p>
        </div>`;
  }

  const countdown = !panel ? '' : timeout > 0 && !data.held ? `
        <div id="wo-countdown-${rid}" class="mt-4 flex flex-col gap-1">
          <p class="text-[11px] text-tertiary" data-wo-countdown-text>${escHtml(t('workOrder.countdown').replace('{s}', Math.ceil(timeout)))}</p>
          <div class="h-1 w-full bg-surface-container-high rounded overflow-hidden">
            <div data-wo-countdown-bar class="h-full bg-tertiary transition-[width] duration-1000 ease-linear" style="width:100%"></div>
          </div>
        </div>` : `
        <p id="wo-countdown-${rid}" class="mt-4 text-[11px] text-outline-variant">${hitlLabel(data.held ? 'workOrder.paused' : 'workOrder.blocking')}</p>`;

  placeHitlCard(rid, `
        <div class="my-6 relative msg-enter" data-hitl-card="${escHtml(rid || '')}" data-wo-agent="${escHtml(data.agent_name || '')}" data-wo-rev="${escHtml(String(order.revision || 1))}">
          <div class="relative bg-surface-container-lowest p-6 rounded-xl border border-primary/30 shadow-2xl">
            ${woHeader(isAmendment ? 'edit_note' : 'assignment', isAmendment ? 'workOrder.amendTitle' : 'workOrder.title',
    tier, data.agent_name, order.revision)}
            <p class="text-sm text-on-surface-variant leading-relaxed mt-2">${messageHtml}</p>
            ${isAmendment ? workOrderDiff(ctx) : ''}
            ${workOrderBody(order, rid, !isAmendment)}
            ${countdown}
            <div id="hitl-controls-${rid}" class="mt-4 flex flex-col gap-2">
              <textarea id="hitl-feedback-${rid}" rows="2" data-i18n-placeholder="workOrder.ph.notes" placeholder="${escHtml(t('workOrder.ph.notes'))}"
                class="w-full bg-surface-container-high border border-outline-variant/20 rounded-md p-2 font-mono text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
              <div class="flex flex-wrap gap-3">
                <button onclick="respondWorkOrder('${rid}', 'approve')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
                  <span class="material-symbols-outlined text-base">check_circle</span> ${hitlLabel('hitl.btn.accept')}
                </button>
                ${timeout > 0 && !data.held ? `
                <button id="wo-pause-${rid}" onclick="holdWorkOrder('${rid}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-tertiary/30 text-tertiary px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-tertiary/10 transition-all">
                  <span class="material-symbols-outlined text-base">pause</span> ${hitlLabel('workOrder.btn.pause')}
                </button>` : ''}
                <button onclick="respondWorkOrder('${rid}', 'edit')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-surface-container-highest transition-all">
                  <span class="material-symbols-outlined text-base">edit_note</span> ${hitlLabel('hitl.btn.revise')}
                </button>
                <button onclick="respondWorkOrder('${rid}', 'reject')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error px-4 py-2 rounded-md font-bold text-[10px] uppercase tracking-[0.15em] hover:bg-error/10 transition-all">
                  <span class="material-symbols-outlined text-base">close</span> ${hitlLabel('hitl.btn.reject')}
                </button>
              </div>
            </div>
          </div>
        </div>`);

  if (timeout > 0 && !data.held) startWorkOrderCountdown(rid, timeout);
}

function startWorkOrderCountdown(rid, timeout) {
  stopWorkOrderCountdown(rid);
  const deadline = Date.now() + timeout * 1000;
  const tick = () => {
    const box = document.getElementById('wo-countdown-' + rid);
    if (!box) return stopWorkOrderCountdown(rid);
    const left = Math.max(0, (deadline - Date.now()) / 1000);
    const text = box.querySelector('[data-wo-countdown-text]');
    const bar = box.querySelector('[data-wo-countdown-bar]');
    if (text) text.textContent = t('workOrder.countdown').replace('{s}', Math.ceil(left));
    if (bar) bar.style.width = (100 * left / timeout) + '%';
    if (left <= 0) stopWorkOrderCountdown(rid);
  };
  tick();
  woTimers.set(rid, setInterval(tick, 1000));
}

function stopWorkOrderCountdown(rid) {
  const timer = woTimers.get(rid);
  if (timer) clearInterval(timer);
  woTimers.delete(rid);
}

// Local effect of a hold (this tab pressed Pause, or another tab did).
function applyWorkOrderHold(rid) {
  stopWorkOrderCountdown(rid);
  const box = document.getElementById('wo-countdown-' + rid);
  if (box) {
    box.className = 'mt-4 text-[11px] text-outline-variant';
    box.innerHTML = hitlLabel('workOrder.paused');
  }
  const pause = document.getElementById('wo-pause-' + rid);
  if (pause) pause.remove();
}
window.applyWorkOrderHold = applyWorkOrderHold;

function holdWorkOrder(rid) {
  if (ws && ws.readyState === 1) {
    ws.send(JSON.stringify({ type: 'hitl_hold', request_id: rid }));
  }
  applyWorkOrderHold(rid);
}

function respondWorkOrder(rid, action) {
  const feedbackEl = document.getElementById('hitl-feedback-' + rid);
  const feedback = feedbackEl ? feedbackEl.value.trim() : '';
  if (action === 'edit' && !feedback) {
    addSystemMsg(t('hitl.reviseEmpty'));
    if (feedbackEl) feedbackEl.focus();
    return;
  }
  const card = feedbackEl ? feedbackEl.closest('[data-wo-agent]') : null;
  const rejectedIds = card
    ? [...card.querySelectorAll('input[data-wo-assumption]')].filter(el => !el.checked).map(el => el.dataset.woAssumption)
    : [];
  if (card) card.querySelectorAll('input[data-wo-assumption]').forEach(el => { el.disabled = true; });
  sendHitlResponse({
    type: 'hitl_response',
    request_id: rid,
    action: action,
    approved: action === 'approve',
    instructions: feedback || null,
    free_input: feedback || null,
    form_values: action === 'approve' ? { rejected_assumption_ids: rejectedIds } : null,
  });
  document.getElementById('hitl-panel').classList.add('hidden');
  disableHitlControls(rid);
  const box = document.getElementById('wo-countdown-' + rid);
  if (box) box.remove();
}

function latestWorkOrderCard(agent) {
  const cards = document.querySelectorAll(`[data-wo-agent="${CSS.escape(agent || '')}"]`);
  return cards.length ? cards[cards.length - 1] : null;
}

// Non-blocking notices: a read-tier contract, step progress, a deviation.
function renderWorkOrderNotice(data) {
  const kind = data.kind;
  if (kind === 'declared' || kind === 'amended') {
    const order = data.work_order || {};
    const amended = kind === 'amended';
    appendMsgToFeed(`
          <div class="my-4 relative msg-enter" data-wo-agent="${escHtml(data.agent_name || '')}" data-wo-rev="${escHtml(String(order.revision || 1))}">
            <div class="relative bg-surface-container-lowest p-5 rounded-xl border border-outline-variant/20">
              ${woHeader(amended ? 'edit_note' : 'assignment', amended ? 'workOrder.amendTitle' : 'workOrder.noticeTitle',
      data.tier || order.tier, data.agent_name, order.revision)}
              ${amended ? workOrderDiff(data) : ''}
              ${workOrderBody(order, '', false)}
            </div>
          </div>`);
    scrollChat();
    return;
  }
  const card = latestWorkOrderCard(data.agent_name);
  if (kind === 'progress' && data.step) {
    if (!card) return;
    let row = card.querySelector(`[data-wo-step="${CSS.escape(data.step.id)}"]`);
    const html = woStepRow(data.step);
    if (row) {
      row.outerHTML = html;
    } else {
      const list = card.querySelector('[data-wo-steps]');
      if (list) list.insertAdjacentHTML('beforeend', html);
    }
    return;
  }
  if (kind === 'deviation' && data.deviation) {
    const dev = data.deviation;
    const line = `⚠ ${t('workOrder.deviation')}: ${dev.tool} — ${t('workOrder.reason.' + dev.reason, dev.reason)}`;
    const box = card ? card.querySelector('[data-wo-deviations]') : null;
    if (box) {
      box.insertAdjacentHTML('beforeend', `<p class="text-[11px] text-tertiary font-mono">${escHtml(line)}</p>`);
    }
    addTelemetry('WORK ORDER :: ' + (data.agent_name || '?') + ' ' + line);
  }
}
