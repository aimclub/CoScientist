// =========================================================================
// Dataset Modal & Sandbox Upload Widget
// =========================================================================
    function openDatasetModal() {
      toggleAttachMenu(false);
      setDatasetUploadProgress(null);
      const input = document.getElementById('dataset-url-input');
      input.value = datasetUrl;
      showDatasetError('');
      document.getElementById('dataset-remove-btn').classList.toggle('hidden', !datasetUrl);
      document.getElementById('dataset-modal').classList.remove('hidden');
      input.focus();
      input.select();
    }

    function closeDatasetModal() {
      document.getElementById('dataset-modal').classList.add('hidden');
    }

    function showDatasetError(message) {
      const node = document.getElementById('dataset-error');
      node.textContent = message || '';
      node.classList.toggle('hidden', !message);
    }

    function datasetUrlError(raw) {
      // Mirrors the server-side check, so a typo is caught before it travels.
      const url = String(raw || '').trim();
      if (!url) return t('dataset.errEmpty');
      let parsed;
      try {
        parsed = new URL(url);
      } catch (error) {
        return t('dataset.errInvalid');
      }
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        return t('dataset.errProtocol');
      }
      if (!parsed.pathname.toLowerCase().endsWith('.zip')) {
        return t('dataset.errNotZip');
      }
      return '';
    }

    function sendDatasetUrl(url) {
      if (!ws || ws.readyState !== 1) {
        showDatasetError(t('dataset.notConnected'));
        return false;
      }
      ws.send(JSON.stringify({ type: 'set_dataset_url', dataset_url: url }));
      return true;
    }

    function saveDatasetLink() {
      const url = document.getElementById('dataset-url-input').value.trim();
      const error = datasetUrlError(url);
      if (error) {
        showDatasetError(error);
        return;
      }
      if (sendDatasetUrl(url)) closeDatasetModal();
    }

    function clearDatasetLink() {
      if (sendDatasetUrl('')) closeDatasetModal();
    }

    // Upload a .zip from the computer. The server stores it in S3 and attaches
    // its link to the session, then broadcasts `dataset_url` to every tab — the
    // same message a pasted link produces, so the chip updates the usual way.
    function setDatasetUploadProgress(name, pct) {
      const box = document.getElementById('dataset-upload-progress');
      if (!box) return;
      box.classList.toggle('hidden', name == null);
      if (name == null) return;
      document.getElementById('dataset-upload-progress-name').textContent = name;
      document.getElementById('dataset-upload-progress-pct').textContent = Math.round(pct) + '%';
      document.getElementById('dataset-upload-progress-bar').style.width = pct + '%';
    }

    function uploadDatasetFile(file) {
      const input = document.getElementById('dataset-file-input');
      if (input) input.value = '';
      if (!file) return;
      showDatasetError('');
      if (!/\.zip$/i.test(file.name)) {
        showDatasetError(t('dataset.errNotZipFile'));
        return;
      }
      if (!activeUser || !activeSession) {
        showDatasetError(t('dataset.notConnected'));
        return;
      }
      const btn = document.getElementById('dataset-upload-btn');
      if (btn) btn.disabled = true;
      setDatasetUploadProgress(file.name, 0);
      const form = new FormData();
      form.append('file', file);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `/api/users/${encodeURIComponent(activeUser.id)}/sessions/${encodeURIComponent(activeSession.id)}/dataset`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) setDatasetUploadProgress(file.name, (e.loaded / e.total) * 100);
      };
      xhr.onload = () => {
        if (btn) btn.disabled = false;
        if (xhr.status >= 200 && xhr.status < 300) {
          setDatasetUploadProgress(null);
          closeDatasetModal();
          return;
        }
        let detail = '';
        try { detail = JSON.parse(xhr.responseText).detail || ''; } catch (_) { }
        setDatasetUploadProgress(null);
        showDatasetError(t('dataset.uploadFailed') + (detail ? ` ${detail}` : ''));
      };
      xhr.onerror = () => {
        if (btn) btn.disabled = false;
        setDatasetUploadProgress(null);
        showDatasetError(t('dataset.uploadFailed'));
      };
      xhr.send(form);
    }

    // =========================================================================
    // Sandbox Dataset Upload Progress Widget
    // =========================================================================
    let datasetLogEventSource = null;
    let activeUploadData = null;

    function updateDatasetUploadUI(d) {
      if (!d) return;
      activeUploadData = d;
      const widget = document.getElementById('dataset-upload-widget');
      const arc = document.getElementById('dataset-upload-arc');
      const pctEl = document.getElementById('dataset-upload-pct');
      const textEl = document.getElementById('dataset-upload-text');

      const p = d.progress || {};
      const total = Number(p.total_mb) || 0;
      const done = Number(p.downloaded_mb) || 0;
      let pctRaw = p.percent != null ? Number(p.percent) : (total > 0 ? (done / total) * 100 : 0);
      const pct = Math.min(100, Math.max(0, isFinite(pctRaw) ? pctRaw : 0));

      const circumference = 113.097; // 2 * PI * 18
      const dashoffset = circumference * (1 - pct / 100);

      if (arc) arc.style.strokeDashoffset = dashoffset;
      if (pctEl) pctEl.textContent = Math.round(pct) + '%';

      if (textEl) {
        if (total > 0) {
          textEl.textContent = `${t('dataset.uploading')}: ${formatDatasetSize(done)} / ${formatDatasetSize(total)}`;
        } else if (done > 0) {
          textEl.textContent = `${t('dataset.uploading')}: ${formatDatasetSize(done)}`;
        } else if (d.filename) {
          textEl.textContent = `${t('dataset.uploading')}: ${d.filename}`;
        } else {
          textEl.textContent = t('dataset.uploadingSandbox');
        }
      }

      const filenameEl = document.getElementById('dataset-upload-filename');
      const speedEl = document.getElementById('dataset-upload-speed');
      const etaEl = document.getElementById('dataset-upload-eta');
      const statusEl = document.getElementById('dataset-upload-status');

      if (filenameEl) filenameEl.textContent = d.filename || d.download_id || '—';
      if (speedEl) speedEl.textContent = p.speed_mb_s ? `${Number(p.speed_mb_s).toFixed(1)} MB/s` : '—';
      if (etaEl) etaEl.textContent = p.eta_seconds ? `${Math.round(p.eta_seconds)}s` : '—';
      if (statusEl) statusEl.textContent = d.status || p.status || 'in_progress';

      if (widget) widget.classList.remove('hidden');
    }

    async function cancelDatasetUpload() {
      const downloadId = activeUploadData ? activeUploadData.download_id : null;
      const userId = activeUser ? activeUser.id : null;
      const sessionId = activeSession ? activeSession.id : null;
      try {
        await fetch('/api/v1/downloads/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            download_id: downloadId,
            user_id: userId,
            session_id: sessionId
          })
        });
      } catch (err) {
        console.warn('Failed to send download cancel request:', err);
      }
      const widget = document.getElementById('dataset-upload-widget');
      if (widget) widget.classList.add('hidden');
    }

    function toggleDatasetUploadDetails() {
      const drawer = document.getElementById('dataset-upload-details');
      if (drawer) drawer.classList.toggle('hidden');
    }

    // The sandbox's download stream is shared by everyone on that machine, so
    // a page listens only while its session has a dataset attached and shows
    // only the download of that archive.
    function isOwnDatasetDownload(d) {
      if (!datasetUrl) return false;
      const url = d.dataset_url || d.url;
      if (url) return url === datasetUrl;
      if (d.filename) return d.filename === datasetDisplayName(datasetUrl);
      return true;
    }

    function syncDatasetLogsSSE() {
      if (!datasetUrl) return disconnectDatasetLogsSSE();
      // Another session's archive may still be on screen after a switch.
      if (activeUploadData && !isOwnDatasetDownload(activeUploadData)) {
        activeUploadData = null;
        const widget = document.getElementById('dataset-upload-widget');
        if (widget) widget.classList.add('hidden');
      }
      connectDatasetLogsSSE();
    }

    function disconnectDatasetLogsSSE() {
      if (datasetLogEventSource) {
        datasetLogEventSource.close();
        datasetLogEventSource = null;
      }
      activeUploadData = null;
      const widget = document.getElementById('dataset-upload-widget');
      if (widget) widget.classList.add('hidden');
    }

    function connectDatasetLogsSSE() {
      if (datasetLogEventSource) return;
      try {
        const url = new URL('/api/downloads/logs', location.href).toString();
        datasetLogEventSource = new EventSource(url);
        datasetLogEventSource.addEventListener('download', (e) => {
          try {
            const d = JSON.parse(e.data);
            if (d && isOwnDatasetDownload(d)) updateDatasetUploadUI(d);
          } catch (_) { }
        });
        datasetLogEventSource.addEventListener('status', (e) => {
          if (String(e.data).trim() === 'idle') {
            // Stream idle
          }
        });
        datasetLogEventSource.onerror = () => {
          // EventSource automatically retries
        };
      } catch (err) {
        console.warn('Dataset logs SSE connection error:', err);
      }
    }

