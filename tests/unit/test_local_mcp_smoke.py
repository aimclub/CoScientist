"""Contract tests for the local MCP protocol smoke-test manifest."""

import importlib.util
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-local-mcp.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("check_local_mcp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_manifest_has_four_unique_local_mcp_urls() -> None:
    servers = _load_smoke_module().SERVERS
    urls = [config["url"] for config in servers.values()]

    assert len(servers) == 4
    assert len(set(urls)) == 4
    assert {urlparse(url).port for url in urls} == {7331, 7332, 7333, 7334}
    assert all(urlparse(url).path == "/mcp" for url in urls)


def test_every_local_mcp_server_has_expected_tools() -> None:
    servers = _load_smoke_module().SERVERS

    assert all(config["tools"] for config in servers.values())
    assert servers["papers-search"]["tools"] == {
        "search_entity",
        "search_papers",
        "download_papers_from_search",
    }
    assert servers["dataset-collection"]["tools"] == {
        "extract_mols_prop_dataset"
    }
