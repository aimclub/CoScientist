"""A2A public API without importing the assembled agent system eagerly."""

from __future__ import annotations

from typing import Any

__all__ = ["AGENT_PORTS", "AGENT_URLS", "AGENT_CARD_URLS", "make_a2a_app"]


def __getattr__(name: str) -> Any:
    """Load expensive configuration only when a public value is requested.

    ``CoScientist.a2a.serve`` must be importable before the assembly registry is
    built. Eagerly importing ``config`` here makes Python build the registry
    while it is still importing the package, which creates a circular import.
    """
    if name in {"AGENT_PORTS", "AGENT_URLS", "AGENT_CARD_URLS"}:
        from CoScientist.a2a import config

        return getattr(config, name)
    if name == "make_a2a_app":
        from CoScientist.a2a.server import make_a2a_app

        return make_a2a_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
