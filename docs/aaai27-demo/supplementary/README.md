# Supplementary material: CoScientist demo, AAAI-27 Demonstrations

## Contents
- `prompt.txt`: the prompt given to CoScientist and to the opencode baseline (the baseline got one extra line naming the local dataset path).
- `prompt_followup.txt`: the second user turn in the CoScientist session, asking for MCP servers from the two methods that ran.
- `coscientist_report.md`: the report CoScientist generated from its research graph (English, run `tyre-main-2`).
- `coscientist_run_summary.md`: time per agent, tool calls, tokens, cost, graph size, hypotheses and verdicts.
- `opencode_report.md`: the report written by the opencode baseline on the same prompt and model (GLM-5.3).
- `task_definition.md`: dataset description, metric, and the reference models we computed by hand before the runs.
- `dataset/tires_2.csv`: 3,774 rubber compounds parsed from 337 patents (recipe in phr, ingredient grades and types, process parameters, measured properties with gaps).

## Pulling a tool server from the catalogue
Servers live in the Docker Hub namespace `peanutbuttermilk`, one repository per converted code repository, tags `<build id>` and `latest`. Each image serves the Model Context Protocol over streamable HTTP on port 8000.

```bash
docker pull peanutbuttermilk/alembic-tool-chempy:latest
docker run -d -p 28000:8000 peanutbuttermilk/alembic-tool-chempy:latest serve https://github.com/bjodah/chempy
```

Calling a tool from Python (package `mcp`):

```python
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with streamablehttp_client("http://localhost:28000/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])

asyncio.run(main())
```

The full description of each repository on Docker Hub carries the build metadata: source repository, tools, and how many of them passed tests and live calls. Long results are returned in a shortened form together with an object-store reference to the complete JSON.

## Servers of the case study
- `alembic-tool-polymergnn`: PolymerGNN (Queen et al. 2023), training, prediction and composition embedding.
- `alembic-tool-mordred-community`: mordred descriptors for small-molecule ingredients, mixture descriptors.
- polyBERT: built from a public copy of the weights; the licence of polyBERT forbids redistribution, so this server is not in the catalogue. The build recipe is the same as for the others.
- TODO(run): servers built during the session (Wan et al. 2024 models, TransPolymer).
