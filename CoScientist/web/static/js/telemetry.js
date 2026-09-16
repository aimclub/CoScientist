// =========================================================================
// Telemetry & Usage Metrics
// =========================================================================
    // =========================================================================
    // Telemetry
    // =========================================================================
    function renderEventCount() {
      const el = document.getElementById('event-count');
      if (el) el.textContent = t('topbar.events', { count: eventCount });
    }

    function addTelemetry(text) {
      const log = document.getElementById('telemetry-log');
      const t = new Date().toLocaleTimeString('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
      log.innerHTML += `<div class="flex gap-2"><span class="text-outline-variant">[${t}]</span> ${escHtml(text)}</div>`;
      log.scrollTop = log.scrollHeight;
      eventCount++;
      renderEventCount();
    }


    // =========================================================================
    // Usage & Cost
    //
    // Cumulative per session and pushed from the server's ledger, so a
    // reconnecting tab gets the whole picture in one snapshot instead of having
    // to add up a stream. Rows are agents; a sandbox run shows as the child of
    // the agent that started it, because that is who spent the money.
    // =========================================================================
    function fmtUsd(value) {
      const n = Number(value) || 0;
      if (n && n < 0.0001) return '<$0.0001';
      return '$' + n.toFixed(4);
    }

    function fmtTokens(value) {
      const n = Number(value) || 0;
      if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
      if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
      return String(n);
    }

    function renderMetrics(data) {
      if (!data) return;
      const totals = data.totals || {};
      const llm = data.llm || {};
      const sandbox = data.sandbox || {};

      document.getElementById('metrics-total').textContent = fmtUsd(totals.cost_usd);

      const summaryEl = document.getElementById('metrics-summary');
      delete summaryEl.dataset.empty;
      const summary = [`${llm.calls || 0} ${t('metrics.calls')}`, `${fmtTokens(totals.total_tokens)} ${t('metrics.tokens')}`];
      if (sandbox.runs) {
        summary.push(`${sandbox.runs} sandbox`, `${Math.round(sandbox.gpu_seconds || 0)}s GPU`);
        if (sandbox.energy_wh) summary.push(`${(sandbox.energy_wh).toFixed(1)} Wh`);
      }
      summaryEl.textContent = summary.join(' · ');

      const rows = (data.agents || []).map(agent => {
        const box = agent.sandbox;
        const child = box ? `
          <div class="flex justify-between text-outline-variant/60 pl-3">
            <span class="truncate">└ sandbox · ${Math.round(box.agent_seconds || 0)}s</span>
            <span>${fmtUsd(box.total_cost_usd)}</span>
          </div>` : '';
        return `
          <div>
            <div class="flex justify-between gap-2">
              <span class="truncate text-on-surface/80" title="${escHtml(agent.agent)}">${escHtml(agent.agent)}</span>
              <span class="text-outline-variant whitespace-nowrap">${fmtTokens(agent.llm.total_tokens)} · ${fmtUsd(agent.cost_usd)}</span>
            </div>${child}
          </div>`;
      });
      document.getElementById('metrics-agents').innerHTML =
        rows.join('') || '<div class="text-outline-variant">—</div>';

      // A model litellm has no price for is counted in tokens but not in money:
      // say so, rather than let the total read as the whole bill.
      const note = document.getElementById('metrics-note');
      if (totals.complete === false) {
        const models = (llm.unpriced_models || []).join(', ');
        note.textContent =
          t('metrics.unpriced', { count: llm.unpriced_calls }) +
          (models ? `: ${models}` : '.');
        note.classList.remove('hidden');
      } else {
        note.classList.add('hidden');
      }
    }

    function resetMetrics() {
      const summaryEl = document.getElementById('metrics-summary');
      document.getElementById('metrics-total').textContent = '$0.0000';
      summaryEl.textContent = t('metrics.noCalls');
      summaryEl.dataset.empty = '1';
      document.getElementById('metrics-agents').innerHTML = '';
      document.getElementById('metrics-note').classList.add('hidden');
    }

