"""Live ТЗ snapshots for the web ТЗ panel.

TZSpecAgent runs inside an AgentTool, i.e. in a nested Runner with its own
child session — the web session's state does not see the ТЗ until the whole
module returns. So the agent PUSHES a snapshot of the ТЗ after every change
(each section saved, each operator round, each agent fill, the approval),
the same way tool activity and metrics reach the browser.

The web UI registers a sink with ``set_tz_sink``; it is called as
``await sink(session_key, payload)``. With no sink the publishing is inert,
and a failing sink never breaks a run.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from CoScientist.graph.session_scope import SessionKey, session_key

logger = logging.getLogger(__name__)

TZSink = Callable[[SessionKey, dict], Awaitable[None]]

_sink: Optional[TZSink] = None


def set_tz_sink(sink: Optional[TZSink]) -> None:
    """Register (or clear, with ``None``) the observer for ТЗ snapshots."""
    global _sink
    _sink = sink


async def publish_tz(context: Any, payload: dict) -> None:
    """Send one ТЗ snapshot to the tabs watching the context's session."""
    sink = _sink
    if sink is None:
        return
    try:
        key = session_key(context)
    except Exception:  # noqa: BLE001 — context shapes vary across ADK paths
        return
    payload.setdefault("timestamp", datetime.now().isoformat())
    try:
        await sink(key, payload)
    except Exception as exc:  # noqa: BLE001 — an observer must not fail a run
        logger.warning("ТЗ snapshot sink failed: %s", exc)


__all__ = ["publish_tz", "set_tz_sink"]
