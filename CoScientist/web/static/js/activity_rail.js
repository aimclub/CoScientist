// =========================================================================
// Navigation & Activity Rail
// =========================================================================
    const AGENTS = [
      { name: "OrchestratorAgent", icon: "hub", desc: "Master Orchestrator" },
      { name: "PlannerAgent", icon: "map", desc: "Roadmap Planner" },
      { name: "ToolsViewer", icon: "science", desc: "Tools Viewer" },
      // The knowledge memory is gone; this graph is the research record.
      { name: "KnowledgeGraph", icon: "bubble_chart", desc: "Research Graph", id: "graph-link", href: "/graph" },
      { name: "SessionTrace", icon: "schedule", desc: "Session Trace", id: "trace-link", href: "/trace" },
      { name: "MCPBuilder", icon: "build", desc: "MCP Builder", href: "/alembic/" },
      { name: "FedotTrace", icon: "monitoring", desc: "FEDOT.MAS Trace", href: "/fedot-trace" },
      { name: "FedotDemo", icon: "hub", desc: "FEDOT.MAS Demo (agent graph)", href: "/fedot-demo/" },
      { name: "CoderSandbox", icon: "terminal", desc: "CoderSandbox", id: "coder-sandbox-link", href: "http://localhost:8884/" },
      { name: "SandboxArtifacts", icon: "inventory_2", desc: "Sandbox artifacts" },
      { name: "__settings__", icon: "settings", desc: "Settings" },
    ];

    function isAgentHighlightedByDefault(name) {
      return true;
    }

    function initAgentNav() {
      const nav = document.getElementById('agent-nav');
      nav.innerHTML = AGENTS.map(a => {
        const highlighted = isAgentHighlightedByDefault(a.name);
        const opacityClass = highlighted ? "opacity-100" : "opacity-80";
        const iconColorClass = highlighted ? "text-primary" : "text-outline-variant";
        const textColorClass = highlighted ? "text-on-surface font-semibold" : "text-on-surface-variant font-medium";
        const elemIdAttr = (a.name === "KnowledgeGraph") ? 'id="graph-link"' : ((a.name === "CoderSandbox") ? 'id="coder-sandbox-link"' : `id="agent-${a.name}"`);
        const hrefAttr = a.href ? `href="${a.href}"` : '';
        const extraDot = (a.name === "CoderSandbox")
          ? `<span id="sandbox-status-dot" class="w-2 h-2 rounded-full bg-outline-variant/60 ml-auto" title="Sandbox standby"></span>`
          : '';

        return `
          <div ${elemIdAttr} ${hrefAttr} onclick="onAgentClick('${a.name}')" class="flex items-center gap-3 py-3 px-4 transition-all duration-200 ${opacityClass} cursor-pointer hover:bg-surface-variant/20 hover:opacity-100">
            <span class="material-symbols-outlined ${iconColorClass} text-lg">${a.icon}</span>
            <span class="text-sm ${textColorClass}" data-i18n="agent.${a.name}.desc">${a.desc}</span>
            ${extraDot}
          </div>
        `;
      }).join('');
      applyLanguage();
    }

    function onAgentClick(name) {
      if (name === "__settings__") {
        openSettings();
      } else if (name === "PlannerAgent") {
        openRoadmapEditor();
      } else if (name === "ToolsViewer") {
        openToolsViewer();
      } else if (name === "KnowledgeGraph" || name === "SessionTrace") {
        // Scope to the open session FIRST. The rail's own href carries no
        // session, so preferring it opened whichever session the page happened
        // to fall back to — the graph of a different run.
        const page = name === "SessionTrace" ? '/trace' : '/graph';
        const scoped = (activeUser && activeSession)
          ? `${page}?user_id=${encodeURIComponent(activeUser.id)}&session_id=${encodeURIComponent(activeSession.id)}`
          : page;
        window.open(scoped, '_blank');
      } else if (name === "MCPBuilder") {
        window.open('/alembic/', '_blank');
      } else if (name === "FedotTrace") {
        window.open('/fedot-trace', '_blank');
      } else if (name === "FedotDemo") {
        window.open('/fedot-demo/', '_blank');
      } else if (name === "SandboxArtifacts") {
        openArtifactsModal();
      } else if (name === "CoderSandbox") {
        const link = document.getElementById('coder-sandbox-link');
        const url = (link && link.href) ? link.href : (activeSandboxWatchUrl || getBaseSandboxUrl());
        window.open(url, '_blank');
      }
    }

    function highlightAgent(name) {
      AGENTS.forEach(a => {
        const targetId = a.id || ('agent-' + a.name);
        const el = document.getElementById(targetId);
        if (!el) return;
        if (a.name === name) {
          el.className = "flex items-center gap-3 py-3 px-4 bg-surface-container-high rounded-lg transition-all duration-200 border-l-2 border-primary cursor-pointer";
          const icon = el.querySelector('.material-symbols-outlined');
          if (icon) icon.className = "material-symbols-outlined text-primary text-lg animate-pulse";
          const label = el.querySelector('[data-i18n]');
          if (label) label.className = "text-sm text-on-surface font-semibold";
        } else {
          const highlighted = isAgentHighlightedByDefault(a.name);
          const opacityClass = highlighted ? "opacity-100" : "opacity-80";
          el.className = `flex items-center gap-3 py-3 px-4 transition-all duration-200 ${opacityClass} cursor-pointer hover:bg-surface-variant/20 hover:opacity-100`;

          const icon = el.querySelector('.material-symbols-outlined');
          if (icon) icon.className = `material-symbols-outlined ${highlighted ? 'text-primary' : 'text-outline-variant'} text-lg`;

          const label = el.querySelector('[data-i18n]');
          if (label) label.className = `text-sm ${highlighted ? 'text-on-surface font-semibold' : 'text-on-surface-variant font-medium'}`;
        }
      });
    }

    function resetAgents() {
      AGENTS.forEach(a => {
        const targetId = a.id || ('agent-' + a.name);
        const el = document.getElementById(targetId);
        if (el) {
          const highlighted = isAgentHighlightedByDefault(a.name);
          const opacityClass = highlighted ? "opacity-100" : "opacity-80";
          el.className = `flex items-center gap-3 py-3 px-4 transition-all duration-200 ${opacityClass} cursor-pointer hover:bg-surface-variant/20 hover:opacity-100`;

          const icon = el.querySelector('.material-symbols-outlined');
          if (icon) icon.className = `material-symbols-outlined ${highlighted ? 'text-primary' : 'text-outline-variant'} text-lg`;

          const label = el.querySelector('[data-i18n]');
          if (label) label.className = `text-sm ${highlighted ? 'text-on-surface font-semibold' : 'text-on-surface-variant font-medium'}`;
        }
      });
    }


    // =========================================================================
    // Activity Rail — live view of which agents run and which tools they call
    //
    // Fed by the same ``agent_event`` stream the chat uses, but rendered as a
    // fixed two-row strip: nothing is ever appended, so a long run cannot push
    // the conversation off screen. Agent chips light up while an agent is
    // producing events; tool pills show that agent's calls with a live counter.
    // =========================================================================
    const ACTIVITY_RAIL_KEY = 'coscientist.activity_rail';
    const ACTIVITY_IDLE_MS = 20000;  // an agent with no events for this long dims

    let activityAgents = new Map();   // agent name -> { icon, tools: Map, calls, lastSeen, transferred }
    let activitySelected = null;      // agent whose tools the second row shows
    let activityPinned = false;       // user clicked a chip -> stop auto-following
    let activityTicker = null;

    const AGENT_ICONS = {
      OrchestratorAgent: 'hub',
      InitAgent: 'flag',
      PlannerAgent: 'map',
      PlanCriticAgent: 'rate_review',
      HypothesesAgent: 'lightbulb',
      ResearchAgent: 'travel_explore',
      TaskExecutorAgent: 'alt_route',
      ToolPipelineAgent: 'checklist',
      ToolPreparerAgent: 'precision_manufacturing',
      ParallelToolSearcherAgent: 'manage_search',
      LocalToolsExtractorAgent: 'inventory_2',
      ToolRetrieverAgent: 'search',
      ToolWebSearcherAgent: 'public',
      ToolReranker: 'swap_vert',
      FullSetToolReranker: 'sort',
      WebToolsDeployerAgent: 'cloud_upload',
      McpBuilderAgent: 'construction',
      CoderAgent: 'terminal',
      DatasetCollectorAgent: 'dataset',
      MedicalAgent: 'ecg_heart',
      ExperimentAgent: 'science',
      FedotAgent: 'network_intelligence',
      ContextInitAgent: 'assignment',
      ContextInitSessionAgent: 'assignment',
      ResultAggregatorAgent: 'summarize',
    };

    const KNOWN_AGENTS = new Set(Object.keys(AGENT_ICONS));

    // Which agents are plumbing is declared in the system YAML (`internal:`)
    // and served by /api/agents. Only the pseudo-authors that are not agents
    // at all live here — they stay hidden even when internal agents are shown.
    const PSEUDO_AUTHORS = new Set(['system', 'user', 'unknown']);
    const INTERNAL_AGENTS = new Set(PSEUDO_AUTHORS);

    function isInternalAgent(name) {
      if (!name) return true;
      const n = String(name).trim();
      if (PSEUDO_AUTHORS.has(n)) return true;
      return !showInternal && INTERNAL_AGENTS.has(n);
    }

    // The rail and the trace tree drop internal agents as events arrive, so
    // flipping the switch replays the session from a fresh snapshot.
    // remember=false applies the server default without recording a choice.
    function setShowInternal(value, { remember = true } = {}) {
      const next = !!value;
      if (remember) {
        // A choice equal to the default is no choice: keep following the env.
        showInternalStored = next === !!appSettings.general.showInternal ? null : next;
        try {
          if (showInternalStored === null) localStorage.removeItem(SHOW_INTERNAL_KEY);
          else localStorage.setItem(SHOW_INTERNAL_KEY, String(next));
        } catch (_) { }
      }
      if (next === showInternal) return;
      showInternal = next;
      document.documentElement.classList.toggle('show-internal', showInternal);
      if (typeof activateSession === 'function' && activeUser && activeSession) {
        activateSession(activeUser, activeSession);
      }
    }
    window.setShowInternal = setShowInternal;
    window.isInternalAgent = isInternalAgent;
    window.INTERNAL_AGENTS = INTERNAL_AGENTS;

    async function loadInternalAgents() {
      try {
        const resp = await fetch('/api/agents');
        if (!resp.ok) return;
        const data = await resp.json();
        (data.internal_agents || []).forEach(name => INTERNAL_AGENTS.add(name));
        // Events that arrived before the list did may have recorded internal
        // agents; the render filter drops them now.
        renderActivityRail();
      } catch {
        // keep the pseudo-authors only
      }
    }
    loadInternalAgents();

    function agentIcon(name) {
      if (AGENT_ICONS[name]) return AGENT_ICONS[name];
      if (/tool/i.test(name)) return 'handyman';
      if (/critic|review/i.test(name)) return 'rate_review';
      if (name === 'system' || name === 'user') return 'settings_ethernet';
      return 'smart_toy';
    }

    function toolIcon(name) {
      const n = String(name || '').toLowerCase();
      if (n.includes('transfer')) return 'alt_route';
      if (n.includes('sandbox') || n.includes('shell') || n.includes('exec') || n.includes('code')) return 'terminal';
      if (n.includes('arxiv') || n.includes('pubmed') || n.includes('openalex') || n.includes('paper')) return 'menu_book';
      if (n.includes('search') || n.includes('web') || n.includes('query')) return 'travel_explore';
      if (n.includes('graph')) return 'bubble_chart';
      if (n.includes('dataset') || n.includes('data')) return 'dataset';
      if (n.includes('file') || n.includes('read') || n.includes('write') || n.includes('doc')) return 'description';
      if (n.includes('plot') || n.includes('chart') || n.includes('metric')) return 'insert_chart';
      if (n.includes('hitl') || n.includes('ask') || n.includes('input')) return 'forum';
      if (n.includes('task') || n.includes('track')) return 'checklist';
      return 'build';
    }

    function activityRailEnabled() {
      return localStorage.getItem(ACTIVITY_RAIL_KEY) !== 'off';
    }

    function toggleActivityRail() {
      localStorage.setItem(ACTIVITY_RAIL_KEY, activityRailEnabled() ? 'off' : 'on');
      renderActivityRail();
    }

    function activityAgent(name) {
      let entry = activityAgents.get(name);
      if (!entry) {
        entry = {
          name: name, icon: agentIcon(name), tools: new Map(), calls: 0, lastSeen: 0,
          running: 0, transferred: false, pending: new Set(),
        };
        activityAgents.set(name, entry);
      }
      return entry;
    }

    function activityBusy(entry) {
      return entry.pending.size + entry.running;
    }

    function activityCloseAgent(name) {
      const entry = activityAgents.get(name);
      if (!entry) return;
      entry.running = 0;
      entry.pending.clear();
      entry.transferred = false;
    }

    function activityTouchAgent(name, timestamp = null) {
      if (!name || isInternalAgent(name)) return;
      const entry = activityAgent(name);
      entry.lastSeen = timestamp ? new Date(timestamp).getTime() : Date.now();
      if (!activityPinned && (entry.calls > 0 || activityBusy(entry) > 0)) {
        activitySelected = name;
      }
      renderActivityRail();
    }

    function activityTool(entry, name) {
      let tool = entry.tools.get(name);
      if (!tool) {
        tool = { name: name, icon: toolIcon(name), calls: 0, done: 0, errors: 0, lastArgs: null };
        entry.tools.set(name, tool);
      }
      return tool;
    }

    function activityRecordCall(author, tc, timestamp = null) {
      const name = tc && tc.name;
      if (!name || isInternalAgent(author)) return;
      const entry = activityAgent(author);
      entry.lastSeen = timestamp ? new Date(timestamp).getTime() : Date.now();

      // Delegation, not tool use — show the target agent as soon as it is
      // picked, before it emits anything of its own.
      const transferred = tc.target_agent || (tc.is_delegation ? tc.name : null) || (name === 'transfer_to_agent'
        ? (tc.args && (tc.args.agent_name || tc.args.agentName))
        : (KNOWN_AGENTS.has(name) || /Agent$/.test(name) ? name : null));
      if (transferred) {
        if (!isInternalAgent(String(transferred))) {
          const next = activityAgent(String(transferred));
          next.transferred = true;
          next.lastSeen = entry.lastSeen;
          if (!activityPinned && (next.calls > 0 || activityBusy(next) > 0)) {
            activitySelected = next.name;
          }
          renderActivityRail();
        }
        return;
      }

      const tool = activityTool(entry, name);
      tool.calls++;
      tool.lastArgs = tc.args || null;
      entry.calls++;
      if (tc.callId) {
        entry.pending.add(tc.callId);
      } else {
        entry.running++;
      }
      if (!activityPinned) activitySelected = entry.name;
      renderActivityRail();
    }

    function activityRecordResponse(author, tr, timestamp = null) {
      const name = tr && tr.name;
      if (!name || name === 'transfer_to_agent' || isInternalAgent(author)) return;
      const isDelegation = tr.is_delegation || KNOWN_AGENTS.has(name) || /Agent$/.test(name);
      if (isDelegation) {
        activityCloseAgent(name);
        renderActivityRail();
        return;
      }
      const entry = activityAgent(author);
      entry.lastSeen = timestamp ? new Date(timestamp).getTime() : Date.now();
      const tool = activityTool(entry, name);
      tool.done++;
      if (activityResponseFailed(tr.response)) tool.errors++;
      if (tr.callId && entry.pending.delete(tr.callId)) {
        // paired with its own call
      } else {
        entry.running = Math.max(0, entry.running - 1);
      }
      renderActivityRail();
    }

    // Single entry point for the `tool_activity` stream, which reports tool use
    // at every nesting level (top-level agents and AgentTool sub-agents alike).
    function applyToolActivity(data, quiet = false) {
      const author = data.author || 'system';

      if (data.phase === 'agent_start' || data.phase === 'agent_end') {
        if (isInternalAgent(author)) return;
        activityTouchAgent(author, data.timestamp);
        if (data.phase === 'agent_end') {
          activityCloseAgent(author);
        }
        if (typeof addExperimentAgentEvent === 'function') {
          addExperimentAgentEvent(author, data);
        }
        renderActivityRail();
        return;
      }

      const tool = data.tool;
      if (!tool) return;

      if (data.phase === 'call') {
        activityRecordCall(author, {
          name: tool, args: data.args, callId: data.call_id,
          is_delegation: data.is_delegation, target_agent: data.target_agent,
        }, data.timestamp);
        addExperimentToolCall(author, {
          name: tool, args: data.args, callId: data.call_id,
          truncated: !!data.args_truncated, timestamp: data.timestamp,
          parent: data.parent, is_delegation: data.is_delegation,
          target_agent: data.target_agent,
        });
        if (!quiet) addTelemetry('TOOL_CALL :: ' + author + ' → ' + tool);
        return;
      }

      const failed = data.phase === 'error';
      const response = failed ? { error: data.error } : data.result;
      const truncated = failed ? !!data.error_truncated : !!data.result_truncated;
      activityRecordResponse(author, {
        name: tool, response: response, callId: data.call_id,
        is_delegation: data.is_delegation, target_agent: data.target_agent,
      }, data.timestamp);
      addExperimentToolResponse(author, {
        name: tool, response: response, callId: data.call_id,
        truncated: truncated, failed: failed, timestamp: data.timestamp,
      });
      if (!quiet) {
        addTelemetry((failed ? 'TOOL_ERROR :: ' : 'TOOL_RESULT :: ') + author
          + (failed ? ' ✖ ' : ' ← ') + tool);
      }
    }

    function activityResponseFailed(response) {
      if (!response) return false;
      if (typeof response === 'string') return /^\s*(error|traceback)/i.test(response);
      if (typeof response !== 'object') return false;
      if (response.error) return true;
      const status = String(response.status || response.result_status || '').toLowerCase();
      return status === 'error' || status === 'failed';
    }

    function activitySelectAgent(name) {
      // Clicking the already-selected chip releases the pin and resumes
      // auto-following whichever agent is currently talking.
      if (activityPinned && activitySelected === name) {
        activityPinned = false;
      } else {
        activitySelected = name;
        activityPinned = true;
      }
      renderActivityRail();
    }

    function activityReset() {
      activityAgents = new Map();
      activitySelected = null;
      activityPinned = false;
      renderActivityRail();
    }

    function activityMarkIdle() {
      activityAgents.forEach(entry => activityCloseAgent(entry.name));
      renderActivityRail();
    }

    function formatToolArgsSafe(args, max = 160) {
      if (!args) return '';
      let str = '';
      try {
        str = typeof args === 'string' ? args : JSON.stringify(args);
      } catch (e) {
        str = String(args);
      }
      return str.length > max ? str.slice(0, max) + '…' : str;
    }

    function scrollActivityRail(elementId, distance) {
      const el = document.getElementById(elementId);
      if (el) {
        el.scrollBy({ left: distance, behavior: 'smooth' });
        setTimeout(() => updateRailScrollButtons(elementId), 250);
      }
    }
    window.scrollActivityRail = scrollActivityRail;

    function updateRailScrollButtons(elementId) {
      const el = document.getElementById(elementId);
      if (!el) return;
      const prefix = elementId === 'activity-agents' ? 'rail-agents' : 'rail-tools';
      const leftBtn = document.getElementById(`${prefix}-left`);
      const rightBtn = document.getElementById(`${prefix}-right`);
      if (!leftBtn || !rightBtn) return;

      const hasOverflow = el.scrollWidth > el.clientWidth + 4;
      if (!hasOverflow) {
        leftBtn.classList.add('hidden');
        leftBtn.classList.remove('flex');
        rightBtn.classList.add('hidden');
        rightBtn.classList.remove('flex');
        return;
      }

      const canScrollLeft = el.scrollLeft > 6;
      const canScrollRight = el.scrollLeft < (el.scrollWidth - el.clientWidth - 6);

      leftBtn.classList.toggle('hidden', !canScrollLeft);
      leftBtn.classList.toggle('flex', canScrollLeft);
      rightBtn.classList.toggle('hidden', !canScrollRight);
      rightBtn.classList.toggle('flex', canScrollRight);
    }

    function attachRailWheelScroll(id) {
      const el = document.getElementById(id);
      if (!el || el._wheelAttached) return;
      el._wheelAttached = true;
      el.addEventListener('wheel', (e) => {
        if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && el.scrollWidth > el.clientWidth) {
          e.preventDefault();
          el.scrollLeft += e.deltaY;
          updateRailScrollButtons(id);
        }
      }, { passive: false });
      el.addEventListener('scroll', () => {
        updateRailScrollButtons(id);
      }, { passive: true });
    }

    function renderActivityRail() {
      const rail = document.getElementById('activity-rail');
      const toggle = document.getElementById('activity-toggle');
      if (!rail) return;

      const enabled = activityRailEnabled();
      if (toggle) {
        toggle.className = enabled
          ? 'text-primary hover:brightness-125 transition-colors'
          : 'text-outline-variant hover:text-primary transition-colors';
      }
      rail.classList.toggle('hidden', !enabled || activityAgents.size === 0);
      if (!enabled || activityAgents.size === 0) return;

      const now = Date.now();
      // Filter out internal pipelines or idle agents that have no tool calls and are not running
      const agents = [...activityAgents.values()]
        .filter(entry => !isInternalAgent(entry.name) && (entry.calls > 0 || activityBusy(entry) > 0))
        .sort((a, b) => a.lastSeen - b.lastSeen);

      rail.classList.toggle('hidden', !enabled || agents.length === 0);
      if (!enabled || agents.length === 0) return;

      if (activitySelected && !agents.some(a => a.name === activitySelected)) {
        activitySelected = null;
      }
      if (!activitySelected && agents.length) {
        const withCalls = agents.filter(a => a.calls > 0);
        activitySelected = withCalls.length ? withCalls[withCalls.length - 1].name : agents[agents.length - 1].name;
      }

      const countEl = document.getElementById('activity-agents-count');
      if (countEl) countEl.textContent = agents.length;

      const agentsBox = document.getElementById('activity-agents');
      if (agentsBox) {
        agentsBox.innerHTML = agents.map(entry => {
          const fresh = (now - entry.lastSeen) < ACTIVITY_IDLE_MS;
          const busy = fresh && activityBusy(entry) > 0;
          const selected = entry.name === activitySelected;

          const tone = busy
            ? 'border-primary/80 bg-primary/15 text-white rail-chip-busy'
            : selected
              ? 'ring-1 ring-primary/60 border-primary bg-surface-container-high/95 text-on-surface rail-chip-selected'
              : fresh
                ? 'border-outline-variant/25 bg-surface-container-low text-on-surface hover:border-primary/40 hover:bg-surface-container'
                : 'border-outline-variant/10 bg-surface-container-lowest/60 text-outline-variant/70 hover:text-on-surface hover:border-outline-variant/30';

          const beacon = busy
            ? `<span class="relative flex h-2 w-2 mr-0.5 shrink-0"><span class="rail-ping-anim absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-primary"></span></span>`
            : '';

          const pulse = busy ? ' animate-pulse text-primary' : (selected ? ' text-primary' : '');

          const badge = entry.calls
            ? `<span class="text-[9px] font-mono font-bold px-1.5 py-0.2 rounded bg-surface-container-highest/90 border border-outline-variant/20 text-on-surface-variant group-hover:text-primary transition-colors flex items-center gap-0.5 shrink-0"><span class="material-symbols-outlined text-[10px] text-primary/80">bolt</span>${entry.calls}</span>`
            : '';

          const delegated = entry.transferred
            ? `<span class="material-symbols-outlined text-[12px] text-primary/80 shrink-0" title="Delegated">alt_route</span>`
            : '';

          const cleanName = escHtml(entry.name.replace(/Agent$/, ''));
          let hint = `${entry.name}${entry.calls ? ` — ${entry.calls} tool call(s)` : ''}${entry.transferred ? ' — delegated' : ''}`;
          if (busy) hint += ' (Running)';

          return `
            <button type="button" onclick="activitySelectAgent('${escJs(entry.name)}')" title="${escHtml(hint)}"
              class="group relative flex items-center gap-1.5 shrink-0 px-2.5 py-1 rounded-lg border text-xs font-medium transition-all duration-150 cursor-pointer select-none shadow-sm ${tone}">
              ${beacon}
              <span class="material-symbols-outlined text-[15px] shrink-0${pulse}">${entry.icon}</span>
              <span class="font-headline tracking-tight text-[11px] font-medium shrink-0">${cleanName}</span>
              ${delegated}
              ${badge}
            </button>`;
        }).join('');
      }

      const selected = activityAgents.get(activitySelected);
      const labelEl = document.getElementById('activity-selected-agent-label');
      if (labelEl) {
        labelEl.textContent = selected ? `[${selected.name.replace(/Agent$/, '')}]` : '';
      }

      const tools = selected ? [...selected.tools.values()] : [];
      const toolsBox = document.getElementById('activity-tools');
      if (toolsBox) {
        if (!tools.length) {
          const noToolsText = (typeof t === 'function' ? t('rail.standby') : null) || 'Standby — awaiting tool invocation';
          toolsBox.innerHTML = `<div class="flex items-center gap-2 py-0.5 px-2 text-[10px] font-mono text-outline-variant/50 italic shrink-0"><span class="w-1.5 h-1.5 rounded-full bg-outline-variant/30"></span><span>${selected ? escHtml(selected.name) + ' — ' + noToolsText : noToolsText}</span></div>`;
        } else {
          const selectedFresh = (now - selected.lastSeen) < ACTIVITY_IDLE_MS;
          toolsBox.innerHTML = tools.map(tool => {
            const running = selectedFresh && tool.calls > tool.done;
            const tone = tool.errors
              ? 'border-error/50 bg-error/15 text-error hover:border-error/70'
              : running
                ? 'border-primary/60 bg-primary/15 text-primary shadow-[0_0_12px_rgba(0,218,243,0.25)]'
                : 'border-secondary/35 bg-secondary/10 text-secondary hover:border-secondary/60 hover:bg-secondary/15';

            const iconClass = running
              ? 'text-primary animate-spin'
              : (tool.errors ? 'text-error' : 'text-secondary');
            const iconName = running
              ? 'sync'
              : (tool.errors ? 'error' : (tool.calls > 0 ? 'check_circle' : tool.icon));

            const count = tool.calls > 1
              ? `<span class="text-[9px] font-mono px-1 rounded bg-surface-container-highest/70 border border-outline-variant/15 text-on-surface-variant font-bold">×${tool.calls}</span>`
              : '';
            const errorBadge = tool.errors
              ? `<span class="text-[8px] font-mono font-bold px-1 rounded bg-error/25 text-error">!${tool.errors}</span>`
              : '';

            let hint = `${tool.name} — ${tool.done}/${tool.calls} finished`;
            if (tool.errors) hint += `, ${tool.errors} error(s)`;
            if (tool.lastArgs && Object.keys(tool.lastArgs).length) {
              hint += `\n${formatToolArgsSafe(tool.lastArgs, 200)}`;
            }

            return `
              <button type="button" onclick="openToolsViewer()" title="${escHtml(hint)}"
                class="group relative flex items-center gap-1.5 shrink-0 px-2 py-0.5 rounded-md border text-[11px] font-mono transition-all duration-150 cursor-pointer shadow-sm ${tone}">
                <span class="material-symbols-outlined text-[13px] shrink-0 ${iconClass}">${iconName}</span>
                <span class="tracking-tight shrink-0">${escHtml(tool.name)}</span>
                ${count}
                ${errorBadge}
              </button>`;
          }).join('');
        }
      }

      attachRailWheelScroll('activity-agents');
      attachRailWheelScroll('activity-tools');
      updateRailScrollButtons('activity-agents');
      updateRailScrollButtons('activity-tools');
    }

    // Re-render on a slow tick so chips fade to "idle" without new events.
    activityTicker = setInterval(() => {
      if (activityAgents.size) renderActivityRail();
    }, 5000);


    // =========================================================================
    // Layout — collapsible left rail
    // =========================================================================
    function applySideNavState() {
      const collapsed = localStorage.getItem(SIDE_NAV_KEY) === 'off';
      document.body.classList.toggle('nav-collapsed', collapsed);
      const icon = document.getElementById('side-nav-toggle-icon');
      icon.textContent = collapsed ? 'left_panel_open' : 'left_panel_close';
      document.getElementById('side-nav-toggle').title = collapsed ? 'Show sidebar' : 'Hide sidebar';
    }

    function toggleSideNav() {
      const collapsed = document.body.classList.contains('nav-collapsed');
      localStorage.setItem(SIDE_NAV_KEY, collapsed ? 'on' : 'off');
      applySideNavState();
    }

    // ── The right rail: plan, pending question, spend ──────────────────────
    // Hidden or resized per browser, the same way the left one is hidden and
    // the graph page's detail panel is resized.
    const RAIL_DEFAULT = 320, RAIL_MIN = 260;

    function setSideRailWidth(px, save) {
      const max = Math.max(RAIL_MIN, Math.round(window.innerWidth * 0.6));
      const width = Math.min(max, Math.max(RAIL_MIN, Math.round(px)));
      document.documentElement.style.setProperty('--rail-w', width + 'px');
      if (save) {
        try { localStorage.setItem(SIDE_RAIL_WIDTH_KEY, String(width)); } catch (_) { }
      }
      return width;
    }

    // Collapse the rail WITHOUT recording a preference. The plan gate below
    // closes the column while the planner is still drafting, and the reader's
    // own choice has to survive that: persisting here would make a run in
    // planner mode silently turn the rail off for good.
    function showSideRail(collapsed) {
      document.body.classList.toggle('rail-collapsed', collapsed);
      const icon = document.getElementById('side-rail-toggle-icon');
      const button = document.getElementById('side-rail-toggle');
      if (icon) icon.textContent = collapsed ? 'right_panel_open' : 'right_panel_close';
      if (button) button.title = t(collapsed ? 'rail.show' : 'rail.hide');
    }

    function applySideRailState() {
      showSideRail(localStorage.getItem(SIDE_RAIL_KEY) === 'off');
    }

    function toggleSideRail() {
      const collapsed = document.body.classList.contains('rail-collapsed');
      localStorage.setItem(SIDE_RAIL_KEY, collapsed ? 'on' : 'off');
      applySideRailState();
    }

    function initSideRail() {
      let saved = null;
      try { saved = parseInt(localStorage.getItem(SIDE_RAIL_WIDTH_KEY), 10); } catch (_) { }
      if (saved) setSideRailWidth(saved, false);
      applySideRailState();

      const grip = document.getElementById('rail-grip');
      if (!grip) return;
      // The rail is the LAST column, so its width is the distance from the
      // pointer to the right edge of the window.
      const widthFrom = event => window.innerWidth - event.clientX;
      grip.addEventListener('pointerdown', event => {
        event.preventDefault();
        grip.setPointerCapture(event.pointerId);
        grip.classList.add('on');
        document.body.classList.add('resizing');
        const move = ev => setSideRailWidth(widthFrom(ev), false);
        const up = ev => {
          grip.removeEventListener('pointermove', move);
          grip.removeEventListener('pointerup', up);
          grip.removeEventListener('pointercancel', up);
          grip.classList.remove('on');
          document.body.classList.remove('resizing');
          setSideRailWidth(widthFrom(ev), true);
        };
        grip.addEventListener('pointermove', move);
        grip.addEventListener('pointerup', up);
        grip.addEventListener('pointercancel', up);
      });
      grip.addEventListener('dblclick', () => setSideRailWidth(RAIL_DEFAULT, true));
      window.addEventListener('resize', () => setSideRailWidth(
        parseInt(getComputedStyle(document.documentElement).getPropertyValue('--rail-w'), 10)
        || RAIL_DEFAULT, false));
    }

    // =========================================================================
    // Layout — plan gate (start mode "planner")
    // =========================================================================
    // While the planner is still drafting, the right panel stays closed and
    // Usage & Cost is left out. Once the plan is approved the panel opens with
    // the plan on top and usage below it. planApproved is per session: set from
    // the snapshot's history, then live by the approval (or by any non-planner
    // agent starting, which covers runs with HITL off). Starts unapproved so a
    // page load in planner mode does not flash the panel before the snapshot.
    let planApproved = false;

    function planGateActive() {
      return appSettings.general.startMode === 'planner' && !planApproved;
    }

    function refreshPlanGate() {
      const wasGated = document.body.classList.contains('plan-gated');
      const gated = planGateActive();
      document.body.classList.toggle('plan-gated', gated);
      document.body.classList.toggle('plan-first', appSettings.general.startMode === 'planner');
      if (gated) showSideRail(true);
      else if (wasGated) applySideRailState();
    }

    // The session was (re)loaded: approved if its history already shows the
    // planner's plan accepted or the work carried on past the planner.
    function resetPlanGate(messages) {
      const plannerRequests = new Set();
      planApproved = (messages || []).some(message => {
        if (message.type === 'hitl_request' && message.agent_name === 'PlannerAgent') {
          plannerRequests.add(message.request_id);
        } else if (message.type === 'hitl_response' || message.type === 'hitl_timeout') {
          return plannerRequests.has(message.request_id)
            && (message.type === 'hitl_timeout' ? !message.paused : message.action === 'approve');
        } else if (message.type === 'agent_event' || message.type === 'agent_output') {
          return isPostPlanAgent(message.author || message.agent);
        }
        return false;
      });
      refreshPlanGate();
    }

    function isPostPlanAgent(name) {
      return !!name && name !== 'user' && !PLAN_AGENTS.includes(name);
    }

    // The plan was accepted in this session: open the panel for the user.
    function releasePlanGate() {
      if (planApproved) return;
      planApproved = true;
      const wasGated = document.body.classList.contains('plan-gated');
      refreshPlanGate();
      if (wasGated) {
        localStorage.setItem(SIDE_RAIL_KEY, 'on');
        applySideRailState();
      }
    }
