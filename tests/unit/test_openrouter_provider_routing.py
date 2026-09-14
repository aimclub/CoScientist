import pytest

from CoScientist.config import get_settings
from CoScientist.agents.common import (
    _openrouter_provider_kwargs,
    _combine_llm_kwargs,
    RetryingLiteLlm,
)
from CoScientist.web.app import _apply_frontend_settings, _settings_payload


def test_default_routing_kwargs_empty():
    settings = get_settings()
    settings.web.openrouter_provider_sort = "default"
    settings.web.openrouter_provider_order = ""

    kwargs = _openrouter_provider_kwargs("openrouter/qwen/qwen3-235b-a22b-2507")
    assert kwargs == {}, "Default routing should not inject any extra_body"


def test_sort_price_routing():
    settings = get_settings()
    settings.web.openrouter_provider_sort = "price"
    settings.web.openrouter_provider_order = ""

    kwargs = _openrouter_provider_kwargs("openrouter/qwen/qwen3-235b-a22b-2507")
    assert kwargs == {
        "extra_body": {
            "provider": {
                "sort": "price",
            }
        }
    }


def test_sort_latency_and_order():
    settings = get_settings()
    settings.web.openrouter_provider_sort = "latency"
    settings.web.openrouter_provider_order = "Together, DeepInfra"

    kwargs = _openrouter_provider_kwargs("openrouter/qwen/qwen3-235b-a22b-2507")
    assert kwargs == {
        "extra_body": {
            "provider": {
                "sort": "latency",
                "order": ["Together", "DeepInfra"],
            }
        }
    }


def test_non_openrouter_model_ignored():
    settings = get_settings()
    settings.web.openrouter_provider_sort = "price"
    settings.web.openrouter_provider_order = "Together"

    for non_or_model in ("azure/gpt-4o", "google/gemini-2.0-flash", "gpt-4o"):
        kwargs = _openrouter_provider_kwargs(non_or_model)
        assert kwargs == {}, f"Model {non_or_model} should never receive OpenRouter provider kwargs"


def test_combine_llm_kwargs():
    d1 = {"reasoning": {"enabled": False}}
    d2 = {"extra_body": {"provider": {"sort": "price"}}}
    d3 = {"timeout": 120}

    combined = _combine_llm_kwargs(d1, d2, d3)
    assert combined == {
        "reasoning": {"enabled": False},
        "extra_body": {"provider": {"sort": "price"}},
        "timeout": 120,
    }


def test_web_settings_apply_and_payload_roundtrip():
    frontend_input = {
        "general": {
            "openrouterProviderSort": "throughput",
            "openrouterProviderOrder": "Fireworks, Groq",
        }
    }
    _apply_frontend_settings(frontend_input)

    settings = get_settings()
    assert settings.web.openrouter_provider_sort == "throughput"
    assert settings.web.openrouter_provider_order == "Fireworks, Groq"

    payload = _settings_payload()
    assert payload["general"]["openrouterProviderSort"] == "throughput"
    assert payload["general"]["openrouterProviderOrder"] == "Fireworks, Groq"

    # Reset to default
    _apply_frontend_settings({
        "general": {
            "openrouterProviderSort": "default",
            "openrouterProviderOrder": "",
        }
    })
    assert get_settings().web.openrouter_provider_sort == "default"
    assert get_settings().web.openrouter_provider_order == ""


def test_retrying_litellm_dynamic_provider_sync():
    settings = get_settings()
    settings.web.openrouter_provider_sort = "default"
    settings.web.openrouter_provider_order = ""

    llm = RetryingLiteLlm(model="openrouter/test-model")
    assert "extra_body" not in llm._additional_args or "provider" not in llm._additional_args.get("extra_body", {})

    # Switch to price
    settings.web.openrouter_provider_sort = "price"
    llm._apply_dynamic_openrouter_provider("openrouter/test-model")
    assert llm._additional_args["extra_body"]["provider"]["sort"] == "price"

    # Switch back to default
    settings.web.openrouter_provider_sort = "default"
    llm._apply_dynamic_openrouter_provider("openrouter/test-model")
    assert "extra_body" not in llm._additional_args or "provider" not in llm._additional_args.get("extra_body", {})
