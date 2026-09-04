"""Self-contained S3 transfer helpers for the generated server.py.

Copied verbatim into ``output/helpers/s3_transfer.py`` by codegen
(``write_server``) so the served MCP boundary can hand back S3 references
instead of paths that only exist inside the build container. Deliberately
stdlib + a LAZILY imported ``boto3`` — never at module level — because this
module is loaded inside ``.venv-server``, which the wrapper only guarantees
carries fastmcp/mcp (+ boto3 when S3 is configured); importing boto3 eagerly
here would break every server that has no S3 configured.

v1 scoping model: the client passes no headers of its own (``dynamic_tools.py``
is untouched). The server reads ``X-Coscientist-User`` / ``X-Coscientist-
Session`` off the transport when present and falls back to a shared
``("local", "default")`` scope otherwise. This is a namespacing convenience,
NOT a security boundary — a presigned URL grants access to whoever holds it.

Error asymmetry (by design, see README): a failed *input* download
(``resolve_input``/``_download_s3``/``_download_http``) raises and fails the
whole tool call — a tool cannot silently run on the wrong/missing data. A
failed *output* upload (``maybe_upload``) only logs to stderr and returns
``None`` — an otherwise-successful tool call must not be turned into a
failure just because publishing its result to S3 did not work.
"""
from __future__ import annotations

import os
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse

# All four must be set (and non-empty) for S3 handling to switch on at all.
# Each is read via _env(): the bare name first, then the project's
# nested-settings spelling ``S3__<name>`` (pydantic env_nested_delimiter, see
# config/settings.py:S3Settings) — so a .env that already configures S3 for
# the main app needs no duplicate bare-name entries.
S3_ENV = ("ENDPOINT_URL", "ACCESS_KEY", "SECRET_KEY", "BUCKET_NAME")
# Case-insensitive convention a tool param name is checked against to decide
# whether its value may be an input/output file reference.
FILE_SUFFIXES = ("_path", "_file")

_DEFAULT_PRESIGN_EXPIRATION = 3600
_MIN_PRESIGN_EXPIRATION = 1
_MAX_PRESIGN_EXPIRATION = 604800  # 7 days — S3 SigV4's own presign ceiling

_DEFAULT_REGION = "us-east-1"

_DEFAULT_HTTP_TIMEOUT = 300  # seconds
_DEFAULT_HTTP_MAX_BYTES = 1024 * 1024 * 1024  # 1 GiB
_HTTP_CHUNK_SIZE = 1024 * 1024


def _env(name: str) -> str | None:
    """Read an ``S3_ENV`` setting: bare name first, ``S3__<name>`` alias
    second (never merged — the first spelling that is set and non-empty
    wins)."""
    return os.environ.get(name) or os.environ.get(f"S3__{name}")


def s3_enabled() -> bool:
    """True iff every ``S3_ENV`` variable is set and non-empty (under either
    its bare or its ``S3__``-prefixed spelling, per variable)."""
    return all(_env(name) for name in S3_ENV)


def is_file_param(name: str) -> bool:
    """Case-insensitive ``*_path`` / ``*_file`` convention (repos vary on
    casing for their own param names)."""
    return name.lower().endswith(FILE_SUFFIXES)


def safe_component(value: str) -> str:
    """Make an identifier safe for an S3 key component (user/session/repo/
    tool/field name). Mirrors ``graph/session_scope.py:safe_component`` —
    duplicated rather than imported, this module must stay free of any
    CoScientist import. NOT used for a downloaded file's basename — see
    ``_safe_filename`` below, which a non-ASCII name would lose its extension
    to under this stricter ASCII-only cleanup."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return cleaned[:96] or "unknown"


_MAX_FILENAME_STEM = 180
_MAX_FILENAME_SUFFIX = 60


def _safe_filename(raw: str) -> str:
    """Sanitize a downloaded basename for the local filesystem WITHOUT
    mangling it the way ``safe_component()`` would — e.g.
    ``safe_component('данные.csv')`` collapses to ``'csv'`` (the non-ASCII
    stem is replaced then ``.strip("._")`` eats it), silently handing a tool
    that dispatches on suffix (pandas/PIL/torch) the wrong data under a
    misleadingly named path. Only path separators and NUL are touched.
    Traversal is not a concern here: the caller already took ``Path(...).name``
    (stripping any directory components) and writes into a fresh, isolated
    ``_download_dir()``.

    Also bounded to a safe filesystem length: an S3 key can run up to 1024
    bytes, well past the ~255-byte filename limit most filesystems enforce
    (``OSError: [Errno 36] File name too long``) — truncate the stem/suffix
    separately so the extension a tool dispatches on survives."""
    name = re.sub(r"[/\\\x00]", "_", raw)
    if name in ("", ".", ".."):
        return "download"
    stem, suffix = Path(name).stem, Path(name).suffix
    return stem[:_MAX_FILENAME_STEM] + suffix[:_MAX_FILENAME_SUFFIX]


def scope_from_headers(headers: dict | None) -> tuple[str, str]:
    """``(user, session)`` from the ``X-Coscientist-User`` / ``X-Coscientist-
    Session`` headers, read case-insensitively; falls back to
    ``("local", "default")`` when either is missing (no client headers, stdio
    transport, or an old fastmcp with no header access)."""
    if headers:
        lowered = {k.lower(): v for k, v in headers.items()}
        user = lowered.get("x-coscientist-user")
        session = lowered.get("x-coscientist-session")
        if user and session:
            return safe_component(user), safe_component(session)
    return "local", "default"


def call_prefix(scope: tuple[str, str], repo_name: str, tool: str) -> str:
    """S3 key prefix for one tool call:
    ``alembic/<user>/<session>/<repo>/<tool>/<8-hex>``."""
    user, session = scope
    return (
        f"alembic/{safe_component(user)}/{safe_component(session)}/"
        f"{safe_component(repo_name)}/{safe_component(tool)}/{uuid.uuid4().hex[:8]}"
    )


def _client_factory():
    """boto3 S3 client built from ``S3_ENV`` (+ optional ``S3_REGION``). A
    module attribute (not inlined into its callers) so tests can swap it out
    without moto or real credentials — see
    ``paper_parser/s3_connection.py:S3BucketService`` for the pattern this
    mirrors. ``region_name`` is required by botocore even for a fully custom
    ``endpoint_url`` — omitting it raises ``NoRegionError``."""
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=_env("ENDPOINT_URL"),
        aws_access_key_id=_env("ACCESS_KEY"),
        aws_secret_access_key=_env("SECRET_KEY"),
        region_name=os.environ.get("S3_REGION", _DEFAULT_REGION),
        config=Config(signature_version="s3v4"),
    )


def _presign_expiration() -> int:
    try:
        value = int(os.environ.get("S3_PRESIGN_EXPIRATION", _DEFAULT_PRESIGN_EXPIRATION))
    except ValueError:
        return _DEFAULT_PRESIGN_EXPIRATION
    return max(_MIN_PRESIGN_EXPIRATION, min(value, _MAX_PRESIGN_EXPIRATION))


def _http_timeout() -> int:
    try:
        return int(os.environ.get("S3_HTTP_TIMEOUT", _DEFAULT_HTTP_TIMEOUT))
    except ValueError:
        return _DEFAULT_HTTP_TIMEOUT


def _http_max_bytes() -> int:
    try:
        return int(os.environ.get("S3_HTTP_MAX_BYTES", _DEFAULT_HTTP_MAX_BYTES))
    except ValueError:
        return _DEFAULT_HTTP_MAX_BYTES


def _download_dir(scratch_dir: Path) -> Path:
    """A fresh, unique subdirectory of ``scratch_dir`` for ONE download — two
    different keys/URLs that happen to share a basename (``s3://b1/dir1/
    data.csv`` and ``s3://b2/dir2/data.csv``) must never land on the same
    local path and silently overwrite one another."""
    dest = scratch_dir / uuid.uuid4().hex[:8]
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _download_s3(uri: str, scratch_dir: Path) -> str:
    """``s3://bucket/key`` -> local path under its own subdirectory of
    ``scratch_dir``. The bucket comes from the URI itself, not
    ``BUCKET_NAME`` (the caller may reference any bucket the credentials can
    read). Errors propagate (wrapped with the URI so the failure is
    attributable) — a tool must not silently run on missing input."""
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    local_path = _download_dir(scratch_dir) / _safe_filename(Path(key).name)
    try:
        _client_factory().download_file(bucket, key, str(local_path))
    except Exception as exc:
        local_path.unlink(missing_ok=True)
        raise RuntimeError(f"failed to fetch {uri}: {exc}") from exc
    return str(local_path)


def _check_content_length(uri: str, response, max_bytes: int) -> None:
    """Reject an HTTP download up front when the server advertises a size
    over the cap, instead of only catching it mid-stream (still enforced by
    the read loop below for servers that lie about or omit the header).

    ``getattr(response, "headers", None) and response.headers.get(...)`` looks
    equivalent but is not: urllib's ``response.headers`` is an
    ``email.message.Message``, which defines ``__len__`` — a response with
    ZERO headers is a falsy-but-real ``Message``, so ``and`` would short-
    circuit to that Message object itself instead of ``None``, and
    ``int(Message)`` raises ``TypeError`` (uncaught below), turning a
    perfectly valid download into a crash. Get ``headers`` first and check
    ``is not None`` explicitly."""
    headers = getattr(response, "headers", None)
    length = headers.get("Content-Length") if headers is not None else None
    if length is None:
        return
    try:
        advertised = int(length)
    except (TypeError, ValueError):
        return
    if advertised > max_bytes:
        raise ValueError(
            f"download from {uri!r} advertises {advertised} bytes, over the "
            f"{max_bytes}-byte limit (S3_HTTP_MAX_BYTES)")


class _DeadlineExceeded(TimeoutError):
    """Raised internally when the overall ``S3_HTTP_TIMEOUT`` wall-clock
    budget (as opposed to urllib's own per-read socket timeout) is exceeded.
    Kept as its own subclass so it is never double-wrapped: it already
    carries the URI in its message and must propagate as-is, while a bare
    ``socket.timeout``/``TimeoutError`` from urllib itself (a stalled
    connection, not our deadline check) still needs ``{uri}`` added to be
    attributable — it is still a plain ``TimeoutError``, not this subclass,
    so it falls through to the generic wrap below. Still catchable by callers
    as ``TimeoutError`` either way."""


def _download_http(uri: str, scratch_dir: Path) -> str:
    """``http(s)://...`` -> local path under its own subdirectory of
    ``scratch_dir``, no credentials attached (a plain fetch of a public/
    presigned URL). Bounded three ways: an ``S3_HTTP_TIMEOUT``-second socket
    timeout on each connect/read, the SAME budget re-applied as an overall
    wall-clock deadline across the read loop (a peer trickling data one byte
    at a time never trips a per-read timeout but must still not run for
    hours), and an ``S3_HTTP_MAX_BYTES`` cap checked against ``Content-Length``
    up front and against bytes actually received as they arrive. A partially
    written file is removed before the error propagates."""
    local_path = _download_dir(scratch_dir) / _safe_filename(Path(urlparse(uri).path).name)
    timeout = _http_timeout()
    max_bytes = _http_max_bytes()
    deadline = time.monotonic() + timeout
    try:
        with urllib.request.urlopen(uri, timeout=timeout) as response:
            _check_content_length(uri, response, max_bytes)
            written = 0
            with open(local_path, "wb") as fh:
                while True:
                    if time.monotonic() > deadline:
                        raise _DeadlineExceeded(
                            f"download from {uri!r} exceeded the {timeout}s overall "
                            f"deadline (S3_HTTP_TIMEOUT)")
                    chunk = response.read(_HTTP_CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise ValueError(
                            f"download from {uri!r} exceeded the {max_bytes}-byte "
                            f"limit (S3_HTTP_MAX_BYTES)")
                    fh.write(chunk)
    except (_DeadlineExceeded, ValueError):
        local_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        # Includes a bare socket timeout (socket.timeout IS TimeoutError as
        # of Python 3.10) and any other urllib/OS failure — none of those
        # carry the URI on their own, so it's added here.
        local_path.unlink(missing_ok=True)
        raise RuntimeError(f"failed to fetch {uri}: {exc}") from exc
    return str(local_path)


def resolve_input(value: object, scratch_dir: Path) -> object:
    """``s3://...`` and ``http(s)://...`` values (scheme matched case-
    insensitively) are downloaded into ``scratch_dir`` and replaced by the
    local path; anything else (a local path, a non-string value) is returned
    unchanged. Existence of a local path is deliberately never checked here —
    that stays the tool function's job, same as before this module existed."""
    if isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith("s3://"):
            return _download_s3(value, scratch_dir)
        if lowered.startswith(("http://", "https://")):
            return _download_http(value, scratch_dir)
    return value


def prepare_kwargs(kwargs: dict, scratch_dir: Path) -> dict:
    """``resolve_input`` applied to every ``*_path``/``*_file`` kwarg; every
    other kwarg passes through untouched."""
    return {
        key: (resolve_input(value, scratch_dir) if is_file_param(key) else value)
        for key, value in kwargs.items()
    }


def maybe_upload(local_path: str, prefix: str, field_key: str) -> dict | None:
    """Upload ``local_path`` to ``<prefix>/<field_key>/<basename>`` and
    presign it. ``field_key`` (the result field this file came from) is part
    of the key so two different fields sharing a basename never collide and
    overwrite each other in the bucket. Returns ``{"s3_key",
    "presigned_url"}`` on success, ``None`` on any failure (S3 not
    configured, upload error) — logged to stderr so the reason is visible in
    ``docker logs``, but never raised: a publish failure must not take down
    an otherwise-successful tool call. Only the exception TYPE and a
    truncated message are logged, never ``str(exc)`` verbatim — a botocore
    error can embed request internals (e.g. ``AWSAccessKeyId=...`` on a
    presigned-URL-shaped error), and this line lands in ``docker logs``."""
    if not s3_enabled():
        return None
    try:
        client = _client_factory()
        bucket = _env("BUCKET_NAME")
        key = f"{prefix}/{safe_component(field_key)}/{Path(local_path).name}"
        client.upload_file(local_path, bucket, key)
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=_presign_expiration(),
        )
        return {"s3_key": key, "presigned_url": url}
    except Exception as exc:  # noqa: BLE001 - a publish failure must not fail the call
        print(f"[s3] upload failed for {local_path}: {type(exc).__name__}: {str(exc)[:200]}",
              file=sys.stderr)
        return None


def _is_publishable(key: str, value: object, deny_roots: tuple) -> bool:
    """True iff ``value`` is an existing regular file, named like a file
    param, and NOT inside any of ``deny_roots``: the cloned repo (publishing
    repo source files would leak them into every result) and the per-call
    scratch dir (a tool that echoes its ``input_path`` back would otherwise
    re-upload the caller's own input and hand back a local path that the
    post-call scratch cleanup is about to delete)."""
    if not (is_file_param(key) and isinstance(value, str)):
        return False
    path = Path(value)
    if not path.is_file():
        return False
    try:
        resolved = path.resolve()
        return not any(resolved.is_relative_to(root.resolve()) for root in deny_roots)
    except OSError:
        return False


def publish_result(result: object, prefix: str, deny_roots) -> object:
    """Recursively walk a dict/list tool result. For every ``*_path``/
    ``*_file`` string entry that is an existing, publishable local file, upload
    it under ``prefix`` and add sibling ``<key>_s3_key`` /
    ``<key>_presigned_url`` entries — the original local path is left
    untouched (it is still correct inside the build container). ``deny_roots``
    is a single ``Path`` or an iterable of them; files under any deny root are
    never uploaded (see ``_is_publishable``)."""
    roots = (deny_roots,) if isinstance(deny_roots, Path) else tuple(deny_roots)
    if isinstance(result, dict):
        out = {}
        for key, value in result.items():
            out[key] = publish_result(value, prefix, roots)
            if _is_publishable(key, value, roots):
                uploaded = maybe_upload(value, prefix, key)
                if uploaded:
                    out[f"{key}_s3_key"] = uploaded["s3_key"]
                    out[f"{key}_presigned_url"] = uploaded["presigned_url"]
        return out
    if isinstance(result, list):
        return [publish_result(item, prefix, roots) for item in result]
    return result
