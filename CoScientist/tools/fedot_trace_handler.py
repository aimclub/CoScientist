import logging
import time
from typing import Optional

logger = logging.getLogger("CoScientist.web.fedot_trace")

# Keep enough history that a tab opened mid-run still sees what already
# happened, without holding an unbounded log for a long-lived server.
_EVENT_LOG_LIMIT = 500


class FedotTraceHandler:
    """Broadcasts FEDOT.MAS trace events to every connected /fedot-trace tab."""

    def __init__(self):
        self._sockets: list = []
        self._event_log: list[dict] = []
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    async def attach_websocket(self, ws) -> None:
        """Register a (re)connected browser socket and replay recent history,
        so a tab opened mid-run isn't staring at a blank page."""
        if ws not in self._sockets:
            self._sockets.append(ws)
        logger.info("FEDOT trace websocket attached (%d connection(s))", len(self._sockets))
        for payload in self._event_log:
            try:
                await ws.send_json(payload)
            except Exception as exc:  # noqa: BLE001 — replay is best-effort
                logger.warning("FEDOT trace replay to a new connection failed: %s", exc)
                break

    def detach_websocket(self, ws) -> None:
        try:
            self._sockets.remove(ws)
        except ValueError:
            pass
        logger.info("FEDOT trace websocket detached (%d connection(s) left)", len(self._sockets))

    async def mark_run_start(self, run_id: str, task_description: str) -> None:
        self._active = True
        await self.broadcast({
            "type": "fedot_trace_event",
            "event": "run_start",
            "run_id": run_id,
            "task_description": task_description,
        })

    async def mark_run_end(self, run_id: str, status: str, error: Optional[str] = None) -> None:
        self._active = False
        payload = {
            "type": "fedot_trace_event",
            "event": "run_end",
            "run_id": run_id,
            "status": status,
        }
        if error:
            payload["error"] = error
        await self.broadcast(payload)

    async def broadcast(self, payload: dict) -> int:
        """Log + send to every connected tab, pruning dead sockets."""
        payload.setdefault("timestamp", time.time())
        self._event_log.append(payload)
        if len(self._event_log) > _EVENT_LOG_LIMIT:
            del self._event_log[: len(self._event_log) - _EVENT_LOG_LIMIT]

        delivered = 0
        for ws in list(self._sockets):
            try:
                await ws.send_json(payload)
                delivered += 1
            except Exception as exc:  # noqa: BLE001 — prune and continue
                logger.warning("FEDOT trace delivery to a socket failed (%s) — pruning", exc)
                self.detach_websocket(ws)
        return delivered


# Module-level singleton — one FEDOT.MAS trace stream per server process,
# same lifetime convention as _web_hitl_handler in CoScientist/web/app.py.
fedot_trace_handler = FedotTraceHandler()
