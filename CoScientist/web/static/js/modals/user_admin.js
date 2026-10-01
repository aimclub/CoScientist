// =========================================================================
// Settings → Users & sessions
// =========================================================================
// An administration panel of this local server: every user and every session,
// with sizes on disk, rename, hide, export and permanent deletion. It keeps
// its own state, so a re-render of the settings form (language switch, search)
// redraws it from memory instead of losing a selection or a pending confirm.

    const userAdmin = {
      users: null,             // null until the first load
      userId: null,            // user whose sessions are listed
      sessions: null,
      selected: new Set(),     // session ids
      selectedUsers: new Set(),
      query: '',
      sort: 'updated',         // updated | created | size
      olderDays: 30,
      editing: null,           // { kind: 'user' | 'session', id }
      confirm: null,           // { title, text, run }
      busy: false,
      message: '',
      messageKind: '',
      loadError: '',
    };

    function uaBytes(bytes) {
      const n = Number(bytes) || 0;
      if (n < 1024) return `${n} B`;
      const units = ['KB', 'MB', 'GB', 'TB'];
      let value = n / 1024, i = 0;
      while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
      return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
    }

    function uaDate(iso) {
      if (!iso) return '—';
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return '—';
      return d.toLocaleString(currentLang === 'ru' ? 'ru-RU' : 'en-GB',
        { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    function uaUser(id = userAdmin.userId) {
      return (userAdmin.users || []).find(u => u.id === id) || null;
    }

    function uaSession(id) {
      return (userAdmin.sessions || []).find(s => s.id === id) || null;
    }

    function uaUrl(userId, sessionId = null, suffix = '') {
      let url = `/api/users/${encodeURIComponent(userId)}`;
      if (sessionId) url += `/sessions/${encodeURIComponent(sessionId)}`;
      return url + suffix;
    }

    // ── loading ─────────────────────────────────────────────────────────────
    async function loadUserAdmin({ keepMessage = false } = {}) {
      if (!keepMessage) userAdmin.message = '';
      try {
        const data = await apiJson('/api/admin/users');
        userAdmin.users = data.users || [];
        userAdmin.loadError = '';
        const userIds = new Set(userAdmin.users.map(u => u.id));
        [...userAdmin.selectedUsers].forEach(id => { if (!userIds.has(id)) userAdmin.selectedUsers.delete(id); });
        if (!uaUser()) {
          userAdmin.userId = (activeUser && uaUser(activeUser.id)) ? activeUser.id
            : (userAdmin.users[0] ? userAdmin.users[0].id : null);
          userAdmin.selected.clear();
        }
        await loadUserAdminSessions();
      } catch (error) {
        userAdmin.loadError = error.message || String(error);
        renderUserAdmin();
      }
    }

    async function loadUserAdminSessions() {
      if (!userAdmin.userId) { userAdmin.sessions = []; renderUserAdmin(); return; }
      try {
        const data = await apiJson(`/api/admin/users/${encodeURIComponent(userAdmin.userId)}/sessions`);
        userAdmin.sessions = data.sessions || [];
        const ids = new Set(userAdmin.sessions.map(s => s.id));
        [...userAdmin.selected].forEach(id => { if (!ids.has(id)) userAdmin.selected.delete(id); });
      } catch (error) {
        userAdmin.loadError = error.message || String(error);
      }
      renderUserAdmin();
    }

    // ── rendering ───────────────────────────────────────────────────────────
    // Called from renderSettingsSection: returns the markup from memory and
    // starts the first load.
    function userAdminSectionHtml() {
      if (userAdmin.users === null && !userAdmin.loadError) setTimeout(loadUserAdmin, 0);
      return `<div id="user-admin-root">${userAdminHtml()}</div>`;
    }

    function renderUserAdmin() {
      const root = document.getElementById('user-admin-root');
      if (root) {
        const focusId = document.activeElement && document.activeElement.id;
        root.innerHTML = userAdminHtml();
        if (focusId && focusId.startsWith('ua-')) {
          const el = document.getElementById(focusId);
          if (el) { el.focus(); if (el.setSelectionRange && el.value) el.setSelectionRange(el.value.length, el.value.length); }
        }
      }
      renderUserAdminConfirm();
    }

    const UA_BTN = 'inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] border border-outline-variant/20 text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors disabled:opacity-40 disabled:cursor-not-allowed';
    const UA_DANGER_BTN = 'inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] border border-error/30 text-error hover:bg-error/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed';
    const UA_ICON_BTN = 'w-7 h-7 inline-flex items-center justify-center rounded-md text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors disabled:opacity-30 disabled:cursor-not-allowed';

    function userAdminHtml() {
      if (userAdmin.loadError && userAdmin.users === null) {
        return `<p class="text-xs text-error">${escHtml(t('admin.loadFailed', { error: userAdmin.loadError }))}</p>
          <button type="button" data-ua="reload" class="${UA_BTN} mt-3"><span class="material-symbols-outlined text-sm">refresh</span>${escHtml(t('admin.reload'))}</button>`;
      }
      if (userAdmin.users === null) {
        return `<p class="text-xs text-outline-variant">${escHtml(t('settings.status.loading'))}</p>`;
      }
      const message = userAdmin.message ? `
        <p class="text-[11px] ${userAdmin.messageKind === 'error' ? 'text-error' : 'text-secondary'} flex items-center gap-1.5" role="status">
          <span class="material-symbols-outlined text-sm">${userAdmin.messageKind === 'error' ? 'error' : 'check_circle'}</span>${escHtml(userAdmin.message)}</p>` : '';
      return `
        <div class="space-y-6">
          ${message}
          <section>
            <div class="flex items-center gap-2 mb-2">
              <h5 class="text-[11px] font-bold uppercase tracking-widest font-headline text-outline-variant">${escHtml(t('admin.users'))}</h5>
              <button type="button" data-ua="reload" class="${UA_ICON_BTN}" title="${escHtml(t('admin.reload'))}" aria-label="${escHtml(t('admin.reload'))}">
                <span class="material-symbols-outlined text-base">refresh</span></button>
              <button type="button" data-ua="delete-selected-users" ${userAdmin.selectedUsers.size && !userAdmin.busy ? '' : 'disabled'} class="${UA_DANGER_BTN} ml-auto">
                <span class="material-symbols-outlined text-sm">group_remove</span>${escHtml(t('admin.deleteSelectedUsers', { n: userAdmin.selectedUsers.size }))}</button>
            </div>
            ${deletableUsers().length > 1 ? `
              <label class="flex items-center gap-2 px-3 mb-1 text-[11px] text-on-surface-variant cursor-pointer w-fit">
                <input type="checkbox" data-ua="check-all-users" ${deletableUsers().every(u => userAdmin.selectedUsers.has(u.id)) ? 'checked' : ''}
                  class="rounded border-outline-variant/40 bg-transparent text-primary" />${escHtml(t('admin.selectAllUsers'))}</label>` : ''}
            <div class="rounded-lg border border-outline-variant/15 divide-y divide-outline-variant/10">
              ${userAdmin.users.length ? userAdmin.users.map(userRowHtml).join('')
                : `<p class="px-3 py-3 text-xs text-outline-variant">${escHtml(t('admin.noUsers'))}</p>`}
            </div>
          </section>
          ${uaUser() ? sessionsBlockHtml() : ''}
        </div>`;
    }

    function userRowHtml(user) {
      const selected = user.id === userAdmin.userId;
      const isMe = activeUser && activeUser.id === user.id;
      const editing = userAdmin.editing && userAdmin.editing.kind === 'user' && userAdmin.editing.id === user.id;
      const name = editing
        ? `<input id="ua-edit-input" type="text" maxlength="64" value="${escHtml(user.nickname)}" data-ua-edit="user"
             class="w-full px-2 py-1 text-xs bg-surface-container-high border border-primary/40 rounded-md text-on-surface" />`
        : `<button type="button" data-ua="select-user" data-id="${escHtml(user.id)}" class="text-left min-w-0 truncate text-[13px] ${selected ? 'font-semibold text-primary' : 'text-on-surface hover:text-primary'}">${escHtml(user.nickname)}</button>`;
      const badges = [
        isMe ? `<span class="px-1.5 py-0.5 rounded text-[10px] bg-primary/10 text-primary">${escHtml(t('admin.you'))}</span>` : '',
        user.running ? `<span class="px-1.5 py-0.5 rounded text-[10px] bg-secondary/10 text-secondary">${escHtml(t('admin.running'))}</span>` : '',
        user.protected ? `<span class="px-1.5 py-0.5 rounded text-[10px] bg-surface-container-high text-outline-variant" title="${escHtml(t('admin.protectedHint'))}">${escHtml(t('admin.protected'))}</span>` : '',
      ].join('');
      const id = escHtml(user.id);
      return `
        <div class="flex items-center gap-3 px-3 py-2 ${selected ? 'bg-primary/5' : ''}">
          <input type="checkbox" data-ua="check-user" data-id="${id}" ${userAdmin.selectedUsers.has(user.id) ? 'checked' : ''} ${user.protected ? 'disabled' : ''}
            title="${escHtml(user.protected ? t('admin.protectedHint') : user.nickname)}" aria-label="${escHtml(user.nickname)}"
            class="shrink-0 rounded border-outline-variant/40 bg-transparent text-primary disabled:opacity-30" />
          <span class="w-7 h-7 shrink-0 rounded-full bg-surface-container-high flex items-center justify-center text-[11px] font-bold text-on-surface-variant">${escHtml((user.nickname || '?').trim().charAt(0).toUpperCase())}</span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 min-w-0">${name}${badges}</div>
            <p class="text-[11px] text-outline-variant mt-0.5">${escHtml(t('admin.userStats', {
              sessions: user.session_count, size: uaBytes(user.size_bytes), last: uaDate(user.last_activity) }))}</p>
          </div>
          <div class="flex items-center gap-0.5 shrink-0">
            ${isMe ? '' : `<button type="button" data-ua="switch-user" data-id="${id}" class="${UA_ICON_BTN}" title="${escHtml(t('admin.switchUser'))}" aria-label="${escHtml(t('admin.switchUser'))}"><span class="material-symbols-outlined text-base">login</span></button>`}
            <button type="button" data-ua="rename-user" data-id="${id}" ${user.protected ? 'disabled' : ''} class="${UA_ICON_BTN}" title="${escHtml(t(user.protected ? 'admin.protectedHint' : 'admin.rename'))}" aria-label="${escHtml(t('admin.rename'))}"><span class="material-symbols-outlined text-base">edit</span></button>
            <button type="button" data-ua="delete-user" data-id="${id}" ${user.protected || userAdmin.busy ? 'disabled' : ''} class="${UA_ICON_BTN} hover:!text-error" title="${escHtml(t(user.protected ? 'admin.protectedHint' : 'admin.deleteUser'))}" aria-label="${escHtml(t('admin.deleteUser'))}"><span class="material-symbols-outlined text-base">delete</span></button>
          </div>
        </div>`;
    }

    function deletableUsers() {
      return (userAdmin.users || []).filter(u => !u.protected);
    }

    function visibleAdminSessions() {
      const q = userAdmin.query.trim().toLowerCase();
      const rows = (userAdmin.sessions || []).filter(s => !q || (s.title || '').toLowerCase().includes(q));
      const by = {
        updated: (a, b) => String(b.updated_at).localeCompare(String(a.updated_at)),
        created: (a, b) => String(b.created_at).localeCompare(String(a.created_at)),
        size: (a, b) => (b.size_bytes || 0) - (a.size_bytes || 0),
      }[userAdmin.sort];
      return rows.sort(by);
    }

    function sessionsBlockHtml() {
      const user = uaUser();
      const rows = visibleAdminSessions();
      const allChecked = rows.length > 0 && rows.every(s => userAdmin.selected.has(s.id));
      const selectedSize = [...userAdmin.selected].reduce((sum, id) => sum + ((uaSession(id) || {}).size_bytes || 0), 0);
      const sortOpt = value => `<option value="${value}" ${userAdmin.sort === value ? 'selected' : ''}>${escHtml(t(`admin.sort.${value}`))}</option>`;
      return `
        <section>
          <h5 class="text-[11px] font-bold uppercase tracking-widest font-headline text-outline-variant mb-2">${escHtml(t('admin.sessionsOf', { name: user.nickname }))}</h5>
          <div class="flex flex-wrap items-center gap-2 mb-2">
            <div class="relative flex-1 min-w-[10rem]">
              <span class="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-outline-variant text-base pointer-events-none">search</span>
              <input id="ua-query" type="search" autocomplete="off" value="${escHtml(userAdmin.query)}" data-ua-input="query" placeholder="${escHtml(t('admin.searchSessions'))}"
                class="w-full pl-8 pr-2 py-1.5 text-xs bg-surface-container-high border border-outline-variant/20 rounded-md text-on-surface placeholder:text-outline-variant/60" />
            </div>
            <label class="flex items-center gap-1.5 text-[11px] text-on-surface-variant">${escHtml(t('admin.sortBy'))}
              <select id="ua-sort" data-ua-input="sort" class="py-1 pl-2 pr-7 text-[11px] bg-surface-container-high border border-outline-variant/20 rounded-md text-on-surface">
                ${sortOpt('updated')}${sortOpt('created')}${sortOpt('size')}
              </select></label>
          </div>
          <div class="flex flex-wrap items-center gap-2 mb-3">
            <button type="button" data-ua="delete-selected" ${userAdmin.selected.size && !userAdmin.busy ? '' : 'disabled'} class="${UA_DANGER_BTN}">
              <span class="material-symbols-outlined text-sm">delete</span>${escHtml(t('admin.deleteSelected', { n: userAdmin.selected.size, size: uaBytes(selectedSize) }))}</button>
            <button type="button" data-ua="delete-empty" ${userAdmin.busy || !(userAdmin.sessions || []).some(s => s.empty) ? 'disabled' : ''} class="${UA_BTN}">
              <span class="material-symbols-outlined text-sm">cleaning_services</span>${escHtml(t('admin.deleteEmpty'))}</button>
            <span class="inline-flex items-center gap-1.5 text-[11px] text-on-surface-variant">
              <button type="button" data-ua="delete-older" ${userAdmin.busy ? 'disabled' : ''} class="${UA_BTN}">
                <span class="material-symbols-outlined text-sm">history</span>${escHtml(t('admin.deleteOlder'))}</button>
              <input id="ua-days" type="number" min="0" max="3650" value="${escHtml(String(userAdmin.olderDays))}" data-ua-input="days" aria-label="${escHtml(t('admin.days'))}"
                class="w-16 px-2 py-1 text-[11px] bg-surface-container-high border border-outline-variant/20 rounded-md text-on-surface" />
              ${escHtml(t('admin.days'))}
            </span>
          </div>
          <div class="rounded-lg border border-outline-variant/15 overflow-x-auto">
            <table class="w-full text-[12px]">
              <thead class="text-[10px] uppercase tracking-wider text-outline-variant bg-surface-container-low/40">
                <tr>
                  <th class="w-8 px-2 py-2"><input type="checkbox" data-ua="check-all" ${allChecked ? 'checked' : ''} ${rows.length ? '' : 'disabled'} aria-label="${escHtml(t('admin.selectAll'))}" class="rounded border-outline-variant/40 bg-transparent text-primary" /></th>
                  <th class="px-2 py-2 text-left font-semibold">${escHtml(t('admin.col.title'))}</th>
                  <th class="px-2 py-2 text-left font-semibold whitespace-nowrap">${escHtml(t('admin.col.updated'))}</th>
                  <th class="px-2 py-2 text-right font-semibold">${escHtml(t('admin.col.events'))}</th>
                  <th class="px-2 py-2 text-right font-semibold">${escHtml(t('admin.col.size'))}</th>
                  <th class="px-2 py-2"></th>
                </tr>
              </thead>
              <tbody class="divide-y divide-outline-variant/10">
                ${rows.length ? rows.map(sessionRowHtml).join('')
                  : `<tr><td colspan="6" class="px-3 py-3 text-xs text-outline-variant">${escHtml(t(userAdmin.sessions === null ? 'settings.status.loading' : 'admin.noSessions'))}</td></tr>`}
              </tbody>
            </table>
          </div>
          <p class="text-[11px] text-outline-variant/80 mt-2 flex items-start gap-1.5">
            <span class="material-symbols-outlined text-sm">info</span>${escHtml(t('admin.deleteNote'))}</p>
        </section>`;
    }

    function sessionRowHtml(session) {
      const id = escHtml(session.id);
      const isActive = activeSession && activeSession.id === session.id;
      const editing = userAdmin.editing && userAdmin.editing.kind === 'session' && userAdmin.editing.id === session.id;
      const title = editing
        ? `<input id="ua-edit-input" type="text" maxlength="120" value="${escHtml(session.title)}" data-ua-edit="session"
             class="w-full px-2 py-1 text-xs bg-surface-container-high border border-primary/40 rounded-md text-on-surface" />`
        : `<span class="truncate ${isActive ? 'font-semibold text-primary' : 'text-on-surface'}" title="${escHtml(session.title)}">${escHtml(session.title)}</span>`;
      const tag = (key, cls) => `<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] ${cls}">${escHtml(t(key))}</span>`;
      const tags = [
        isActive ? tag('admin.current', 'bg-primary/10 text-primary') : '',
        session.running ? tag('admin.running', 'bg-secondary/10 text-secondary') : '',
        session.hidden ? tag('admin.hidden', 'bg-surface-container-high text-outline-variant') : '',
        session.empty ? tag('admin.empty', 'bg-surface-container-high text-outline-variant') : '',
      ].join('');
      return `
        <tr class="${userAdmin.selected.has(session.id) ? 'bg-primary/5' : ''}">
          <td class="px-2 py-1.5 text-center"><input type="checkbox" data-ua="check" data-id="${id}" ${userAdmin.selected.has(session.id) ? 'checked' : ''} aria-label="${escHtml(session.title)}" class="rounded border-outline-variant/40 bg-transparent text-primary" /></td>
          <td class="px-2 py-1.5 max-w-0 w-full">
            <div class="flex min-w-0">${title}</div>
            <div class="flex flex-wrap items-center gap-1.5 mt-0.5">
              <span class="text-[10px] text-outline-variant">${escHtml(t('admin.created', { date: uaDate(session.created_at) }))}${session.checkpoints ? ' · ' + escHtml(t('admin.checkpoints', { n: session.checkpoints })) : ''}</span>${tags}
            </div>
          </td>
          <td class="px-2 py-1.5 whitespace-nowrap text-on-surface-variant">${escHtml(uaDate(session.updated_at))}</td>
          <td class="px-2 py-1.5 text-right tabular-nums text-on-surface-variant">${escHtml(String(session.events || 0))}</td>
          <td class="px-2 py-1.5 text-right tabular-nums whitespace-nowrap text-on-surface-variant">${escHtml(uaBytes(session.size_bytes))}</td>
          <td class="px-1 py-1.5 whitespace-nowrap text-right">
            <button type="button" data-ua="open" data-id="${id}" ${isActive ? 'disabled' : ''} class="${UA_ICON_BTN}" title="${escHtml(t('admin.open'))}" aria-label="${escHtml(t('admin.open'))}"><span class="material-symbols-outlined text-base">open_in_new</span></button>
            <button type="button" data-ua="rename-session" data-id="${id}" class="${UA_ICON_BTN}" title="${escHtml(t('admin.rename'))}" aria-label="${escHtml(t('admin.rename'))}"><span class="material-symbols-outlined text-base">edit</span></button>
            <button type="button" data-ua="toggle-hidden" data-id="${id}" class="${UA_ICON_BTN}" title="${escHtml(t(session.hidden ? 'admin.unhide' : 'admin.hide'))}" aria-label="${escHtml(t(session.hidden ? 'admin.unhide' : 'admin.hide'))}"><span class="material-symbols-outlined text-base">${session.hidden ? 'visibility' : 'visibility_off'}</span></button>
            <button type="button" data-ua="export" data-id="${id}" class="${UA_ICON_BTN}" title="${escHtml(t('admin.export'))}" aria-label="${escHtml(t('admin.export'))}"><span class="material-symbols-outlined text-base">download</span></button>
            <button type="button" data-ua="delete-session" data-id="${id}" ${userAdmin.busy ? 'disabled' : ''} class="${UA_ICON_BTN} hover:!text-error" title="${escHtml(t('admin.delete'))}" aria-label="${escHtml(t('admin.delete'))}"><span class="material-symbols-outlined text-base">delete</span></button>
          </td>
        </tr>`;
    }

    // ── confirmation dialog ─────────────────────────────────────────────────
    function renderUserAdminConfirm() {
      let host = document.getElementById('ua-confirm');
      const c = userAdmin.confirm;
      if (!c || !settingsModalOpen()) { if (host) host.remove(); return; }
      if (!host) {
        host = document.createElement('div');
        host.id = 'ua-confirm';
        host.className = 'absolute inset-0 z-20 flex items-center justify-center bg-black/60';
        document.getElementById('settings-dialog').parentElement.appendChild(host);
      }
      host.innerHTML = `
        <div role="alertdialog" aria-modal="true" aria-labelledby="ua-confirm-title" aria-describedby="ua-confirm-text"
          class="w-full max-w-md mx-4 rounded-xl border border-error/30 bg-surface-container shadow-2xl p-5">
          <div class="flex items-start gap-3">
            <span class="material-symbols-outlined text-error text-2xl">warning</span>
            <div class="min-w-0 flex-1">
              <h4 id="ua-confirm-title" class="font-headline text-sm font-bold text-on-surface">${escHtml(c.title)}</h4>
              <p id="ua-confirm-text" class="text-xs text-on-surface-variant mt-2 leading-relaxed whitespace-pre-line">${escHtml(c.text)}</p>
            </div>
          </div>
          <div class="flex justify-end gap-2 mt-5">
            <button type="button" data-ua="confirm-cancel" ${userAdmin.busy ? 'disabled' : ''}
              class="px-4 py-2 rounded-md text-[11px] font-bold bg-surface-container-high border border-outline-variant/20 text-on-surface hover:bg-surface-variant/40">${escHtml(t('admin.no'))}</button>
            <button type="button" id="ua-confirm-ok" data-ua="confirm-ok" ${userAdmin.busy ? 'disabled' : ''}
              class="px-4 py-2 rounded-md text-[11px] font-bold bg-error text-on-error hover:brightness-110 disabled:opacity-40">${escHtml(userAdmin.busy ? t('admin.deleting') : t('admin.yes'))}</button>
          </div>
        </div>`;
      // Safe default: Enter on the focused button answers "No".
      host.querySelector('[data-ua="confirm-cancel"]').focus();
    }

    function askUserAdmin(confirm) {
      userAdmin.confirm = confirm;
      renderUserAdminConfirm();
    }

    function closeUserAdminConfirm() {
      if (userAdmin.busy) return;
      userAdmin.confirm = null;
      renderUserAdminConfirm();
    }

    function sessionsSummary(sessions) {
      const size = sessions.reduce((sum, s) => sum + (s.size_bytes || 0), 0);
      let text = t('admin.confirm.sessions', { n: sessions.length, size: uaBytes(size) });
      const running = sessions.filter(s => s.running).length;
      if (running) text += '\n\n' + t('admin.confirm.running', { n: running });
      if (activeSession && sessions.some(s => s.id === activeSession.id)) text += '\n\n' + t('admin.confirm.current');
      return text + '\n\n' + t('admin.confirm.irreversible');
    }

    // ── actions ─────────────────────────────────────────────────────────────
    function setUserAdminMessage(text, kind = 'ok') {
      userAdmin.message = text;
      userAdmin.messageKind = kind;
    }

    function describeErrors(errors) {
      const n = Object.keys(errors || {}).length;
      return n ? ' ' + t('admin.partialErrors', { n }) : '';
    }

    // Brings the header (user picker, session picker, open session) in step
    // with what was just changed or deleted.
    async function syncHeaderAfterAdmin({ deletedUserId = null, deletedSessionIds = [] } = {}) {
      try {
        const data = await apiJson('/api/users');
        knownUsers = data.users || [];
      } catch (_) { }
      if (activeUser && deletedUserId === activeUser.id) {
        disconnectCurrentSocket();
        activeUser = null;
        activeSession = null;
        try {
          localStorage.removeItem(USER_STORAGE_KEY);
          localStorage.removeItem(SESSION_STORAGE_KEY);
        } catch (_) { }
        closeSettings(true);
        openIdentityModal();
        return;
      }
      if (!activeUser) return;
      const fresh = knownUsers.find(u => u.id === activeUser.id);
      if (fresh && fresh.nickname !== activeUser.nickname) {
        activeUser.nickname = fresh.nickname;
        document.getElementById('active-nickname').textContent = fresh.nickname;
        try { localStorage.setItem(NICK_STORAGE_KEY, fresh.nickname); } catch (_) { }
      }
      populateUserSelectors();
      if (activeSession && deletedSessionIds.includes(activeSession.id)) {
        await ensureUserSession(activeUser, null, { startFresh: true });
        return;
      }
      await loadSessions(activeUser);
      if (activeSession) activeSession = knownSessions.find(s => s.id === activeSession.id) || activeSession;
      populateSessionSelector();
    }

    // The server closes this tab's socket when it deletes the open session;
    // close it first so the tab does not treat that as a lost session and
    // re-bootstrap behind our back.
    function detachIfDeleting(sessionIds) {
      if (activeSession && sessionIds.includes(activeSession.id)) disconnectCurrentSocket();
    }

    async function runDeleteSessions(userId, sessions) {
      const ids = sessions.map(s => s.id);
      if (userId === (activeUser && activeUser.id)) detachIfDeleting(ids);
      const data = ids.length === 1
        ? await apiJson(uaUrl(userId, ids[0]), { method: 'DELETE' }).then(r => ({ deleted: ids, errors: r.errors && Object.keys(r.errors).length ? { [ids[0]]: r.errors } : {} }))
        : await apiJson(uaUrl(userId, null, '/sessions/bulk-delete'), {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
        });
      return data;
    }

    async function performUserAdmin(run) {
      userAdmin.busy = true;
      renderUserAdminConfirm();
      try {
        await run();
      } catch (error) {
        setUserAdminMessage(t('admin.failed', { error: error.message || error }), 'error');
      } finally {
        userAdmin.busy = false;
        userAdmin.confirm = null;
        renderUserAdminConfirm();
        await loadUserAdmin({ keepMessage: true });
      }
    }

    function confirmDeleteSessions(sessions, title) {
      if (!sessions.length) return;
      const userId = userAdmin.userId;
      askUserAdmin({
        title,
        text: sessionsSummary(sessions),
        run: async () => {
          const data = await runDeleteSessions(userId, sessions);
          const deleted = data.deleted || [];
          deleted.forEach(id => userAdmin.selected.delete(id));
          setUserAdminMessage(t('admin.deletedSessions', { n: deleted.length }) + describeErrors(data.errors),
            Object.keys(data.errors || {}).length ? 'error' : 'ok');
          if (userId === (activeUser && activeUser.id)) await syncHeaderAfterAdmin({ deletedSessionIds: deleted });
        },
      });
    }

    // One user or several: one dialog, one request.
    function confirmDeleteUsers(users) {
      if (!users.length) return;
      const sessions = users.reduce((sum, u) => sum + (u.session_count || 0), 0);
      const size = users.reduce((sum, u) => sum + (u.size_bytes || 0), 0);
      const includesMe = activeUser && users.some(u => u.id === activeUser.id);
      askUserAdmin({
        title: users.length === 1
          ? t('admin.confirm.userTitle', { name: users[0].nickname })
          : t('admin.confirm.usersTitle', { n: users.length }),
        text: (users.length === 1 ? '' : users.map(u => u.nickname).join(', ') + '\n\n')
          + t(users.length === 1 ? 'admin.confirm.user' : 'admin.confirm.users', { n: sessions, size: uaBytes(size) })
          + (users.some(u => u.running) ? '\n\n' + t('admin.confirm.userRunning') : '')
          + (includesMe ? '\n\n' + t('admin.confirm.self') : '')
          + '\n\n' + t('admin.confirm.irreversible'),
        run: async () => {
          if (includesMe) disconnectCurrentSocket();
          const data = await apiJson('/api/users/bulk-delete', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: users.map(u => u.id) }),
          });
          const deleted = data.deleted || [];
          deleted.forEach(id => userAdmin.selectedUsers.delete(id));
          if (deleted.includes(userAdmin.userId)) { userAdmin.userId = null; userAdmin.sessions = null; userAdmin.selected.clear(); }
          const names = users.filter(u => deleted.includes(u.id)).map(u => u.nickname).join(', ');
          const failed = Object.keys(data.errors || {}).length || Object.keys(data.skipped || {}).length;
          setUserAdminMessage(t('admin.deletedUsers', { names: names || '—', n: data.sessions || 0 })
            + describeErrors(data.errors)
            + (Object.keys(data.skipped || {}).length ? ' ' + t('admin.skippedUsers', { n: Object.keys(data.skipped).length }) : ''),
            failed ? 'error' : 'ok');
          await syncHeaderAfterAdmin({ deletedUserId: includesMe && deleted.includes(activeUser.id) ? activeUser.id : null });
        },
      });
    }

    async function commitUserAdminEdit(value) {
      const edit = userAdmin.editing;
      if (!edit) return;
      userAdmin.editing = null;
      const text = (value || '').trim();
      try {
        if (edit.kind === 'user') {
          const user = uaUser(edit.id);
          if (!user || !text || text === user.nickname) return renderUserAdmin();
          await apiJson(uaUrl(edit.id), {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nickname: text }),
          });
        } else {
          const session = uaSession(edit.id);
          if (!session || !text || text === session.title) return renderUserAdmin();
          const data = await apiJson(uaUrl(userAdmin.userId, edit.id), {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: text }),
          });
          if (activeSession && activeSession.id === edit.id) activeSession = data.session;
        }
        setUserAdminMessage(t('admin.renamed'));
        await syncHeaderAfterAdmin();
      } catch (error) {
        setUserAdminMessage(t('admin.failed', { error: error.message || error }), 'error');
      }
      await loadUserAdmin({ keepMessage: true });
    }

    function startUserAdminEdit(kind, id) {
      userAdmin.editing = { kind, id };
      renderUserAdmin();
      const input = document.getElementById('ua-edit-input');
      if (input) { input.focus(); input.select(); }
    }

    async function handleUserAdminClick(btn) {
      const id = btn.dataset.id;
      switch (btn.dataset.ua) {
        case 'reload': userAdmin.loadError = ''; await loadUserAdmin(); break;
        case 'select-user':
          if (userAdmin.userId !== id) {
            userAdmin.userId = id; userAdmin.sessions = null; userAdmin.selected.clear(); userAdmin.query = '';
            renderUserAdmin();
            await loadUserAdminSessions();
          }
          break;
        case 'switch-user': await onUserSelected(id); renderUserAdmin(); break;
        case 'rename-user': startUserAdminEdit('user', id); break;
        case 'rename-session': startUserAdminEdit('session', id); break;
        case 'delete-user': { const user = uaUser(id); if (user) confirmDeleteUsers([user]); break; }
        case 'delete-selected-users':
          confirmDeleteUsers([...userAdmin.selectedUsers].map(uaUser).filter(Boolean));
          break;
        case 'delete-session': {
          const session = uaSession(id);
          if (session) confirmDeleteSessions([session], t('admin.confirm.sessionTitle', { name: session.title }));
          break;
        }
        case 'delete-selected':
          confirmDeleteSessions([...userAdmin.selected].map(uaSession).filter(Boolean), t('admin.confirm.selectedTitle'));
          break;
        case 'delete-empty':
          confirmDeleteSessions((userAdmin.sessions || []).filter(s => s.empty), t('admin.confirm.emptyTitle'));
          break;
        case 'delete-older': {
          const days = Math.max(0, Number(userAdmin.olderDays) || 0);
          const cutoff = Date.now() - days * 86400000;
          const old = (userAdmin.sessions || []).filter(s => new Date(s.updated_at).getTime() < cutoff);
          if (!old.length) { setUserAdminMessage(t('admin.nothingOlder', { days })); renderUserAdmin(); break; }
          confirmDeleteSessions(old, t('admin.confirm.olderTitle', { days }));
          break;
        }
        case 'toggle-hidden': {
          const session = uaSession(id);
          if (!session) break;
          try {
            await apiJson(uaUrl(userAdmin.userId, id, session.hidden ? '/unhide' : '/hide'), { method: 'POST' });
            if (activeUser && activeUser.id === userAdmin.userId) await syncHeaderAfterAdmin();
          } catch (error) { setUserAdminMessage(t('admin.failed', { error: error.message || error }), 'error'); }
          await loadUserAdminSessions();
          break;
        }
        case 'export': {
          const session = uaSession(id);
          if (session) await exportSession(userAdmin.userId, session.id);
          break;
        }
        case 'open': {
          const user = knownUsers.find(u => u.id === userAdmin.userId) || uaUser();
          const session = uaSession(id);
          if (!user || !session) break;
          if (!activeUser || activeUser.id !== user.id) {
            await ensureUserSession(user, session.id);
          } else {
            await activateSession(activeUser, session);
          }
          closeSettings();
          break;
        }
        case 'confirm-cancel': closeUserAdminConfirm(); break;
        case 'confirm-ok': if (userAdmin.confirm && !userAdmin.busy) await performUserAdmin(userAdmin.confirm.run); break;
      }
    }

    document.addEventListener('click', event => {
      const btn = event.target.closest('#user-admin-root [data-ua], #ua-confirm [data-ua]');
      if (!btn || btn.disabled) return;
      if (btn.tagName === 'INPUT') return; // checkboxes are handled on change
      handleUserAdminClick(btn);
    });

    document.addEventListener('change', event => {
      const el = event.target;
      if (!el.closest || !el.closest('#user-admin-root')) return;
      if (el.dataset.ua === 'check') {
        if (el.checked) userAdmin.selected.add(el.dataset.id); else userAdmin.selected.delete(el.dataset.id);
        renderUserAdmin();
      } else if (el.dataset.ua === 'check-all') {
        visibleAdminSessions().forEach(s => (el.checked ? userAdmin.selected.add(s.id) : userAdmin.selected.delete(s.id)));
        renderUserAdmin();
      } else if (el.dataset.ua === 'check-user') {
        if (el.checked) userAdmin.selectedUsers.add(el.dataset.id); else userAdmin.selectedUsers.delete(el.dataset.id);
        renderUserAdmin();
      } else if (el.dataset.ua === 'check-all-users') {
        deletableUsers().forEach(u => (el.checked ? userAdmin.selectedUsers.add(u.id) : userAdmin.selectedUsers.delete(u.id)));
        renderUserAdmin();
      } else if (el.dataset.uaInput === 'sort') {
        userAdmin.sort = el.value;
        renderUserAdmin();
      }
    });

    document.addEventListener('input', event => {
      const el = event.target;
      if (!el.dataset || !el.dataset.uaInput) return;
      if (el.dataset.uaInput === 'query') { userAdmin.query = el.value; renderUserAdmin(); }
      else if (el.dataset.uaInput === 'days') userAdmin.olderDays = el.value;
    });

    // Capture phase: Escape must close our dialog or cancel an edit before the
    // settings modal's own handler closes the whole modal.
    document.addEventListener('keydown', event => {
      const el = event.target;
      if (userAdmin.confirm && settingsModalOpen()) {
        if (event.key === 'Escape') { event.stopImmediatePropagation(); closeUserAdminConfirm(); }
        return;
      }
      if (el && el.dataset && el.dataset.uaEdit) {
        if (event.key === 'Enter') { event.preventDefault(); commitUserAdminEdit(el.value); }
        else if (event.key === 'Escape') { event.stopImmediatePropagation(); userAdmin.editing = null; renderUserAdmin(); }
      }
    }, true);

    document.addEventListener('focusout', event => {
      const el = event.target;
      if (el && el.dataset && el.dataset.uaEdit && userAdmin.editing) commitUserAdminEdit(el.value);
    });
