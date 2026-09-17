"""Live contract of the CFD MCP service — what EquipmentAgent relies on.

The tool docs (assembly/bindings.py: cfd_mcp), the equipment prompt and the
state collector (microfluidics/cfd.py) were written against the answers
recorded in tests/fixtures/cfd_mcp/. This checks the live service still gives
them: the five tools and their required arguments, the reactor list, the
asynchronous run (pending -> fetched by request_id -> cancelled) and the error
answer for an unknown run.

Starts a solver run: safe ONLY on the emulator deployment. The service runs one
experiment at a time — do not run this next to another CFD test.

Needs MCP_MICROFLUIDIC_CFD_3_TOOLS, MICROFLUIDIC_CFD_3_TOOLS_KEY and the network;
skipped otherwise. Run from the repo root:

    pytest tests/integration/test_cfd_mcp_contract.py -q -s
"""
import asyncio
import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("MCP_MICROFLUIDIC_CFD_3_TOOLS")
KEY = os.getenv("MICROFLUIDIC_CFD_3_TOOLS_KEY")
pytestmark = pytest.mark.skipif(not (URL and KEY), reason="CFD service is not configured")

REQUIRED = {
    "cfd_list_reactors": set(),
    "cfd_run_reactor_experiment": {"reactor", "inlet_speed_m_per_s"},
    "cfd_get_experiment_result": {"request_id"},
    "cfd_list_artifacts": {"request_id"},
    "cfd_cancel_run": {"request_id"},
}
RESULT_KEYS = {"request_id", "status", "finished", "design", "derived", "results",
               "trustworthy", "blocking", "stages", "error"}


async def _session(calls):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(
        URL, headers={"X-API-Key": KEY}, timeout=30, sse_read_timeout=900
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            results = [await session.call_tool(name, args) for name, args in calls]
            return tools, results


def _run(calls=()):
    try:
        return asyncio.run(_session(list(calls)))
    except OSError as exc:
        pytest.skip(f"CFD service unreachable: {exc}")


def test_tools_and_required_arguments():
    tools, _ = _run()
    schemas = {t.name: t.inputSchema for t in tools}
    for name, required in REQUIRED.items():
        assert name in schemas, f"the service has no {name}"
        assert set(schemas[name].get("required", [])) == required, name


def test_reactor_list():
    _, (result,) = _run([("cfd_list_reactors", {})])
    reactors = result.structuredContent["reactors"]
    two_feed = [r for r in reactors if r["zones"]["supports_two_reactant_feed"] and r["available"]]
    assert two_feed, "no available reactor can host an A + B reaction"


def test_a_run_is_asynchronous_and_can_be_cancelled():
    request_id = f"contract-{uuid.uuid4().hex[:8]}"
    args = {"reactor": "t_junction", "inlet_speed_m_per_s": 0.02,
            "concentration_a_mol_per_m3": 100.0, "concentration_b_mol_per_m3": 100.0,
            "rate_constant_m3_per_mol_s": 0.01, "wait_seconds": 0, "request_id": request_id}
    _, (started, fetched, cancelled) = _run([
        ("cfd_run_reactor_experiment", args),
        ("cfd_get_experiment_result", {"request_id": request_id}),
        ("cfd_cancel_run", {"request_id": request_id}),
    ])
    if started.isError and "capacity_exceeded" in started.content[0].text:
        pytest.skip("the service is busy with another run")
    assert not started.isError, started.content[0].text
    assert RESULT_KEYS <= set(started.structuredContent)
    assert started.structuredContent["request_id"] == request_id
    assert started.structuredContent["status"] in {"pending", "succeeded", "failed"}
    assert fetched.structuredContent["request_id"] == request_id
    assert {"cancelled", "already_terminal"} <= set(cancelled.structuredContent)


def test_an_unknown_run_is_an_is_error_answer():
    _, (result,) = _run([("cfd_get_experiment_result", {"request_id": "no-such-run"})])
    assert result.isError
    assert "request_not_found" in result.content[0].text
