"""No-network tests for the optional loopback Codex-provider launcher."""

import importlib.util
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "run_with_codex_proxy.py"
spec = importlib.util.spec_from_file_location("run_with_codex_proxy", SOURCE)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture(autouse=True)
def isolate_harness_flags(monkeypatch):
    # The launcher sets process-wide flags; do not leak them into HITL tests.
    monkeypatch.setenv("HITL__ENABLED", "false")
    monkeypatch.setenv("COSCIENTIST_HARNESS_CHAT_HITL", "0")


def write_config(path, base="http://127.0.0.1:8317/v1"):
    path.write_text(
        'model = "gpt-6-astra"\nmodel_provider = "local"\n'
        '[model_providers.local]\n'
        f'base_url = "{base}"\n'
        'env_key = "TEST_LOCAL_PROXY_KEY"\n', encoding="utf-8"
    )


def test_requires_explicit_client_key(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    write_config(config)
    monkeypatch.delenv("TEST_LOCAL_PROXY_KEY", raising=False)
    with pytest.raises(ValueError, match="TEST_LOCAL_PROXY_KEY"):
        launcher.configure_environment(config)


def test_configures_local_litellm_provider(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    write_config(config)
    monkeypatch.setenv("TEST_LOCAL_PROXY_KEY", "test-only-key")
    monkeypatch.delenv("HITL__ENABLED", raising=False)
    for name in ("COSCIENTIST_CODEX_PROXY", "LLM__MAIN_URL", "LLM__MAIN_MODEL",
                 "LLM__OPENAI_API_KEY", "LLM__CODER_MODEL", "LLM__SCENARIO_MODEL",
                 "LLM__SCENARIO_URL"):
        monkeypatch.delenv(name, raising=False)
    endpoint, model = launcher.configure_environment(config)
    assert (endpoint, model) == ("http://127.0.0.1:8317/v1", "openai/gpt-6-astra")
    assert launcher.os.environ["LLM__OPENAI_API_KEY"] == "test-only-key"
    assert launcher.os.environ["COSCIENTIST_CODEX_PROXY"] == "1"
    assert launcher.os.environ["HITL__ENABLED"] == "true"


def test_explicit_hitl_opt_out_is_preserved(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    write_config(config)
    monkeypatch.setenv("TEST_LOCAL_PROXY_KEY", "test-only-key")
    monkeypatch.setenv("HITL__ENABLED", "false")

    launcher.configure_environment(config)

    assert launcher.os.environ["HITL__ENABLED"] == "false"


def test_uses_named_windows_user_variable_when_process_does_not_have_it(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    write_config(config)
    monkeypatch.delenv("TEST_LOCAL_PROXY_KEY", raising=False)
    monkeypatch.setattr(launcher, "_windows_user_environment",
                        lambda name: "test-only-key" if name == "TEST_LOCAL_PROXY_KEY" else None)
    launcher.configure_environment(config)
    assert launcher.os.environ["LLM__OPENAI_API_KEY"] == "test-only-key"


def test_rejects_nonlocal_provider(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    write_config(config, "https://external.example/v1")
    monkeypatch.setenv("TEST_LOCAL_PROXY_KEY", "test-only-key")
    with pytest.raises(ValueError, match="local HTTP proxy"):
        launcher.configure_environment(config)


def test_agent_model_passes_proxy_endpoint_to_litellm(monkeypatch):
    from CoScientist.agents import common

    monkeypatch.setenv("COSCIENTIST_CODEX_PROXY", "1")
    monkeypatch.setattr(common.settings.llm, "main_url", "http://127.0.0.1:8317/v1")
    monkeypatch.setattr(common.settings.llm, "openai_api_key", "test-only-key")
    model = common.make_llm("openai/gpt-6-astra")
    assert model._additional_args["api_base"] == "http://127.0.0.1:8317/v1"
    assert model._additional_args["api_key"] == "test-only-key"


def test_model_generates_via_local_chat_endpoint(monkeypatch):
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    from CoScientist.agents import common

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append((self.path, json.loads(self.rfile.read(length))))
            body = json.dumps({
                "id": "chatcmpl-test", "object": "chat.completion",
                "created": 1, "model": "fake-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setenv("COSCIENTIST_CODEX_PROXY", "1")
        monkeypatch.setattr(common.settings.llm, "main_url",
                            f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.setattr(common.settings.llm, "openai_api_key", "test-only-key")
        model = common.make_llm("openai/fake-model")
        request = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="ping")])])

        async def generate():
            return [response async for response in model.generate_content_async(request)]

        responses = asyncio.run(generate())
        assert responses[-1].content.parts[0].text == "pong"
        assert received[0][0] == "/v1/chat/completions"
        assert received[0][1]["model"] == "fake-model"
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()


def test_probe_checks_client_key_without_inference():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/v1/models" and
                               self.headers.get("Authorization") == "Bearer test-only-key" else 401)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/v1"
        launcher.probe_provider(endpoint, "test-only-key")
        with pytest.raises(RuntimeError, match="HTTP 401"):
            launcher.probe_provider(endpoint, "wrong-key")
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()


def test_model_preserves_openai_tool_calls(monkeypatch):
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    from CoScientist.agents import common

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({
                "id": "chatcmpl-tool", "object": "chat.completion",
                "created": 1, "model": "fake-model",
                "choices": [{"index": 0, "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{"id": "call_1", "type": "function", "function": {
                        "name": "lookup", "arguments": '{"query":"test"}'}}],
                }, "finish_reason": "tool_calls"}],
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setenv("COSCIENTIST_CODEX_PROXY", "1")
        monkeypatch.setattr(common.settings.llm, "main_url",
                            f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.setattr(common.settings.llm, "openai_api_key", "test-only-key")
        model = common.make_llm("openai/fake-model")
        request = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="lookup")])])

        async def generate():
            return [response async for response in model.generate_content_async(request)]

        calls = [part.function_call for response in asyncio.run(generate())
                 for part in response.content.parts if part.function_call]
        assert calls[0].name == "lookup"
        assert calls[0].args == {"query": "test"}
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()
