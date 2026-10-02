"""MooseChem cache/job isolation: Cyrillic prompts and per-job get_hypotheses."""
from __future__ import annotations

import asyncio
import re

from CoScientist.hypothesis_subsystem.moosechem_mcp_tool import (
    MooseChemMCPTool,
    checkpoint_dir_for_query,
)


def _legacy_ascii_slug(question: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", question[:40].lower()).strip("_") + "_mcp"


def test_cyrillic_prompts_do_not_collapse_to_the_same_checkpoint():
    q1 = "Как разработать адсорбционный материал для кристаллического фиолетового?"
    q2 = "Как образуются магнетит-(апатитовые) месторождения?"
    assert _legacy_ascii_slug(q1) == "_mcp"
    assert _legacy_ascii_slug(q2) == "_mcp"
    d1 = checkpoint_dir_for_query(q1)
    d2 = checkpoint_dir_for_query(q2)
    assert d1.startswith("hyp_") and d1.endswith("_mcp")
    assert d1 != d2


def test_same_question_reuses_the_same_checkpoint():
    q = "Как эффективно выделять и характеризовать экзосомы?"
    assert checkpoint_dir_for_query(q) == checkpoint_dir_for_query(q)


def test_background_survey_is_part_of_the_cache_key():
    q = "Which CMIP6 models for regional climate?"
    assert checkpoint_dir_for_query(q, "survey A") != checkpoint_dir_for_query(q, "survey B")


def test_get_hypotheses_sends_job_id_and_never_omits_it():
    tool = MooseChemMCPTool(mcp_url="http://example.invalid/mcp")
    captured = {}

    async def fake_call(session, tool_name, arguments, timeout_sec=30):
        captured["name"] = tool_name
        captured["arguments"] = arguments
        return {"metadata": {"hypotheses": []}}

    tool._call_tool = fake_call  # type: ignore[method-assign]
    asyncio.run(tool._get_hypotheses(session=None, max_hypotheses=3, job_id="job-own"))
    assert captured["name"] == "get_hypotheses"
    assert captured["arguments"]["job_id"] == "job-own"
    assert "evaluation_path" not in captured["arguments"]
