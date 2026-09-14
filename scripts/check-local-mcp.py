"""Validate local MCP transports and their expected tool surfaces."""

from __future__ import annotations

import argparse
import asyncio
import sys
from urllib.parse import urlsplit, urlunsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


SERVERS = {
    "papers-search": {
        "url": "http://localhost:7331/mcp",
        "tools": {
            "search_entity",
            "search_papers",
            "download_papers_from_search",
        },
    },
    "chemical": {
        "url": "http://localhost:7332/mcp",
        "tools": {
            "name2smiles",
            "smiles2name",
            "smiles2prop",
            "visualize_molecule",
            "fetch_activity_data",
            "extract_reactions",
            "extract_molecules",
            "calculate_docking",
            "retrosynthesis_tree_search",
            "classify_reaction",
            "forward_predict",
        },
    },
    "dataset-collection": {
        "url": "http://localhost:7333/mcp",
        "tools": {"extract_mols_prop_dataset"},
    },
    "paper-analysis": {
        "url": "http://localhost:7334/mcp",
        "tools": {
            "explore_chemistry_database",
            "explore_my_papers",
        },
    },
}


def endpoint_url(url: str, host: str | None) -> str:
    """Replace only the endpoint host while preserving scheme, port and path."""
    if not host:
        return url
    parsed = urlsplit(url)
    if parsed.port is None:
        raise ValueError(f"MCP URL has no explicit port: {url}")
    return urlunsplit(
        (parsed.scheme, f"{host}:{parsed.port}", parsed.path, parsed.query, "")
    )


async def inspect_server(
    name: str,
    config: dict,
    *,
    host: str | None,
    timeout: float,
) -> tuple[str, list[str]]:
    """Initialize one MCP session and return its advertised tool names."""
    url = endpoint_url(config["url"], host)
    async with streamablehttp_client(url, timeout=timeout) as (
        read,
        write,
        _,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    discovered = [tool.name for tool in result.tools]
    if len(discovered) != len(set(discovered)):
        raise RuntimeError(f"{name} returned duplicate tool names: {discovered}")

    missing = sorted(config["tools"] - set(discovered))
    if missing:
        raise RuntimeError(f"{name} is missing expected tools: {missing}")
    return url, sorted(discovered)


async def check_all(host: str | None, timeout: float) -> int:
    failures: list[str] = []
    for name, config in SERVERS.items():
        try:
            url, tools = await inspect_server(
                name,
                config,
                host=host,
                timeout=timeout,
            )
            print(f"{name}: OK {url}")
            print(f"  tools: {', '.join(tools)}")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print(f"{name}: FAILED — {exc}", file=sys.stderr)

    if failures:
        print(
            f"{len(failures)} of {len(SERVERS)} MCP servers failed validation.",
            file=sys.stderr,
        )
        return 1

    print(f"All {len(SERVERS)} MCP servers passed initialize/tools-list.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        help=(
            "Replace localhost in every endpoint, for example "
            "host.docker.internal when running from an A2A container."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Per-server MCP connection timeout in seconds (default: 30).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(check_all(args.host, args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
