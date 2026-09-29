# CoScientist in this chat harness

Keep the conversation with the user in the harness chat. Use the local bridge
(`scripts/harness_bridge.py`) to submit research tasks to CoScientist; the web
interface is a live view of the same user/session in the right-side preview.

- Start the server with `.venv\Scripts\python.exe -m CoScientist web --host 127.0.0.1 --port 8000`.
- If the user opts into the local provider configured in Codex, use
  `.venv\Scripts\python.exe scripts\run_with_codex_proxy.py` instead. It requires
  the provider's client-key variable in the environment, Windows user environment,
  or ignored `.env`;
  never read or copy a Codex login token.
- Run `.venv\Scripts\python.exe scripts\harness_bridge.py init` and open its `gui_url` in the preview.
- Send a task with `... harness_bridge.py send "<task>"`; use `status` to read progress/results. Never send a task twice just because a short wait returned `running`.
- Use `... harness_bridge.py feed` to bring new agent messages and HITL requests
  into this chat. Ask the user here, then send only their explicit choice with
  `... harness_bridge.py hitl <request_id> <action>`. Never approve automatically.
  The GUI remains a live graph/trace view, not the primary conversation.
- The harness can relay events while an assistant turn is active; the local
  server cannot independently post into this chat after the turn ends.
- Credentials belong in ignored `.env` or environment variables. Do not paste or commit keys.
- The web server and its sessions are process-local. After a restart, run `init` again and reopen the returned link.
