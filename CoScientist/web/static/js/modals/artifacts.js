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
    // Fetched during this visit: path → durable link, so a second click opens
    // the file instead of copying it across again.
    const artifactsFetched = new Map();

    function openArtifactsModal() {
      if (typeof toggleAttachMenu === 'function') toggleAttachMenu(false);
      document.getElementById('artifacts-modal').classList.remove('hidden');
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
        const response = await fetch(
          `${base}/files?path=${encodeURIComponent(artifactsPath)}`, { cache: 'no-store' });
        payload = await response.json();
      } catch (error) {
        body.innerHTML = '';
        artifactsNote('Песочница не ответила: ' + error, 'error');
        return;
      }
      if (payload.status !== 'ok') {
        body.innerHTML = '';
        // The usual cause is an honest one — no sandbox has been started for
        // this session yet — so say that rather than "failed".
        artifactsNote(payload.message || 'Песочница недоступна.', 'error');
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
        const link = artifactsFetched.get(full);
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
          body: JSON.stringify({ path }),
        });
        const result = await response.json();
        if (result.status !== 'success') {
          button.disabled = false;
          button.textContent = 'забрать';
          artifactsNote(result.message || 'Забрать не удалось.', 'error');
          return;
        }
        artifactsFetched.set(path, result.url);
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
