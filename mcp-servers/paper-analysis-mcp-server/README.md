# paper-analysis-mcp-server

## Environment

Create a `.env` file in this directory based on `.env.example`.

## Server Tools

This server's MCP tools include:

### 1. `explore_scientific_database`

- Purpose: Answer general chemistry questions using the indexed chemistry papers database (Chroma).
- Input:
	- `task` (string): user question.
- Output:
	- JSON with `answer` and supporting context/metadata.
- Use when:
	- you need database-backed chemistry answers not tied to a specific user-uploaded paper set.

### 2. `explore_my_papers`

- Purpose: Answer questions about user-provided PDF papers, including figures/reactions/molecules and paper metadata.
- Input:
	- `task` (string): user question about uploaded papers.
	- `config` (RunnableConfig): used for MCP session context (includes `session_id`).
- Output:
	- JSON with `answer` and metadata.
	- Returns `{"answer": "No papers provided for search."}` if no PDFs are found.
- Use when:
	- the question is about the current uploaded paper set, specific document details, or cross-paper comparison.

### 3. `get_papers_database_statistics`

- Purpose: Report what the papers database (Chroma, `CHROMADB_COLLECTION`) holds: the number of unique papers and their share per research domain and field, across the whole database and within each domain.
- Input: none.
- Output:
	- A report in Russian, formatted as Markdown (a string, not JSON): summary, domains, fields within each domain, all fields. The web UI's statistics page renders it as a dashboard. Example below.
- Use when:
	- the question is about the database itself (how many papers it holds, which domains or fields it covers), not about what the papers say.
- Notes:
	- Reads chunk metadata through the server's existing `vector_store` and never writes to the database.
	- Answers instantly from memory. A background thread scans the collection when the server starts, then every `PAPER_STATS_CHECK_MINUTES` (default 10) asks Chroma only for the chunk count, and rescans when it changed or the result is older than `PAPER_STATS_MAX_AGE_HOURS` (default 24). The report says when it was computed. Until the first scan finishes, the tool returns progress instead of numbers; if a refresh fails, it keeps the last result and says so.
	- Each scan is logged with its duration, e.g. `Paper statistics: 1135 papers from 12459 chunks, scanned in 8.6s`.
	- Papers are unique `article_id` values. Chunks with `role="summary"` are outdated and ignored. A paper's domain and field are the values most of its chunks carry, so every section shares one denominator.

```markdown
Данные на 21.09.2026 17:24 UTC (12 мин назад). Коллекция проверяется на изменения каждые 10 мин; при изменениях статистика пересчитывается автоматически.

## Сводка

| Показатель | Значение |
|---|---:|
| Статей в базе | 142 |
| Областей науки | 3 |
| Научных направлений | 6 |
| Фрагментов в коллекции | 25 134 |

## Области науки

| Область науки | Статей | Доля |
|---|---:|---:|
| Физические науки | 78 | 54,9 % |
| Науки о жизни | 41 | 28,9 % |
| Науки о здоровье | 23 | 16,2 % |

## Направления внутри областей

### Физические науки · 78 статей

| Направление | Статей | Доля в области |
|---|---:|---:|
| Химия | 52 | 66,7 % |
| Материаловедение | 26 | 33,3 % |

### Науки о жизни · 41 статья

| Направление | Статей | Доля в области |
|---|---:|---:|
| Биохимия, генетика и молекулярная биология | 30 | 73,2 % |
| Сельскохозяйственные и биологические науки | 11 | 26,8 % |

### Науки о здоровье · 23 статьи

| Направление | Статей | Доля в области |
|---|---:|---:|
| Фармакология, токсикология и фармацевтика | 16 | 69,6 % |
| Медицина | 7 | 30,4 % |

## Все научные направления

| Научное направление | Статей | Доля |
|---|---:|---:|
| Химия | 52 | 36,6 % |
| Биохимия, генетика и молекулярная биология | 30 | 21,1 % |
| Материаловедение | 26 | 18,3 % |
| Фармакология, токсикология и фармацевтика | 16 | 11,3 % |
| Сельскохозяйственные и биологические науки | 11 | 7,7 % |
| Медицина | 7 | 4,9 % |

Учтено фрагментов: 24 850 из 25 134. Устаревшие аннотации и фрагменты без идентификатора статьи не учитываются; область и направление статьи определяются по большинству её фрагментов.
```

## Run With uv

From `mcp-servers/paper-analysis-mcp-server`:

```bash
set -a
source .env
set +a
uv sync --frozen --no-install-project
uv run --no-project python paper_analysis_server.py
```

The server imports `CoScientist.*` modules, so the repository root must be importable. Outside Docker that runs the full `CoScientist/__init__.py`, which imports `google-adk`; this environment does not include it, so the local run fails on that import. Docker copies only the subpackages the server needs and avoids this, so prefer the Docker run below.

## Run With Docker

Build from `mcp-servers/paper-analysis-mcp-server`, but use the repository root as the Docker build context:

```bash
docker build -f Dockerfile -t paper-analysis-mcp-server ../..
```

Run the container with the environment file and port mapping:

```bash
docker run --rm -i -p 7331:7331 --env-file .env paper-analysis-mcp-server
```

The server will be available at `http://localhost:7331/mcp`.