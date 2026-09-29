# Chat-harness integration

CoScientist's existing FastAPI/WebSocket server owns the research session. The
CLI bridge talks to that server, while the GUI subscribes to the same session.
The main chat stays in the harness; no second chat backend or separate run of
`CoScientistManager` is created.

## Setup (Windows PowerShell)

```powershell
uv sync --frozen --python 3.12
# Configure .env using CoScientist/examples/example_config.env (at least a
# working LLM endpoint/model/key for real research). Never commit .env.
.venv\Scripts\python.exe -m CoScientist web --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
.venv\Scripts\python.exe scripts\harness_bridge.py init
.venv\Scripts\python.exe scripts\harness_bridge.py send "Research question" --wait 15
.venv\Scripts\python.exe scripts\harness_bridge.py status
.venv\Scripts\python.exe scripts\harness_bridge.py feed
```

Open `gui_url` from `init` in the right-side preview. A deep link now selects
the exact user/session, including when another session was previously saved in
the browser. `init` reuses the current session while the server is running;
after a restart, the server creates a fresh process-local registry and `init`
normally creates a new session. If the previous persisted session is still
listed by the server, `init --session-id <existing-id>` explicitly reattaches
it (use its returned `gui_url`). The bridge stores only URL and session IDs in the ignored
`.coscientist-harness.json`; never put credentials in that file.

`send` returns `running` after its wait time without cancelling the server
task. `feed` returns new chat-facing agent messages and HITL requests, with a
cursor to avoid duplicate updates (use `--replay` to inspect recent history).
Tool arguments/results are excluded from the chat feed. Relay meaningful events
in the harness chat; the GUI remains a live graph and transcript. On an HITL
request, ask the operator here and send only their explicit answer with
`harness_bridge.py hitl <request_id> approve|reject|edit|provide_input|select`
and `--message` or `--option` where needed. `hitl <id> hold` pauses a WebHITL
veto window while discussing. The local bridge cannot post autonomously into
the harness chat after the assistant turn ends. With the Codex-proxy launcher,
HITL is enabled by default (unless `HITL__ENABLED=false` is explicitly set),
and server-side HITL timeouts are disabled so a decision is never auto-approved
while awaiting an answer in chat.
Final responses are saved in the session event stream, so `status` can retrieve
them after the bridge reconnects. Never infer success from server availability
alone; real inference also needs configured credentials and any task-specific
services (search, storage, sandbox).

Keep the server bound to `127.0.0.1`: its existing local user/session endpoints
have no authentication and must not be exposed to the network.

## Existing local Codex provider (optional)

`scripts/run_with_codex_proxy.py` reads the active model and loopback provider
address from the local Codex `config.toml`, then launches CoScientist with
LiteLLM's OpenAI-compatible adapter. It never reads login tokens or writes a
client key. The provider's `env_key` must be set in the launching environment,
the Windows user environment, or manually in the ignored `.env`. The launcher
reads only that named variable and never prints its value. For this machine it is
`CLIPROXY_API_KEY`, and the configured server is `127.0.0.1:8317/v1`.

```powershell
# Set CLIPROXY_API_KEY using your secret manager or edit ignored .env locally.
# Do not put its value in chat or in a tracked file.
.venv\Scripts\python.exe scripts\run_with_codex_proxy.py
```

The local proxy is a separate service, not evidence that a ChatGPT/Codex
subscription includes API usage. Verify access and applicable terms for that
service before running a paid research task. The launcher probes `/v1/models`
without inference and fails before starting the web UI if the key is missing or
rejected. As with ordinary `.env` changes, restart the
server after switching providers, then run `harness_bridge.py init` again.
