# Run configuration of the case study

Model for every agent: `openrouter/z-ai/glm-5.3` (reasoning effort `low`; the model rejects calls with reasoning disabled).

Settings that differ from the repository defaults (`.env` names):

| Setting | Value | Meaning |
|---|---|---|
| `RESEARCH_AGENT_SEARCHES` | 6 | web/OpenAlex searches per literature task |
| `HYPOTHESES__MAX_ACTIVE` | 3 | hypotheses under verification at once; the rest are postponed with a reason |
| `ALEMBIC__AGENT_BUILD_ENABLED` | true | the McpBuilder agent may convert a repository during a run |
| `ALEMBIC__HUB_SEARCH_ENABLED` | true | look for a server in the public catalogue before building |
| `EXECUTOR__FEDOT_FALLBACK` | false | no AutoML fallback; the coder trains models itself |
| `ARTIFACT_GATE` | 0 | training is not blocked by the artefact gate |

Agent wiring and prompts: `system.yaml` (this folder) and `CoScientist/agents/prompts/templates.py` in the repository at the commit named in `README.md`. Tool catalogue for retrieval: a local Postgres + Qdrant index with the bge-m3 embedder (1024-d); the public catalogue is the Docker Hub namespace `peanutbuttermilk`.

Session `tyre-main-2`: 3 user turns. Turn 1 is `prompt.txt` with the dataset attached (105 min, $3.44). Turn 2 is `prompt_followup.txt` (build servers from the two methods that ran). Turn 3 (`prompt_followup_repeat.txt`) was reframed by the orchestrator as a new study and is not used in the paper. Session `tyre-followup-1` is a fresh session with the candidate-recipe question (4.3 min, $0.14).
