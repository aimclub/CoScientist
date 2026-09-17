# Handoff: CoScientist-side changes for the S3 vault integration

Audience: the agent that modifies the CoScientist repository.
Repository: `/Users/arseny/projects/coscientist/CoScientist`.
Companion document: `DESIGN.md` in the s3mcp repository, revision 2.3. It defines
the vault server contract that this work consumes. Do not commit this file.
Revision 2 of this handoff. Synced with DESIGN.md revision 2.3.

## Background

A separate project (s3mcp) provides an MCP server for S3 file storage. Version 2 of
that server enforces scoped keys, one return contract, and prefix-based retention:

- Key layout: `<retention>/<user_id>/<session_id>/<feature>/<filename>`.
- `retention` is `ephemeral` or `permanent`. A bucket lifecycle rule deletes objects
  under `ephemeral/` after N days. No rule touches `permanent/`.
- Worker uploads always land under `ephemeral/`. Workers cannot choose retention.
- The framework promotes deliverables at finalize time. Promotion is a server-side
  copy from `ephemeral/` to `permanent/`. The source stays until the lifecycle rule
  reclaims it. Promotion returns a new key.
- Every tool result carries `bucket`, `s3_key`, and `presigned_url`.
- `bucket` plus `s3_key` is the durable reference. Store only these two fields.
  Generate presigned URLs at consumption time. Never store a URL as the canonical
  reference.
- The server has two tool surfaces. Workers see `get_upload_link` and
  `get_download_link`. The framework holds `promote_artifact`, `cleanup_session`,
  `update_artifact_metadata`, `get_session_manifest`, and `list_artifacts`.

Your job: make CoScientist produce and consume this contract, record file references
in the execution graph, and close the durability gaps listed below.

## Required changes

### 1. Record file references in the execution graph

Today a `tool_call` node stores only truncated strings. Input args are JSON-dumped
and cut to 300 chars. Output is cut to 400 chars. See
`CoScientist/graph/plugin.py:99-101, 276-310` and the model at
`CoScientist/graph/models.py:36-49`.

Changes:

1. Add two fields to `Node` in `CoScientist/graph/models.py`:
   `input_files: List[str]` and `output_files: List[str]`. Store `s3://bucket/key`
   strings built from the `bucket` and `s3_key` result fields.
2. Do not store `presigned_url` values in graph nodes. URLs expire in one hour.
   The `s3://bucket/key` form is the durable reference. Consumers mint a fresh URL
   with `get_download_link` when they need one.
3. In `graph/plugin.py` `after_tool_callback`, extract `bucket` and `s3_key` from
   the tool result. Write them into `output_files`.
4. Extract file arguments from tool args in `before_tool_callback`. Write them into
   `input_files`.
5. Raise the 300/400 char limits or drop them. Large inputs lose file paths today.
6. Mirror the same logic in `CoScientist/graph/emitter.py:87-105` for A2A servers.

### 2. Standardize the S3 return contract in the MCP servers

Three conventions coexist. Only presigned URLs are visible to reporting, because
`reporting/collect.py::_is_artifact_url` (`collect.py:65-76`) matches http(s) URLs
whose key ends in `presigned_url` or whose path has a media extension.

Changes per server under `mcp-servers/`:

1. `dataset-collection-mcp-server/dataset_collection_server.py:166,193-194` —
   return a `presigned_url` next to the existing `s3://bucket/key` strings.
2. `papers-search-mcp-server/papers_search_server.py:162-171` — return a
   `presigned_url` next to the raw `s3_key`.
3. Every server returns `bucket`, `s3_key`, `presigned_url` in tool results.
4. Every server writes new objects under `ephemeral/<user_id>/<session_id>/...`.
   This brings them under the lifecycle rule. Objects at the old prefixes never
   expire today.
5. Do not change the regex fallback in `collect.py` if all servers follow the contract.

### 3. Fix the chemical server scoping

`mcp-servers/chemical-mcp-server/server/chemical_server.py` and `ocr_pipeline.py`
write to the global prefix `chemical_mcp/...`. All users share it.

Changes:

1. Accept `user_id` and `session_id` in the affected tools.
2. Write under `ephemeral/<user_id>/<session_id>/chemical_mcp/...`.
3. Remove the server-local CSV write in `chemical_server.py:45`. The path is
   meaningless across containers. Upload the CSV to S3 and return the contract.

### 4. Align S3 configuration names

Three naming schemes exist today: `S3__*`, `S3_*`, and bare `ENDPOINT_URL` /
`BUCKET_NAME`. See the settings in each server directory.

Change all servers and the main app to `S3__ENDPOINT_URL`, `S3__ACCESS_KEY`,
`S3__SECRET_KEY`, `S3__BUCKET_NAME`. This matches the pydantic settings in
`CoScientist/config/settings.py:127-132`.

### 5. Deduplicate the S3 client

`CoScientist/paper_parser/s3_connection.py:25` and
`mcp-servers/chemical-mcp-server/server/utils/s3_utils.py:8` are near-identical
copies. Move one copy into a shared location that all servers import. The copy in
`s3_utils.py` has the extra `upload_bytes` method. Keep that method.

### 6. Close the workspace durability gap

`reporting/collect.py:247-281` scans `workspace/ws_<session_id>` on the local disk.
In remote mode (`CODE_EXEC__URL` is set, `tools/coder_tools/coder_tools.py:404-428`)
the files live on the code-exec host. The scan then finds nothing and loses figures.

Change: at run end, upload the collected workspace artifacts to S3 under
`ephemeral/<user_id>/<session_id>/workspace/`. Use the vault server tools. Record
the keys in the report `MANIFEST.json` (`reporting/finalize.py:67-90`). The finalize
step promotes the figures that the report references. The rest expires under the
lifecycle rule.

### 7. Make the artifact list survive restarts

The capture plugins write presigned URLs to ADK session state
(`tools/mcp_artifact_plugin.py:28-53`). Session state uses
`InMemorySessionService` (`CoScientist/main.py:164`). A restart loses the list.

Change:

1. Write each captured artifact to a JSON file under
   `graph_runs/sessions/<user>/<session>/artifacts.json`, next to the graph
   snapshots. Store `bucket`, `s3_key`, a short label, and the capturing tool name.
2. Do not store the artifacts in S3 for this purpose. The vault session manifest is
   a derived query. It has no writable object and cannot accept appends.
3. The graph node fields from change 1 give a second durable copy.
4. The report collector reads the JSON file first. Session state is the fallback.

### 8. Adopt the retention model

1. Workers upload under `ephemeral/` only. No retention choice at upload time.
2. `finalize_report` (`reporting/finalize.py:40-64`) runs after all worker agents
   complete. It calls the vault `promote_artifact` for each deliverable the report
   references. It writes the new `permanent/` keys into `MANIFEST.json` and the
   report.
3. Keys recorded in graph nodes during the run still work after promotion. The
   `ephemeral/` sources stay until the lifecycle rule reclaims them.
4. Keep `cleanup_uploaded_papers` (`agents/callbacks/research_callbacks.py:131-156`).
   The lifecycle rule now covers everything else.

### 9. Register only the worker surface with agents

1. Worker agent toolsets get `get_upload_link` and `get_download_link` only.
2. Register `list_artifacts` for a worker only when that agent needs self-inspection.
3. Framework callbacks and lifecycle hooks hold `promote_artifact`,
   `cleanup_session`, `update_artifact_metadata`, and `get_session_manifest`.
   Worker agents must not see destructive or lifecycle tools.

## Known facts that shape the work

- The execution graph is JSON snapshots under `graph_runs/sessions/`. There is no
  database. `CoScientist/alembic/` is an agent pipeline, not migrations.
- The result-aggregator MCP server is mostly dead code. The live path is
  `tools/result_formatter_tool.py:63-87` plus `reporting/collect.py:169`.
- Presigned URLs expire in one hour. The objects persist. Old graph snapshots contain
  dead links. Store `s3://bucket/key` and mint URLs on demand.
- The research graph has free-text slots (`Evidence.source_ref`,
  `CodeArtifact.path` in `graph/research/schema.py`). These are agent-written.
  They do not replace automatic capture in the execution graph.
- The vault server validates every caller-supplied `s3_key` against the key layout
  and rejects `..` segments. CoScientist code can pass keys back unchanged.

## Acceptance checks

1. Run one pipeline end to end. Every `tool_call` node in `execution.json` has
   `input_files` and `output_files` with `s3://bucket/key` entries. No presigned
   URLs in node records.
2. Every MCP tool result follows the contract: `bucket`, `s3_key`, `presigned_url`.
3. `format_results` collects artifacts from all five MCP servers.
4. A run in remote code-exec mode still produces report figures.
5. Restart the process before reporting. The report still finds the artifacts.
6. All new objects land under `ephemeral/` or `permanent/`. No writes at the bucket
   root or at the old unscoped prefixes.
7. After `finalize_report`, every referenced deliverable exists under `permanent/`.
   `MANIFEST.json` carries the new keys.
