"""Opt-in live test of the SAME adapter used by ReactorAgent.

Requires RUN_OPTIMIZATION_A2A_TEST=1 and OPTIMIZATION_A2A_INPUT=/path/input.json.
Input: a JSON object with structured_tz, literature_analysis, synthesis_routes,
economics_ranking and optional economics. Uses explicit planning-only mode;
never approves execution.
"""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from CoScientist.microfluidics.a2a_optimization import adapter
"""
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OPTIMIZATION_A2A_TEST") != "1",
    reason="Live A2A test requires explicit opt-in",
)


def test_optimization_handoff_without_equipment_execution():
    source = os.environ.get("OPTIMIZATION_A2A_INPUT")
    assert source, "Set OPTIMIZATION_A2A_INPUT to a reviewed input JSON file"
    inputs = json.loads(Path(source).read_text(encoding="utf-8"))
    assert isinstance(inputs, dict)
    adapter.prepare_inputs(inputs, planning_only=True)  # Validate what is sent, before sending.
    ctx = SimpleNamespace(state={key: inputs.get(key) for key in adapter.INPUT_KEYS})

    async def run():
        result = await adapter.optimization_start(ctx, planning_only=True)
        for _ in range(12):
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result["state"] not in {"submitted", "working"}:
                break
            await asyncio.sleep(5)
            result = await adapter.optimization_get_status(ctx)
        return result

    result = asyncio.run(run())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert result["state"] in {"completed", "input_required"}, result
    assert result.get("task_id")
    if result["state"] == "input_required":
        assert result["phase"] in {"approval", "waiting_input"}, result
    assert result["planning_only"] is True
    assert ctx.state[adapter.HISTORY_KEY][result["experiment_id"]]["response"]
"""