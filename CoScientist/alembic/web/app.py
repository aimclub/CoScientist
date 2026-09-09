"""Alembic dashboard FastAPI app.

Serves three HTML entry points and mounts the shared per-job build router
(``build_api.router``) that exposes JSON artifact reads, a log-tail WebSocket,
and the ``docker build``-able bundle download. All build execution goes through
:func:`CoScientist.tools.alembic_tools.build_mcp_server`, which spawns
``start_chain.py`` as a detached daemon subprocess with its own workdir under
``.alembic/a2a_builds/<job_id>/``. The web layer never runs the pipeline in
process, so no browser event (page close, refresh, navigation) can interrupt
a build.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The pipeline modules live as a top-level ``alembic`` package under
# CoScientist/alembic; add its parent to sys.path so ``from alembic import ...``
# works whether this module is imported from start_chain (which does the same)
# or embedded into the CoScientist web app.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

WEB_DIR = Path(__file__).parent
TEMPLATE_PATH = WEB_DIR / "templates" / "index.html"
BUILDS_LIST_PATH = WEB_DIR / "templates" / "builds_list.html"


def create_app() -> FastAPI:
    app = FastAPI(title="Alembic Pipeline Dashboard", version="3.0.0")

    # Shared per-job REST + WS router — mounted here and also included by the
    # main CoScientist web app under the /alembic prefix.
    from CoScientist.alembic.web.build_api import router as build_router
    app.include_router(build_router)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return TEMPLATE_PATH.read_text(encoding="utf-8")

    @app.get("/builds", response_class=HTMLResponse)
    async def builds_index():
        return BUILDS_LIST_PATH.read_text(encoding="utf-8")

    @app.get("/builds/{job_id}", response_class=HTMLResponse)
    async def build_page(job_id: str):
        # Same dashboard template — its JS reads the path and switches to
        # the per-job log-tail WS.
        return TEMPLATE_PATH.read_text(encoding="utf-8")

    return app
