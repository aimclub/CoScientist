"""Structural checks for the aggregate local MCP Docker Compose stack."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "mcp-servers" / "docker-compose.yml"
FACADE_COMPOSE_PATH = ROOT / "docker" / "docker-compose.codesynapse-facade.yml"

EXPECTED = {
    "papers-search-mcp-server": {
        "port": "7331:7331",
        "env_file": "./papers-search-mcp-server/.env",
    },
    "chemical-mcp-server": {
        "port": "7332:7331",
        "env_file": "./chemical-mcp-server/.env",
    },
    "dataset-collection-mcp-server": {
        "port": "7333:7331",
        "env_file": "./dataset-collection-mcp-server/.env",
    },
    "paper-analysis-mcp-server": {
        "port": "7334:7331",
        "env_file": "./paper-analysis-mcp-server/.env",
    },
}


def _services() -> dict:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    return compose["services"]


def test_compose_declares_every_required_coscientist_mcp_service() -> None:
    """Optional S3/support services may coexist with the four façade tools."""

    assert set(EXPECTED).issubset(_services())


def test_each_mcp_service_has_stable_port_env_and_health_contract() -> None:
    for name, expected in EXPECTED.items():
        service = _services()[name]

        assert service["ports"] == [expected["port"]]
        assert service["env_file"] == [expected["env_file"]]
        assert service["restart"] == "unless-stopped"
        assert "healthcheck" in service
        assert "network_mode" not in service

        environment = service.get("environment", {})
        forbidden_fragments = ("key", "secret", "password", "token")
        assert not any(
            fragment in key.lower()
            for key in environment
            for fragment in forbidden_fragments
        )


def test_chemical_image_uses_its_own_build_context() -> None:
    assert _services()["chemical-mcp-server"]["build"] == {
        "context": "./chemical-mcp-server",
        "dockerfile": "Dockerfile",
    }


def test_paper_analysis_template_keeps_runtime_credentials_empty() -> None:
    path = (
        ROOT
        / "mcp-servers"
        / "paper-analysis-mcp-server"
        / ".env.example"
    )
    values = {
        key: value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
        for key, value in [line.split("=", 1)]
    }

    assert values["LLM__ALLOWED_PROVIDERS"] == ""
    for key in ("LLM__SERVICE_KEY", "OPENAI_API_KEY", "S3__ACCESS_KEY", "S3__SECRET_KEY"):
        assert values[key] == ""


def test_local_mcps_share_the_codesynapse_network_with_the_facade() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    facade = yaml.safe_load(FACADE_COMPOSE_PATH.read_text(encoding="utf-8"))

    assert compose["networks"]["codesynapse-internal"]["external"] is True
    assert facade["services"]["coscientist-facade"]["ports"] == ["${CODESYNAPSE_A2A_PORT:-8010}:8010"]
    assert facade["services"]["coscientist-facade"]["environment"]["HITL__ENABLED"] == "true"
    for service in compose["services"].values():
        assert service["networks"] == ["codesynapse-internal"]
