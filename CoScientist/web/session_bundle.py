"""Session bundle — export and import complete session state as a ZIP archive.

A session bundle (``*.cossession.zip``) captures every in-memory and on-disk
layer that constitutes a CoScientist session so it can be:

* **saved** to disk and **restored** after a process restart;
* **downloaded** and **shared** with another person who imports it.

Bundle contents
~~~~~~~~~~~~~~~
::

    manifest.json                   — format version, export timestamp, original IDs, title
    adk_session.json                — ADK Session (state + events) via pydantic model_dump
    agent_events.json               — WebRuntime.agent_events log (chat + tool activity)
    metrics.json                    — WebRuntime.metrics (cost snapshot)
    dataset_url.json                — attached dataset URL
    report_language.json            — report language chosen for the session
    settings_snapshot.json          — settings at export time (read-only, informational)
    graphs/execution.json           — execution graph snapshot
    graphs/research_active.json     — research graph snapshot
    knowledge_memory_snapshot.json  — global memory snapshot (read-only, informational)
"""

from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from CoScientist.agents.callbacks.report_language import REPORT_LANGUAGES

logger = logging.getLogger("CoScientist.web.session_bundle")

BUNDLE_VERSION = 1
BUNDLE_EXTENSION = ".cossession.zip"

# Keys inside the ZIP
_MANIFEST = "manifest.json"
_ADK_SESSION = "adk_session.json"
_AGENT_EVENTS = "agent_events.json"
_METRICS = "metrics.json"
_DATASET_URL = "dataset_url.json"
_REPORT_LANGUAGE = "report_language.json"
_SETTINGS = "settings_snapshot.json"
_GRAPH_EXECUTION = "graphs/execution.json"
_GRAPH_RESEARCH = "graphs/research_active.json"
_KNOWLEDGE_MEMORY = "knowledge_memory_snapshot.json"


def _json_bytes(obj: Any) -> bytes:
    """Serialize *obj* to compact UTF-8 JSON bytes.

    Uses ``default=str`` so non-serializable leaves (pydantic models, enums,
    datetimes …) degrade to strings rather than blowing up the whole export.
    """
    return json.dumps(
        obj,
        ensure_ascii=False,
        default=str,
        indent=2,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

async def export_session(
    runtime: Any,          # WebRuntime
    key: tuple[str, str],  # (user_id, session_id)
) -> bytes:
    """Collect every layer of a session and pack them into a ZIP archive.

    Returns the raw ZIP bytes (ready for streaming / writing to disk).
    """
    from CoScientist.web.app import APP_NAME

    user_id, session_id = key

    # 1. Registry metadata
    session_meta = runtime.registry.get_session(user_id, session_id) or {}
    user_meta = runtime.registry.get_user(user_id) or {}
    title = session_meta.get("title", "session")

    # 2. ADK session (pydantic → dict)
    adk_session_data: Optional[Dict[str, Any]] = None
    try:
        adk_session = await runtime.session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if adk_session is not None:
            adk_session_data = adk_session.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not serialize ADK session: %s", exc)

    # 3. Agent events log
    agent_events = list(runtime.agent_events.get(key, []))

    # 4. Metrics
    metrics = runtime.metrics.get(key)

    # 5. Dataset URL
    dataset_url = runtime.dataset_urls.get(key, "")
    report_language = runtime.report_languages.get(key, "")

    # 6. Settings snapshot
    settings_snapshot: Dict[str, Any] = {}
    try:
        from CoScientist.web.app import _settings_payload
        settings_snapshot = _settings_payload()
    except Exception:  # noqa: BLE001
        pass

    # 7. Execution graph
    execution_graph: Optional[Dict[str, Any]] = None
    try:
        from CoScientist.graph.memory import get_knowledge_graph
        kg = get_knowledge_graph(user_id=user_id, session_id=session_id)
        execution_graph = kg.full()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read execution graph: %s", exc)

    # 8. Research graph
    research_graph: Optional[Dict[str, Any]] = None
    try:
        from CoScientist.graph.research.store import get_research_graph
        rg = get_research_graph(user_id=user_id, session_id=session_id)
        research_graph = rg.full()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read research graph: %s", exc)

    # 9. Knowledge memory snapshot (global, read-only)
    knowledge_memory: Optional[Dict[str, Any]] = None
    try:
        from CoScientist.graph.memory_store import get_global_knowledge_memory
        km = get_global_knowledge_memory()
        knowledge_memory = km.full()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read knowledge memory: %s", exc)

    # --- Build manifest ---
    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "original_user_id": user_id,
        "original_session_id": session_id,
        "original_nickname": user_meta.get("nickname", ""),
        "title": title,
        "session_meta": session_meta,
    }

    # --- Pack ZIP ---
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_MANIFEST, _json_bytes(manifest))
        if adk_session_data is not None:
            zf.writestr(_ADK_SESSION, _json_bytes(adk_session_data))
        zf.writestr(_AGENT_EVENTS, _json_bytes(agent_events))
        if metrics is not None:
            zf.writestr(_METRICS, _json_bytes(metrics))
        zf.writestr(_DATASET_URL, _json_bytes({"dataset_url": dataset_url}))
        # No BUNDLE_VERSION bump: an older bundle without this member reads
        # back as {}, and older code ignores a zip entry it does not know.
        zf.writestr(_REPORT_LANGUAGE, _json_bytes({"report_language": report_language}))
        zf.writestr(_SETTINGS, _json_bytes(settings_snapshot))
        if execution_graph is not None:
            zf.writestr(_GRAPH_EXECUTION, _json_bytes(execution_graph))
        if research_graph is not None:
            zf.writestr(_GRAPH_RESEARCH, _json_bytes(research_graph))
        if knowledge_memory is not None:
            zf.writestr(_KNOWLEDGE_MEMORY, _json_bytes(knowledge_memory))

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

async def import_session(
    runtime: Any,           # WebRuntime
    target_user_id: str,    # user to assign the session to
    bundle_bytes: bytes,
) -> Dict[str, Any]:
    """Unpack a session bundle and restore it into the running process.

    Creates a *new* session (new session_id) under ``target_user_id``.
    Returns ``{"user": {...}, "session": {...}}`` on success.
    """
    from CoScientist.web.app import APP_NAME
    from CoScientist.graph.session_scope import (
        GRAPH_SCOPE_SESSION_KEY,
        GRAPH_SCOPE_USER_KEY,
    )

    # --- Unpack ---
    try:
        zf = zipfile.ZipFile(io.BytesIO(bundle_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid bundle file: {exc}") from exc

    def _read_json(name: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(zf.read(name))
        except (KeyError, json.JSONDecodeError):
            return None

    manifest = _read_json(_MANIFEST)
    if manifest is None:
        raise ValueError("Bundle has no manifest.json — not a valid session bundle.")
    if manifest.get("bundle_version", 0) > BUNDLE_VERSION:
        raise ValueError(
            f"Bundle version {manifest.get('bundle_version')} is newer than "
            f"supported ({BUNDLE_VERSION}). Please update CoScientist."
        )

    adk_session_data = _read_json(_ADK_SESSION)
    agent_events = _read_json(_AGENT_EVENTS) or []
    metrics = _read_json(_METRICS)
    dataset_url_data = _read_json(_DATASET_URL) or {}
    report_language_data = _read_json(_REPORT_LANGUAGE) or {}
    research_graph_data = _read_json(_GRAPH_RESEARCH)
    execution_graph_data = _read_json(_GRAPH_EXECUTION)

    title = manifest.get("title", "Imported session")
    session_id = f"session_{uuid4().hex}"

    # --- Ensure user exists in registry ---
    user = runtime.registry.ensure_user(target_user_id)
    user_id = user["id"]

    # --- Create ADK session ---
    initial_state: Dict[str, Any] = {
        "active_tasks": [],
        GRAPH_SCOPE_USER_KEY: user_id,
        GRAPH_SCOPE_SESSION_KEY: session_id,
    }
    # Merge saved state (active_tasks, report_config, …)
    if adk_session_data and isinstance(adk_session_data.get("state"), dict):
        saved_state = dict(adk_session_data["state"])
        # Override scope keys to match the new user/session
        saved_state[GRAPH_SCOPE_USER_KEY] = user_id
        saved_state[GRAPH_SCOPE_SESSION_KEY] = session_id
        initial_state.update(saved_state)

    adk_session = await runtime.session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )

    # Replay events into the ADK session so the model sees conversation history
    if adk_session_data and isinstance(adk_session_data.get("events"), list):
        from google.adk.events.event import Event as ADKEvent
        for raw_event in adk_session_data["events"]:
            try:
                event = ADKEvent.model_validate(raw_event)
                await runtime.session_service.append_event(adk_session, event)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Skipping unrestorable event: %s", exc)

    # --- Create registry session ---
    session_meta_data = manifest.get("session_meta", {})
    session = runtime.registry.import_session(
        user_id=user_id,
        session_id=session_id,
        title=title,
        created_at=session_meta_data.get("created_at"),
        updated_at=session_meta_data.get("updated_at"),
    )

    key = (user_id, session_id)

    # --- Restore agent events ---
    if isinstance(agent_events, list) and agent_events:
        runtime.agent_events[key] = agent_events

    # --- Restore metrics ---
    if metrics is not None:
        runtime.metrics[key] = metrics

    # --- Restore dataset URL ---
    dataset_url = dataset_url_data.get("dataset_url", "")
    if dataset_url:
        runtime.dataset_urls[key] = dataset_url
    report_language = report_language_data.get("report_language", "")
    # A bundle is a file the user can edit, so it does not get to bypass the
    # enum the socket enforces. An unknown value leaves the session with no
    # choice, and the callback normalizer supplies the default.
    if report_language in REPORT_LANGUAGES:
        runtime.report_languages[key] = report_language
    elif report_language:
        logger.warning(
            "Session bundle carries an unknown report language %r. Ignored.",
            report_language,
        )

    # --- Restore graphs ---
    _restore_graph_files(user_id, session_id, execution_graph_data, research_graph_data)

    zf.close()

    return {"user": user, "session": session}


def _restore_graph_files(
    user_id: str,
    session_id: str,
    execution_data: Optional[Dict[str, Any]],
    research_data: Optional[Dict[str, Any]],
) -> None:
    """Write graph snapshots to the on-disk location the stores expect."""
    from CoScientist.graph.session_scope import storage_dir

    graph_dir = os.getenv("GRAPH_SNAPSHOT_DIR", "./graph_runs")
    session_dir = storage_dir(graph_dir, (user_id, session_id))
    session_dir.mkdir(parents=True, exist_ok=True)

    if execution_data is not None:
        _write_json(session_dir / "execution.json", execution_data)
    if research_data is not None:
        from CoScientist.graph.research.store import _default_file
        _write_json(session_dir / _default_file(), research_data)


def _write_json(path: Path, data: Any) -> None:
    """Atomic JSON write."""
    tmp = path.with_suffix(".json.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Saved-sessions management (on-disk snapshots)
# ---------------------------------------------------------------------------

def _snapshots_dir() -> Path:
    """Directory where manually saved sessions live."""
    try:
        from CoScientist.config import get_settings
        return Path(get_settings().web.session_snapshots_dir)
    except Exception:  # noqa: BLE001
        return Path("session_snapshots")


def save_to_disk(bundle_bytes: bytes, title: str, user_id: str, session_id: str) -> str:
    """Write a bundle to the snapshots directory. Returns the filename."""
    directory = _snapshots_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:60].strip()
    filename = f"{safe_title}_{stamp}{BUNDLE_EXTENSION}"
    (directory / filename).write_bytes(bundle_bytes)
    return filename


def list_saved_sessions() -> list[Dict[str, Any]]:
    """Scan the snapshots directory and read each bundle's manifest."""
    directory = _snapshots_dir()
    if not directory.is_dir():
        return []
    result = []
    for path in sorted(directory.glob(f"*{BUNDLE_EXTENSION}"), reverse=True):
        try:
            with zipfile.ZipFile(path, "r") as zf:
                manifest = json.loads(zf.read(_MANIFEST))
            result.append({
                "filename": path.name,
                "title": manifest.get("title", path.stem),
                "exported_at": manifest.get("exported_at", ""),
                "original_nickname": manifest.get("original_nickname", ""),
                "size_bytes": path.stat().st_size,
            })
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping unreadable snapshot %s: %s", path.name, exc)
    return result


def read_saved_bundle(filename: str) -> bytes:
    """Read a saved bundle by filename (no path traversal)."""
    safe = Path(filename).name
    path = _snapshots_dir() / safe
    if not path.is_file():
        raise FileNotFoundError(f"No saved session '{safe}'.")
    return path.read_bytes()


def delete_saved_session(filename: str) -> bool:
    """Delete a saved bundle by filename."""
    safe = Path(filename).name
    path = _snapshots_dir() / safe
    if path.is_file():
        path.unlink()
        return True
    return False
