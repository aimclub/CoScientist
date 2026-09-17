# S3 vault integration, part 2: consume the durable reference

Follows #<part 1>. Branch from `feature/s3-vault-integration`, so review that one
first. If part 1 merges before this, the branch fast-forwards.

Part 1 made every MCP server produce `bucket` + `s3_key` + `presigned_url`, put
every object under `ephemeral/<user_id>/<session_id>/`, and kept the durable
reference in graph nodes and in a per-session artifact index. Nothing read one
back. CoScientist had no vault client, so an `s3://bucket/key` could not become
a file again. `collect_artifacts` counted these entries and logged the gap.

This branch adds the client and handoff changes 6, 8 and 9.

## What changed

**The vault client.** `CoScientist/tools/vault_client.py` opens one MCP session
per call and closes it. The ADK session manager caches a session and binds its
exit stack to the loop that created it, so a shared instance fails on the second
call from a fresh loop. `call_vault_sync` refuses to run on the event loop, where
`asyncio.run` would deadlock.

**Two consumers, two mechanisms.** Worker agents get a normal ADK `McpToolset`,
filtered to `get_upload_link` and `get_download_link`. The vault also exposes
`promote_artifact`, `cleanup_session`, `update_artifact_metadata`,
`get_session_manifest` and `list_artifacts`. An agent never sees those. Framework
code calls them through the client, outside any agent.

**Change 6, the remote workspace.** `collect.py` walks `workspace/ws_<session>`
on the local disk. With `CODE_EXEC__URL` set the files sit on the code-exec host,
the walk finds nothing, and the report loses every figure the run drew.

The code-exec API is submit and result only. It cannot serve a file. So the file
leaves from the inside: the framework mints a presigned PUT link with the vault,
and the sandbox uploads to S3 with it. Part 1's content-type fix is what makes
that bare PUT work.

The upload runs through `python3` and `urllib`, not `curl`. The code-exec image
(`docker/Dockerfile`) is `python:3.12-slim` plus build-essential, vim and git. It
has no curl, and it always has python3.

**Change 8, promotion.** A worker writes under `ephemeral/`, where the lifecycle
rule deletes the object after `EPHEMERAL_TTL_DAYS` (default 7). The report
outlives that. `collect_artifacts` downloads to a local path and drops the key,
so it now writes the mapping to `.artifact_sources.json` in the report folder.
`finalize_report` reads that file, promotes each object, and writes the new
`permanent/` keys into `MANIFEST.json` under a new `promoted` map.

**Change 9, the tool split.** One vault instance, filtered client-side with the
ADK `tool_filter`. A second `VAULT_SURFACE` instance is not needed: the presigned
URL points at S3, not at the vault, so the sandbox needs egress to S3 only and
the vault stays private to CoScientist. `docker-compose.yml` is unchanged.

## Two departures from the handoff

**Change 6 does not go in `finalize.py`.** The handoff points there and says "at
run end". The bug it names is lost figures, and a figure reaches the report only
through `collect_artifacts`, which runs earlier, when the aggregator calls
`format_results`. A sync at finalize time would be strictly too late. It runs in
`format_results`, before collection.

**Promotion covers only what S3 already holds.** `report.md`, the LaTeX output
and the files a local sandbox left on this disk were never uploaded. Handoff item
8.1 forbids a worker writing to `permanent/` directly, so promoting those would
mean upload-then-promote. The handoff asks for the figures the report references,
and that is the scope here.

## Also in scope

- `collect_artifacts` takes a `resolve_url` callable. A presigned URL lives one
  hour, so a long run — or one that was restarted — arrives holding dead links.
  The object is still there, and the vault mints a new URL from the key beside
  it. The function stays synchronous and reaches no network itself, which keeps
  it testable and keeps the existing tests valid.
- The artifact loop now dedupes on the durable reference, not only on the URL.
  Two entries for one object can carry two different presigned URLs.
- `collect_artifacts` takes `synced_files`. What the sync uploaded arrives
  through the index, and the disk walk would find the same files again. The two
  paths overlap whenever the code-exec server runs on this host, which is the
  documented dev setup: both sides read `code_exec.workspace_root`. Naming the
  files rather than switching the walk off keeps a failed upload reachable.
- `McpArtifactCapturePlugin` no longer stores an `upload_url` as an artifact URL,
  and it indexes an uploaded worker file only when the name looks like a figure
  or a table. Now that agents hold the vault, a `get_upload_link` reply would
  otherwise be indexed before anything was uploaded, and a checkpoint an agent
  parked there would be downloaded into `tables/` and rendered as one.
- Collection now runs in `asyncio.to_thread`. It downloads every artifact, and
  each dead link adds a vault round trip, all of which used to block the event
  loop.
- `cleanup_session` added `len(batch)` to its deleted count and never read the
  `Errors` key that `delete_objects` returns. A partly denied delete reported
  full success. It now counts `Deleted` and reports the failures.

## One thing worth a second look

`finalize_report` now reaches the network. It is wrapped, and a vault that is
down costs the deliverable its durability and not its existence — there is a
test for that. But it is a new runtime dependency in a path that had none.

The mapping travels through a file rather than session state on purpose:
`web/app.py:1893` passes `state=None` to `finalize_report` while `main.py:389`
passes the real state. Anything hung off state there would silently do nothing in
the web path. That is the same shape as the plugin-list gap the part-1 review
found.

## Verification

`.venv/bin/python -m pytest tests/unit -q` gives 528 passed and 3 failed. The
three (`test_hitl_agenttool_scope` twice, `test_opik_tracer` once, the last needs
an Opik API key) fail on `main` as well. 44 new tests cover the client envelope
and its failure modes, re-minting, the source mapping, promotion with the vault
up and down, and the workspace sync.

These need a live stack and did not run:

1. Call `get_upload_link` and `get_download_link` from a CoderAgent turn. Confirm
   the agent cannot see `cleanup_session` or `promote_artifact`.
2. Run one pipeline with `CODE_EXEC__URL` set. The report carries the sandbox
   figures, and they sit under `ephemeral/<user>/<session>/workspace/` in MinIO.
3. Run the same pipeline with `CODE_EXEC__URL` empty. The figures still arrive
   through the disk walk, and no figure appears twice.
4. Run it once more with the code-exec server on this host. The sandbox and the
   report collector then share a directory, and each figure must still appear
   once.
5. After the run, `MANIFEST.json` carries a `promoted` entry per figure, and each
   key resolves under `permanent/`.
6. Grep `execution.json` for `presigned_url` and `X-Amz-Signature`. Expect no
   match.
7. Stop the vault container and run a pipeline. The report still completes.

## Configuration

One new setting: `MCP__VAULT_URL`, for example
`http://localhost:7338/mcp` against the compose stack. Unset, the toolset and
every framework call drop out and the run behaves as it does today.

## Not in this branch

CI for `mcp-servers/`. `.github/workflows/` holds only `deploy-web.yml`, so no
server there deploys on a merge to main. It is deploy plumbing with no overlap
with this code.
