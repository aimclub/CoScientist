"""Experimental adapter for MASDA_Datasets' observed JSON-RPC wire contract.

MASDA advertises A2A 0.3 but currently accepts ``SendMessage`` with the
``A2A-Version: 1.0`` header. Keep that discrepancy isolated here. No generic
ADK/a2a-sdk transport or MASDA-local file path is used for delivery.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Mapping, Optional
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from CoScientist.config import get_settings
from CoScientist.graph.session_scope import (
    GRAPH_SCOPE_SESSION_KEY,
    GRAPH_SCOPE_USER_KEY,
    safe_component,
)
from CoScientist.tools.workspace_sync import _workspace_id

logger = logging.getLogger(__name__)
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class MasdaError(RuntimeError):
    """A MASDA transport, response, or artifact delivery failure."""


@dataclass(frozen=True)
class MasdaResult:
    task_id: str
    record_count: int
    workspace_path: Path
    source_url: Optional[str]

    def as_text(self) -> str:
        lines = [
            "MASDA dataset acquisition completed successfully.",
            f"Records: {self.record_count}.",
            f"Workspace artifact: {self.workspace_path}",
            f"MASDA task id: {self.task_id}",
        ]
        if self.source_url:
            lines.append(f"Source URL: {self.source_url}")
        return "\n".join(lines)


def _http_url(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MasdaError(f"{label} is missing")
    url = value.strip()
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise MasdaError(f"{label} must be an absolute HTTP(S) URL")
    return url


def _request_body(request: str) -> dict[str, Any]:
    if not request.strip():
        raise MasdaError("MASDA delegation request is empty")
    return {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "SendMessage",
        "params": {
            "tenant": "",
            "message": {
                "message_id": str(uuid4()),
                "context_id": "",
                "task_id": "",
                "role": "ROLE_USER",
                "parts": [{"text": request}],
                "metadata": {},
                "extensions": [],
                "reference_task_ids": [],
            },
            "configuration": {
                "accepted_output_modes": ["application/json"],
                "return_immediately": False,
            },
            "metadata": {},
        },
    }


async def _rpc_endpoint(
    client: httpx.AsyncClient, rpc_url: Optional[str], card_url: Optional[str]
) -> str:
    if rpc_url:
        return _http_url(rpc_url, "MASDA RPC URL")
    if not card_url:
        raise MasdaError("MASDA RPC URL or AgentCard URL is required")
    response = await client.get(_http_url(card_url, "MASDA AgentCard URL"))
    response.raise_for_status()
    try:
        card = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise MasdaError("MASDA AgentCard is not valid JSON") from exc
    if not isinstance(card, dict):
        raise MasdaError("MASDA AgentCard must be a JSON object")
    # The card supplies only the RPC endpoint. Its advertised protocolVersion
    # does not match the observed SendMessage wire contract.
    return _http_url(card.get("url"), "MASDA AgentCard RPC URL")


async def _send_message(
    request: str,
    *,
    rpc_url: Optional[str],
    card_url: Optional[str],
    a2a_version: str,
    timeout_s: float,
    client: Optional[httpx.AsyncClient] = None,
) -> Mapping[str, Any]:
    async def send(active: httpx.AsyncClient) -> Mapping[str, Any]:
        try:
            endpoint = await _rpc_endpoint(active, rpc_url, card_url)
            response = await active.post(
                endpoint,
                json=_request_body(request),
                headers={
                    "Content-Type": "application/json",
                    "A2A-Version": a2a_version,
                },
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise MasdaError("MASDA A2A request timed out") from exc
        except httpx.HTTPStatusError as exc:
            raise MasdaError(
                f"MASDA A2A HTTP error: {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise MasdaError(f"MASDA A2A connection error: {exc}") from exc
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise MasdaError("MASDA A2A response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise MasdaError("MASDA A2A response must be a JSON object")
        error = payload.get("error")
        if error is not None:
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise MasdaError(f"MASDA JSON-RPC error: {detail}")
        return payload

    if client is not None:
        return await send(client)
    async with httpx.AsyncClient(timeout=timeout_s) as owned:
        return await send(owned)


def _objects(value: Any):
    """Walk the observed A2A artifact containers without assuming part order."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _harvest(task: Mapping[str, Any]) -> Mapping[str, Any]:
    artifacts = task.get("artifacts")
    if not isinstance(artifacts, list):
        raise MasdaError("MASDA completed task has no artifacts")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if artifact.get("name") != "harvest_result":
            continue
        for value in _objects(artifact):
            if "record_count" in value and "records" in value and "files" in value:
                return value
    raise MasdaError("MASDA completed task has no harvest_result data")


def _safe_csv_filename(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "dataset.csv"
    if not _FILENAME_RE.fullmatch(value) or value in (".", ".."):
        raise MasdaError("MASDA dataset filename is unsafe")
    suffix = Path(value).suffix.lower()
    if suffix and suffix != ".csv":
        raise MasdaError("MASDA dataset filename is not CSV")
    return value if suffix else f"{value}.csv"


def _embedded_csv(task: Mapping[str, Any]) -> tuple[str, bytes]:
    candidates: list[tuple[str, str]] = []
    for value in _objects(task.get("artifacts", [])):
        if "raw" not in value:
            continue
        filename = value.get("filename") or value.get("name") or ""
        media_type = value.get("mediaType") or value.get("mimeType") or ""
        if not (
            isinstance(filename, str) and filename.lower().endswith(".csv")
            or isinstance(media_type, str) and media_type.lower() == "text/csv"
        ):
            continue
        if media_type and str(media_type).lower() != "text/csv":
            raise MasdaError("MASDA dataset artifact has unexpected mediaType")
        candidates.append((filename, value["raw"]))
    if not candidates:
        raise MasdaError("MASDA completed task has no embedded CSV dataset artifact")
    if len(candidates) != 1:
        raise MasdaError("MASDA completed task has multiple embedded CSV candidates")
    filename, raw = candidates[0]
    if not isinstance(raw, str) or not raw:
        raise MasdaError("MASDA embedded CSV is empty")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MasdaError("MASDA embedded CSV has invalid base64") from exc
    if not data.strip():
        raise MasdaError("MASDA embedded CSV is empty")
    return _safe_csv_filename(filename), data


def _record_count(harvest: Mapping[str, Any], data: bytes) -> int:
    raw_count = harvest.get("record_count")
    if (
        isinstance(raw_count, bool)
        or not isinstance(raw_count, (int, float))
        or not math.isfinite(raw_count)
        or raw_count < 1
        or int(raw_count) != raw_count
    ):
        raise MasdaError("MASDA harvest_result has no positive record_count")
    count = int(raw_count)
    try:
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise MasdaError("MASDA embedded dataset is not readable UTF-8 CSV") from exc
    if len(rows) < 2 or not rows[0] or len(rows) - 1 != count:
        raise MasdaError(
            f"MASDA CSV row count does not match harvest_result record_count ({count})"
        )
    return count


def _source_url(harvest: Mapping[str, Any]) -> Optional[str]:
    urls = {
        obj[key]
        for obj in _objects([harvest.get("records"), harvest.get("files")])
        for key in ("url", "source_url")
        if isinstance(obj.get(key), str)
        and urlsplit(obj[key]).scheme in ("http", "https")
    }
    return next(iter(urls)) if len(urls) == 1 else None


def _task(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    result = payload.get("result")
    task = result.get("task") if isinstance(result, dict) else None
    if not isinstance(task, dict):
        raise MasdaError("MASDA A2A response has no result.task")
    status = task.get("status")
    state = status.get("state") if isinstance(status, dict) else None
    if state != "TASK_STATE_COMPLETED":
        detail = ""
        if isinstance(status, dict):
            detail = " ".join(
                obj["text"] for obj in _objects(status.get("message"))
                if isinstance(obj.get("text"), str)
            )
        raise MasdaError(f"MASDA task did not complete: {state or 'missing state'} {detail}".strip())
    return task


def _workspace_path(state: Mapping[str, Any], task_id: str, filename: str) -> Path:
    if not (state.get(GRAPH_SCOPE_USER_KEY) and state.get(GRAPH_SCOPE_SESSION_KEY)):
        raise MasdaError("MASDA cannot resolve the public CoScientist session scope")
    workspace_id = _workspace_id(state)
    if not workspace_id:
        raise MasdaError("MASDA cannot resolve the current CoScientist workspace")
    if not re.fullmatch(r"ws_[A-Za-z0-9_-]{1,64}", str(workspace_id)):
        raise MasdaError("MASDA workspace id is unsafe")
    root = Path(get_settings().code_exec.workspace_root).resolve()
    task_slug = safe_component(task_id)[:48]
    unique = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    return root / workspace_id / "data" / "masda" / f"{task_slug}-{unique}" / filename


async def acquire_dataset(
    request: str,
    *,
    state: Mapping[str, Any],
    rpc_url: Optional[str],
    card_url: Optional[str],
    a2a_version: str = "1.0",
    timeout_s: float = 300.0,
    client: Optional[httpx.AsyncClient] = None,
) -> MasdaResult:
    payload = await _send_message(
        request,
        rpc_url=rpc_url,
        card_url=card_url,
        a2a_version=a2a_version,
        timeout_s=timeout_s,
        client=client,
    )
    task = _task(payload)
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise MasdaError("MASDA completed task has no id")
    harvest = _harvest(task)
    filename, data = _embedded_csv(task)
    count = _record_count(harvest, data)
    path = _workspace_path(state, task_id, filename)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(data)
        temporary.replace(path)
    except OSError as exc:
        raise MasdaError(f"MASDA dataset could not be saved in the workspace: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return MasdaResult(
        task_id=task_id,
        record_count=count,
        workspace_path=path,
        source_url=_source_url(harvest),
    )


def _delegated_request(ctx: InvocationContext) -> str:
    for event in reversed(ctx.session.events):
        if event.author == "user" and event.content and event.content.parts:
            text = "\n".join(part.text for part in event.content.parts if part.text)
            if text.strip():
                return text
    raise MasdaError("MASDA delegation contains no request text")


class MasdaDatasetsAgent(BaseAgent):
    """Deterministic ADK child agent for MASDA's observed SendMessage dialect."""

    rpc_url: Optional[str] = None
    card_url: Optional[str] = None
    a2a_version: str = "1.0"
    timeout_s: float = 300.0

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state_delta: dict[str, Any] = {}
        try:
            from CoScientist.a2a.acquisition import (
                assigned_masda_task_id, build_receipt, record_success,
            )
            coscientist_task_id = assigned_masda_task_id(ctx.session.state)
            result = await acquire_dataset(
                _delegated_request(ctx),
                state=ctx.session.state,
                rpc_url=self.rpc_url,
                card_url=self.card_url,
                a2a_version=self.a2a_version,
                timeout_s=self.timeout_s,
            )
            receipt = build_receipt(
                state=ctx.session.state, server_task_id=result.task_id,
                path=result.workspace_path, record_count=result.record_count,
            )
            state_delta = record_success(
                ctx.session.state, receipt, coscientist_task_id
            )
            text = result.as_text()
        except MasdaError as exc:
            logger.warning("MASDA dataset acquisition failed: %s", exc)
            text = f"MASDA dataset acquisition failed: {exc}. No builtin fallback was used."
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            branch=ctx.branch,
            content=types.Content(role="model", parts=[types.Part.from_text(text=text)]),
            actions=EventActions(state_delta=state_delta),
        )
