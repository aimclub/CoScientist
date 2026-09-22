"""Execution-isolation tests for the Codesynapse façade pipeline adapter."""

import asyncio
import sys
from types import ModuleType, SimpleNamespace

from CoScientist.integrations.codesynapse.executor import ManagerPipelineExecutor


def test_manager_pipeline_keeps_the_a2a_control_loop_responsive(monkeypatch):
    observed_loops = []

    class Manager:
        def __init__(self, **_kwargs):
            pass

        async def run(self, _request, verbose):
            observed_loops.append(asyncio.get_running_loop())
            return "report"

        async def close(self):
            return None

    fake_main = ModuleType("CoScientist.main")
    fake_main.CoScientistManager = Manager
    monkeypatch.setitem(sys.modules, "CoScientist.main", fake_main)

    async def scenario():
        control_loop = asyncio.get_running_loop()
        result = await ManagerPipelineExecutor().execute(
            SimpleNamespace(
                coscientist_run_id="run-1",
                tenant_id="tenant-1",
                research_request="Find a hypothesis",
                trace_recorder=None,
            ),
            hitl_handler=object(),
        )

        assert result == "report"
        assert len(observed_loops) == 1
        assert observed_loops[0] is not control_loop

    asyncio.run(scenario())
