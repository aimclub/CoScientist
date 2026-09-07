"""Shared agent initialisation helpers.

Every per-agent module imports from here so settings are resolved once and the
LLM/tooling setup is consistent across agents.
"""
import asyncio
import logging
import os
from typing import Any, AsyncGenerator

import litellm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from CoScientist.config import get_settings
from CoScientist.hitl.handler import ConsoleHITLHandler, DelegatingHITLHandler
from CoScientist.utils.selective_proxy import LiteLLMProxy

settings = get_settings()

_logger = logging.getLogger(__name__)

# Transient upstream failures (provider hiccups, rate limits, 5xx) that are worth
# retrying. OpenRouter wraps a flaky underlying provider as a BadRequestError with
# "Provider returned error", which litellm's own num_retries does NOT retry — so
# we retry around the whole model call ourselves.
_RETRYABLE_SUBSTRINGS = (
    "provider returned error",
    "rate limit",
    "ratelimit",
    "overloaded",
    "service unavailable",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "client has been closed",
    "502",
    "503",
    "504",
    "529",
)
_RETRYABLE_TYPES = (
    "RateLimitError",
    "Timeout",
    "APIConnectionError",
    "ServiceUnavailableError",
    "InternalServerError",
    "APIError",
)
_LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))


def is_proxy_error(err: Exception) -> bool:
    """Return True if *err* represents an unreachable proxy or network connection failure."""
    if not settings.web.use_proxy:
        return False
    msg = str(err).lower()
    proxy_keywords = (
        "proxy",
        "all connection attempts failed",
        "connecterror",
        "connection refused",
        "cannot connect to host",
        "failed to connect",
        "proxyerror",
        "timed out",
        "timeout",
        "connecttimeout",
    )
    if any(k in msg for k in proxy_keywords):
        return True
    if settings.services.proxy_url and ("connectionerror" in msg or "connecterror" in msg or "apiconnectionerror" in msg):
        return True
    return False


def _is_transient(err: Exception) -> bool:
    if is_proxy_error(err):
        return False
    if type(err).__name__ in _RETRYABLE_TYPES:
        return True
    msg = str(err).lower()
    return any(s in msg for s in _RETRYABLE_SUBSTRINGS)


class RetryingLiteLlm(LiteLlm):
    """LiteLlm that retries the whole call on transient upstream errors.

    Only retries when nothing has been yielded yet (so a partial stream is never
    duplicated) and only for transient errors; everything else propagates.
    """

    @staticmethod
    async def _verify_proxy_reachable() -> None:
        """Fast HTTP probe to confirm the corporate proxy can reach the internet/VPN.

        When a corporate VPN is not connected, the local proxy container accepts
        TCP connections on localhost, but hangs indefinitely when trying to reach
        upstream endpoints. litellm's default request_timeout is 6000s (100 min),
        causing an infinite freeze in the UI. We probe an upstream endpoint THROUGH
        the proxy with a 5s deadline to fail fast when VPN is off.
        """
        if not settings.web.use_proxy or not settings.services.proxy_url:
            return

        import httpx

        probe_url = "https://openrouter.ai/api/v1/models"
        try:
            async with httpx.AsyncClient(
                proxy=settings.services.proxy_url,
                timeout=httpx.Timeout(5.0, connect=5.0)
            ) as client:
                await client.get(probe_url)
        except Exception as err:
            _logger.warning("Proxy pre-flight probe failed: %s", err)
            raise ConnectionError(
                f"Error connecting to proxy server."
                f"Please ensure the proxy container is running, corporate VPN is enabled (other - disabled), "
                f"and proxy is accessible: {err}"
            ) from err

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        await self._verify_proxy_reachable()
        attempt = 0
        while True:
            yielded = False
            try:
                async for resp in super().generate_content_async(llm_request, stream=stream):
                    yielded = True
                    yield resp
                return
            except Exception as err:  # noqa: BLE001 — classify then re-raise
                attempt += 1
                max_r = settings.web.max_retries
                if yielded or attempt > max_r or not _is_transient(err):
                    raise
                delay = min(1.5 ** attempt, 8.0)
                _logger.warning(
                    "Transient LLM error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt, max_r, delay, err,
                )
                await asyncio.sleep(delay)

MODEL = settings.llm.main_model
litellm.api_key = settings.llm.openai_api_key
litellm.request_timeout = 45.0
# Silence litellm's "Provider List: https://docs.litellm.ai/docs/providers" spam.
# It fires when litellm can't map a model prefix (e.g. "qwen/...") to a known
# provider during cost/token bookkeeping — harmless, but it floods the console.
litellm.suppress_debug_info = True

_litellm_proxy: LiteLLMProxy | None = None
if settings.services.proxy_url:
    _litellm_proxy = LiteLLMProxy(settings.services.proxy_url)
    if settings.web.use_proxy:
        _litellm_proxy.enable()


def sync_proxy_session() -> None:
    """Synchronize litellm proxy with the runtime ``use_proxy`` toggle."""
    if _litellm_proxy is not None:
        if settings.web.use_proxy:
            _litellm_proxy.enable()
        else:
            _litellm_proxy.disable()

hitl_handler = DelegatingHITLHandler(ConsoleHITLHandler())

# The CoderAgent runs on a dedicated (stronger) model — its multi-step tool-use
# benefits from more capability. Falls back to the main model when unset.
#
# Routing mirrors the other agents exactly: the provider prefix in the model
# string (e.g. "openrouter/qwen/...") selects the provider/base-URL, and the
# global `litellm.api_key` (set above) carries the key. We deliberately do NOT
# pass `api_base` here — doing so makes litellm strip the provider prefix, fail
# to re-infer the provider, and spam "Provider List: ..." warnings.
CODER_MODEL = settings.llm.coder_model or settings.llm.main_model


def make_llm(model: str = MODEL) -> LiteLlm:
    """Return a (retry-wrapped) LiteLlm for the main model (or an override)."""
    return RetryingLiteLlm(model=model)


def make_coder_llm() -> LiteLlm:
    """Return a (retry-wrapped) LiteLlm for the dedicated coder model."""
    return RetryingLiteLlm(model=CODER_MODEL)
