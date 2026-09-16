"""Rewrite S3 links in report markdown to local web-app links.

Agents paste raw S3 URLs into report prose. A presigned URL expires. A plain
endpoint URL points at the internal MinIO address, which a browser cannot
reach. An ``s3://bucket/key`` reference is not clickable at all.

This module replaces each of them with a relative
``/api/artifact/<bucket>/<key>`` link. The web app mints a fresh presigned URL
on each request to that route, so a report link never expires for the user and
never exposes the internal endpoint.

A link the module cannot parse is left untouched.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional, Set, Tuple
from urllib.parse import quote, unquote, urlparse

from CoScientist.utils.s3_refs import split_s3_uri

logger = logging.getLogger(__name__)

ARTIFACT_ROUTE = "/api/artifact"

# A URL in markdown or prose. Stops at whitespace, quotes, and the delimiters
# of a markdown link or image.
_HTTP_URL_RE = re.compile(r"https?://[^\s\"'<>\)\]]+")
_S3_URI_RE = re.compile(r"s3://[^\s\"'<>\)\]]+")

# Sentence punctuation after a bare URL is not part of the URL.
_TRAILING_PUNCTUATION = ".,;:"


def artifact_link(bucket: str, key: str) -> str:
    """Build the local link the report carries for one object."""
    return f"{ARTIFACT_ROUTE}/{quote(bucket, safe='')}/{quote(key, safe='/')}"


def _configured_hosts() -> Set[str]:
    """The host:port pairs of the configured S3 endpoints, read at call time."""
    hosts = set()
    for var in ("S3__ENDPOINT_URL", "S3__EXTERNAL_ENDPOINT_URL"):
        value = os.getenv(var)
        if not value:
            continue
        netloc = urlparse(value).netloc
        if netloc:
            hosts.add(netloc)
    return hosts


def _bucket_key_from_url(url: str, known_hosts: Set[str]) -> Optional[Tuple[str, str]]:
    """Extract (bucket, key) from an S3 URL, or None when it is not one.

    A URL with an ``X-Amz-Signature`` query parameter is a presigned S3 URL.
    A URL without a signature counts only when its host is one of the
    configured S3 endpoints. Anything else is an ordinary web link.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    signed = "X-Amz-Signature=" in parsed.query
    if not signed and parsed.netloc not in known_hosts:
        return None
    bucket, sep, key = parsed.path.lstrip("/").partition("/")
    if not sep or not bucket or not key:
        return None
    key = unquote(key)
    if ".." in key.split("/"):
        return None
    return bucket, key


def _rewrite_http(match: "re.Match", known_hosts: Set[str]) -> str:
    url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
    parsed = _bucket_key_from_url(url, known_hosts)
    if parsed is None:
        return match.group(0)
    bucket, key = parsed
    return artifact_link(bucket, key) + match.group(0)[len(url):]


def _rewrite_s3(match: "re.Match") -> str:
    uri = match.group(0).rstrip(_TRAILING_PUNCTUATION)
    parsed = split_s3_uri(uri)
    if parsed is None:
        return match.group(0)
    bucket, key = parsed
    if ".." in key.split("/"):
        return match.group(0)
    return artifact_link(bucket, key) + match.group(0)[len(uri):]


def remint_report_urls(text: str) -> str:
    """Replace S3 links in report text with local ``/api/artifact/`` links.

    Never raises: a report with an odd link must still reach the user.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        known_hosts = _configured_hosts()
        text = _HTTP_URL_RE.sub(lambda m: _rewrite_http(m, known_hosts), text)
        text = _S3_URI_RE.sub(_rewrite_s3, text)
        return text
    except Exception:  # noqa: BLE001 — never break a report over a link
        logger.warning("remint_report_urls failed; returning the report unchanged", exc_info=True)
        return text


__all__ = ["ARTIFACT_ROUTE", "artifact_link", "remint_report_urls"]
