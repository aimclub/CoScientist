# paper-analysis-mcp-server

## Environment

Create a `.env` file in this directory based on `.env.example`.

## Server tools

### `explore_scientific_database`

Answer a general scientific question using retrieved and reranked body chunks, associated figures and an LLM. Use this for a synthesized answer; use `find_papers_in_db` for a list of publications.

### `explore_my_papers`

Answer questions about specific uploaded PDFs, including figures, experimental details, conclusions, titles and authors. Downloads the PDFs from the configured upload bucket, extracts reactions and molecules through OpenChemIE, and sends the PDFs with that additional context to the LLM.

### `find_papers_in_db`

Find publications by extracting metadata filters from the query, searching body chunks and reranking them. Results are deduplicated by article ID.

### `find_relevant_data_in_db`

Retrieve structured source material without generating a final answer. Uses LLM-extracted metadata filters, retrieves and reranks body chunks, and attaches referenced figures with captions and image payloads from S3.

## Run With uv

From `mcp-servers/paper-analysis-mcp-server`:

```bash
set -a
source .env
set +a
uv sync --frozen --no-install-project
uv run --no-project python papers_search_server.py
```

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