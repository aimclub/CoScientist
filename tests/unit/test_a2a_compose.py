"""Structural checks for the A2A Docker Compose stack."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict:
    path = ROOT / "docker" / "docker-compose.a2a.yml"
    return yaml.safe_load(path.read_text())


def _declared_a2a_agents() -> dict[str, int]:
    system = yaml.safe_load(
        (ROOT / "CoScientist" / "agents" / "system.yaml").read_text()
    )
    return {
        config["a2a"]["key"]: config["a2a"]["port"]
        for config in system["agents"].values()
        if "a2a" in config
    }


def _a2a_services() -> dict:
    return {
        name: service
        for name, service in _compose()["services"].items()
        if name.startswith("a2a-")
    }


def test_a2a_image_is_built_once_and_reused_by_all_services():
    a2a_services = _a2a_services()

    assert {service["image"] for service in a2a_services.values()} == {
        "coscientist-a2a:latest"
    }
    assert [
        name for name, service in a2a_services.items()
        if "build" in service
    ] == ["a2a-orchestrator"]
    assert a2a_services["a2a-orchestrator"]["build"] == {
        "context": "..",
        "dockerfile": "docker/Dockerfile.a2a",
    }


def test_every_declared_a2a_agent_has_an_independent_compose_service():
    agents = _declared_a2a_agents()
    services = _a2a_services()

    assert set(services) == {
        f"a2a-{key.replace('_', '-')}" for key in agents
    }
    for key in agents:
        service = services[f"a2a-{key.replace('_', '-')}"]
        assert service["command"] == [
            "python",
            "-m",
            "CoScientist.a2a.serve",
            key,
        ]
        assert "depends_on" not in service


def test_each_service_has_a_card_healthcheck_and_synchronised_port():
    agents = _declared_a2a_agents()
    services = _a2a_services()

    for key, default_port in agents.items():
        service_name = f"a2a-{key.replace('_', '-')}"
        service = services[service_name]
        port_variable = f"{key.upper()}_PORT"
        interpolated_port = f"${{{port_variable}:-{default_port}}}"

        assert service["environment"][port_variable] == interpolated_port
        assert service["ports"] == [
            f"{interpolated_port}:{interpolated_port}"
        ]
        assert service["environment"]["A2A_PUBLIC_HOST"] == (
            f"${{A2A_PUBLIC_HOST:-{service_name}}}"
        )

        healthcheck = service["healthcheck"]
        assert healthcheck["test"][0] == "CMD-SHELL"
        assert "/.well-known/agent-card.json" in healthcheck["test"][1]
        assert f"$${{{port_variable}}}" in healthcheck["test"][1]


def test_compose_defaults_are_suitable_for_non_interactive_a2a_clients():
    compose = _compose()
    services = _a2a_services()

    assert compose["networks"]["a2a"]["name"] == "coscientist-a2a"
    for service in services.values():
        assert service["environment"]["HITL__ENABLED"] == "false"
        assert service["environment"]["A2A_DISABLE_OPIK"] == (
            "${A2A_DISABLE_OPIK-1}"
        )
        assert service["restart"] == "unless-stopped"
        assert service["networks"] == ["a2a"]
