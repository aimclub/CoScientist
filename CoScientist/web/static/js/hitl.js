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
  work_report: 'workReport',
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
    // A tool's arguments are code; an agent's proposed result is a plan, a
    // summary, a page of prose. `code` decides which of the two treatments
    // the block gets — the same <pre> used to set both in IBM Plex Mono.
    const isToolCall = hitlTrigger(data) === 'before_tool';
    return {
      labelKey: isToolCall ? 'hitl.block.toolCall' : 'hitl.block.output',
      text: String(ctx.output),
      code: isToolCall,
    };
  }
  if (ctx.command) return { labelKey: 'hitl.block.command', text: String(ctx.command), code: true };
  if (ctx.user_query) return { labelKey: 'hitl.block.userQuery', text: String(ctx.user_query), code: false };
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
  redrawPlanCards();
}

// The plan card builds every label in JS — counts interpolated into "{n} tasks",
// the design-matrix headers, the per-task field names — so there is no
// data-i18n span for applyTranslations to swap. It is redrawn from the request
// it was drawn from instead; fold state lives in planOpenTasks, so the same
// tasks stay open across the redraw.
function redrawPlanCards() {
  if (typeof planByRequest === 'undefined') return;
  planByRequest.forEach((_, rid) => {
    const data = hitlCards.get(rid);
    // Only cards actually on screen: placeHitlCard appends when it finds none,
    // so a stale entry would resurrect a card the session has already cleared.
    if (!data || !document.querySelector(`[data-hitl-card="${CSS.escape(rid)}"]`)) return;
    const box = document.getElementById('hitl-controls-' + rid);
    const answered = !!(box && box.querySelector('button[disabled]'));
    renderExperimentPlanReview(!answered, data);
    if (answered) disableHitlControls(rid);
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
// no countdown, controls disabled until the server redelivers the request as
// still open.
//
// There used to be a second copy of every card in the right sidebar. It said
// the same thing as the one in the feed and could not be answered, so it was
// two places to read and one place to act. `live` is the only thing the
// renderers ever took from it — whether this request is still open — so that
// is what they are given now.
function showHITL(data, { history = false } = {}) {
  const live = !history;
  hitlCards.set(data.request_id || '', data);

  // Structured intake (e.g. the research frame): render a per-field form
  // instead of the free-text review, then stop — the other HITL points keep
  // the free-text / option path below.
  if (data.form && Array.isArray(data.form.blocks)) {
    renderHitlForm(live, data);
  } else if (((data.context || {}).experiment_plan || {}).tasks) {
    // An experiment plan is not a paragraph to skim: it is a design matrix and
    // a task list, and it is what the human is being asked to approve. The
    // backend ships it structured next to the rendered Markdown, so it gets a
    // view of its own rather than a <pre> of pipe-separated rows.
    renderExperimentPlanReview(live, data);
  } else if (data.trigger === 'work_report') {
    // Work Report (what the agent found, against its order): accept, send back
    // for rework with findings marked wrong, or reject.
    renderWorkReportCard(live, data);
  } else if (String(data.trigger || '').startsWith('work_order')) {
    // Work Order (the agent's contract before it acts): its own card with
    // assumptions to uncheck, a veto countdown and a Pause button.
    renderWorkOrderCard(live, data);
  } else {
    renderHitlCard(live, data);
  }
  if (history) disableHitlControls(data.request_id);
  scrollChat();
}

function renderHitlCard(live, data) {
  const messageHtml = hitlDynamic(data, 'message', localizeHitlMessage(data));
  const viaHtml = hitlDynamic(data, 'via', describeHitlVia(data));
  const agentHtml = `<span class="font-bold text-on-surface">${escHtml(data.agent_name || '—')}</span>`;

  let openRoadmapSidebarBtn = '';
  let openRoadmapChatBtn = '';
  if (data.agent_name === 'PlannerAgent') {
    openRoadmapSidebarBtn = `
      <button onclick="openRoadmapEditor()" class="w-full mt-2 flex items-center justify-center gap-2 bg-surface-variant border border-outline-variant/20 text-on-surface py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-surface-container-high transition-all">
        <span class="material-symbols-outlined text-sm">map</span> ${hitlLabel('hitl.btn.openRoadmap')}
      </button>
    `;
    openRoadmapChatBtn = `
      <div class="mt-4">
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
        <p class="text-[12px] text-on-surface-variant leading-relaxed">${hitlLabel('hitl.answerInChat')}</p>` : `
        <div class="flex gap-3">
          <button onclick="respondHITL('${data.request_id}', true)" class="flex-1 flex items-center justify-center gap-2 bg-primary text-on-primary py-3 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
            <span class="material-symbols-outlined text-base">check_circle</span> ${hitlLabel('hitl.btn.accept')}
          </button>
          <button onclick="respondHITL('${data.request_id}', false)" class="flex-1 flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error py-3 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-error/10 transition-all">
            <span class="material-symbols-outlined text-base">close</span> ${hitlLabel('hitl.btn.reject')}
          </button>
        </div>`;

  // Also show in chat: the request details + Accept / Revise controls.
  const detail = hitlDetailBlock(data);
  // Prose drops the grey fill entirely: white-on-grey is what made this hard
  // to look at, and an accent rule marks the block just as well without
  // putting a second surface under the one thing the human has to read.
  const detailBody = !detail ? '' : detail.code
    ? `<pre class="font-mono text-[13px] leading-relaxed text-on-surface whitespace-pre-wrap `
      + `bg-surface-container-high px-3 py-2.5 rounded-lg border border-outline-variant/20">${escHtml(detail.text)}</pre>`
    : `<div class="md-body hitl-prose text-on-surface border-l-2 border-primary/40 pl-4 pr-1">`
      + `${renderMarkdown(detail.text)}</div>`;
  const asDocument = documentBlock(data);
  const outputBlock = !detail && !asDocument ? '' : `
        <div class="mt-4 pt-4 border-t border-outline-variant/15">
          <p class="text-[13px] font-bold text-on-surface-variant uppercase tracking-wider mb-2">${hitlLabel(
      detail ? detail.labelKey : 'hitl.block.output')}</p>
          ${asDocument || foldable(detailBody, detail.text, { bg: '#191c22' })}
        </div>`;
  placeHitlCard(data.request_id, `
    <div class="my-6 relative msg-enter max-w-4xl" data-hitl-card="${escHtml(data.request_id || '')}">
      <div class="absolute -inset-2 bg-gradient-to-r from-primary/10 via-transparent to-primary/10 blur-2xl opacity-40"></div>
      <div class="relative bg-surface-container-low p-5 rounded-xl border border-primary/40 shadow-2xl">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
            <span class="material-symbols-outlined text-on-primary text-sm">ads_click</span>
          </div>
          <h3 class="font-headline font-bold text-base text-on-surface uppercase tracking-tight">${hitlLabel('hitl.title')}</h3>
        </div>
        <p class="text-sm text-on-surface-variant leading-relaxed">${messageHtml}</p>
        <div class="mt-2 flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[11px]">
          <span><span class="text-outline-variant">${hitlLabel('hitl.viaLabel')}:</span> <span class="text-primary">${viaHtml}</span></span>
        </div>
        ${outputBlock}
        ${isProvideInput ? `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pt-4 border-t border-outline-variant/15 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" data-i18n-placeholder="hitl.ph.input" placeholder="${escHtml(t('hitl.ph.input'))}"
            class="w-full bg-surface-container-high border border-outline-variant/25 rounded-md px-2.5 py-2 text-[13px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex">
            <button onclick="respondHITLInput('${data.request_id}')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">send</span> ${hitlLabel('hitl.btn.send')}
            </button>
          </div>
        </div>` : hasOptions ? `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pt-4 border-t border-outline-variant/15 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" data-i18n-placeholder="hitl.ph.reply" placeholder="${escHtml(t('hitl.ph.reply'))}"
            class="w-full bg-surface-container-high border border-outline-variant/25 rounded-md px-2.5 py-2 text-[13px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex flex-wrap gap-2">
            <button onclick="respondHITLEdit('${data.request_id}')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">reply</span> ${hitlLabel('hitl.btn.reply')}
            </button>
            ${data.options.map(o => `
            <button onclick="respondHITLOption('${data.request_id}', '${escJs(o)}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-surface-container-highest transition-all">${escHtml(o)}</button>`).join('')}
          </div>
        </div>` : `
        <div id="hitl-controls-${data.request_id}" class="mt-4 pt-4 border-t border-outline-variant/15 flex flex-col gap-2">
          <textarea id="hitl-feedback-${data.request_id}" rows="2" data-i18n-placeholder="hitl.ph.revise" placeholder="${escHtml(t('hitl.ph.revise'))}"
            class="w-full bg-surface-container-high border border-outline-variant/25 rounded-md px-2.5 py-2 text-[13px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
          <div class="flex gap-3">
            <button onclick="respondHITL('${data.request_id}', true)" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
              <span class="material-symbols-outlined text-base">check_circle</span> ${hitlLabel('hitl.btn.accept')}
            </button>
            <button onclick="respondHITL('${data.request_id}', false)" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-error/10 transition-all">
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
  // Answered, timed out or cancelled: the question is closed, so the panel it
  // opened closes with it. One the reader opened by hand stays.
  if (window.closeDocumentForRequest) closeDocumentForRequest(requestId);
  // Nothing left to act on: fold whatever this card was showing open.
  const card = document.querySelector(`[data-hitl-card="${CSS.escape(String(requestId || ''))}"]`);
  if (card) card.querySelectorAll('.fold-open').forEach(collapseFold);
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
  if (request.trigger === 'work_report') {
    const disputed = ((response.form_values || {}).disputed_finding_ids || []).length;
    const key = action === 'approve' ? 'workReport.accepted' : action === 'edit' ? 'workReport.sentBack' : 'workReport.rejected';
    return t(key)
      + (disputed ? ' — ' + t('workReport.disputedCount').replace('{n}', disputed) : '')
      + (feedback ? ': ' + feedback : '');
  }
  // The receipts a run leaves in the feed. The keys were written when the rest
  // of this function was localised; these three lines kept their literals, so a
  // Russian session recorded every verdict as "✓ HITL Approved".
  if (action === 'provide_input')
    return t('hitl.inputSent', { feedback: feedback || t('hitl.empty') });
  if (action === 'select') return '☑ ' + (response.selected_option || feedback);
  if (action === 'edit') return t('hitl.revisionRequested', { feedback: feedback });
  // The feedback used to hang off the rejected branch alone: `a ? b : c + d`
  // groups as `a ? b : (c + d)`, so an approval with a comment dropped it.
  return t(response.approved ? 'hitl.approved' : 'hitl.rejected')
    + (feedback ? ': ' + feedback : '');
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
  const request = hitlCards.get(payload.request_id || '');
  if (payload.action === 'approve' && request && request.agent_name === 'PlannerAgent') {
    releasePlanGate();
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
  disableHitlControls(requestId);

  if (currentPlannerHitlRequest && currentPlannerHitlRequest.request_id === requestId) {
    currentPlannerHitlRequest = null;
    updateRoadmapModalButtons();
  }
}

function respondHITL(requestId, approved) {
  const feedbackEl = document.getElementById('hitl-feedback-' + requestId);
  const feedback = feedbackEl ? feedbackEl.value.trim() : '';
  // Approving with feedback means the operator wants the output revised.
  const action = approved && feedback ? 'edit' : (approved ? 'approve' : 'reject');
  sendHitlResponse({
    type: 'hitl_response',
    request_id: requestId,
    action,
    approved: action === 'approve',
    instructions: feedback || null,
    free_input: feedback || null,
  });
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
  disableHitlControls(requestId);

  if (currentPlannerHitlRequest && currentPlannerHitlRequest.request_id === requestId) {
    currentPlannerHitlRequest = null;
    updateRoadmapModalButtons();
  }
}

// ── Structured frame form (research frame intake) ────────────────────────
function renderHitlForm(live, data) {
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
        ? `<span class="text-[11px] text-error uppercase tracking-wider">${escHtml(t('hitl.form.notSet'))}</span>`
        : `<span class="text-[11px] text-outline-variant uppercase tracking-wider">${escHtml(f.status || '')}</span>`;
      const val = f.open ? '' : String(f.value || '');
      const label = loc(f.label, f.name);
      const placeholder = loc(f.placeholder, t('hitl.form.placeholderFallback'));
      return `
            <div class="flex flex-col gap-1">
              <div class="flex items-center justify-between">
                <label class="text-[15px] font-semibold text-on-surface">${escHtml(label)}</label>
                ${openTag}
              </div>
              <textarea id="frm-${rid}-${bi}-${fi}" data-block="${escJs(b.title)}" data-field="${escJs(f.name)}"
                rows="2" placeholder="${escHtml(placeholder)}"
                class="w-full bg-surface-container-high border border-outline-variant/25 rounded-md px-3 py-2 text-[15px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50">${escHtml(val)}</textarea>
            </div>`;
    }).join('');
    const blockTitle = loc(b.title_i18n, b.title);
    const blockUsage = loc(b.usage_i18n, b.usage);
    return `
          <div class="mt-4 border border-outline-variant/15 rounded-lg p-4 bg-surface-container-high/30">
            <p class="text-[19px] font-bold text-on-surface leading-tight">${escHtml(blockTitle)}</p>
            ${blockUsage ? `<p class="text-[13px] text-on-surface-variant/80 mb-2.5 mt-0.5">${escHtml(blockUsage)}</p>` : '<div class="mb-2"></div>'}
            <div class="flex flex-col gap-2">${fieldsHtml}</div>
          </div>`;
  }).join('');


  // Open while the request is live — a form cannot be filled in folded —
  // and folded once it has been answered or replayed from the transcript.
  const blocksBlock = foldable(blocksHtml, blocksHtml, { bg: '#191c22', open: live });

  const formTitle = loc(form.title_i18n, form.title || t('hitl.form.title'));
  const formIntro = loc(form.intro_i18n, form.intro || data.message || '');
  // insertAdjacentHTML, not `innerHTML +=`: re-parsing the whole feed would
  // wipe whatever the operator is typing into the earlier cards.
  placeHitlCard(rid, `
        <div id="hitl-controls-${rid}" data-hitl-card="${escHtml(rid || '')}" class="my-6 relative msg-enter max-w-4xl">
          <div class="relative bg-surface-container-low p-5 rounded-xl border border-primary/40 shadow-2xl">
            <div class="flex items-center gap-3 mb-2">
              <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
                <span class="material-symbols-outlined text-on-primary text-sm">fact_check</span>
              </div>
              <h3 class="font-headline font-bold text-base text-on-surface uppercase tracking-tight">${escHtml(formTitle)}</h3>
            </div>
            <p class="text-sm text-on-surface-variant leading-relaxed">${escHtml(formIntro)}</p>
            ${blocksBlock}
            <div class="flex flex-wrap gap-3 mt-4">
              <button onclick="respondHITLForm('${rid}', true)" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
                <span class="material-symbols-outlined text-base">check_circle</span> ${escHtml(t('hitl.form.save'))}
              </button>
              <button onclick="respondHITLForm('${rid}', false)" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-surface-container-highest transition-all">
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

function woChip(text, cls = 'text-on-surface-variant border-outline-variant/30 bg-surface-container-high') {
  return `<span class="inline-block text-[11px] font-mono px-2 py-0.5 rounded border ${cls}">${escHtml(text)}</span>`;
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
        <div class="mt-3 pt-3 border-t border-outline-variant/15 first:mt-0 first:pt-0 first:border-0">
          <p class="text-[11px] font-bold text-on-surface-variant uppercase tracking-wider mb-1.5">${hitlLabel(labelKey)}</p>
          ${inner}
        </div>`;
}

// A card with a document shows its steps as one row of marks: the progress
// notices still replace a chip in place, so the run stays visible, and what each
// step is *for* is read in the panel. `woStepRow` keeps the full shape for a
// card that has no document to send the reader to.
function woStepChip(step) {
  const status = step.status || 'pending';
  const tip = [step.id, step.title, step.note, step.expected_outcome]
    .filter(Boolean).join(' — ');
  const tone = status === 'done' ? 'text-secondary border-secondary/40 bg-secondary/10'
    : status === 'in_progress' ? 'text-primary border-primary/50 bg-primary/10'
      : status === 'skipped' ? 'text-outline-variant/70 border-outline-variant/20'
        : 'text-outline-variant border-outline-variant/30';
  return `
          <li data-wo-step="${escHtml(step.id)}" data-wo-status="${escHtml(status)}"
            title="${escHtml(tip)}"
            class="inline-flex items-baseline gap-1 px-1.5 py-0.5 rounded border font-mono text-[11px] ${tone}">
            <span data-wo-mark>${WO_STEP_MARK[status] || '○'}</span>${escHtml(step.id)}
          </li>`;
}

function woStepRow(step, compact) {
  if (compact) return woStepChip(step);
  const status = step.status || 'pending';
  const tools = woToolChips(step.tools, step.internal_tools);
  return `
        <li data-wo-step="${escHtml(step.id)}" data-wo-status="${escHtml(status)}" class="flex flex-col gap-0.5">
          <div class="flex items-baseline gap-2">
            <span data-wo-mark class="font-mono text-primary w-4 text-center">${WO_STEP_MARK[status] || '○'}</span>
            <span class="font-mono text-[11px] text-outline-variant shrink-0">${escHtml(step.id)}</span>
            <span class="text-on-surface">${escHtml(step.title || '')}</span>
            <span class="flex flex-wrap gap-1">${tools}</span>
          </div>
          ${step.expected_outcome ? `<p class="pl-6 text-[12px] text-on-surface-variant">→ ${escHtml(step.expected_outcome)}</p>` : ''}
          <p data-wo-note class="pl-6 text-[12px] text-on-surface-variant italic">${escHtml(step.note || '')}</p>
        </li>`;
}

// The contract itself. interactive=true renders assumptions as checkboxes.
function workOrderBody(order, rid, interactive, compact) {
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
  const assumptionsBlock = woSection('workOrder.assumptions', assumptions
    ? (interactive ? `<p class="text-[12px] text-on-surface-variant mb-1.5">${hitlLabel('workOrder.assumptionsHint')}</p>` : '')
    + `<div class="flex flex-col gap-1">${assumptions}</div>`
    : '');
  const stepsBlock = woSection('workOrder.steps', (order.steps || []).length
    ? `<ol data-wo-steps data-compact="${compact ? '1' : '0'}" class="flex flex-col gap-1.5">`
      + order.steps.map(step => woStepRow(step, compact)).join('') + '</ol>'
    : '');

  // What the card is answered with, and what a progress notice patches. Never
  // folded: `.fold-body` clips with `overflow: hidden`, so a checkbox below the
  // line cannot be clicked and a step chip cannot be seen to tick.
  //
  // With a document it is chips, because the words are in the file. Without
  // one there is nowhere else for them to be, so it is the real thing.
  const controls = `
        <div class="text-xs text-on-surface-variant leading-relaxed flex flex-col gap-1.5 mt-3">
          ${compact ? chipsRow(order, interactive) + stepsRow(order)
    : assumptionsBlock + stepsBlock}
          <div data-wo-deviations class="flex flex-col gap-1"></div>
        </div>`;

  if (compact) {
    // Only the mechanism, never the prose: a checkbox per assumption because
    // `respondWorkOrder` reads them back, a chip per step because the progress
    // notices replace them as the agent works. Both say what they are in a
    // tooltip and in full in the document this card opens.
    return controls;
  }

  const body = `
        <div class="text-xs text-on-surface-variant leading-relaxed">
          ${woSection('workOrder.goal', `<p class="text-on-surface">${escHtml(order.goal || '')}</p>`)}
          ${woSection('workOrder.done', order.done_criteria ? `<p>${escHtml(order.done_criteria)}</p>` : '')}
          ${tools ? `<div class="${toolsOnlyInternal ? 'wo-internal' : ''}">${woSection('workOrder.tools', `<div class="flex flex-wrap gap-1">${tools}</div>`)}</div>` : ''}
          ${woSection('workOrder.sideEffects', effects ? `<div class="flex flex-wrap gap-1">${effects}</div>` : '')}
          ${woSection('workOrder.expected', order.expected_outcome ? `<p>${escHtml(order.expected_outcome)}</p>` : '')}
          ${woSection('workOrder.fallback', order.fallback ? `<p>${escHtml(order.fallback)}</p>` : '')}
        </div>`;
  // The prose folds; the controls under it do not. `.fold-body` clips with
  // `overflow: hidden`, so anything inside it that has to be clicked — or
  // patched by a progress notice — would be unreachable below the 11rem line.
  return foldable(body, JSON.stringify(order), { bg: '#191c22' }) + controls;
}

// ── The two rows the card is answered with ────────────────────────────────
function chipsRow(order, interactive) {
  const chips = (order.assumptions || []).map(a => `
            <label title="${escHtml(a.id + ' — ' + (a.text || ''))}"
              class="inline-flex items-baseline gap-1 px-1.5 py-0.5 rounded border cursor-pointer
                     font-mono text-[11px] border-outline-variant/30 hover:border-primary/50
                     transition-colors ${a.rejected ? 'line-through-dim' : 'text-on-surface-variant'}">
              <input type="checkbox" data-wo-assumption="${escHtml(a.id)}"
                class="accent-primary align-middle"
                ${a.rejected ? '' : 'checked'} ${interactive ? '' : 'disabled'} />
              ${escHtml(a.id)}
            </label>`).join('');
  if (!chips) return '';
  return `<div class="flex items-baseline flex-wrap gap-1.5">
            <span class="text-[12px] text-outline-variant shrink-0">${hitlLabel('workOrder.assumptions')}</span>
            ${chips}
          </div>`;
}

// `done` is not the only way a step closes: the server counts `skipped` as
// closed too (work_order.report_warnings reads open_steps the same way), so a
// run that skipped one would otherwise read 3/4 for ever.
const WO_STEP_OPEN = new Set(['pending', 'in_progress']);

function stepsRow(order) {
  const steps = order.steps || [];
  if (!steps.length) return '';
  const closed = steps.filter(s => !WO_STEP_OPEN.has(s.status || 'pending')).length;
  return `<div class="flex items-baseline flex-wrap gap-1.5">
            <span class="text-[12px] text-outline-variant shrink-0">${hitlLabel('workOrder.steps')}</span>
            <ol data-wo-steps data-compact="1" class="inline-flex flex-wrap items-baseline gap-1">${
    steps.map(woStepChip).join('')}</ol>
            <span data-wo-progress class="text-[11px] font-mono text-outline-variant">${closed}/${steps.length}</span>
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
    `<pre class="font-mono text-[12px] text-secondary whitespace-pre-wrap bg-surface-container-high px-2.5 py-2 rounded border border-outline-variant/20">${escHtml(rows.join('\n'))}</pre>`) : '';
  return reason + changes;
}

function woHeader(icon, titleKey, tier, agent, revision) {
  const tierCls = WO_TIER_STYLE[tier] || WO_TIER_STYLE.compute;
  return `
        <div class="flex items-center gap-3 flex-wrap">
          <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
            <span class="material-symbols-outlined text-on-primary text-sm">${icon}</span>
          </div>
          <h3 class="font-headline font-bold text-base text-on-surface uppercase tracking-tight">${hitlLabel(titleKey)}</h3>
          ${tier ? `<span class="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${tierCls}">${hitlLabel('workOrder.tier.' + tier)}</span>` : ''}
          <span class="text-[12px] font-bold text-on-surface">${escHtml(agent || '—')}</span>
          <span class="font-mono text-[10px] text-outline-variant">rev ${escHtml(String(revision || 1))}</span>
        </div>`;
}

function renderWorkOrderCard(live, data) {
  const rid = data.request_id;
  const ctx = data.context || {};
  const order = ctx.work_order || {};
  const tier = ctx.tier || order.tier || 'compute';
  const isAmendment = data.trigger === 'work_order_amendment';
  // A history card never counts down: its window has closed.
  const timeout = live ? (Number(data.timeout_seconds) || 0) : 0;
  const messageHtml = hitlDynamic(data, 'message', localizeHitlMessage(data));


  const countdown = woCountdown(live, data, timeout, 'workOrder.countdown');

  placeHitlCard(rid, `
        <div class="my-6 relative msg-enter max-w-4xl" data-hitl-card="${escHtml(rid || '')}" data-wo-agent="${escHtml(data.agent_name || '')}" data-wo-rev="${escHtml(String(order.revision || 1))}">
          <div class="relative bg-surface-container-low p-5 rounded-xl border border-primary/40 shadow-2xl">
            ${woHeader(isAmendment ? 'edit_note' : 'assignment', isAmendment ? 'workOrder.amendTitle' : 'workOrder.title',
    tier, data.agent_name, order.revision)}
            <p class="text-sm text-on-surface-variant leading-relaxed mt-2">${messageHtml}</p>
            ${isAmendment ? workOrderDiff(ctx) : ''}
            ${documentBlock(data)}
            ${workOrderBody(order, rid, !isAmendment, !!(data.document && data.document.artifact_id))}
            ${countdown}
            <div id="hitl-controls-${rid}" class="mt-4 flex flex-col gap-2">
              <textarea id="hitl-feedback-${rid}" rows="2" data-i18n-placeholder="workOrder.ph.notes" placeholder="${escHtml(t('workOrder.ph.notes'))}"
                class="w-full bg-surface-container-high border border-outline-variant/25 rounded-md px-2.5 py-2 text-[13px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
              <div class="flex flex-wrap gap-3">
                <button onclick="respondWorkOrder('${rid}', 'approve')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
                  <span class="material-symbols-outlined text-base">check_circle</span> ${hitlLabel('hitl.btn.accept')}
                </button>
                ${timeout > 0 && !data.held ? `
                <button id="wo-pause-${rid}" onclick="holdWorkOrder('${rid}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-tertiary/30 text-tertiary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-tertiary/10 transition-all">
                  <span class="material-symbols-outlined text-base">pause</span> ${hitlLabel('workOrder.btn.pause')}
                </button>` : ''}
                <button onclick="respondWorkOrder('${rid}', 'reject')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-error/10 transition-all">
                  <span class="material-symbols-outlined text-base">close</span> ${hitlLabel('hitl.btn.reject')}
                </button>
              </div>
            </div>
          </div>
        </div>`);

  if (timeout > 0 && !data.held) startWorkOrderCountdown(rid, timeout);
}

// The veto countdown (or "waiting for your decision") under a live card.
function woCountdown(live, data, timeout, textKey) {
  const rid = data.request_id;
  if (!live) return '';
  if (timeout > 0 && !data.held) {
    return `
        <div id="wo-countdown-${rid}" data-wo-countdown-key="${escHtml(textKey)}" class="mt-4 flex flex-col gap-1">
          <p class="text-[11px] text-tertiary" data-wo-countdown-text>${escHtml(t(textKey).replace('{s}', Math.ceil(timeout)))}</p>
          <div class="h-1 w-full bg-surface-container-high rounded overflow-hidden">
            <div data-wo-countdown-bar class="h-full bg-tertiary transition-[width] duration-1000 ease-linear" style="width:100%"></div>
          </div>
        </div>`;
  }
  return `
        <p id="wo-countdown-${rid}" class="mt-4 text-[11px] text-outline-variant">${hitlLabel(data.held ? 'workOrder.paused' : 'workOrder.blocking')}</p>`;
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
    const key = box.dataset.woCountdownKey || 'workOrder.countdown';
    if (text) text.textContent = t(key).replace('{s}', Math.ceil(left));
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
  // The single approval button doubles as "revise" when notes were entered.
  if (action === 'approve' && feedback) action = 'edit';
  if (action === 'edit' && !feedback) {
    addSystemMsg(t('hitl.reviseEmpty'));
    if (feedbackEl) feedbackEl.focus();
    return;
  }
  const card = feedbackEl ? feedbackEl.closest('[data-hitl-card]') : null;
  const rejectedIds = card
    ? [...card.querySelectorAll('input[data-wo-assumption]')].filter(el => !el.checked).map(el => el.dataset.woAssumption)
    : [];
  const disputedIds = card
    ? [...card.querySelectorAll('input[data-wr-finding]')].filter(el => el.checked).map(el => el.dataset.wrFinding)
    : [];
  if (card) card.querySelectorAll('input[data-wo-assumption], input[data-wr-finding]').forEach(el => { el.disabled = true; });
  // What the operator marked travels with EVERY action, not with one of them.
  //
  // These two lists used to be attached per action — rejections only on
  // `approve`, disputes only on `edit` — while the single button silently turns
  // `approve` into `edit` the moment a note is typed (above). So the ordinary
  // move of unticking an assumption AND saying why dropped the untick on the
  // floor: the agent was asked to revise and never told which assumption the
  // operator had rejected. Marking something and being ignored is worse than
  // having no checkbox at all.
  const formValues = {};
  if (rejectedIds.length) formValues.rejected_assumption_ids = rejectedIds;
  if (disputedIds.length) formValues.disputed_finding_ids = disputedIds;
  sendHitlResponse({
    type: 'hitl_response',
    request_id: rid,
    action: action,
    approved: action === 'approve',
    instructions: feedback || null,
    free_input: feedback || null,
    form_values: Object.keys(formValues).length ? formValues : null,
  });
  disableHitlControls(rid);
  const box = document.getElementById('wo-countdown-' + rid);
  if (box) box.remove();
}

// ── Work Report cards ────────────────────────────────────────────────────
const WR_VERDICT_STYLE = {
  met: 'text-primary border-primary/30 bg-primary/10',
  partial: 'text-tertiary border-tertiary/30 bg-tertiary/10',
  not_met: 'text-error border-error/30 bg-error/10',
};
const WR_CONFIDENCE_STYLE = {
  high: 'text-primary border-primary/30 bg-primary/10',
  medium: 'text-on-surface-variant border-outline-variant/30 bg-surface-container-high',
  low: 'text-tertiary border-tertiary/30 bg-tertiary/10',
};

function wrWarning(w) {
  const params = {
    steps: (w.steps || []).join(', '),
    findings: (w.findings || []).join(', '),
    count: w.count != null ? w.count : '',
    verdict: t('workReport.verdict.' + w.verdict, w.verdict || ''),
  };
  return `<p class="text-[11px] text-tertiary">⚠ ${escHtml(fillHitl('workReport.warn.' + w.code, params))}</p>`;
}

function wrFindingRow(f, interactive) {
  const head = `
            <span class="font-mono text-[10px] text-outline-variant">${escHtml(f.id)}</span>
            <span class="text-on-surface">${escHtml(f.text || '')}</span>
            ${woChip(t('workReport.confidence.' + f.confidence, f.confidence || ''), WR_CONFIDENCE_STYLE[f.confidence] || WR_CONFIDENCE_STYLE.medium)}
            ${f.step_id ? `<span class="font-mono text-[10px] text-outline-variant">${escHtml(f.step_id)}</span>` : ''}`;
  const evidence = f.evidence
    ? `<p class="pl-6 text-[11px] font-mono text-secondary break-all whitespace-pre-wrap">${escHtml(f.evidence)}</p>`
    : `<p class="pl-6 text-[11px] text-tertiary italic">${hitlLabel('workReport.noEvidence')}</p>`;
  if (interactive) {
    return `
          <li class="flex flex-col gap-0.5">
            <label class="flex items-baseline gap-2 flex-wrap cursor-pointer">
              <input type="checkbox" data-wr-finding="${escHtml(f.id)}" class="accent-error" title="${escHtml(t('workReport.markWrong'))}" />
              ${head}
            </label>
            ${evidence}
          </li>`;
  }
  const struck = f.disputed ? 'line-through' : '';
  return `
          <li class="flex flex-col gap-0.5">
            <div class="flex items-baseline gap-2 flex-wrap pl-6 ${struck}">${head}</div>
            ${evidence}
          </li>`;
}

// The report set against the order. interactive=true lets the human mark findings wrong.
function workReportBody(order, report, extra, interactive, compact) {
  const warnings = (extra.warnings || []).map(wrWarning).join('');
  const journal = extra.journal || {
    tool_calls: order.tool_calls || {},
    side_effects: [],
    amendments: order.amendments || [],
    deviations: order.deviations || [],
  };
  const disputed = new Set(report.disputed_finding_ids || []);
  const findings = (report.findings || [])
    .map(f => wrFindingRow({ ...f, disputed: disputed.has(f.id) }, interactive)).join('');
  const verdict = report.fallback ? '' : woChip(
    t('workReport.verdict.' + report.done_verdict, report.done_verdict || ''),
    WR_VERDICT_STYLE[report.done_verdict] || WR_VERDICT_STYLE.partial);
  const done = order.done_criteria || verdict ? `
            <p>${escHtml(order.done_criteria || '')} ${verdict}</p>
            ${report.done_evidence ? `<p class="text-[11px] text-outline-variant">${escHtml(report.done_evidence)}</p>` : ''}` : '';
  const outcome = order.expected_outcome || report.actual_outcome ? `
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div><p class="text-[10px] text-outline-variant">${hitlLabel('workOrder.expected')}</p><p>${escHtml(order.expected_outcome || '—')}</p></div>
              <div><p class="text-[10px] text-outline-variant">${hitlLabel('workReport.actual')}</p><p class="text-on-surface">${escHtml(report.actual_outcome || '—')}</p></div>
            </div>` : '';
  const artifacts = (report.artifacts || []).map(a => `
            <p class="flex items-baseline gap-2 flex-wrap">${woChip(t('workReport.kind.' + a.kind, a.kind || 'other'))}
              <span class="font-mono text-[11px] text-on-surface break-all">${escHtml(a.ref || '')}</span>
              ${a.description ? `<span class="text-[11px] text-outline-variant">${escHtml(a.description)}</span>` : ''}</p>`).join('');
  const calls = Object.entries(journal.tool_calls || {}).map(([tn, n]) => woChip(`${tn} ×${n}`)).join(' ');
  const effects = (journal.side_effects || []).map(k => woChip(k, WO_TIER_STYLE.side_effect)).join(' ');
  const amendments = (journal.amendments || []).map(a =>
    `<p class="text-[11px]"><span class="font-mono text-outline-variant">rev ${escHtml(String(a.revision || '?'))}</span> ${escHtml(a.reason || '')}</p>`).join('');
  const deviations = (journal.deviations || []).map(d =>
    `<p class="text-[11px] text-tertiary font-mono">⚠ ${escHtml(d.tool || '?')} — ${escHtml(t('workOrder.reason.' + d.reason, d.reason || ''))}</p>`).join('');
  const journalHtml = calls || effects || amendments || deviations ? `
            <div class="flex flex-col gap-1.5">
              ${calls ? `<div class="flex flex-wrap gap-1">${calls}</div>` : ''}
              ${effects ? `<div class="flex flex-wrap gap-1 items-center"><span class="text-[10px] text-outline-variant">${hitlLabel('workReport.sideEffectsDone')}</span> ${effects}</div>` : ''}
              ${amendments ? `<div><p class="text-[10px] text-outline-variant">${hitlLabel('workReport.amendments')}</p>${amendments}</div>` : ''}
              ${deviations ? `<div><p class="text-[10px] text-outline-variant">${hitlLabel('workReport.deviations')}</p>${deviations}</div>` : ''}
            </div>` : '';
  const summary = report.fallback
    ? `<p class="text-[10px] text-outline-variant mb-1">${hitlLabel('workReport.finalAnswer')}</p>
       ${foldable(`<div class="md-body hitl-prose text-on-surface border-l-2 border-primary/40 pl-4 pr-1">`
         + `${renderMarkdown(report.summary || '—')}</div>`, report.summary || '', { bg: '#191c22' })}`
    : `<p class="text-on-surface">${escHtml(report.summary || '')}</p>`;
  const findingsBlock = woSection('workReport.findings', findings
    ? (interactive ? `<p class="text-[12px] text-on-surface-variant mb-1.5">${hitlLabel('workReport.findingsHint')}</p>` : '')
      + `<ol class="flex flex-col gap-1.5">${findings}</ol>`
    : '');
  const warningsBlock = warnings
    ? `<div class="mt-3 flex flex-col gap-1 p-2 rounded border border-tertiary/30 bg-tertiary/5">${warnings}</div>`
    : '';

  if (compact) {
    // The findings carry the dispute checkboxes, and a warning is the one thing
    // that must not wait for someone to open a panel.
    return `
        <div class="text-xs text-on-surface-variant leading-relaxed">
          ${warningsBlock}
          ${findingsBlock}
        </div>`;
  }

  const body = `
        <div class="text-xs text-on-surface-variant leading-relaxed">
          ${warningsBlock}
          ${woSection('workOrder.goal', `<p>${escHtml(order.goal || '')}</p>`)}
          ${woSection('workReport.summary', summary)}
          ${findingsBlock}
          ${woSection('workOrder.done', done)}
          ${woSection('workReport.outcome', outcome)}
          ${woSection('workReport.steps', (order.steps || []).length
      ? `<ol class="flex flex-col gap-1.5">${order.steps.map(s => woStepRow(s, false)).join('')}</ol>` : '')}
          ${woSection('workReport.artifacts', artifacts ? `<div class="flex flex-col gap-1">${artifacts}</div>` : '')}
          ${woSection('workReport.journal', journalHtml)}
        </div>`;
  return foldable(body, JSON.stringify(report), { bg: '#191c22' });
}

function renderWorkReportCard(live, data) {
  const rid = data.request_id;
  const ctx = data.context || {};
  const order = ctx.work_order || {};
  const report = ctx.work_report || {};
  const tier = ctx.tier || order.tier || 'compute';
  const timeout = live ? (Number(data.timeout_seconds) || 0) : 0;
  const messageHtml = hitlDynamic(data, 'message', localizeHitlMessage(data));

  placeHitlCard(rid, `
        <div class="my-6 relative msg-enter max-w-4xl" data-hitl-card="${escHtml(rid || '')}" data-wr-agent="${escHtml(data.agent_name || '')}">
          <div class="relative bg-surface-container-low p-5 rounded-xl border border-primary/40 shadow-2xl">
            ${woHeader('fact_check', 'workReport.title', tier, data.agent_name, order.revision)}
            <p class="font-mono text-[10px] text-outline-variant mt-1">${escHtml(t('workReport.round').replace('{n}', report.round || 1))}</p>
            <p class="text-sm text-on-surface-variant leading-relaxed mt-2">${messageHtml}</p>
            ${documentBlock(data)}
            ${workReportBody(order, report, ctx, !report.fallback, !!(data.document && data.document.artifact_id))}
            ${woCountdown(live, data, timeout, 'workReport.countdown')}
            <div id="hitl-controls-${rid}" class="mt-4 flex flex-col gap-2">
              <textarea id="hitl-feedback-${rid}" rows="2" data-i18n-placeholder="workReport.ph.notes" placeholder="${escHtml(t('workReport.ph.notes'))}"
                class="w-full bg-surface-container-high border border-outline-variant/25 rounded-md px-2.5 py-2 text-[13px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
              <div class="flex flex-wrap gap-3">
                <button onclick="respondWorkOrder('${rid}', 'approve')" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
                  <span class="material-symbols-outlined text-base">check_circle</span> ${hitlLabel('hitl.btn.accept')}
                </button>
                ${timeout > 0 && !data.held ? `
                <button id="wo-pause-${rid}" onclick="holdWorkOrder('${rid}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-tertiary/30 text-tertiary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-tertiary/10 transition-all">
                  <span class="material-symbols-outlined text-base">pause</span> ${hitlLabel('workOrder.btn.pause')}
                </button>` : ''}
                <button onclick="respondWorkOrder('${rid}', 'reject')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-error/10 transition-all">
                  <span class="material-symbols-outlined text-base">close</span> ${hitlLabel('hitl.btn.reject')}
                </button>
              </div>
            </div>
          </div>
        </div>`);

  if (timeout > 0 && !data.held) startWorkOrderCountdown(rid, timeout);
}

function latestWorkOrderCard(agent) {
  const cards = document.querySelectorAll(`[data-wo-agent="${CSS.escape(agent || '')}"]`);
  return cards.length ? cards[cards.length - 1] : null;
}

// Non-blocking notices: a read-tier contract, step progress, a deviation, and
// (from a replayed transcript) a submitted Work Report.
function renderWorkOrderNotice(data) {
  const kind = data.kind;
  if (kind === 'report') {
    const order = data.work_order || {};
    const report = data.work_report || {};
    appendMsgToFeed(`
          <div class="my-4 relative msg-enter max-w-4xl" data-wr-agent="${escHtml(data.agent_name || '')}">
            <div class="relative bg-surface-container-low p-5 rounded-xl border border-outline-variant/25">
              ${woHeader('fact_check', 'workReport.title', data.tier || order.tier, data.agent_name, order.revision)}
              ${workReportBody(order, report, data, false)}
            </div>
          </div>`);
    scrollChat();
    return;
  }
  if (kind === 'declared' || kind === 'amended') {
    const order = data.work_order || {};
    const amended = kind === 'amended';
    appendMsgToFeed(`
          <div class="my-4 relative msg-enter max-w-4xl" data-wo-agent="${escHtml(data.agent_name || '')}" data-wo-rev="${escHtml(String(order.revision || 1))}">
            <div class="relative bg-surface-container-low p-5 rounded-xl border border-outline-variant/25">
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
    const list = card.querySelector('[data-wo-steps]');
    // A card whose detail moved to a document lists its steps compactly; a
    // replacement row has to match, or one tick would bring the detail back.
    const html = woStepRow(data.step, !!list && list.dataset.compact === '1');
    if (row) {
      row.outerHTML = html;
    } else if (list) {
      list.insertAdjacentHTML('beforeend', html);
    }
    // The compact row carries a "2/4" beside it; without this it would still
    // read 0/4 while the chips went green one by one.
    const tally = card.querySelector('[data-wo-progress]');
    if (tally && list) {
      const steps = [...list.querySelectorAll('[data-wo-step]')];
      const closed = steps.filter(el => !WO_STEP_OPEN.has(el.dataset.woStatus || 'pending')).length;
      tally.textContent = `${closed}/${steps.length}`;
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
const PLAN_CHIP_TONE = 'text-on-surface-variant border-outline-variant/30 bg-surface-container-high';

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
  return rows.map(x => `<span class="inline-block bg-surface-container-high border border-outline-variant/25 rounded px-1.5 py-0.5 mr-1 mb-1 text-[11px] font-mono">${escHtml(String(x))}</span>`).join('');
}

function planChip(label, value, tone) {
  const name = label ? `<span class="opacity-80 uppercase tracking-wider">${escHtml(label)}</span>` : '';
  return `<span class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-mono ${tone || PLAN_CHIP_TONE}">${name}${escHtml(String(value))}</span>`;
}

function planRouteChip(route) {
  return `<span class="inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-mono ${PLAN_ROUTE_TONE[route] || PLAN_CHIP_TONE}">${escHtml(route || '')}</span>`;
}

function planField(label, valueHtml) {
  return `<div class="grid grid-cols-[minmax(104px,max-content)_1fr] gap-x-3 py-1.5 border-b border-outline-variant/15 last:border-0">
    <span class="text-[11px] uppercase tracking-wider text-outline-variant pt-0.5">${escHtml(label)}</span>
    <span class="text-[12px] text-on-surface-variant leading-relaxed break-words min-w-0">${valueHtml}</span>
  </div>`;
}

function planSection(title, bodyHtml) {
  if (!bodyHtml) return '';
  return `<div class="mt-3 pt-3 border-t border-outline-variant/15 first:mt-0 first:pt-0 first:border-0">
    <p class="text-[11px] font-bold text-on-surface-variant uppercase tracking-wider mb-1.5">${escHtml(title)}</p>
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
    .map(key => `<th class="text-left font-bold uppercase tracking-wider text-[11px] text-on-surface-variant px-2 py-2 whitespace-nowrap">${escHtml(t(key))}</th>`)
    .join('');
  const rows = plan.matrix.map(r => `
    <tr class="border-t border-outline-variant/10 align-top">
      <td class="px-2 py-1.5 font-mono text-[11px] text-primary whitespace-nowrap">${escHtml(r.task_id || '')}</td>
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
    <span class="font-mono text-[11px] text-primary">${escHtml(c.criterion_id || '')}</span>
    <span class="text-[11px] uppercase tracking-wider text-outline-variant ml-1">${escHtml(c.kind || '')}</span>
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
    <span class="text-[11px] uppercase tracking-wider text-outline-variant ml-1">${escHtml(d.kind || '')}</span>
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
      <span class="font-mono text-[11px] text-primary">${escHtml(task.id || ('#' + (index + 1)))}</span>
      <span class="text-[13px] font-medium text-on-surface truncate flex-1">${escHtml(task.name || '')}</span>
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
    <span class="text-[11px] uppercase tracking-wider text-outline-variant ml-1">${escHtml(i.category || '')}</span>
    ${i.task_id ? `<span class="font-mono text-[11px] text-primary ml-1">${escHtml(i.task_id)}</span>` : ''}
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

function renderExperimentPlanReview(live, data) {
  const plan = (data.context || {}).experiment_plan;
  const rid = data.request_id;
  planByRequest.set(rid, plan);


  const hypotheses = (plan.hypotheses || []).map(h =>
    `<div class="mb-1"><span class="font-mono text-[11px] text-primary">${escHtml(h.id || '')}</span>
      <span class="text-[11px] ml-1">${planText(h.statement)}</span></div>`).join('');

  // Everything that is read rather than glanced at. The goal stays above the
  // fold with the chips: between them they say what this plan is, which is
  // what someone scrolling past needs.
  const detail = `
    ${plan.hypothesis ? planField(t('plan.hypothesis'), planText(plan.hypothesis)) : ''}
    ${planField(t('plan.methods'), planItems(plan.methods))}
    ${hypotheses ? planSection(t('plan.hypotheses'), hypotheses) : ''}
    ${planCritiqueBlock(plan)}
    ${planMatrix(plan)}
    <div class="mt-3 flex items-center justify-between">
      <p class="text-[13px] font-bold text-on-surface-variant uppercase tracking-wider">${escHtml(t('plan.tasksTitle'))}</p>
      <button type="button" id="plan-toggle-all-${escHtml(rid)}" onclick="togglePlanAllTasks('${escJs(rid)}')"
        class="text-[13px] uppercase tracking-wider text-primary hover:underline">${escHtml(t('plan.expandAll'))}</button>
    </div>
    <div id="plan-tasks-${escHtml(rid)}" class="mt-1">${plan.tasks.map((task, i) => planTaskCard(rid, task, i)).join('')}</div>
    ${planSection(t('plan.risks'), planBullets(plan.risks))}
    ${planSection(t('plan.assumptions'), planBullets(plan.assumptions))}`;

  placeHitlCard(rid, `
<div data-hitl-card="${escHtml(rid || '')}" class="my-6 relative msg-enter max-w-4xl">
  <div class="absolute -inset-2 bg-gradient-to-r from-primary/10 via-transparent to-primary/10 blur-2xl opacity-40"></div>
  <div class="relative bg-surface-container-low p-5 rounded-xl border border-primary/40 shadow-2xl">
    <div class="flex items-center gap-3 mb-2">
      <div class="w-8 h-8 rounded-full bg-primary flex items-center justify-center shadow-[0_0_15px_rgba(0,218,243,0.4)]">
        <span class="material-symbols-outlined text-on-primary text-sm">science</span>
      </div>
      <h3 class="font-headline font-bold text-base text-on-surface uppercase tracking-tight">${escHtml(t('plan.title'))}</h3>
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
    ${documentBlock(data) || foldable(detail, JSON.stringify(plan), { bg: '#191c22' })}
    <!-- Only the answer is disabled once this review is over (timeout, or
         the operator has answered): the plan stays readable and its task
         cards stay foldable, which is the whole point of drawing it. -->
    <div id="hitl-controls-${escHtml(rid)}" class="mt-4 flex flex-col gap-2">
      <textarea id="hitl-feedback-${escHtml(rid)}" rows="2" placeholder="${escHtml(t('plan.feedbackPlaceholder'))}"
        class="w-full bg-surface-container-high border border-outline-variant/25 rounded-md px-2.5 py-2 text-[13px] text-on-surface placeholder:text-outline-variant focus:outline-none focus:border-primary/50"></textarea>
      <div class="flex flex-wrap gap-3">
        <button onclick="respondHITL('${escJs(rid)}', true)" class="flex items-center justify-center gap-2 bg-primary text-on-primary px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] shadow-lg shadow-primary/20 hover:brightness-110 active:scale-95 transition-all">
          <span class="material-symbols-outlined text-base">check_circle</span> ${escHtml(t('plan.accept'))}
        </button>
        <button onclick="respondHITLEdit('${escJs(rid)}')" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-on-surface px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-surface-container-highest transition-all">
          <span class="material-symbols-outlined text-base">edit_note</span> ${escHtml(t('plan.revise'))}
        </button>
        <button onclick="respondHITL('${escJs(rid)}', false)" class="flex items-center justify-center gap-2 bg-surface-container-high border border-outline-variant/20 text-error px-4 py-2 rounded-md font-bold text-[12px] uppercase tracking-[0.08em] hover:bg-error/10 transition-all">
          <span class="material-symbols-outlined text-base">close</span> ${escHtml(t('plan.reject'))}
        </button>
      </div>
    </div>
  </div>
</div>`);
}
