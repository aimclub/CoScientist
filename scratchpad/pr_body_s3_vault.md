## S3 vault integration, part 1

CoScientist loses file references today. A graph node truncated a tool result at
300 characters, and a file path sat past that cut. The five in-repo MCP servers
used three S3 return conventions and four environment-variable schemes. The
chemical server wrote every user into one global prefix. The artifact list lived
in an in-memory session service, so a restart before the report lost every
figure the run had made.

This branch makes the six changes that need no running vault server. It also
vendors the vault server itself, so the deferred work has something to call.

Base: `main`. This branch is independent of `feature/output-lang-as-param`.

### What changed

**Durable references.** A `tool_call` node now carries `input_files` and
`output_files`, both lists of `s3://bucket/key`. A presigned URL never enters a
node: the URL expires while the object stays, so an old snapshot full of URLs
holds dead links. A new `CoScientist/utils/s3_refs.py` walks a nested tool
result, parses the JSON string inside an MCP `content[].text` envelope, and
collects every `bucket` plus `s3_key` pair it finds.

**One return contract.** Every tool that stores an object returns `bucket`,
`s3_key`, and `presigned_url`. Upload tools return `upload_url`.

**Per-session keys.** Every server writes under
`ephemeral/<user_id>/<session_id>/<feature>/`. The bucket lifecycle rule filters
on the top segment, so objects at the old prefixes matched no rule and never
expired. The chemical tools take `user_id` and `session_id`, and a new
`SessionScopePlugin` fills both at the tool boundary from the scope the graph
already uses. It touches an argument only when the tool declares it and the
caller left it empty, so an undeclared tool sees no change and a deliberate
cross-session read still works.

**One set of names.** Every server reads `S3__ENDPOINT_URL`, `S3__ACCESS_KEY`,
`S3__SECRET_KEY`, and `S3__BUCKET_NAME`. The old names still work for one
release, so a running deploy does not break on merge. Please move the deployed
`.env` files over before the next release.

**One S3 client.** The chemical server imports `S3BucketService` from
`CoScientist.paper_parser`. Its near-identical copy is deleted.

**A durable artifact list.** The capture plugin writes each artifact to
`graph_runs/sessions/<user>/<session>/artifacts.json`, beside the graph
snapshots. The report collector reads that file first, and the session-state
scan stays as the fallback for a run that started before the file existed.

**The vault server is now in `mcp-servers/vault-mcp-server/`.** The repository
owner approved the copy. `docker-compose.yml` gains the server on port 7338,
plus `minio` and `minio-setup` behind a `local-s3` profile. The profile keeps
MinIO off by default, because the four existing servers point at an S3 endpoint
this compose file does not define.

### Also in scope

- `adk web` had its own plugin list and did not get `SessionScopePlugin`. Every
  `adk web` user therefore shared one `unknown_user` prefix. It now gets that
  plugin and `McpArtifactCapturePlugin`, which it was also missing.
- The vault upload link no longer signs a content type. The signed header made a
  plain PUT fail with `SignatureDoesNotMatch`, which is the request the tool
  docstring tells an agent to make. The bundled dev client hid this, because it
  sent the header. It now sends a bare PUT.
- A repeat capture of one object refreshes its cached URL. The index used to
  keep the first URL, which is the one that expires first.
- The report collector counts a reference it cannot download, so the gap reaches
  the log. It also skips source PDFs. Twenty search results are not data tables.
- The two plugin lists in `main.py` and `agent.py` are maintained separately,
  so this class of omission can happen again. A shared builder would stop it.

### One departure from the approved plan

The plan says raise the node text limits to 2000 and 4000 characters, from 300
and 400. This branch raises them to 800 and 1500 instead.

The reason the plan gave was that a file reference sits at the end of a tool
result, and the old cut removed it. Change 1 removes that reason: the references
now travel in `input_files` and `output_files`, and the string is only for
reading. Meanwhile `GraphStore` rewrites the whole graph JSON on every node,
edge, and status change, inside the lock. A checked-in 248-node run does about
750 of those rewrites, and 2000/4000 grows the final snapshot about 2.6 times.
That turns roughly 80 MB of per-run writes into roughly 210 MB, for readability
alone.

Say the word and I set it back to 2000 and 4000. It is a one-line change in
`graph/plugin.py` and `graph/emitter.py`.

### Deferred to the next branch

- Upload the workspace at run end.
- Promote deliverables to `permanent/` at finalize. Every deliverable stays
  under `ephemeral/` until then, and the lifecycle rule deletes it after
  `EPHEMERAL_TTL_DAYS`.
- Split the worker and framework vault tool surfaces.
- CI for `mcp-servers/`. Only the web project deploys on a merge to main today.

All three need a vault MCP client in CoScientist, which does not exist yet.
Nothing here resolves an `s3://bucket/key` back into a file.

### Verification

`pytest tests/unit -q`: 484 pass. The 3 failures
(`test_hitl_agenttool_scope.py` twice, `test_opik_tracer.py` once) also fail on
`main`. The new tests cover reference extraction, the node fields, the index,
the collector, and the scope plugin.

End-to-end checks need a live stack and did not run. Please check these before
merge: every server reaches S3 with the new names, every new object lands under
`ephemeral/<user>/<session>/`, and two users writing at once stay apart.

### Merge note

Do not rename the headings `## Figures` and `## Data tables` in
`CoScientist/reporting/collect.py`. The report-language work on
`feature/output-lang-as-param` substitutes on those exact strings.
