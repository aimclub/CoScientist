"""Wiring contract for the EconomicsAgent's web-price fallback."""
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_economics_agent_has_websearch_fallback() -> None:
    config = yaml.safe_load(
        (ROOT / "CoScientist" / "agents" / "microfluidics.yaml").read_text()
    )

    assert "websearch" in config["agents"]["EconomicsAgent"]["tools"]
    assert config["agents"]["EconomicsAgent"]["hitl"] is True


def test_optimizer_has_websearch_and_human_recovery() -> None:
    config = yaml.safe_load(
        (ROOT / "CoScientist" / "agents" / "microfluidics.yaml").read_text()
    )
    optimizer = config["agents"]["OptimizerAgent"]

    assert "websearch" in optimizer["tools"]
    assert optimizer["hitl"] is True


def test_optimizer_prompt_documents_economics_ranking_contract() -> None:
    from types import SimpleNamespace

    from CoScientist.agents.prompts.templates import microfluidics_optimizer

    prompt = microfluidics_optimizer(
        SimpleNamespace(render_tools=lambda: "", render_hitl=lambda: "")
    )
    assert '"target_qty"' in prompt
    assert '"cost_per_unit"' in prompt
    assert "qualified_routes.routes" in prompt
