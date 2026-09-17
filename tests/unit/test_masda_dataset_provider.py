"""MASDA provider selection, observed wire contract, and workspace delivery."""

import asyncio
import base64
import json
import re
from types import SimpleNamespace

import httpx
import pytest
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.events import Event
from google.genai import types

from CoScientist.a2a.masda import MasdaDatasetsAgent, MasdaError, acquire_dataset
from CoScientist.assembly import build_system, load_config
from CoScientist.config import Settings, get_settings
from CoScientist.config.settings import DatasetSettings
from CoScientist.graph.session_scope import GRAPH_SCOPE_SESSION_KEY, GRAPH_SCOPE_USER_KEY


RPC_URL = "http://masda.test:9999"
CARD_URL = f"{RPC_URL}/.well-known/agent-card.json"
SOURCE_URL = "https://example.org/penguins.csv"
CSV = b"species,island\n" + b"Adelie,Torgersen\n" * 344


def _state():
    return {
        GRAPH_SCOPE_USER_KEY: "web-user",
        GRAPH_SCOPE_SESSION_KEY: "session_public",
        "coder_workspace_id": "ws_session_public",
    }


def _attached(agent):
    return [tool.agent for tool in agent.tools if hasattr(tool, "agent")]


@pytest.fixture
def masda_system(monkeypatch):
    dataset = get_settings().dataset
    monkeypatch.setattr(dataset, "provider", "masda")
    monkeypatch.setattr(dataset, "masda_a2a_rpc_url", RPC_URL)
    monkeypatch.setattr(dataset, "masda_a2a_card_url", None)
    return build_system(load_config())


def _masda_routing_step(system):
    match = re.search(
        r"\d+\. When an external tabular dataset.*?(?=\n\d+\. |\Z)",
        system.root.instruction,
        flags=re.DOTALL,
    )
    assert match, "MASDA acquisition step missing from Orchestrator instruction"
    return " ".join(match.group().lower().split())


def _completed_response(*, include_csv=True, csv_raw=None, state="TASK_STATE_COMPLETED"):
    artifacts = [
        {
            "name": "harvest_result",
            "parts": [{"data": {
                "record_count": 344.0,
                "records": [{"url": SOURCE_URL}],
                "files": [{"dataset_path": "output/jobs/a2a/task-123/dataset.csv"}],
            }}],
        },
        {
            "name": "dataset_report",
            "parts": [{
                "raw": base64.b64encode(b'{"record_count":344}').decode(),
                "filename": "dataset_report.json",
                "mediaType": "application/json",
            }],
        },
    ]
    if include_csv:
        artifacts.append({
            "name": "dataset",
            "parts": [{
                "raw": csv_raw if csv_raw is not None else base64.b64encode(CSV).decode(),
                "filename": "dataset.csv",
                "mediaType": "text/csv",
            }],
        })
    return {"jsonrpc": "2.0", "result": {"task": {
        "id": "task-123",
        "contextId": "context-1",
        "status": {"state": state},
        "artifacts": artifacts,
    }}}


def _run(request, *, state=None, handler, rpc_url=RPC_URL, card_url=None):
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await acquire_dataset(
                request,
                state=state if state is not None else _state(),
                rpc_url=rpc_url,
                card_url=card_url,
                client=client,
            )

    return asyncio.run(execute())


def test_builtin_remains_default_and_independent_of_masda(monkeypatch):
    assert DatasetSettings().provider == "builtin"
    dataset = get_settings().dataset
    monkeypatch.setattr(dataset, "provider", "builtin")
    monkeypatch.setattr(dataset, "masda_a2a_card_url", None)
    monkeypatch.setattr(dataset, "masda_a2a_rpc_url", "not-a-url")
    system = build_system(load_config())
    assert "MasdaDatasetsAgent" not in system.agents
    assert [agent.name for agent in _attached(system.agent("CoderAgent"))] == [
        "DatasetCollectorAgent"
    ]


@pytest.mark.parametrize("use_card", [False, True])
def test_masda_assembly_uses_deterministic_agent_without_builtin_fallback(monkeypatch, use_card):
    dataset = get_settings().dataset
    monkeypatch.setattr(dataset, "provider", "masda")
    monkeypatch.setattr(dataset, "masda_a2a_rpc_url", None if use_card else RPC_URL)
    monkeypatch.setattr(dataset, "masda_a2a_card_url", CARD_URL if use_card else None)
    config = load_config()
    system = build_system(config)
    agent = system.agent("MasdaDatasetsAgent")
    assert isinstance(agent, MasdaDatasetsAgent)
    assert not isinstance(agent, RemoteA2aAgent)
    assert agent in _attached(system.root)
    assert "DatasetCollectorAgent" not in [
        child.name for child in _attached(system.agent("CoderAgent"))
    ]
    assert not config.agent("DatasetCollectorAgent").is_enabled()
    assert "without silent builtin fallback" in system.root.instruction
    assert "DatasetCollectorAgent" not in system.agent("CoderAgent").instruction


def test_masda_route_is_for_external_csv_acquisition_only(masda_system):
    step = _masda_routing_step(masda_system)
    assert "external tabular dataset needs acquisition" in step
    assert "exact direct csv url is the validated v1 path" in step
    assert "returned coscientist workspace path" in step
    assert "provider selection comes from configuration" in step
    route = masda_system.config.agent("MasdaDatasetsAgent")
    assert "acquisition provider" in route.description.lower()
    assert "processes" not in route.description.lower()
    assert "exact direct csv urls are validated v1" in route.routing.lower()


def test_masda_route_excludes_local_uploads_and_downstream_work(masda_system):
    step = _masda_routing_step(masda_system)
    assert "not already available locally" in step
    assert "workspace files and user uploads" in step
    for activity in (
        "analysis", "preprocessing", "feature engineering", "ml",
        "visualization", "synthetic-data generation", "unrelated computation",
    ):
        assert activity in step
    assert "route those to execution" in step


def test_masda_description_discovery_is_experimental(masda_system):
    step = _masda_routing_step(masda_system)
    assert "description-only or ambiguous discovery is experimental" in step
    assert "task_state_completed does not prove semantic correctness" in step
    assert "description-only discovery is experimental" in (
        masda_system.config.agent("MasdaDatasetsAgent").routing.lower()
    )


def test_masda_requires_rpc_or_card_url(monkeypatch):
    dataset = get_settings().dataset
    monkeypatch.setattr(dataset, "provider", "masda")
    monkeypatch.setattr(dataset, "masda_a2a_rpc_url", None)
    monkeypatch.setattr(dataset, "masda_a2a_card_url", None)
    with pytest.raises(ValueError, match="DATASET__MASDA_A2A_RPC_URL"):
        load_config()


def test_nested_env_settings_select_provider_and_url(monkeypatch):
    monkeypatch.setenv("DATASET__PROVIDER", "masda")
    monkeypatch.setenv("DATASET__MASDA_A2A_RPC_URL", RPC_URL)
    settings = Settings(_env_file=None)
    assert settings.dataset.provider == "masda"
    assert settings.dataset.masda_a2a_rpc_url == RPC_URL


def test_send_message_and_materialize_csv_in_public_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    observed = {}

    def handler(request):
        observed["url"] = str(request.url)
        observed["headers"] = request.headers
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completed_response())

    result = _run(f"Fetch {SOURCE_URL}", handler=handler)
    assert observed["url"] == RPC_URL
    assert observed["headers"]["A2A-Version"] == "1.0"
    assert observed["headers"]["Content-Type"] == "application/json"
    assert observed["body"]["method"] == "SendMessage"
    assert observed["body"]["params"]["message"]["role"] == "ROLE_USER"
    assert observed["body"]["params"]["configuration"]["return_immediately"] is False
    assert observed["body"]["params"]["message"]["parts"][0]["text"] == f"Fetch {SOURCE_URL}"
    assert result.record_count == 344
    assert result.task_id == "task-123"
    assert result.source_url == SOURCE_URL
    assert result.workspace_path.is_file()
    assert result.workspace_path.read_bytes() == CSV
    assert result.workspace_path.is_relative_to(tmp_path / "ws_session_public" / "data" / "masda")
    assert "ws_session_public" in result.as_text()
    assert "output/jobs/a2a" not in result.as_text()


def test_card_url_is_backward_compatible_for_rpc_discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        if request.method == "GET":
            return httpx.Response(200, json={
                "url": RPC_URL, "protocolVersion": "0.3", "preferredTransport": "JSONRPC"
            })
        return httpx.Response(200, json=_completed_response())

    result = _run("Fetch penguins", handler=handler, rpc_url=None, card_url=CARD_URL)
    assert calls == [("GET", CARD_URL), ("POST", RPC_URL)]
    assert result.record_count == 344


@pytest.mark.parametrize("response, expected", [
    (httpx.Response(503), "HTTP error: 503"),
    (httpx.Response(200, text="not json"), "not valid JSON"),
    (httpx.Response(200, json={"error": {"message": "bad request"}}), "JSON-RPC error"),
    (httpx.Response(200, json={"result": {}}), "no result.task"),
    (httpx.Response(200, json=_completed_response(state="TASK_STATE_FAILED")), "did not complete"),
    (httpx.Response(200, json=_completed_response(state="TASK_STATE_REJECTED")), "did not complete"),
    (httpx.Response(200, json=_completed_response(include_csv=False)), "no embedded CSV"),
    (httpx.Response(200, json=_completed_response(csv_raw="%%%")), "invalid base64"),
    (httpx.Response(200, json=_completed_response(csv_raw="")), "embedded CSV is empty"),
    (httpx.Response(200, json=_completed_response(csv_raw=base64.b64encode(b"  ").decode())), "embedded CSV is empty"),
])
def test_remote_failures_do_not_create_dataset(monkeypatch, tmp_path, response, expected):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    with pytest.raises(MasdaError, match=expected):
        _run("Fetch penguins", handler=lambda request: response)
    assert not list(tmp_path.rglob("*.csv"))


def test_timeout_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))

    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(MasdaError, match="timed out"):
        _run("Fetch penguins", handler=handler)


def test_unsafe_filename_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    response = _completed_response()
    response["result"]["task"]["artifacts"][-1]["parts"][0]["filename"] = "../dataset.csv"
    with pytest.raises(MasdaError, match="filename is unsafe"):
        _run("Fetch penguins", handler=lambda request: httpx.Response(200, json=response))


def test_csv_filename_with_wrong_media_type_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    response = _completed_response()
    response["result"]["task"]["artifacts"][-1]["parts"][0]["mediaType"] = "application/json"
    with pytest.raises(MasdaError, match="unexpected mediaType"):
        _run("Fetch penguins", handler=lambda request: httpx.Response(200, json=response))


def test_missing_public_scope_does_not_write_to_transient_child_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings().code_exec, "workspace_root", str(tmp_path))
    with pytest.raises(MasdaError, match="public CoScientist session scope"):
        _run(
            "Fetch penguins", state={"coder_workspace_id": "ws_child"},
            handler=lambda request: httpx.Response(200, json=_completed_response()),
        )
    assert not list(tmp_path.rglob("*.csv"))


def test_agent_error_is_visible_to_orchestrator_without_builtin_call(monkeypatch):
    async def failed(*args, **kwargs):
        raise MasdaError("TASK_STATE_FAILED")

    monkeypatch.setattr("CoScientist.a2a.masda.acquire_dataset", failed)
    agent = MasdaDatasetsAgent(name="MasdaDatasetsAgent", rpc_url=RPC_URL)
    context = SimpleNamespace(
        invocation_id="invocation", branch="",
        session=SimpleNamespace(
            state=_state(),
            events=[Event(author="user", content=types.Content(
                parts=[types.Part.from_text(text="Get a dataset")]
            ))],
        ),
    )

    async def collect():
        return [event async for event in agent._run_async_impl(context)]

    events = asyncio.run(collect())
    assert len(events) == 1
    assert "TASK_STATE_FAILED" in events[0].content.parts[0].text
    assert "No builtin fallback" in events[0].content.parts[0].text
