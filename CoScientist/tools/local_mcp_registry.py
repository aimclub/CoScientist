"""Static registry for the MCP services bundled with the local Compose stack.

The façade uses this catalogue while the PostgreSQL-backed RAG registry is not
deployed.  It intentionally performs no network I/O: MCP availability is a
runtime concern of the consumer that invokes a selected server.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from CoScientist.storage import RetrievalToolResult


@dataclass(frozen=True)
class LocalMCPServer:
    """Connection metadata for one local streamable-HTTP MCP server."""

    server_id: str
    name: str
    url: str
    description: str
    protocol: str = "http"


@dataclass(frozen=True)
class LocalMCPTool:
    """One tool advertised by a server in the local MCP Compose stack."""

    tool: str
    server_id: str
    description: str
    score: float = 1.0


def local_servers() -> tuple[LocalMCPServer, ...]:
    """Return the four MCP services from ``mcp-servers/docker-compose.yml``.

    Defaults are Docker-internal DNS names.  The two existing and two new
    ``MCP__*_URL`` variables make the registry usable from a host process too.
    """

    return (
        LocalMCPServer(
            server_id="papers-search",
            name="papers-search",
            url=os.getenv("MCP__PAPERS_SEARCH_URL", "http://papers-search-mcp-server:7331/mcp"),
            description="Search OpenAlex entities and papers, then download paper PDFs.",
        ),
        LocalMCPServer(
            server_id="chemical",
            name="chemical",
            url=os.getenv("MCP__CHEMICAL_URL", "http://chemical-mcp-server:7331/mcp"),
            description="Chemical structure, activity, docking, reaction and retrosynthesis tools.",
        ),
        LocalMCPServer(
            server_id="dataset-collection",
            name="dataset-collection",
            url=os.getenv("MCP__DATASET_COLLECTION_URL", "http://dataset-collection-mcp-server:7331/mcp"),
            description="Extract molecular property datasets from supplied scientific documents.",
        ),
        LocalMCPServer(
            server_id="paper-analysis",
            name="paper-analysis",
            url=os.getenv("MCP__PAPER_ANALYSIS_URL", "http://paper-analysis-mcp-server:7331/mcp"),
            description="Explore chemistry knowledge and the project's uploaded papers.",
        ),
    )


LOCAL_MCP_TOOLS: tuple[LocalMCPTool, ...] = (
    LocalMCPTool("search_entity", "papers-search", "Search a scholarly entity by type and name."),
    LocalMCPTool("search_papers", "papers-search", "Search scholarly papers by a textual query."),
    LocalMCPTool("download_papers_from_search", "papers-search", "Download PDFs from a paper-search result."),
    LocalMCPTool("fetch_activity_data", "chemical", "Fetch compound activity data for a biological target."),
    LocalMCPTool("name2smiles", "chemical", "Convert a compound name to a SMILES string."),
    LocalMCPTool("smiles2name", "chemical", "Resolve a SMILES string to a compound name."),
    LocalMCPTool("smiles2prop", "chemical", "Calculate molecular properties from a SMILES string."),
    LocalMCPTool("visualize_molecule", "chemical", "Render a molecular structure from a SMILES string."),
    LocalMCPTool("extract_reactions", "chemical", "Extract chemical reactions from a document or image."),
    LocalMCPTool("extract_molecules", "chemical", "Extract chemical molecules from a document or image."),
    LocalMCPTool("calculate_docking", "chemical", "Calculate a docking score for a molecule and target."),
    LocalMCPTool("retrosynthesis_tree_search", "chemical", "Find retrosynthesis routes for a target molecule."),
    LocalMCPTool("classify_reaction", "chemical", "Classify a chemical reaction."),
    LocalMCPTool("forward_predict", "chemical", "Predict products of a chemical reaction."),
    LocalMCPTool("extract_mols_prop_dataset", "dataset-collection", "Create a molecular-property dataset from papers."),
    LocalMCPTool("explore_chemistry_database", "paper-analysis", "Answer a chemistry-database exploration task."),
    LocalMCPTool("explore_my_papers", "paper-analysis", "Answer a question using project paper artifacts."),
)


def local_server(server_id: str) -> LocalMCPServer | None:
    """Resolve a local registry id without querying PostgreSQL."""

    return next((server for server in local_servers() if server.server_id == server_id), None)


def local_tool_results() -> tuple[RetrievalToolResult, ...]:
    """Return static tool metadata in the existing retrieval-tool contract."""

    return tuple(
        RetrievalToolResult(
            tool=tool.tool,
            server_id=tool.server_id,
            description=tool.description,
            score=tool.score,
        )
        for tool in LOCAL_MCP_TOOLS
    )
