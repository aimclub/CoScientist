from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "start-codesynapse-a2a.ps1"


def test_launcher_maps_host_mongodb_settings_to_the_facade_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "$env:MONGODB_URI" in text
    assert "$env:MONGODB_DATABASE" in text
    assert "CODESYNAPSE_MONGO_URI" in text
    assert "CODESYNAPSE_MONGO_DATABASE" in text
    assert "host.docker.internal" in text


def test_launcher_starts_a_standard_a2a_facade_and_waits_for_readiness() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "JwksUrl" not in text
    assert "CODESYNAPSE_JWKS_URL" not in text
    assert "docker-compose.codesynapse-facade.yml" in text
    assert "/readyz" in text
    assert ".well-known/agent-card.json" in text
