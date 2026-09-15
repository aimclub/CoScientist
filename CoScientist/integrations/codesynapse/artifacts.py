"""Size policy shared by A2A artifacts and Codesynapse trace payloads."""

INLINE_ARTIFACT_LIMIT_BYTES = 512 * 1024
INLINE_TRACE_PAYLOAD_LIMIT_BYTES = 128 * 1024


def payload_delivery_mode(size_bytes: int, *, artifact: bool) -> str:
    """Return ``inline`` or ``reference`` without ever silently truncating data."""

    if size_bytes < 0:
        raise ValueError("size_bytes must be non-negative")
    limit = INLINE_ARTIFACT_LIMIT_BYTES if artifact else INLINE_TRACE_PAYLOAD_LIMIT_BYTES
    return "inline" if size_bytes <= limit else "reference"
