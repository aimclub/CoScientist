"""Redaction that runs before integration data leaves CoScientist memory."""

from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "presigned",
    "secret",
    "signature",
    "token",
)
_REDACTED = "***redacted***"
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[a-zA-Z0-9_-]{16,}\b"),
    re.compile(r"(?i)(x-amz-signature=)[^&\s]+"),
)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact(value: Any) -> Any:
    """Return a deep redacted copy of mappings and lists.

    The integration never stores bearer capabilities or provider credentials,
    even though it otherwise retains project trace data indefinitely.
    """

    if isinstance(value, dict):
        return {
            key: _REDACTED if _is_sensitive_key(key) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        result = value
        for pattern in _SENSITIVE_VALUE_PATTERNS:
            result = pattern.sub(
                lambda match: f"{match.group(1)}{_REDACTED}" if match.lastindex else _REDACTED,
                result,
            )
        return result
    return value
