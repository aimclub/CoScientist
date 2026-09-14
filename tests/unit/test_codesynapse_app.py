from fastapi.testclient import TestClient

from CoScientist.integrations.codesynapse.app import create_app
from CoScientist.integrations.codesynapse.facade import CodesynapseFacade, StartRequest
from CoScientist.integrations.codesynapse.settings import CodesynapseIntegrationSettings
from CoScientist.integrations.codesynapse.store import InMemoryIntegrationStore


class _Executor:
    async def execute(self, request, hitl_handler):
        return "report"


def test_facade_app_exposes_a2a_agent_card_and_health_check():
    store = InMemoryIntegrationStore()
    app = create_app(
        CodesynapseIntegrationSettings(a2a_public_url="http://testserver"),
        facade=CodesynapseFacade(store=store, executor=_Executor()),
        store=store,
    )
    client = TestClient(app)

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/.well-known/agent-card.json").json()["name"] == "coscientist"


def test_a2a_start_returns_working_task_before_pipeline_completes():
    class BlockingExecutor:
        async def execute(self, request, hitl_handler):
            import asyncio

            await asyncio.sleep(0.05)
            return "report"

    store = InMemoryIntegrationStore()
    app = create_app(
        CodesynapseIntegrationSettings(a2a_public_url="http://testserver"),
        facade=CodesynapseFacade(store=store, executor=BlockingExecutor()),
        store=store,
    )
    client = TestClient(app)
    response = client.post("/", json={
        "jsonrpc": "2.0",
        "id": "request-1",
        "method": "message/send",
        "params": {
            "message": {"messageId": "message-1", "role": "user", "parts": [{"kind": "text", "text": "Find a hypothesis"}]},
            "configuration": {"blocking": False},
        },
    })

    assert response.status_code == 200
    assert response.json()["result"]["status"]["state"] == "working"


def test_a2a_message_stream_emits_progress_before_terminal_task():
    class TraceExecutor:
        async def execute(self, request, hitl_handler):
            await request.trace_recorder.emit(
                "tool.started",
                agent="ResearchAgent",
                data={"tool_name": "tavily_search"},
            )
            return "report"

    store = InMemoryIntegrationStore()
    app = create_app(
        CodesynapseIntegrationSettings(a2a_public_url="http://testserver"),
        facade=CodesynapseFacade(store=store, executor=TraceExecutor()),
        store=store,
    )
    response = TestClient(app).post("/", json={
        "jsonrpc": "2.0",
        "id": "request-1",
        "method": "message/stream",
        "params": {
            "message": {
                "messageId": "message-1",
                "role": "user",
                "parts": [{"kind": "text", "text": "Find a hypothesis"}],
            },
        },
    }, headers={"Accept": "text/event-stream"})

    assert response.status_code == 200
    assert '"kind":"status-update"' in response.text
    assert '"type":"tool.started"' in response.text
    assert '"state":"working"' in response.text
    assert '"state":"completed"' in response.text


def test_a2a_task_get_completes_without_codesynapse_metadata_or_jwt():
    store = InMemoryIntegrationStore()
    app = create_app(
        CodesynapseIntegrationSettings(a2a_public_url="http://testserver"),
        facade=CodesynapseFacade(store=store, executor=_Executor()),
        store=store,
    )
    with TestClient(app) as client:
        started = client.post("/", json={
            "jsonrpc": "2.0",
            "id": "request-1",
            "method": "message/send",
            "params": {
                "message": {"messageId": "message-1", "role": "user", "parts": [{"kind": "text", "text": "Find a hypothesis"}]},
                "configuration": {"blocking": False},
            },
        }).json()["result"]
        task = client.post("/", json={
            "jsonrpc": "2.0",
            "id": "request-2",
            "method": "tasks/get",
            "params": {"id": started["id"]},
        })

    assert task.status_code == 200
    assert task.json()["result"]["status"]["state"] == "completed"


def test_jwtless_app_keeps_capability_protected_control_plane():
    """Removing start-request JWT must not expose HITL/cancel/replay routes."""

    store = InMemoryIntegrationStore()
    app = create_app(
        CodesynapseIntegrationSettings(a2a_public_url="http://testserver"),
        facade=CodesynapseFacade(store=store, executor=_Executor()),
        store=store,
    )

    response = TestClient(app).post("/internal/runs/run-1/cancel")

    assert response.status_code == 401


def test_jwtless_app_installs_trace_delivery_for_capability_metadata():
    store = InMemoryIntegrationStore()
    facade = CodesynapseFacade(store=store, executor=_Executor())
    create_app(
        CodesynapseIntegrationSettings(a2a_public_url="http://testserver"),
        facade=facade,
        store=store,
    )

    dispatcher = facade._delivery_factory(
        StartRequest(
            external_run_id="external-1",
            tenant_id="root",
            project_id="project-1",
            research_request="Find a hypothesis",
            trace_callback_url="http://codesynapse.internal/events",
            trace_capability_token="trace-capability",
        )
    )

    assert dispatcher is not None
