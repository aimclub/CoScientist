"""Durable ADK sessions for the local web runtime.

ADK's in-memory service is useful for tests, but its session catalogue is lost
on every web restart.  This adapter keeps ADK's normal async API and stores a
JSON copy after every event.  Files are per session, so a torn write cannot
hide unrelated sessions and the replacement is atomic.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from google.adk.events.event import Event
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.session import Session

from CoScientist.web.session_store import state_dir

_LOCK = threading.RLock()
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


class DurableSessionService(InMemorySessionService):
    """An InMemorySessionService with an on-disk session backing store."""

    def __init__(self, root: Optional[Path] = None) -> None:
        super().__init__()
        self.root = Path(root or state_dir()) / "adk_sessions"

    def _path(self, app_name: str, user_id: str, session_id: str) -> Path:
        return (
            self.root / _SAFE.sub("_", app_name) / _SAFE.sub("_", user_id)
            / f"{_SAFE.sub('_', session_id)}.json"
        )

    def _load(self, app_name: str, user_id: str, session_id: str) -> Optional[Session]:
        key = self._path(app_name, user_id, session_id)
        try:
            payload = json.loads(key.read_text(encoding="utf-8"))
            session = Session.model_validate(payload)
        except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
            return None
        self.sessions.setdefault(app_name, {}).setdefault(user_id, {})[session_id] = session
        return session

    def _canonical(self, session: Session) -> Session:
        return self.sessions[session.app_name][session.user_id][session.id]

    def _persist(self, session: Session) -> None:
        target = self._path(session.app_name, session.user_id, session.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(session.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, target)

    async def create_session(self, **kwargs: Any) -> Session:
        app_name = kwargs["app_name"]
        user_id = kwargs["user_id"]
        session_id = kwargs.get("session_id")
        if session_id and self._load(app_name, user_id, session_id) is not None:
            # Let ADK raise its normal AlreadyExistsError.
            return await super().create_session(**kwargs)
        session = await super().create_session(**kwargs)
        with _LOCK:
            self._persist(self._canonical(session))
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        if session_id not in self.sessions.get(app_name, {}).get(user_id, {}):
            self._load(app_name, user_id, session_id)
        return await super().get_session(
            app_name=app_name, user_id=user_id, session_id=session_id, config=config
        )

    async def append_event(self, session: Session, event: Event) -> Event:
        if session.id not in self.sessions.get(session.app_name, {}).get(session.user_id, {}):
            self._load(session.app_name, session.user_id, session.id)
        # Do not hold a synchronous lock across ADK's await: a concurrent
        # append in the same event loop would otherwise block the loop itself.
        result = await super().append_event(session=session, event=event)
        with _LOCK:
            self._persist(self._canonical(session))
        return result

    async def replace_session(self, session: Session) -> None:
        """Persist an intentional state/events replacement, e.g. rollback."""
        with _LOCK:
            canonical = self._canonical(session)
            canonical.state = dict(session.state)
            canonical.events = list(session.events)
            canonical.last_update_time = session.last_update_time
            self._persist(canonical)

    async def delete_session(self, **kwargs: Any) -> None:
        await super().delete_session(**kwargs)
        self._path(kwargs["app_name"], kwargs["user_id"], kwargs["session_id"]).unlink(
            missing_ok=True
        )


__all__ = ["DurableSessionService"]
