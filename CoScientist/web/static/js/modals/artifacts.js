// =========================================================================
// Sandbox Artifacts panel — what the run actually left behind
// =========================================================================
// The sandbox agent publishes what it chooses to publish. Everything else it
// made sat on a machine only the sandbox could read, and the person watching
// the run had no way to look. This lists the workspace and pulls a path across
// on demand — the same transfer the agents use, so a file fetched here and a
// file fetched by an agent are one object under one link.

    const SANDBOX_ROOT = '/workspace';
    let artifactsPath = SANDBOX_ROOT;
    // Which workspace is being read: '' means the one bound to this session,
    // anything else is a task id the sandbox still holds. The sandbox addresses
    // containers by task id, so a neighbouring run is one parameter away.
    let artifactsWorkspace = '';
    // Fetched during this visit: workspace + path → durable link, so a second
    // click opens the file instead of copying it across again.
    const artifactsFetched = new Map();

    function fetchedKey(path) {
      return `${artifactsWorkspace}\u0000${path}`;
    }

    async function openArtifactsModal() {
      if (typeof toggleAttachMenu === 'function') toggleAttachMenu(false);
      document.getElementById('artifacts-modal').classList.remove('hidden');
      // The list first, then the listing: which workspace to read comes out of
      // the list, and firing both at once read the session's binding — which,
      // for a session whose sandbox was started elsewhere, is nothing at all.
      await loadWorkspaces();
      loadArtifacts(SANDBOX_ROOT);
    }

    // What the workspace list says about a task, in the words a reader uses.
    const WORKSPACE_STATUS = {
      running: 'работает', cooldown: 'остывает', soft_stopping: 'останавливается',
      queued: 'в очереди', completed: 'завершён', failed: 'упал',
      stopped: 'остановлен', error: 'ошибка',
    };

    function workspaceLabel(workspace) {
      const id = String(workspace.sandbox_id || '');
      const status = WORKSPACE_STATUS[workspace.status] || workspace.status || '';
      // The prompt arrives as the markdown the agent was handed; its heading
      // marks say nothing here and eat the width the id and status need.
      const task = String(workspace.task || '')
        .replace(/[#*`>]/g, ' ').replace(/\s+/g, ' ').trim();
      const head = workspace.current ? `текущая (${id.slice(0, 8)})` : id.slice(0, 8);
      const tail = task ? ` — ${task.slice(0, 40)}` : '';
      return `${head} · ${status}${tail}`;
    }

    async function loadWorkspaces() {
      const select = document.getElementById('artifacts-workspace');
      const base = artifactsSession();
      if (!base) { select.innerHTML = ''; return; }
      select.innerHTML = '<option value="">песочница этой сессии</option>';

      let payload;
      try {
        const response = await fetch(`${base}/tasks`, { cache: 'no-store' });
        payload = await response.json();
      } catch (error) {
        return;  // The listing below reports the real trouble; one message is enough.
      }
      if (payload.status !== 'ok') return;

      const workspaces = payload.workspaces || [];
      if (!workspaces.length) return;

      // Read something on open rather than nothing: this session's own sandbox
      // if it has one, otherwise whatever the sandbox says is still openable.
      // Nothing is "the session's sandbox" implicitly any more — the request
      // always names a task id, because the session may not have a binding.
      if (!workspaces.some(w => w.sandbox_id === artifactsWorkspace)) {
        const chosen = workspaces.find(w => w.current && w.browsable)
          || workspaces.find(w => w.browsable) || workspaces[0];
        artifactsWorkspace = chosen.sandbox_id;
      }

      select.innerHTML = workspaces.map(workspace => {
        const id = escAttr(workspace.sandbox_id);
        const selected = workspace.sandbox_id === artifactsWorkspace ? ' selected' : '';
        // A container the sandbox has already torn down cannot be listed, but
        // saying so is the sandbox's call, not a guess made here: the row stays
        // selectable and the refusal, when it comes, is shown in full.
        const note = workspace.browsable ? '' : ' · контейнер остановлен';
        return `<option value="${id}"${selected}>`
             + `${escHtml(workspaceLabel(workspace))}${note}</option>`;
      }).join('');
    }

    function pickWorkspace(sandboxId) {
      artifactsWorkspace = sandboxId || '';
      loadArtifacts(SANDBOX_ROOT);
    }

    function closeArtifactsModal() {
      document.getElementById('artifacts-modal').classList.add('hidden');
    }

    function artifactsSession() {
      if (!activeUser || !activeSession) return null;
      return `/api/users/${encodeURIComponent(activeUser.id)}`
           + `/sessions/${encodeURIComponent(activeSession.id)}/sandbox`;
    }

    function artifactsNote(message, kind) {
      const node = document.getElementById('artifacts-note');
      node.textContent = message || '';
      node.className = 'text-[11px] mt-3 ' + (
        kind === 'error' ? 'text-error' : 'text-outline-variant');
      node.classList.toggle('hidden', !message);
    }

    function humanSize(bytes) {
      const n = Number(bytes);
      if (!Number.isFinite(n) || n < 0) return '';
      if (n < 1024) return `${n} Б`;
      if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} КБ`;
      if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} МБ`;
      return `${(n / 1024 ** 3).toFixed(2)} ГБ`;
    }

    async function loadArtifacts(path) {
      const base = artifactsSession();
      const body = document.getElementById('artifacts-body');
      if (!base) {
        body.innerHTML = '';
        artifactsNote('Откройте сессию — песочница принадлежит ей.', 'error');
        return;
      }
      artifactsPath = path || SANDBOX_ROOT;
      document.getElementById('artifacts-path').textContent = artifactsPath;
      body.innerHTML = '<div class="text-[11px] text-outline-variant py-6 text-center">Смотрю…</div>';
      artifactsNote('');

      let payload;
      try {
        const query = `path=${encodeURIComponent(artifactsPath)}`
          + (artifactsWorkspace ? `&sandbox_id=${encodeURIComponent(artifactsWorkspace)}` : '');
        const response = await fetch(`${base}/files?${query}`, { cache: 'no-store' });
        payload = await response.json();
      } catch (error) {
        body.innerHTML = '';
        artifactsNote('Песочница не ответила: ' + error, 'error');
        return;
      }
      if (payload.status !== 'ok') {
        body.innerHTML = '';
        // The usual causes are honest ones — no sandbox started for this
        // session, or a container already torn down — so say which, rather
        // than "failed".
        const message = String(payload.message || 'Песочница недоступна.');
        artifactsNote(/\b409\b/.test(message)
          ? 'Контейнер этой задачи уже остановлен — файлы из него недоступны.'
          : message, 'error');
        return;
      }
      renderArtifacts(payload.entries || []);
    }

    // The listing last drawn, so a redraw after a fetch shows the same folder.
    let lastArtifactEntries = [];

    function renderArtifacts(entries) {
      if (entries) lastArtifactEntries = entries;
      entries = lastArtifactEntries;
      const body = document.getElementById('artifacts-body');
      const up = artifactsPath !== SANDBOX_ROOT
        ? `<div class="art-row" onclick="loadArtifacts('${escAttr(parentPath(artifactsPath))}')">
             <span class="material-symbols-outlined text-sm text-outline-variant">arrow_upward</span>
             <span class="art-name">..</span></div>`
        : '';

      if (!entries.length) {
        body.innerHTML = up + '<div class="text-[11px] text-outline-variant py-6 text-center">Пусто.</div>';
        return;
      }
      // Folders first, then files, each alphabetically: a workspace after a
      // training run is a hundred checkpoints and three things you want.
      const sorted = entries.slice().sort((a, b) => {
        const da = a.type === 'directory', db = b.type === 'directory';
        if (da !== db) return da ? -1 : 1;
        return String(a.name || '').localeCompare(String(b.name || ''));
      });

      body.innerHTML = up + sorted.map(entry => {
        const isDir = entry.type === 'directory';
        const full = entry.path || `${artifactsPath}/${entry.name}`;
        const link = artifactsFetched.get(fetchedKey(full));
        const icon = isDir ? 'folder' : 'description';
        const action = link
          ? `<a class="art-open" href="${escAttr(link)}" target="_blank" rel="noopener">открыть ↗</a>`
          : `<button class="art-get" onclick="fetchArtifact('${escAttr(full)}', this)">забрать</button>`;
        const onclick = isDir ? ` onclick="loadArtifacts('${escAttr(full)}')"` : '';
        return `<div class="art-row"${onclick}>
            <span class="material-symbols-outlined text-sm text-outline-variant">${icon}</span>
            <span class="art-name">${escHtml(entry.name || '')}</span>
            <span class="art-size">${isDir ? '' : humanSize(entry.size)}</span>
            ${action}
          </div>`;
      }).join('');
    }

    function parentPath(path) {
      const trimmed = String(path || '').replace(/\/+$/, '');
      const cut = trimmed.lastIndexOf('/');
      return cut > 0 ? trimmed.slice(0, cut) : SANDBOX_ROOT;
    }

    async function fetchArtifact(path, button) {
      const base = artifactsSession();
      if (!base) return;
      button.disabled = true;
      button.textContent = 'беру…';
      artifactsNote('');
      try {
        const response = await fetch(`${base}/fetch`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, sandbox_id: artifactsWorkspace || null }),
        });
        const result = await response.json();
        if (result.status !== 'success') {
          button.disabled = false;
          button.textContent = 'забрать';
          artifactsNote(result.message || 'Забрать не удалось.', 'error');
          return;
        }
        artifactsFetched.set(fetchedKey(path), result.url);
        // Redraw rather than patch the row: the button becomes a link, and the
        // next visit to this folder should already show it as fetched.
        renderArtifacts();
        artifactsNote(`Забрано: ${path} (${humanSize(result.size_bytes)}). Ссылка не протухает.`);
      } catch (error) {
        button.disabled = false;
        button.textContent = 'забрать';
        artifactsNote('Забрать не удалось: ' + error, 'error');
      }
    }

    function escAttr(value) {
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;');
    }
