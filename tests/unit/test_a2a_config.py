"""Tests for A2A advertised vs internal URL configuration."""

import importlib
import sys
import types
from pathlib import Path


def _load_config_module(monkeypatch):
    fake_schema = types.ModuleType("CoScientist.assembly.schema")

    class FakeA2A:
        def __init__(self, key, port):
            self.key = key
            self.port = port

    class FakeAgent:
        def __init__(self, key, port):
            self.a2a = FakeA2A(key, port)

    class FakeConfig:
        def a2a_agents(self):
            return [
                FakeAgent("research", 8003),
                FakeAgent("coder", 8006),
            ]

    fake_schema.get_config = lambda: FakeConfig()
    monkeypatch.setitem(sys.modules, "CoScientist", types.ModuleType("CoScientist"))
    monkeypatch.setitem(sys.modules, "CoScientist.assembly", types.ModuleType("CoScientist.assembly"))
    monkeypatch.setitem(sys.modules, "CoScientist.assembly.schema", fake_schema)

    path = Path(__file__).resolve().parents[2] / "CoScientist" / "a2a" / "config.py"
    spec = importlib.util.spec_from_file_location("a2a_config_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_agent_urls_can_differ_from_internal_card_urls(monkeypatch):
    monkeypatch.setenv("A2A_HOST", "host.docker.internal")
    monkeypatch.setenv("A2A_PUBLIC_HOST", "127.0.0.1")

    config = _load_config_module(monkeypatch)

    assert config.AGENT_URLS["research"] == "http://127.0.0.1:8003/"
    assert (
        config.AGENT_CARD_URLS["research"]
        == "http://host.docker.internal:8003/.well-known/agent.json"
    )


def test_agent_card_urls_can_use_per_agent_internal_hosts(monkeypatch):
    monkeypatch.setenv("A2A_HOST", "a2a-default")
    monkeypatch.setenv("RESEARCH_HOST", "a2a-research")
    monkeypatch.setenv("CODER_HOST", "a2a-coder")

    config = _load_config_module(monkeypatch)

    assert (
        config.AGENT_CARD_URLS["research"]
        == "http://a2a-research:8003/.well-known/agent.json"
    )
    assert (
        config.AGENT_CARD_URLS["coder"]
        == "http://a2a-coder:8006/.well-known/agent.json"
    )
