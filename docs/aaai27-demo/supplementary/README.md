# Supplementary material: CoScientist demo, AAAI-27 Demonstrations

## Contents

Top level: the demo video and the CoScientist configuration of the runs.

- `coscientist_aaai27_demo.mp4`: the demo video (4:12).
- `system.yaml`: agent wiring used for the runs; `run_config.md`: model, limits, flags, and the turns of each session. Code: https://github.com/aimclub/CoScientist, branch `coscientist-aaai-demo`, commit `49eccbd`.

Folders:

- `prompts/`: `prompt.txt` (the prompt given to CoScientist and to the opencode baseline; the baseline got one extra line naming the local dataset path), `prompt_followup.txt` (second turn: build servers from the two methods that ran), `prompt_followup_repeat.txt` (third turn; the orchestrator reframed it as a new study, so the repeat experiment in the paper is the separate session `tyre-followup-1`), `narration_script.md` (video narration and shot list).
- `reports/`: `coscientist_report.md` (generated from the research graph, run `tyre-main-2`), `coscientist_run_summary.md` (time per agent, tool calls, tokens, cost, graph size, verdicts), `opencode_report.md` (the baseline on the same prompt and model, GLM-5.3).
- `sessions/`: `tyre-main-2.cossession.zip`, the exported session (research graph, agent events, artefact index). Import it into a CoScientist web instance: `curl -X POST http://localhost:8000/api/users/x/import-session -F file=@tyre-main-2.cossession.zip`, then open the chat, `/graph?view=research`, and `/trace`. `*_summary.md`: per-agent time, calls, tokens, cost and verdicts for `tyre-main-2` and `tyre-followup-1`.
- `case_study/`: `task_definition.md` (dataset, metric, reference models computed by hand before the runs), `alembic_build_log.md` (what Alembic did for each of the five repositories of the case), `dataset/tires_2.csv` (3,774 rubber compounds parsed from 337 patents: recipe in phr, ingredient grades and types, process parameters, measured properties with gaps).
- `figures/`: `graph_hypotheses.png` (Figure 2 of the paper), `graph_full.png` (the full research graph of `tyre-main-2` in the viewer).

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
