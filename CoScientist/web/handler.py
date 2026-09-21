"""Session-aware Human-in-the-Loop handler for the local Web UI."""

import asyncio
import logging
import time
import uuid
from datetime import datetime

from CoScientist.hitl.handler import AbstractHITLHandler
from CoScientist.hitl.models import HITLAction, HITLRequest, HITLResponse

logger = logging.getLogger("CoScientist.web.hitl")
SessionKey = tuple[str, str]


def hitl_response_event(request_id: str, response_data: dict) -> dict:
    """The operator's answer to one HITL card, as a transcript entry."""
    return {
        "type": "hitl_response",
        "request_id": request_id,
        "action": response_data.get("action"),
        "approved": response_data.get("approved"),
        "selected_option": response_data.get("selected_option"),
        "instructions": response_data.get("instructions"),
        "free_input": response_data.get("free_input"),
        "form_values": response_data.get("form_values"),
        "timestamp": datetime.now().isoformat(),
    }


class WebHITLHandler(AbstractHITLHandler):
    """Route HITL requests only to tabs displaying the owning session."""

    def __init__(self):
        # request_id -> future/payload/session metadata
        self._pending: dict[str, dict] = {}
        # (user_id, session_id) -> connected browser sockets. ``None`` is kept
        # solely for backwards-compatible callers that have no session context.
        self._sockets: dict[SessionKey | None, list] = {}
        self._event_log: list[dict] = []
        self._sender = None
        # Writes HITL cards and their answers into the session transcript, so a
        # reload, an export or an import still shows decisions already taken.
        self._recorder = None
        # Optional durable checkpoint hook.  It is called before every HITL
        # wait, including callback/tool HITLs that never produce an ADK
        # RequestInput interrupt.
        self._checkpoint = None

    @property
    def hitl_timeout_seconds(self) -> float:
        if hasattr(self, "_hitl_timeout_seconds"):
            return self._hitl_timeout_seconds
        try:
            from CoScientist.config import get_settings
            return get_settings().web.hitl_auto_approve_timeout
        except Exception:
            return 300

    @hitl_timeout_seconds.setter
    def hitl_timeout_seconds(self, value: float) -> None:
        self._hitl_timeout_seconds = float(value)

    @property
    def HITL_TIMEOUT_SECONDS(self) -> int:
        return self.hitl_timeout_seconds

    def __deepcopy__(self, memo):
        return self

    @property
    def _websocket(self):
        """Backwards-compatible access to the most recently attached socket."""
        sockets = [socket for group in self._sockets.values() for socket in group]
        return sockets[-1] if sockets else None

    def set_websocket(self, ws):
        """Legacy setter: register one unscoped socket, or clear all sockets."""
        self._sockets = {} if ws is None else {None: [ws]}

    def set_sender(self, sender) -> None:
        """Use the Web runtime's serialized socket writer when available."""
        self._sender = sender

    def set_recorder(self, recorder) -> None:
        """Persist HITL events through ``recorder(session_key, event)``."""
        self._recorder = recorder

    def set_checkpoint_sink(self, checkpoint) -> None:
        """Persist a resumable boundary before a human decision is awaited."""
        self._checkpoint = checkpoint

    def _record(self, session_key: SessionKey | None, event: dict) -> None:
        if self._recorder is None or session_key is None:
            return
        try:
            # A copy: a hold later mutates the live payload for redelivery.
            self._recorder(session_key, dict(event))
        except Exception as exc:  # noqa: BLE001 — persistence must never break a run
            logger.warning("HITL event could not be recorded: %s", exc)

    async def _send_json(self, ws, payload: dict, session_key) -> None:
        if self._sender is not None:
            await self._sender(ws, payload, session_key)
        else:
            await ws.send_json(payload)

    def connection_count(self) -> int:
        return sum(len(group) for group in self._sockets.values())

    def has_connections(self, session_key: SessionKey | None = None) -> bool:
        if session_key is None:
            return self.connection_count() > 0
        return bool(self._sockets.get(session_key))

    async def attach_websocket(
        self,
        ws,
        session_key: SessionKey | None = None,
    ) -> None:
        """Attach a tab and redeliver its unresolved session requests."""
        sockets = self._sockets.setdefault(session_key, [])
        if ws not in sockets:
            sockets.append(ws)
        logger.info("HITL websocket attached (%d connection(s))", self.connection_count())

        for request_id, entry in list(self._pending.items()):
            future = entry.get("future")
            if future is None or future.done():
                self._pending.pop(request_id, None)
                continue
            if entry.get("session_key") not in (None, session_key):
                continue
            try:
                await self._send_json(ws, entry["payload"], session_key)
                logger.info("HITL request %s redelivered", request_id[:8])
            except Exception as exc:  # noqa: BLE001
                logger.warning("HITL redelivery of %s failed: %s", request_id[:8], exc)

    def detach_websocket(
        self,
        ws,
        session_key: SessionKey | None = None,
    ) -> None:
        sockets = self._sockets.get(session_key, [])
        try:
            sockets.remove(ws)
        except ValueError:
            pass
        if not sockets:
            self._sockets.pop(session_key, None)
        logger.info("HITL websocket detached (%d connection(s) left)", self.connection_count())

    async def _broadcast(
        self,
        payload: dict,
        session_key: SessionKey | None,
    ) -> int:
        """Send a request to one session, or all tabs for legacy unscoped calls."""
        if session_key is None:
            targets = [socket for group in self._sockets.values() for socket in group]
        else:
            targets = list(self._sockets.get(session_key, []))

        delivered = 0
        for ws in targets:
            try:
                await self._send_json(ws, payload, session_key)
                delivered += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("HITL delivery failed (%s); pruning socket", exc)
                for key, sockets in list(self._sockets.items()):
                    if ws in sockets:
                        self.detach_websocket(ws, key)
        return delivered

    def pending_summary(self) -> list[dict]:
        now = time.time()
        return [
            {
                "request_id": request_id[:8],
                "agent_name": entry["payload"].get("agent_name"),
                "session_key": entry.get("session_key"),
                "age_seconds": round(now - entry["created"], 1),
            }
            for request_id, entry in self._pending.items()
        ]

    @staticmethod
    def _request_session_key(request: HITLRequest) -> SessionKey | None:
        session = (request.context or {}).get("_session")
        if not isinstance(session, dict):
            return None
        user_id = session.get("user_id")
        session_id = session.get("session_id")
        if not user_id or not session_id:
            return None
        return str(user_id), str(session_id)

    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        request_id = str(uuid.uuid4())
        session_key = self._request_session_key(request)
        public_context = dict(request.context or {})
        public_context.pop("_session", None)

        # A request may bring its own window (a Work Order veto window);
        # otherwise the operator's global auto-approve timeout applies.
        timeout_sec = (
            float(request.timeout_seconds)
            if request.timeout_seconds is not None
            else self.hitl_timeout_seconds
        )
        payload = {
            "type": "hitl_request",
            "request_id": request_id,
            "agent_name": request.agent_name,
            "action_type": request.action_type.value,
            "message": request.message,
            "options": request.options,
            "context": public_context,
            "form": request.form,
            "invoked_via": request.invoked_via,
            "trigger": request.trigger,
            "timeout_seconds": timeout_sec,
            "timestamp": datetime.now().isoformat(),
        }
        self._record(session_key, payload)
        if self._checkpoint is not None and session_key is not None:
            try:
                await self._checkpoint(session_key, payload)
            except Exception as exc:  # noqa: BLE001 - checkpointing is observer-only
                logger.warning("HITL checkpoint could not be created: %s", exc)

        log_payload = dict(payload)
        log_payload["_session_key"] = session_key
        self._event_log.append(log_payload)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        entry = {
            "future": future,
            "payload": payload,
            "created": time.time(),
            "session_key": session_key,
            # Auto-approve moment (loop time); None waits for the human. A hold
            # from the browser clears it mid-wait (see hold_request).
            "deadline": loop.time() + timeout_sec if timeout_sec > 0 else None,
        }
        self._pending[request_id] = entry

        delivered = await self._broadcast(payload, session_key)
        if delivered:
            logger.info("HITL request %s sent to %d tab(s)", request_id[:8], delivered)
        else:
            if timeout_sec > 0:
                logger.warning(
                    "HITL request %s has no live tab; waiting %ss for reconnect",
                    request_id[:8],
                    timeout_sec,
                )
            else:
                logger.warning(
                    "HITL request %s has no live tab; waiting indefinitely for reconnect",
                    request_id[:8],
                )

        try:
            response_data = await self._await_response(entry)
        except asyncio.TimeoutError:
            response_data = {"action": "approve", "approved": True}
            timeout_event = {
                "type": "hitl_timeout",
                "request_id": request_id,
                "agent_name": request.agent_name,
                "timeout_seconds": timeout_sec,
                "timestamp": datetime.now().isoformat(),
            }
            self._record(session_key, timeout_event)
            await self._broadcast(timeout_event, session_key)
        except asyncio.CancelledError:
            cancelled_event = {
                "type": "hitl_cancelled",
                "request_id": request_id,
                "agent_name": request.agent_name,
                "timestamp": datetime.now().isoformat(),
            }
            self._record(session_key, cancelled_event)
            await self._broadcast(cancelled_event, session_key)
            raise
        finally:
            # ``shield`` deliberately keeps the response future alive when the
            # caller is cancelled. Remove and cancel it explicitly so a stopped
            # run cannot be redelivered as a stale request on reconnect.
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()

        action = HITLAction(response_data.get("action", "approve"))
        return HITLResponse(
            action=action,
            approved=response_data.get("approved", False),
            selected_option=response_data.get("selected_option"),
            instructions=response_data.get("instructions"),
            free_input=response_data.get("free_input"),
            form_values=response_data.get("form_values"),
        )

    @staticmethod
    async def _await_response(entry: dict) -> dict:
        """Wait for the human's answer until the entry's (movable) deadline.

        ``asyncio.wait`` never cancels the future it watches, so — like the
        ``shield`` it replaces — a cancelled caller leaves the response future
        to the ``finally`` in ``handle_request``. The deadline is re-read on
        every wake-up: a hold clears it while we sleep, and the next wake-up
        then waits for the human with no limit.
        """
        future = entry["future"]
        loop = asyncio.get_running_loop()
        while True:
            deadline = entry.get("deadline")
            if deadline is None:
                return await asyncio.shield(future)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            await asyncio.wait({future}, timeout=remaining)
            if future.done():
                return future.result()

    async def hold_request(
        self,
        request_id: str,
        session_key: SessionKey | None = None,
    ) -> bool:
        """Stop a request's auto-approve countdown ("Pause" on a veto window)."""
        entry = self._pending.get(request_id)
        if not entry or entry["future"].done():
            return False
        if session_key is not None and entry.get("session_key") not in (None, session_key):
            logger.warning("Ignoring HITL hold %s from wrong session", request_id[:8])
            return False
        entry["deadline"] = None
        # A tab that reconnects must not restart a countdown that was paused.
        entry["payload"]["timeout_seconds"] = 0
        entry["payload"]["held"] = True
        await self._broadcast(
            {"type": "hitl_hold", "request_id": request_id},
            entry.get("session_key"),
        )
        logger.info("HITL request %s put on hold", request_id[:8])
        return True

    async def notify(self, payload: dict) -> None:
        """Deliver a non-blocking Work Order notice to the owning session."""
        body = dict(payload)
        session = body.pop("_session", None)
        session_key = None
        if isinstance(session, dict) and session.get("user_id") and session.get("session_id"):
            session_key = (str(session["user_id"]), str(session["session_id"]))
        message = {"type": "work_order_notice", "timestamp": time.time(), **body}
        self._record(session_key, message)
        log_payload = dict(message)
        log_payload["_session_key"] = session_key
        self._event_log.append(log_payload)
        await self._broadcast(message, session_key)

    def resolve_request(
        self,
        request_id: str,
        response_data: dict,
        session_key: SessionKey | None = None,
    ) -> bool:
        """Resolve a request, rejecting responses from a different session."""
        entry = self._pending.get(request_id)
        if entry and session_key is not None and entry.get("session_key") not in (None, session_key):
            logger.warning("Ignoring HITL response %s from wrong session", request_id[:8])
            return False
        entry = self._pending.pop(request_id, None)
        if entry and not entry["future"].done():
            entry["future"].set_result(response_data)
            self._record(entry.get("session_key"), hitl_response_event(request_id, response_data))
            return True
        return False

    def reset(self, session_key: SessionKey | None = None) -> None:
        """Cancel unresolved requests globally or only for one session."""
        for request_id, entry in list(self._pending.items()):
            if session_key is not None and entry.get("session_key") != session_key:
                continue
            if not entry["future"].done():
                entry["future"].cancel()
            self._pending.pop(request_id, None)
        self.clear_event_log(session_key)

    def get_event_log(self, session_key: SessionKey | None = None) -> list[dict]:
        events = self._event_log
        if session_key is not None:
            events = [event for event in events if event.get("_session_key") == session_key]
        return [
            {key: value for key, value in event.items() if key != "_session_key"}
            for event in events
        ]

    def clear_event_log(self, session_key: SessionKey | None = None) -> None:
        if session_key is None:
            self._event_log.clear()
        else:
            self._event_log = [
                event for event in self._event_log
                if event.get("_session_key") != session_key
            ]
