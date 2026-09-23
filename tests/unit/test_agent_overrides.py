"""Settings → Agents: the operator's per-agent changes over system.yaml.

``settings.agents`` holds them (web UI, or ``AGENTS__OVERRIDES`` /
``AGENTS__DEFAULT_REASONING`` in .env) and they are read where the YAML's own
values are: ``AgentConfig.is_enabled`` / ``resolved_reasoning`` and the
assembler's ``_resolve_model``, i.e. when a session's agent tree is built.
"""
from __future__ import annotations

import json

import pytest

from CoScientist.assembly import assembler
from CoScientist.assembly.schema import load_config
from CoScientist.config import get_settings
from CoScientist.config.settings import AgentOverride, Settings
from CoScientist.web.agent_settings import (
    agents_catalog,
    apply_agent_settings,
    current_agent_settings,
)


@pytest.fixture(autouse=True)
def _clean_overrides():
    block = get_settings().agents
    saved = (block.default_reasoning, dict(block.overrides))
    block.default_reasoning, block.overrides = None, {}
    yield block
    block.default_reasoning, block.overrides = saved


def _override(name, **fields):
    get_settings().agents.overrides[name] = AgentOverride(**fields)


def test_an_override_switches_an_ordinary_agent_off_and_back_on():
    cfg = load_config()
    research = cfg.agent("ResearchAgent")
    assert research.is_enabled()
    _override("ResearchAgent", enabled=False)
    assert not research.is_enabled()
    # The YAML's own answer is still there for the catalog to show.
    assert research.declared_enabled()
    assert "ResearchAgent" not in [a.name for a in cfg.enabled_subordinates("OrchestratorAgent")]


@pytest.mark.parametrize("name", ["OrchestratorAgent", "ToolRetrieverAgent", "PlannerAgent"])
def test_root_internal_and_start_mode_agents_ignore_an_enabled_override(name):
    """The root is the run's only entry point, internal agents are a
    composite's stages, and the start mode attaches or removes the planner
    pipeline itself: a UI switch must not fight any of them."""
    agent = load_config().agent(name)
    declared = agent.declared_enabled()
    _override(name, enabled=not declared)
    assert agent.is_enabled() is declared


def test_a_reasoning_override_wins_over_the_yaml_and_a_bad_one_is_ignored():
    agent = load_config().agent("ResearchAgent")
    declared = agent.resolved_reasoning()
    _override("ResearchAgent", reasoning="HIGH")
    assert agent.resolved_reasoning() == "high"
    _override("ResearchAgent", reasoning="extreme")
    assert agent.resolved_reasoning() == declared


def test_the_assembler_builds_with_the_overridden_model_and_default_reasoning(monkeypatch):
    calls = []
    from CoScientist.agents import common

    monkeypatch.setattr(common, "make_llm", lambda *a, **kw: calls.append(("main", a, kw)))
    monkeypatch.setattr(common, "make_coder_llm", lambda *a, **kw: calls.append(("coder", a, kw)))

    system = load_config()
    # TaskExecutorAgent declares no reasoning of its own: it inherits the default.
    executor = system.agent("TaskExecutorAgent")
    assert executor.reasoning is None
    get_settings().agents.default_reasoning = "medium"
    _override("TaskExecutorAgent", model="coder")
    assembler._resolve_model(executor, system)
    kind, _, kwargs = calls[-1]
    assert kind == "coder"
    assert kwargs["reasoning"] == "medium"


def test_apply_keeps_only_valid_differences():
    apply_agent_settings({
        "defaultReasoning": "nonsense",
        "overrides": {
            "MedicalAgent": {"enabled": False},
            "ResearchAgent": {"reasoning": "Low", "model": "  coder "},
            "HypothesesAgent": {"reasoning": "extreme"},
            "Empty": {},
        },
    })
    assert current_agent_settings() == {
        "defaultReasoning": "",
        "overrides": {
            "MedicalAgent": {"enabled": False},
            "ResearchAgent": {"reasoning": "low", "model": "coder"},
        },
    }


def test_the_env_carries_the_whole_map_as_json(monkeypatch):
    monkeypatch.setenv("AGENTS__OVERRIDES", json.dumps({"MedicalAgent": {"enabled": False}}))
    monkeypatch.setenv("AGENTS__DEFAULT_REASONING", "low")
    agents = Settings().agents
    assert agents.default_reasoning == "low"
    # Agent names keep their case: they are keys, not field names.
    assert agents.overrides["MedicalAgent"].enabled is False


def test_the_catalog_shows_declared_values_not_overridden_ones():
    _override("ResearchAgent", enabled=False, reasoning="high")
    entry = next(a for a in agents_catalog()["agents"] if a["name"] == "ResearchAgent")
    assert entry["enabled"] is True
    assert entry["reasoning"] == "medium"
    assert entry["hasModel"] and entry["lock"] is None
    root = next(a for a in agents_catalog()["agents"] if a["root"])
    assert root["lock"] == "root"
