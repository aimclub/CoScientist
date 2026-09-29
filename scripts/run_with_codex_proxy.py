"""Launch CoScientist against the loopback provider configured in Codex CLI.

The selected Codex provider must expose an OpenAI-compatible API and its
client key must already be present in the environment variable named by
config.toml. This script never reads Codex login tokens or writes secrets.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _windows_user_environment(name: str) -> str | None:
    """Read one named user variable when T3 predates a Windows env update."""
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry:
            value, _ = winreg.QueryValueEx(registry, name)
    except (FileNotFoundError, OSError):
        return None
    return value if isinstance(value, str) and value else None


def configure_environment(config_path: Path) -> tuple[str, str]:
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    provider_name = config.get("model_provider")
    provider = config.get("model_providers", {}).get(provider_name, {})
    base_url = provider.get("base_url", "")
    key_name = provider.get("env_key", "")
    model_name = config.get("model", "")
    parsed = urlparse(base_url)

    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Codex provider must use a local HTTP proxy")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Codex provider URL must not contain credentials or query parameters")
    if not key_name or not isinstance(key_name, str):
        raise ValueError("Codex provider has no env_key in its config")
    key = os.getenv(key_name) or _windows_user_environment(key_name)
    if not key:
        raise ValueError(
            f"Set {key_name} in the user environment or the ignored .env; "
            "do not paste the key into chat or commit it."
        )
    if not model_name or not isinstance(model_name, str):
        raise ValueError("Codex config has no model")

    # The local proxy accepts the OpenAI chat-completions protocol. The prefix
    # selects LiteLLM's OpenAI adapter; LiteLLM sends the unprefixed model ID.
    model = f"openai/{model_name}"
    # A chat-harness launch needs approvals to be surfaced to the operator.
    # Respect an explicit HITL__ENABLED=false from the environment or .env.
    os.environ.setdefault("HITL__ENABLED", "true")
    os.environ.update({
        "COSCIENTIST_CODEX_PROXY": "1",
        # The harness chat reviews HITL requests; a server-side veto timer must
        # never approve one while the operator is answering in another window.
        "COSCIENTIST_HARNESS_CHAT_HITL": "1",
        "LLM__MAIN_URL": base_url.rstrip("/"),
        "LLM__SCENARIO_URL": base_url.rstrip("/"),
        "LLM__MAIN_MODEL": model,
        "LLM__SCENARIO_MODEL": model,
        "LLM__CODER_MODEL": model,
        "LLM__OPENAI_API_KEY": key,
    })
    return base_url, model


def probe_provider(endpoint: str, key: str) -> None:
    """Verify the configured local service accepts the client key, without inference."""
    request = Request(endpoint.rstrip("/") + "/models",
                      headers={"Authorization": f"Bearer {key}"})
    try:
        with urlopen(request, timeout=8) as response:
            if response.status != 200:
                raise RuntimeError(f"Local Codex provider returned HTTP {response.status}")
    except HTTPError as exc:
        raise RuntimeError(f"Local Codex provider rejected the client key (HTTP {exc.code})") from None
    except URLError as exc:
        raise RuntimeError(f"Local Codex provider is unavailable: {exc.reason}") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-config", type=Path, default=Path.home() / ".codex" / "config.toml")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    try:
        endpoint, model = configure_environment(args.codex_config)
        probe_provider(endpoint, os.environ["LLM__OPENAI_API_KEY"])
    except (OSError, ValueError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        print(f"Cannot start CoScientist: {exc}", file=sys.stderr)
        return 1
    print(f"CoScientist provider: {endpoint} ({model}); key loaded from environment.", flush=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from CoScientist.cli import run_web

    run_web(host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
