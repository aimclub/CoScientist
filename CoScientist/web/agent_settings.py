"""The Agents section of the web settings: what each agent is, and what the
operator changed about it.

system.yaml stays the declaration; ``settings.agents`` holds the operator's
overrides (on/off, reasoning, model) and the assembler reads them when a
session's agent tree is built. This module is the web side of that: the
catalog the settings modal lists (read off a fresh load of the profile, so it
shows the declared values, not the overridden ones), and the read/write of the
overrides in the ``appSettings`` shape.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from CoScientist.assembly.schema import (
    REASONING_EFFORTS,
    AgentConfig,
    SystemConfig,
    _is_setting_ref,
    load_config,
    normalize_reasoning,
)
from CoScientist.config import get_settings
from CoScientist.config.settings import AgentOverride

_log = logging.getLogger(__name__)

# What the modal offers for reasoning, in order. "" = as declared.
REASONING_CHOICES = ["off", *REASONING_EFFORTS]
MODEL_ALIASES = ("main", "coder", "nir")


def _has_model(cfg: AgentConfig) -> bool:
    """Whether the agent calls a model of its own (so reasoning/model apply)."""
    if cfg.cls == "llm":
        return True
    if not cfg.cls.startswith("custom:"):
        return False
    try:
        from google.adk.agents import LlmAgent

        from CoScientist.assembly.registry import REGISTRY

        return issubclass(REGISTRY.agent_class(cfg.cls.split(":", 1)[1]), LlmAgent)
    except Exception:  # noqa: BLE001 — an unregistered class: say "no model"
        return False


def _flow_order(system: SystemConfig) -> List[str]:
    """Agents in the order a run meets them: pre-stages, the delegation tree
    from the root (depth first), post-stages, then whatever is left over."""
    order: List[str] = []

    def visit(name: str) -> None:
        if name in order or name not in system.agents:
            return
        order.append(name)
        for dep in system.agents[name].subordinates + system.agents[name].children:
            visit(dep)

    for name in system.pipeline.pre:
        visit(name)
    visit(system.root.name)
    for name in system.pipeline.post:
        visit(name)
    for name in system.agents:
        visit(name)
    return order


def _model_names() -> Dict[str, Optional[str]]:
    llm = get_settings().llm
    return {
        "main": llm.main_model,
        "coder": llm.coder_model or llm.main_model,
        "nir": llm.nir_model or llm.main_model,
    }


def _lock_reason(cfg: AgentConfig) -> Optional[str]:
    if cfg.root:
        return "root"
    if cfg.internal:
        return "internal"
    if not cfg.enabled_overridable():
        return "startMode"
    return None


def agents_catalog() -> Dict[str, Any]:
    """Every agent of the active profile, with its declared values.

    Loaded afresh (not the cached get_config()) and read through the
    ``declared_*`` accessors, so a toggle shows what the YAML says and the
    override is shown next to it, never folded into it.
    """
    system = load_config()
    parents: Dict[str, List[str]] = {}
    for cfg in system.agents.values():
        for dep in cfg.subordinates + cfg.children:
            parents.setdefault(dep, []).append(cfg.name)

    agents = []
    for name in _flow_order(system):
        cfg = system.agents[name]
        has_model = _has_model(cfg)
        try:
            declared_enabled = cfg.declared_enabled()
        except Exception:  # noqa: BLE001 — a reference to a missing setting
            declared_enabled = False
        stage = ("pre" if name in system.pipeline.pre
                 else "post" if name in system.pipeline.post else None)
        agents.append({
            "name": name,
            "class": cfg.cls,
            "description": cfg.description or "",
            "root": bool(cfg.root),
            "internal": bool(cfg.internal),
            "stage": stage,
            "parents": parents.get(name, []),
            "subordinates": list(cfg.subordinates) + list(cfg.children),
            "enabled": declared_enabled,
            # The setting that decides `enabled` in the YAML, if any: the
            # modal says the switch overrides it.
            "enabledRef": str(cfg.enabled)[2:-1] if _is_setting_ref(cfg.enabled) else None,
            "lock": _lock_reason(cfg),
            "hasModel": has_model,
            "model": (cfg.model or system.defaults.model) if has_model else None,
            "reasoning": _reasoning_label(cfg.declared_reasoning()) if has_model else None,
            "reasoningRef": str(cfg.reasoning)[2:-1] if _is_setting_ref(cfg.reasoning) else None,
        })
    return {
        "agents": agents,
        "defaults": {
            "model": system.defaults.model,
            "reasoning": _reasoning_label(system.defaults.reasoning),
        },
        "models": _model_names(),
        "reasoningChoices": REASONING_CHOICES,
    }


def _reasoning_label(value: Any) -> Optional[str]:
    """A reasoning value as the modal shows it: "off", an effort, or None."""
    if value is False:
        return "off"
    if value is True:
        return "medium"
    normalized = normalize_reasoning(value)
    if normalized in ("none", "disabled"):
        return "off"
    return normalized


def current_agent_settings() -> Dict[str, Any]:
    """``settings.agents`` in the appSettings shape (camelCase, unset fields dropped)."""
    block = get_settings().agents
    return {
        "defaultReasoning": block.default_reasoning or "",
        "overrides": {
            name: override.model_dump(exclude_none=True)
            for name, override in sorted(block.overrides.items())
            if override.model_dump(exclude_none=True)
        },
    }


def apply_agent_settings(section: Dict[str, Any]) -> None:
    """Write the modal's Agents section into ``settings.agents``.

    Values the ``reasoning:`` vocabulary does not accept are dropped with a
    warning rather than stored, so a bad import cannot reach the assembler.
    Takes effect when the next session's tree is built.
    """
    block = get_settings().agents
    if "defaultReasoning" in section:
        raw = section["defaultReasoning"]
        value = normalize_reasoning(raw) if raw not in (None, "") else None
        if raw not in (None, "") and value is None:
            _log.warning("agents.defaultReasoning=%r is not a reasoning level; ignored", raw)
        block.default_reasoning = value if isinstance(value, str) else None

    if "overrides" in section:
        overrides: Dict[str, AgentOverride] = {}
        for name, raw in (section.get("overrides") or {}).items():
            if not isinstance(raw, dict):
                continue
            enabled = raw.get("enabled")
            reasoning = raw.get("reasoning")
            if reasoning not in (None, ""):
                if normalize_reasoning(reasoning) is None:
                    _log.warning("reasoning %r for %s is not a reasoning level; ignored", reasoning, name)
                    reasoning = None
                else:
                    reasoning = normalize_reasoning(reasoning)
            else:
                reasoning = None
            model = str(raw.get("model") or "").strip() or None
            override = AgentOverride(
                enabled=bool(enabled) if isinstance(enabled, bool) else None,
                reasoning=reasoning,
                model=model,
            )
            if override.model_dump(exclude_none=True):
                overrides[str(name)] = override
        block.overrides = overrides
