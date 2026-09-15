"""Run the dedicated Codesynapse CoScientist façade service."""

from __future__ import annotations

import os

import uvicorn

from CoScientist.integrations.codesynapse.app import create_app


def create_app_for_uvicorn():
    """Create one independent application instance in each Uvicorn worker."""

    return create_app()


def _worker_count() -> int:
    """Use one owner for process-local jobs, HITL futures and subscriptions."""

    configured = int(os.getenv("CODESYNAPSE_A2A_WORKERS", "1"))
    if configured != 1:
        raise ValueError(
            "CODESYNAPSE_A2A_WORKERS must be 1: façade run and HITL state "
            "is owned by a single process"
        )
    return configured


def main() -> None:
    uvicorn.run(
        "CoScientist.integrations.codesynapse.__main__:create_app_for_uvicorn",
        factory=True,
        host="0.0.0.0",
        port=8010,
        log_level="info",
        workers=_worker_count(),
    )


if __name__ == "__main__":
    main()
