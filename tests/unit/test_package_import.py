"""Tests for keeping package import light enough for module entry points."""

import importlib
import sys
from types import ModuleType


def test_package_import_does_not_build_agents():
    for name in list(sys.modules):
        if name == "CoScientist" or name.startswith("CoScientist."):
            del sys.modules[name]

    package = importlib.import_module("CoScientist")

    assert package.__version__ == "1.0.0"
    assert "CoScientist.agents" not in sys.modules
    assert "CoScientist.main" not in sys.modules


def test_event_logger_import_does_not_configure_opik():
    for name in list(sys.modules):
        if name == "CoScientist.logging" or name.startswith("CoScientist.logging."):
            del sys.modules[name]

    importlib.import_module("CoScientist.logging.event_logger")

    assert "CoScientist.logging.opik_tracer" not in sys.modules


def test_agents_skip_opik_tracing_when_a2a_disables_it(monkeypatch):
    package = importlib.import_module("CoScientist")
    sys.modules.pop("CoScientist.agents", None)
    package.__dict__.pop("agents", None)

    root = object()
    assembly = ModuleType("CoScientist.assembly")
    assembly.build_system = lambda: type("System", (), {"root": root})()
    logging = ModuleType("CoScientist.logging")
    monkeypatch.setitem(sys.modules, "CoScientist.assembly", assembly)
    monkeypatch.setitem(sys.modules, "CoScientist.logging", logging)
    monkeypatch.setenv("A2A_DISABLE_OPIK", "1")

    agents = importlib.import_module("CoScientist.agents")

    assert agents.root_agent is root
