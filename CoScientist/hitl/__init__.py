"""Lazy Human-in-the-Loop (HITL) exports."""
from importlib import import_module
from typing import Any

_EXPORTS = {
    "HITLAction": ("CoScientist.hitl.models", "HITLAction"),
    "HITLRequest": ("CoScientist.hitl.models", "HITLRequest"),
    "HITLResponse": ("CoScientist.hitl.models", "HITLResponse"),
    "AbstractHITLHandler": ("CoScientist.hitl.handler", "AbstractHITLHandler"),
    "ConsoleHITLHandler": ("CoScientist.hitl.handler", "ConsoleHITLHandler"),
    "HITLToolset": ("CoScientist.hitl.tool", "HITLToolset"),
    "SessionAgent": ("CoScientist.hitl.session_agent", "SessionAgent"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
