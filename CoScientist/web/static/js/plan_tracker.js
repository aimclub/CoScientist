// =========================================================================
// Plan Tracker — the bottom-right panel: one line per task, with its state.
//
// It holds no plan of its own: the roadmap modal already merges every source
// (session snapshot, create_plan / update_task_status results, manual edits)
// into one task list, and calls render() whenever that list changes.
//
// A LINEAR pipeline (config `pipeline.linear`, e.g. microfluidics) is a plan
// in itself: its stages are the lines, and the status indicator — which
// tracks the stage the run is at — calls render() when a stage changes. The
// roadmap's tasks then nest under the stage of their assignee (the LIT-xx
// tasks under «Анализ литературы», whose members include ResearchAgent).
// =========================================================================
(function () {
  'use strict';

  const STATUS_VIEW = {
    done: { icon: 'check_circle', iconClass: 'text-secondary', textClass: 'text-on-surface-variant/60', label: 'plan.status.done' },
    in_progress: { icon: 'autorenew', iconClass: 'text-primary animate-spin', textClass: 'text-on-surface font-semibold', label: 'plan.status.in_progress' },
    error: { icon: 'error', iconClass: 'text-error', textClass: 'text-error/90', label: 'plan.status.error' },
    todo: { icon: 'radio_button_unchecked', iconClass: 'text-outline-variant/60', textClass: 'text-on-surface-variant', label: 'plan.status.todo' },
  };

  // The row last scrolled to: the list follows the work only when it moves
  // on, so a user reading further down is not yanked back on every update.
  let followedKey = null;

  function currentTasks() {
    return (window.RoadmapModal && window.RoadmapModal.getTasks()) || [];
  }

  function currentStages() {
    return (window.StatusIndicator && window.StatusIndicator.stages()) || [];
  }

  /** Rows of a plain roadmap: one per task. */
  function taskRows(tasks, normalize) {
    return tasks.map((task, idx) => ({
      key: 'task:' + (task.id || idx),
      id: task.id || idx + 1,
      number: idx + 1,
      title: task.title || t('plan.untitled', 'Untitled task'),
      status: normalize(task.status),
      nested: false,
    }));
  }

  /** Rows of a linear pipeline: its stages, each followed by the roadmap
   *  tasks its members execute. A task whose assignee is in no stage goes
   *  with the others; if none is, the tasks follow the last stage. */
  function stageRows(stages, tasks, normalize) {
    const stageOf = name => (name ? window.StatusIndicator.stageOf(name) : -1);
    const hosts = tasks.map(task => stageOf(task.assignee));
    const fallback = hosts.find(host => host >= 0);
    const host = i => (hosts[i] >= 0 ? hosts[i] : (fallback === undefined ? stages.length - 1 : fallback));
    const subRows = taskRows(tasks, normalize).map(row => Object.assign(row, { nested: true }));

    return stages.flatMap((stage, i) => [{
      key: 'stage:' + stage.agent,
      id: i + 1,
      number: i + 1,
      title: stage.title,
      status: stage.status,
      nested: false,
    }].concat(subRows.filter((_, j) => host(j) === i)));
  }

  function render(tasks = currentTasks()) {
    const panel = document.getElementById('plan-tracker');
    const list = document.getElementById('plan-tracker-list');
    if (!panel || !list) return;
    const normalize = window.RoadmapModal.normalizeStatus;
    const stages = currentStages();

    // No plan yet: stay out of the layout entirely rather than reserving an
    // empty card, so the sidebar doesn't show a box with nothing in it.
    if (!tasks.length && !stages.length) {
      panel.classList.add('hidden');
      followedKey = null;
      list.innerHTML = '';
      return;
    }
    panel.classList.remove('hidden');

    // The count and the bar measure the top-level lines: the stages when the
    // run is linear (the roadmap is one stage's business), else the tasks.
    const rows = stages.length ? stageRows(stages, tasks, normalize) : taskRows(tasks, normalize);
    const top = rows.filter(row => !row.nested);
    const done = top.filter(row => row.status === 'done').length;
    const percent = Math.round((done / top.length) * 100);
    document.getElementById('plan-tracker-count').textContent = `${done}/${top.length}`;
    document.getElementById('plan-tracker-bar').style.width = percent + '%';

    list.innerHTML = rows.map(row => {
      const view = STATUS_VIEW[row.status] || STATUS_VIEW.todo;
      const tooltip = `${row.id} · ${t(view.label)}\n${row.title}`;
      const rowClass = view === STATUS_VIEW.in_progress ? 'bg-primary/5 border-primary/60' : 'border-transparent';
      const indent = row.nested ? 'ml-5' : '';
      return `
        <li data-row-key="${escHtml(row.key)}" title="${escHtml(tooltip)}"
          class="flex items-center gap-2 pl-1.5 pr-1 py-1 rounded-r border-l-2 ${indent} ${rowClass}">
          <span class="material-symbols-outlined text-[14px] shrink-0 ${view.iconClass}">${view.icon}</span>
          <span class="text-[9px] font-mono text-outline-variant/70 w-4 text-right shrink-0">${row.number}</span>
          <span class="text-[11px] leading-snug truncate ${view.textClass}">${escHtml(row.title)}</span>
        </li>`;
    }).join('');

    // Follow the innermost work: a running task rather than its stage.
    const active = rows.filter(row => row.status === 'in_progress').sort((a, b) => b.nested - a.nested)[0];
    if (active && active.key !== followedKey) {
      followedKey = active.key;
      const row = list.querySelector(`[data-row-key="${CSS.escape(active.key)}"]`);
      if (row) list.scrollTop = Math.max(0, row.offsetTop - list.clientHeight / 3);
    }
  }

  window.PlanTracker = { render };
  render();
})();
