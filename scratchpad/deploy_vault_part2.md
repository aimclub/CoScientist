# Redeploy with the S3 vault

This describes what to change on the server for the S3 vault. It covers the
`.env` files and the new container in Docker Compose.

## When to do each step

The deploy job pins `DEPLOY_BRANCH: main` and runs `git reset --hard
origin/main`.

Part 1 is already on `main` (#336). It gave every MCP server the one S3
contract and the per-session key layout. It reads no new configuration, so the
server needs nothing for it.

Part 2 is still open. It is the branch that reads `MCP__VAULT_URL`.

Split the work like this:

1. Do the server setup below **before** part 2 merges. All of it is safe. The
   code on `main` today does not read `MCP__VAULT_URL`, so the new key is
   inert. The vault container is separate from the web service.
2. On the merge, do nothing by hand. The existing job updates the code and
   restarts the service.

There is no half-working window. If `MCP__VAULT_URL` is not set, the vault
toolset and every framework call drop out, and a run still completes.

No dependency changed. The `mcp` client library comes with `google-adk` and is
already in `uv.lock`, so `uv sync --frozen` needs nothing new.

## What works after this deploy

- **Artifact promotion.** At the end of a run, `MANIFEST.json` carries a
  `promoted` map. Each report figure and table gets a copy under `permanent/`,
  which the lifecycle rule does not delete.
- **Dead link recovery.** The report collector mints a fresh download link from
  the stored key. A run that spans a restart no longer loses its figures.
- **The vault tools for agents.** `CoderAgent` and `DatasetCollectorAgent` get
  `get_upload_link` and `get_download_link`.

**The remote workspace sync stays inert.** It runs only when `CODE_EXEC__URL`
is set. This server has no such key, so the sandbox is local and the report
collector reads the files from disk as before. Expect nothing under
`ephemeral/<user>/<session>/workspace/` in MinIO. This is correct, not a
failure.

## Part 1: the CoScientist .env

Add one line to `~/.config/coscientist/.env`:

```
MCP__VAULT_URL=http://localhost:7338/mcp
```

The form matches the key that is already there,
`MCP__RESULT_FORMATTER_URL=http://localhost:7337/mcp`. Use the address that the
web service can reach. If the vault container runs on another host, put that
host here.

**Do not touch the `S3__*` keys in this file.** They configure the paper
parser (`CoScientist/paper_parser/parse_and_split.py`, which reads
`S3__USE_S3`). The vault reads its own `S3__*` keys from a different file. The
names are the same, the consumers are not. Keep the two files separate.

The web service never talks to S3 directly with a key and a secret. It calls
the vault over MCP, and it downloads the links the vault returns.

## Part 2: the vault container

The service is `vault-mcp-server` in `mcp-servers/docker-compose.yml`. It
publishes host port 7338 and listens on 7331 inside the network, the same port
as every sibling MCP server.

Two `.env` files feed it. Neither is in git. Both have an `.env.example` beside
them. Copy the example, then edit.

`mcp-servers/.env.example` arrives with part 2. Until that merges, the deploy
directory sits on `main` and does not hold it. Write the file by hand from the
listing in step 1, or read it on the branch.

### Step 1. Create the Compose project env file

The compose file reads `${PIP_PROXY}` and `${EPHEMERAL_TTL_DAYS}`. Compose
takes them from a `.env` file next to `docker-compose.yml`. That file is not in
git. Copy the example:

```
cd ~/cosci/CoScientist/mcp-servers
cp .env.example .env
```

Then set `PIP_PROXY` to the proxy the web service uses. Read the address from
`~/.config/systemd/user/coscientist-web.service`. `PIP_PROXY` becomes the
`HTTP_PROXY` build argument. Without it, `pip install` runs with no proxy
during the image build, and the build fails on a VM with restricted egress.

**This file is also the env file of `chemical-mcp-server`.** The compose file
gives that one service `env_file: .env` while every other service points at its
own folder. If the server already runs the chemical MCP server, the file
already exists. Add the two keys to it. Do not overwrite it.

### Step 2. Create the vault env file

`mcp-servers/vault-mcp-server/.env` is not in git either. Compose fails at
once if the file is missing. Copy the example and edit it. The example carries
the external-S3 rule in a comment:

```
cd ~/cosci/CoScientist/mcp-servers/vault-mcp-server
cp .env.example .env
```

For an external MinIO, the file must read like this:

```
S3__ENDPOINT_URL=http://<minio-host>:9000
S3__EXTERNAL_ENDPOINT_URL=http://<minio-host>:9000
S3__ACCESS_KEY=<access-key>
S3__SECRET_KEY=<secret-key>
S3__BUCKET_NAME=agent-vault
EPHEMERAL_TTL_DAYS=7
VAULT_SURFACE=all
MCP_PORT=7331
```

Four points on these values:

1. **Both endpoints hold the same address.** The example file splits them
   (`http://minio:9000` and `http://localhost:9000`) because a MinIO that runs
   in the same Compose project has one name inside the network and another one
   outside. An external MinIO has one routable address. Copy the example
   unchanged and the vault starts and then fails every call.
2. **The external endpoint must be reachable from every client.** The vault
   signs each link for this host. The web service downloads with it. Later,
   when `CODE_EXEC__URL` is set, the sandbox uploads with it.
3. **`VAULT_SURFACE=all`.** This branch runs one instance. The worker toolset
   filters the tool list on the client side, so an agent sees only
   `get_upload_link` and `get_download_link`. The framework needs
   `promote_artifact` on the same port.
4. **`EPHEMERAL_TTL_DAYS` must match the lifecycle rule** you set in step 3.
   The value here sets the link lifetime. The value in the rule sets the object
   lifetime. If they differ, a link outlives its object.

The endpoint in the local development `.env` is `http://10.32.1.114:9000` with
the bucket `chemcoscientist-paper-analysis`. Confirm the real address against
the server file at `~/.config/coscientist/.env` before you fill this in.

### Step 3. Prepare the bucket

Use a new bucket, `agent-vault`. Do not point the vault at
`chemcoscientist-paper-analysis`. The setup grants anonymous read on the
`permanent/` prefix. On a shared bucket that changes who can read content the
vault does not own.

Run three commands once against the external MinIO:

```
mc mb <alias>/agent-vault --ignore-existing
mc ilm rule add --expire-days 7 --prefix ephemeral/ <alias>/agent-vault
mc anonymous set download <alias>/agent-vault/permanent
```

Without the lifecycle rule, nothing under `ephemeral/` ever expires. Without
the anonymous policy, the plain `permanent/` links do not resolve.

The access key in the vault `.env` needs read and write on this bucket.

### Step 4. Build and start the container

```
cd ~/cosci/CoScientist/mcp-servers
docker compose up -d --build vault-mcp-server
```

This starts one service. It does not touch the other MCP servers.

### Step 5. Check it

```
curl http://<minio-host>:9000/minio/health/live
curl -v http://localhost:7338/mcp
docker logs vault-mcp-server --tail 50
```

For a full check, run the demonstration client. It uploads, downloads,
promotes, and cleans up:

```
cd ~/cosci/CoScientist/mcp-servers/vault-mcp-server
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
VAULT_MCP_URL=http://localhost:7338/mcp python3 mcp_client.py
```

Success shows `[+] Upload complete.`, `[+] Permanent download OK: ...`, and
`[+] Manifest holds ... artifacts.`

### Step 6. Restart the web service

```
systemctl --user restart coscientist-web
journalctl --user -u coscientist-web -f
```

Do this after the merge, or now if you only added `MCP__VAULT_URL`.

## The proxy trap

The systemd unit sets a global proxy:

```
Environment=HTTP_PROXY=http://10.32.11.45:7890
Environment=HTTPS_PROXY=http://10.32.11.45:7890
Environment=NO_PROXY=localhost,127.0.0.1
```

`requests` and `httpx` both read these variables. Every presigned download and
every vault call now goes through the tunnel. `localhost:7338` is safe, because
`NO_PROXY` covers it. The MinIO host is not covered.

Add the MinIO host to `NO_PROXY` in
`~/.config/systemd/user/coscientist-web.service`:

```
Environment=NO_PROXY=localhost,127.0.0.1,<minio-host>
```

Then run `systemctl --user daemon-reload` and restart the service. Note that
the file `deploy/coscientist-web.service` in git holds the same unit. Keep the
two the same, or the next person copies an old value.

If a report shows no figures, check this first. The log line reads
`collect: failed to download ...`.

Two stale addresses to know about. `deploy/README.md` says the proxy is
`172.17.0.1:7890`. The unit on the server says `10.32.11.45:7890`. Trust the
unit.

## Local MinIO instead

For a test host with no external MinIO, start MinIO from the same Compose file:

```
cd ~/cosci/CoScientist/mcp-servers
docker compose --profile local-s3 up -d --build
```

The profile starts MinIO on ports 9000 and 9001 and a one-shot `minio-setup`
container. The setup container creates the bucket, adds the user
`agent-user`, applies the lifecycle rule, and sets the anonymous policy. Then
the vault `.env` uses the split form from the example file:

```
S3__ENDPOINT_URL=http://minio:9000
S3__EXTERNAL_ENDPOINT_URL=http://localhost:9000
S3__ACCESS_KEY=agent-user
S3__SECRET_KEY=agent-secret-key
```

The profile is off by default. The other MCP servers point at an S3 endpoint
this Compose file does not define, so a MinIO that starts by itself would move
where they write.

## Roll back

1. Remove `MCP__VAULT_URL` from `~/.config/coscientist/.env`.
2. Restart the web service.

The vault toolset drops out of both agents, promotion logs one line and skips,
and the collector falls back to the stored links. Runs still complete. The
container may keep running. Nothing calls it.

## Summary of files you edit on the server

| File | Change |
| --- | --- |
| `~/.config/coscientist/.env` | Add `MCP__VAULT_URL=http://localhost:7338/mcp` |
| `~/cosci/CoScientist/mcp-servers/.env` | From `.env.example`. Set `PIP_PROXY`. Shared with chemical-mcp-server |
| `~/cosci/CoScientist/mcp-servers/vault-mcp-server/.env` | New. From `.env.example`, both endpoints equal |
| `~/.config/systemd/user/coscientist-web.service` | Add the MinIO host to `NO_PROXY` |

The two new `.env` files sit inside the deploy directory. The deploy job runs
`git reset --hard`, which does not delete untracked and ignored files, so they
survive each deploy. Line 131 of `.gitignore` already covers both.
