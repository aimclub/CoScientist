"""Capability-scoped upload of large CoScientist output artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from CoScientist.integrations.codesynapse.models import ArtifactPart

RequestCallable = Callable[..., Awaitable[Any]]


class CodesynapseArtifactClient:
    """Exchange a per-run capability for one presigned upload and finalize it."""

    def __init__(
        self,
        *,
        upload_request_url: str,
        finalize_url: str,
        capability_token: str,
        request: RequestCallable | None = None,
    ) -> None:
        if not upload_request_url or not finalize_url or not capability_token:
            raise ValueError("large artifact delivery requires upload, finalize and capability metadata")
        self._upload_request_url = upload_request_url
        self._finalize_url = finalize_url
        self._capability_token = capability_token
        self._request = request

    async def upload_text(self, *, name: str, filename: str, text: str, mime_type: str) -> ArtifactPart:
        content = text.encode("utf-8")
        checksum_sha256 = hashlib.sha256(content).hexdigest()
        headers = {"Authorization": f"Bearer {self._capability_token}"}
        grant = await self._send(
            "POST",
            self._upload_request_url,
            headers=headers,
            json={"name": name, "filename": filename, "mime_type": mime_type, "size_bytes": len(content)},
        )
        self._ensure_success(grant, "artifact upload grant")
        payload = grant.json()
        upload_url = payload.get("upload_url")
        artifact_id = payload.get("artifact_id")
        if not isinstance(upload_url, str) or not isinstance(artifact_id, str):
            raise ValueError("artifact upload grant must include upload_url and artifact_id")
        uploaded = await self._send("PUT", upload_url, content=content)
        self._ensure_success(uploaded, "presigned artifact upload")
        finalized = await self._send(
            "POST",
            self._finalize_url,
            headers=headers,
            json={
                "artifact_id": artifact_id,
                "checksum_sha256": checksum_sha256,
                "mime_type": mime_type,
                "size_bytes": len(content),
            },
        )
        self._ensure_success(finalized, "artifact finalize")
        return ArtifactPart(
            name=name,
            mime_type=mime_type,
            artifact_id=artifact_id,
            checksum_sha256=checksum_sha256,
        )

    async def _send(self, method: str, url: str, **kwargs: Any):
        if self._request is not None:
            return await self._request(method, url, **kwargs)
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await client.request(method, url, **kwargs)

    @staticmethod
    def _ensure_success(response: Any, operation: str) -> None:
        if not getattr(response, "is_success", False):
            raise RuntimeError(f"{operation} failed with HTTP {getattr(response, 'status_code', 'unknown')}")
