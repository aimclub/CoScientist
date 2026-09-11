"""FastAPI application factory for the CoScientist Codesynapse façade."""

from __future__ import annotations

from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from fastapi import HTTPException

from CoScientist.integrations.codesynapse.a2a_adapter import FacadeAgentExecutor, FacadeTaskStore, make_agent_card
from CoScientist.integrations.codesynapse.control_api import StoreCapabilityValidator, make_control_router
from CoScientist.integrations.codesynapse.delivery import TraceDeliveryClient, TraceOutboxDispatcher
from CoScientist.integrations.codesynapse.process_executor import ProcessManagerPipelineExecutor
from CoScientist.integrations.codesynapse.facade import CodesynapseFacade
from CoScientist.integrations.codesynapse.migrate import apply_indexes
from CoScientist.integrations.codesynapse.mongo_store import MongoIntegrationStore
from CoScientist.integrations.codesynapse.settings import CodesynapseIntegrationSettings


def create_app(
    settings: CodesynapseIntegrationSettings | None = None,
    *,
    facade: CodesynapseFacade | None = None,
    store=None,
):
    """Create the standard A2A façade for the CoScientist research pipeline."""

    settings = settings or CodesynapseIntegrationSettings()
    missing = settings.missing_readiness_requirements()
    if missing and facade is None:
        raise RuntimeError(f"Codesynapse façade is not configured: {', '.join(missing)}")
    database = None
    if facade is None:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(settings.mongo_uri)
        database = client[settings.mongo_database]
        store = MongoIntegrationStore(database)
        facade = CodesynapseFacade(store=store, executor=ProcessManagerPipelineExecutor())
    if store is None:
        raise ValueError("store is required when injecting a façade")

    if getattr(facade, "_delivery_factory", None) is None:
        def delivery_factory(request):
            if not request.trace_callback_url or not request.trace_capability_token:
                return None
            return TraceOutboxDispatcher(
                store,
                TraceDeliveryClient(
                    callback_url=request.trace_callback_url,
                    capability_token=request.trace_capability_token,
                ),
            )

        facade.set_delivery_factory(delivery_factory)

    handler = DefaultRequestHandler(
        agent_executor=FacadeAgentExecutor(facade),
        task_store=FacadeTaskStore(facade),
    )
    app = A2AFastAPIApplication(
        agent_card=make_agent_card(settings.a2a_public_url or "http://localhost:8010"),
        http_handler=handler,
    ).build()
    app.include_router(make_control_router(facade, store, StoreCapabilityValidator(store)))
    async def prepare_storage() -> None:
        if database is not None:
            await apply_indexes(database)
        # The façade deliberately has no resume semantics in the MVP. Persisted
        # non-terminal tasks become visibly interrupted before new A2A work is
        # accepted after a process restart.
        await facade.interrupt_non_terminal_tasks()

    app.router.on_startup.append(prepare_storage)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        missing_requirements = settings.missing_readiness_requirements()
        if missing_requirements:
            raise HTTPException(status_code=503, detail={"missing": missing_requirements})
        return {"status": "ready"}

    app.state.coscientist_facade = facade
    return app
