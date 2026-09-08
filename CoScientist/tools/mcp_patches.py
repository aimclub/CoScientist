"""Backport of modelcontextprotocol/python-sdk PR #2005 (merged upstream, not
yet in the installed mcp 1.28.0 release).

Problem: when a remote MCP server emits a truncated/invalid SSE frame (observed
with the hosted Tavily server on large search results — the JSON-RPC payload is
cut mid-string), the stock client logs "Error parsing SSE message" and sends a
bare Exception into the read stream. That never resolves the pending request,
so the tool call hangs until the read timeout and the whole agent turn is lost.

This patch makes the failure fast and visible instead: the pending request is
answered with a JSON-RPC error carrying the original request id, so the agent
immediately gets a tool error it can react to (e.g. retry the search with a
narrower query).

The patch is version-gated: it applies only while the installed mcp lacks the
upstream fix. Remove this module once the pinned mcp version ships PR #2005
(check that _handle_sse_event answers parse failures with a JSONRPCError).
"""
from __future__ import annotations

import logging
from importlib.metadata import version as _pkg_version

from mcp.client import streamable_http as _sh
from mcp.shared.message import SessionMessage
from mcp.types import ErrorData, JSONRPCError, JSONRPCMessage

logger = logging.getLogger(__name__)

# JSON-RPC "Parse error" — the payload was not valid JSON.
_PARSE_ERROR_CODE = -32700

# Last mcp version known to ship WITHOUT the upstream fix. Bump after verifying
# a newer release still lacks it; drop this module once the fix is released.
_LAST_BROKEN_VERSION = (1, 28)


class _InvalidSSEPayload(Exception):
    """A 'message' SSE event whose data is not a valid JSON-RPC message."""


def _mcp_is_broken() -> bool:
    try:
        parts = _pkg_version("mcp").split(".")
        return (int(parts[0]), int(parts[1])) <= _LAST_BROKEN_VERSION
    except Exception:  # noqa: BLE001 — when in doubt, keep the safety net
        return True


_orig_handle_sse_event = _sh.StreamableHTTPTransport._handle_sse_event
_orig_handle_sse_response = _sh.StreamableHTTPTransport._handle_sse_response


async def _patched_handle_sse_event(self, sse, read_stream_writer, **kwargs):
    if sse.event == "message" and sse.data:
        try:
            JSONRPCMessage.model_validate_json(sse.data)
        except Exception as exc:
            # Do NOT let the stock handler send a bare Exception (it would
            # strand the pending request). Raise so the response handler can
            # fail the request properly.
            raise _InvalidSSEPayload(
                f"server sent invalid JSON-RPC over SSE: {exc}"
            ) from exc
    return await _orig_handle_sse_event(self, sse, read_stream_writer, **kwargs)


async def _fail_pending_request(ctx, reason: str) -> None:
    """Answer the in-flight request with a JSON-RPC error (unblocks the caller)."""
    request_id = getattr(ctx.session_message.message.root, "id", None)
    if request_id is None:  # a notification — nothing is waiting on it
        return
    error = JSONRPCError(
        jsonrpc="2.0",
        id=request_id,
        error=ErrorData(code=_PARSE_ERROR_CODE, message=reason),
    )
    await ctx.read_stream_writer.send(SessionMessage(JSONRPCMessage(error)))


# Vendored from mcp 1.27.2 StreamableHTTPTransport._handle_sse_response. The
# stock body swallows every exception ("SSE stream ended"), which would also
# swallow _InvalidSSEPayload — so the body is replicated with one extra except
# branch that fails the pending request instead of stranding it.
async def _patched_handle_sse_response(self, response, ctx, is_initialization=False):
    last_event_id = None
    retry_interval_ms = None

    try:
        event_source = _sh.EventSource(response)
        async for sse in event_source.aiter_sse():
            if sse.id:
                last_event_id = sse.id
            if sse.retry is not None:
                retry_interval_ms = sse.retry

            is_complete = await self._handle_sse_event(
                sse,
                ctx.read_stream_writer,
                resumption_callback=(
                    ctx.metadata.on_resumption_token_update if ctx.metadata else None
                ),
                is_initialization=is_initialization,
            )
            if is_complete:
                await response.aclose()
                return
    except _InvalidSSEPayload as exc:
        logger.error("MCP SSE payload invalid; failing request fast: %s", exc)
        await _fail_pending_request(ctx, str(exc))
        await response.aclose()
        return
    except Exception as e:  # noqa: BLE001 — mirror upstream behavior
        logger.debug(f"SSE stream ended: {e}")

    # Stream ended without response - reconnect if we received an event with ID
    if last_event_id is not None:
        logger.info("SSE stream disconnected, reconnecting...")
        await self._handle_reconnection(ctx, last_event_id, retry_interval_ms)


async def _patched_handle_resumption_request(self, ctx):
    try:
        return await _orig_handle_resumption_request(self, ctx)
    except _InvalidSSEPayload as exc:
        logger.error("MCP SSE payload invalid on resumption; failing request: %s", exc)
        await _fail_pending_request(ctx, str(exc))


_orig_handle_resumption_request = _sh.StreamableHTTPTransport._handle_resumption_request

_applied = False


def apply() -> None:
    """Install the backport (idempotent; no-op on fixed mcp versions)."""
    global _applied
    if _applied or not _mcp_is_broken():
        return
    _sh.StreamableHTTPTransport._handle_sse_event = _patched_handle_sse_event
    _sh.StreamableHTTPTransport._handle_sse_response = _patched_handle_sse_response
    _sh.StreamableHTTPTransport._handle_resumption_request = (
        _patched_handle_resumption_request
    )
    _applied = True
    logger.info("Applied MCP SSE error-propagation backport (python-sdk PR #2005)")


apply()
