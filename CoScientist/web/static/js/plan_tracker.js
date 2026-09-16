// =========================================================================
// Plan Tracker — the bottom-right panel: one line per task, with its state.
//
// It holds no plan of its own: the roadmap modal already merges every source
// (session snapshot, create_plan / update_task_status results, manual edits)
// into one task list, and calls render() whenever that list changes.
// =========================================================================
(function () {
  'use strict';

  const STATUS_VIEW = {
    done: { icon: 'check_circle', iconClass: 'text-secondary', textClass: 'text-on-surface-variant/60', label: 'plan.status.done' },
    in_progress: { icon: 'autorenew', iconClass: 'text-primary animate-spin', textClass: 'text-on-surface font-semibold', label: 'plan.status.in_progress' },
    error: { icon: 'error', iconClass: 'text-error', textClass: 'text-error/90', label: 'plan.status.error' },
    todo: { icon: 'radio_button_unchecked', iconClass: 'text-outline-variant/60', textClass: 'text-on-surface-variant', label: 'plan.status.todo' },
  };

  // The task last scrolled to: the list follows the work only when it moves
  // on, so a user reading further down is not yanked back on every update.
  let followedTaskId = null;

  function currentTasks() {
    return (window.RoadmapModal && window.RoadmapModal.getTasks()) || [];
  }

  function render(tasks = currentTasks()) {
    const panel = document.getElementById('plan-tracker');
    const list = document.getElementById('plan-tracker-list');
    if (!panel || !list) return;
    const normalize = window.RoadmapModal.normalizeStatus;

    // No plan yet: stay out of the layout entirely rather than reserving an
    // empty card, so the sidebar doesn't show a box with nothing in it.
    if (!tasks.length) {
      panel.classList.add('hidden');
      followedTaskId = null;
      list.innerHTML = '';
      return;
    }
    panel.classList.remove('hidden');

    const done = tasks.filter(task => normalize(task.status) === 'done').length;
    const percent = Math.round((done / tasks.length) * 100);
    document.getElementById('plan-tracker-count').textContent = `${done}/${tasks.length}`;
    document.getElementById('plan-tracker-bar').style.width = percent + '%';

    list.innerHTML = tasks.map((task, idx) => {
      const view = STATUS_VIEW[normalize(task.status)] || STATUS_VIEW.todo;
      const title = task.title || t('plan.untitled', 'Untitled task');
      const tooltip = `${task.id || idx + 1} · ${t(view.label)}\n${title}`;
      const rowClass = view === STATUS_VIEW.in_progress ? 'bg-primary/5 border-primary/60' : 'border-transparent';
      return `
        <li data-task-id="${escHtml(task.id || '')}" title="${escHtml(tooltip)}"
          class="flex items-start gap-2 pl-1.5 pr-1 py-1 rounded-r border-l-2 ${rowClass}">
          <span class="material-symbols-outlined text-[14px] shrink-0 mt-px ${view.iconClass}">${view.icon}</span>
          <span class="text-[9px] font-mono text-outline-variant/70 w-4 text-right shrink-0 mt-px">${idx + 1}</span>
          <span class="text-[11px] leading-snug break-words min-w-0 flex-1 ${view.textClass}">${escHtml(title)}</span>
        </li>`;
    }).join('');

    const active = tasks.find(task => normalize(task.status) === 'in_progress');
    if (active && active.id !== followedTaskId) {
      followedTaskId = active.id;
      const row = list.querySelector(`[data-task-id="${CSS.escape(active.id || '')}"]`);
      if (row) list.scrollTop = Math.max(0, row.offsetTop - list.clientHeight / 3);
    }
  }

  window.PlanTracker = { render };
  render();
})();
