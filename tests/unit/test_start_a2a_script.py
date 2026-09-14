from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "start-a2a.ps1"


def test_launcher_exposes_synapse_ready_defaults() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert '$PublicHost = "localhost"' in text
    assert '$TimeoutSeconds = 300' in text
    assert "docker\\docker-compose.a2a.yml" in text
    assert "JSON-RPC path for Synapse registration: /" in text


def test_launcher_covers_every_compose_a2a_service() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    expected = {
        "a2a-orchestrator": 8000,
        "a2a-planner": 8001,
        "a2a-hypotheses": 8002,
        "a2a-research": 8003,
        "a2a-task-execution": 8004,
        "a2a-medical": 8005,
        "a2a-coder": 8006,
        "a2a-init": 8008,
    }

    for service, port in expected.items():
        assert service in text
        assert str(port) in text
