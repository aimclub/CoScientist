"""The meta-agent config recovery plugin.

Covers the dominant FEDOT failure mode on this stand: the model answers, but the
answer is not a clean JSON text part, so ADK never fills output_key and
_execute_meta_call raises "<agent> did not produce '<key>' in session state" —
82 of 88 config-generation failures measured on 2026-09-01.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from google.genai import types

from CoScientist.tools.fedot_mas_patch import MetaJsonRecoveryPlugin

CONFIG = {
    "agents": [{"name": "a1", "instruction": "run it", "output_key": "o1"}],
    "pipeline": {"type": "agent", "agent_name": "a1"},
}


class _MetaAgent:
    """A meta agent: ADK stores its answer against a schema."""

    name = "pool_generator"
    output_schema = object()


class _Worker:
    """A pipeline worker: free-text answer, nothing to store."""

    name = "interval_estimator"
    output_schema = None


def _ctx(agent):
    return SimpleNamespace(
        agent_name=agent.name,
        get_invocation_context=lambda: SimpleNamespace(agent=agent),
    )


META = _ctx(_MetaAgent())


def _response(parts):
    return SimpleNamespace(content=types.Content(role="model", parts=parts))


def _run(plugin, response, ctx=None):
    return asyncio.run(
        plugin.after_model_callback(callback_context=ctx or META, llm_response=response)
    )


def test_recovers_json_parked_in_a_thought_part():
    """GLM, the model configured for the meta agents, does exactly this."""
    plugin = MetaJsonRecoveryPlugin()
    out = _run(plugin, _response([
        types.Part(text="Let me design the pool.", thought=True),
        types.Part(text=json.dumps(CONFIG), thought=True),
    ]))
    assert out is not None
    assert json.loads(out.content.parts[0].text) == CONFIG
    assert plugin.repaired == ["pool_generator"]


def test_recovers_json_wrapped_in_a_fence_with_preamble():
    plugin = MetaJsonRecoveryPlugin()
    out = _run(plugin, _response([
        types.Part(text="Here is the pipeline:\n```json\n" + json.dumps(CONFIG) + "\n```\nDone."),
    ]))
    assert out is not None
    assert json.loads(out.content.parts[0].text) == CONFIG


def test_leaves_a_clean_answer_untouched():
    plugin = MetaJsonRecoveryPlugin()
    assert _run(plugin, _response([types.Part(text=json.dumps(CONFIG))])) is None
    assert plugin.repaired == []


def test_leaves_a_tool_call_untouched():
    plugin = MetaJsonRecoveryPlugin()
    call = types.Part.from_function_call(name="some_tool", args={})
    assert _run(plugin, _response([call])) is None


def test_invents_nothing_when_there_is_no_json():
    """A genuine refusal must still surface as the original error, not a fake config."""
    plugin = MetaJsonRecoveryPlugin()
    assert _run(plugin, _response([
        types.Part(text="I cannot design a pipeline for this task."),
    ])) is None
    assert plugin.repaired == []


def test_empty_response_is_a_pass_through():
    plugin = MetaJsonRecoveryPlugin()
    assert _run(plugin, SimpleNamespace(content=None)) is None


def test_leaves_a_pipeline_worker_alone():
    """Plugins reach the pipeline agents too, and a worker's prose must survive.

    Regression for 2026-09-02, when an unscoped version of this plugin rewrote
    worker answers — "rebuilt experiment_executor config from the text part" and
    "rebuilt interval_estimator config from the thought part" — replacing a prose
    report that merely contained JSON with the JSON alone, discarding the
    narrative the caller actually reads.
    """
    plugin = MetaJsonRecoveryPlugin()
    worker_answer = _response([
        types.Part(
            text="I ran the tool and got:\n```json\n"
            + json.dumps(CONFIG)
            + "\n```\nR2 for the test sample was 0.91."
        ),
    ])
    assert _run(plugin, worker_answer, ctx=_ctx(_Worker())) is None
    assert plugin.repaired == []
    # …while the same answer from a schema-bound meta agent is still recovered.
    assert _run(plugin, worker_answer) is not None


def test_unreachable_agent_is_left_alone():
    """Fail closed: no agent visible means no rewrite."""
    plugin = MetaJsonRecoveryPlugin()
    bare = SimpleNamespace(agent_name="x")
    prose = _response([types.Part(text='prose ```json\n{"a": 1}\n```')])
    assert _run(plugin, prose, ctx=bare) is None
