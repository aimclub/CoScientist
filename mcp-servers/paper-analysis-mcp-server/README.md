# papers-search-mcp-server

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
	- Plain-text report (a string, not JSON). Example below.
- Use when:
	- the question is about the database itself (how many papers it holds, which domains or fields it covers), not about what the papers say.
- Notes:
	- Reads chunk metadata through the server's existing `vector_store` and never writes to the database.
	- Answers instantly from memory. A background thread scans the collection when the server starts, then every `PAPER_STATS_CHECK_MINUTES` (default 10) asks Chroma only for the chunk count, and rescans when it changed or the result is older than `PAPER_STATS_MAX_AGE_HOURS` (default 24). The report says when it was computed. Until the first scan finishes, the tool returns progress instead of numbers; if a refresh fails, it keeps the last result and says so.
	- Each scan is logged with its duration, e.g. `Paper statistics: 1135 papers from 12459 chunks, scanned in 8.6s`.
	- Papers are unique `article_id` values. Chunks with `role="summary"` are outdated and ignored. A paper's domain and field are the values most of its chunks carry, so every section shares one denominator.

```
Scientific paper database: collection 'coscientist_papers' at 10.32.1.36:9941
Computed 2026-09-21 17:24 UTC (12 min ago); refreshed automatically when the collection changes.

Unique papers: 142
Chunks: 25,310 in the collection, 24,980 counted, 330 ignored (outdated summaries and rows without article_id)

Domains (142 papers = 100%):
  Physical Sciences     78   54.9%
  Life Sciences         41   28.9%
  ...

Fields (142 papers = 100%):
  Chemistry             52   36.6%
  Materials Science     26   18.3%
  ...

Fields within each domain (% of that domain's papers):
  Physical Sciences - 78 papers
    Chemistry           52   66.7%
    Materials Science   26   33.3%
  ...
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