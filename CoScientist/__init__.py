"""CoScientist package exports.

Keep package import lightweight: module entry points such as
``python -m CoScientist.a2a.serve`` must not build agents before their own
startup code applies A2A environment defaults.
"""
from importlib import import_module
from typing import Any

__version__ = "1.0.0"

_EXPORTS = {
    "CoScientistManager": ("CoScientist.main", "CoScientistManager"),
    "create_manager": ("CoScientist.main", "create_manager"),
    "FedotMASToolset": ("CoScientist.tools", "FedotMASToolset"),
    "orchestrator_agent": ("CoScientist.agents", "orchestrator_agent"),
    "hypotheses_agent": ("CoScientist.agents", "hypotheses_agent"),
    "research_agent": ("CoScientist.agents", "research_agent"),
    "fedot_agent": ("CoScientist.agents", "fedot_agent"),
    "tool_retriever_agent": ("CoScientist.agents", "tool_retriever_agent"),
    "task_execution_agent": ("CoScientist.agents", "task_execution_agent"),
    "tool_websearcher_agent": ("CoScientist.agents", "tool_websearcher_agent"),
    "tool_agent": ("CoScientist.agents", "tool_agent"),
    "RetrievalFinalResult": ("CoScientist.storage", "RetrievalFinalResult"),
    "RetrievalToolResult": ("CoScientist.storage", "RetrievalToolResult"),
    "HITLAction": ("CoScientist.hitl", "HITLAction"),
    "HITLRequest": ("CoScientist.hitl", "HITLRequest"),
    "HITLResponse": ("CoScientist.hitl", "HITLResponse"),
    "AbstractHITLHandler": ("CoScientist.hitl", "AbstractHITLHandler"),
    "ConsoleHITLHandler": ("CoScientist.hitl", "ConsoleHITLHandler"),
    "HITLToolset": ("CoScientist.hitl", "HITLToolset"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
