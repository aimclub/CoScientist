# Fix: bound every S3 call, and refuse to start without S3 config

Branch: `fix/s3-client-timeouts` → `main`

## Summary

The chemical MCP server logs `anyio.ClosedResourceError`, and the files it makes
reach no bucket. One unbounded S3 call causes both. This branch bounds the call
and makes a missing S3 configuration visible at startup.

## The problem

`S3BucketService.create_s3_client` built the boto3 client with
`Config(signature_version="s3v4")` and nothing else. The botocore defaults are
60 s to connect, 60 s to read, and up to 5 attempts. An endpoint that drops
packets therefore blocks the caller for about 300 s.

`DynamicMCPToolset` sets `sse_read_timeout` to 300 s. So the client gives up
first and closes the stream. The server then writes its response into a stream
that is already closed, and the MCP transport raises. The log shows only that
teardown:

```
anyio.ClosedResourceError
RuntimeError: Unexpected ASGI message 'http.response.start' sent, after response
already completed.
```

Neither line names the upload that hung. The tool returns nothing, so the file
exists nowhere.

The most common trigger is an empty `S3__ENDPOINT_URL`. boto3 then falls back to
the real AWS endpoint of the bucket name. A host without that egress blackholes
the request, and the retries run out at about 300 s.

## Changes

**Bound the S3 clients.** `CoScientist/paper_parser/s3_connection.py` and both
clients in `mcp-servers/vault-mcp-server/vault_server.py` now use 5 s to
connect, 30 s to read, and 3 attempts. A bad endpoint fails in seconds. The tool
returns an error that the agent can read, and the MCP session stays open.
`read_timeout` applies to one socket read, so a large transfer still completes.

**Fail fast on missing configuration.** `main()` in the chemical server checks
the four `S3__*` settings and stops when one is empty. The message names both
compose files, because they read different env files:

- `mcp-servers/docker-compose.yml` reads `mcp-servers/.env`
- `mcp-servers/chemical-mcp-server/docker-compose.yml` reads
  `mcp-servers/chemical-mcp-server/.env`

**Log the target at startup.** The server prints the endpoint and the bucket, so
one line of the log answers where the files go.

**Never return a bucket of `None`.** `vault.contract()` raises instead.
`CoScientist/utils/s3_refs` drops a record that has a key and no bucket, because
a key alone does not say where the object is. Such an artifact used to disappear
from the execution graph, the artifact index, and the report, without a message.

## Scope

- `CoScientist/paper_parser/s3_connection.py` — timeouts and a retry cap on the
  shared client. The papers-search, dataset-collection, and chemical images all
  copy this file.
- `mcp-servers/vault-mcp-server/vault_server.py` — the same bounds on the
  internal client and the signing client.
- `mcp-servers/chemical-mcp-server/server/chemical_server.py` —
  `_check_s3_settings()` in `main()`, and a startup log line.
- `mcp-servers/chemical-mcp-server/server/utils/vault.py` — `contract()` raises
  when the bucket name is empty.

## Deployment note

This branch sets the S3 configuration of no host. It only makes a missing
configuration visible.

Both compose files use `restart: unless-stopped`. A host that lacks `S3__*` will
crash-loop after this change, and `DynamicMCPToolset.get_tools` skips an
unreachable server without a message. Every chemical tool then disappears from
the agent, including the tools that never touch S3.

Check the env file of the host before you deploy, or apply the configuration and
this change in the same restart.

## Test

`tests/unit/test_s3_refs.py` and `tests/unit/test_session_scope_plugin.py` pass.
32 tests.

No test covers the timeout values. They are configuration, and a test for them
would assert the botocore API rather than our behavior.
