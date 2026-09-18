# Report links, sandbox artifacts, and one language switch

This branch fixes three user-facing problems in the web interface.

## 1. Language: one switch, locked during a run

Before: the interface language had a toggle in the settings pane. The report language had a separate select in the chat composer. Both could change at any time, also in the middle of a run. Many strings had no Russian translation.

Now:

- The settings-pane toggle is the single language control. It sets the interface language and the report language.
- The report-language select in the chat composer is removed.
- Language change is locked while a run is active. The client disables the toggle. The server rejects `set_report_language` with `report_language_rejected`. One report keeps one language.
- The Russian translation is complete. This covers the identity, dataset, roadmap, experiment, saved-sessions, and MCP-rebuild modals. It also covers the HITL card, session operations, settings and roadmap messages, and the standalone graph and builds pages.

## 2. Sandbox artifacts reach the report

Before: the OpenHands sandbox returned its uploads as `s3_uploads` entries with a `key` field. The artifact capture contract requires `bucket` and `s3_key`. The uploads were never captured in a durable way. They disappeared from the report when the presigned URL expired after one hour. Non-media files such as PDFs, archives, and checkpoints were dropped.

Now:

- The uploads are normalized to `bucket` + `s3_key` where they are parsed. They land in the per-session artifact index and survive URL expiry.
- `collect_artifacts` adds a `## Files` section for non-media artifacts, with download links. The `## Figures` and `## Data tables` sections are unchanged.
- Bulk source material from papers search stays out of the report.

## 3. Report links open for every user

Before: agents pasted raw presigned URLs into report text. The URLs expired after one hour. They were also signed against the internal storage endpoint. The Host header is part of the signature, so a browser on a different host got an XML AccessDenied page.

Now:

- Report markdown is rewritten at delivery. Each S3 link becomes a local `/api/artifact/<bucket>/<key>` link.
- A new endpoint mints a fresh signed URL for each click and redirects. Vault objects go through the vault. Other buckets use the shared credentials. A short in-memory cache prevents minting on every click.
- Links in old reports keep working. The internal endpoint never reaches the browser.
- `S3BucketService` supports a new optional `S3__EXTERNAL_ENDPOINT_URL`. When set, URLs are signed against the browser-reachable endpoint.
- Node artifact lists no longer show tool server addresses. An agent that echoes the MCP endpoint it called (`http://host:7338/mcp`) did not produce a file. These links are now filtered out of the artifact sections of execution-graph nodes.

## Tests

- 553 unit tests pass. New coverage: `test_report_links.py` (19 tests) and `test_sandbox_artifacts.py`.
- The 2 failures in `test_hitl_agenttool_scope.py` exist on clean HEAD. They depend on `HITL__ENABLED` and pass when it is set. They are not caused by this branch.
- Smoke test: the app boots. The index, graph, and builds pages return 200. The artifact endpoint redirects correctly.

## Deploy notes

- Set `S3__EXTERNAL_ENDPOINT_URL` to the storage address that browsers can reach.
- Add the storage host to `NO_PROXY` in the systemd unit.
- Details are in `deploy/README.md`, section "Artifact links on a cluster".
