"""Parallel assembly of the microfluidics ТЗ (TZSessionAgent.parallel_build).

The sections are split into SECTION_GROUPS and one worker per group fills its
part at the same time, each into its own state key; the parts are then put
together into state["structured_tz"]. Driven through the real ADK flow (Runner,
LlmAgent, FunctionTool) with a scripted model, so branch isolation, the
interleaving of concurrent runs and the state commits are the real ones.
"""
import asyncio
import re
from types import SimpleNamespace

import pytest
from google.adk.models import LlmResponse
from google.adk.models.base_llm import BaseLlm
from google.genai import types

from CoScientist.hitl.handler import AbstractHITLHandler
from CoScientist.hitl.models import HITLAction, HITLResponse
from CoScientist.microfluidics import tz_agent
from CoScientist.microfluidics.models import CANONICAL_BLOCKS
from CoScientist.microfluidics.tz_agent import TZSessionAgent
from CoScientist.microfluidics.tz_builder import (
    SECTION_GROUPS,
    TZ_STATE_KEY,
    agent_fill_pending,
    agent_fill_request,
    apply_group_fills,
    fill_tz_section,
    group_blocks,
    group_fill_delta,
    group_fill_key,
    group_part_key,
    load_tz,
    make_group_agent_fill_tool,
    make_group_fill_tool,
)

REQUEST = "Нужна антиокислительная присадка к моторному маслу."
_GROUP = {g.key: g for g in SECTION_GROUPS}


# ── the group tool ───────────────────────────────────────────────────────────

def _tool_context(state=None, invocation_id="inv-1"):
    return SimpleNamespace(
        state={} if state is None else state,
        invocation_id=invocation_id,
        function_call_id=None,
        session=None,
        user_content=types.Content(role="user", parts=[types.Part(text=REQUEST)]),
    )


def _fields(title):
    return [{"name": f"Поле раздела {title}", "value": "значение", "status": "задано заказчиком"}]


def test_groups_cover_every_section_once():
    grouped = [t for g in SECTION_GROUPS for t in g.sections]
    assert sorted(grouped) == sorted(CANONICAL_BLOCKS)
    assert len(grouped) == len(set(grouped))


def test_group_tool_saves_to_its_own_key_in_group_order():
    group = _GROUP["quality"]
    tool = make_group_fill_tool(group)
    ctx = _tool_context()

    first = tool(group.sections[0], "usage", _fields(group.sections[0]), ctx)

    assert first["status"] == "ok"
    assert first["progress"] == f"1/{len(group.sections)}"
    assert first["next_section"] == group.sections[1]
    assert TZ_STATE_KEY not in ctx.state  # the shared ТЗ is not touched
    assert [b.title for b in group_blocks(ctx.state, "inv-1", group)] == [group.sections[0]]


def test_group_tool_rejects_a_section_of_another_group():
    tool = make_group_fill_tool(_GROUP["quality"])
    ctx = _tool_context()

    result = tool("Тип задачи", "usage", _fields("Тип задачи"), ctx)

    assert result["status"] == "error"
    assert "заполняет другой агент" in result["errors"][0]
    assert result["expected_section"] == "Требуемые свойства"
    assert group_part_key(_GROUP["quality"]) not in ctx.state


def test_group_tool_keeps_the_order_within_the_group():
    group = _GROUP["limits"]
    tool = make_group_fill_tool(group)
    ctx = _tool_context()

    result = tool(group.sections[2], "usage", _fields(group.sections[2]), ctx)

    assert result["status"] == "error"
    assert "строго по порядку" in result["errors"][0]


def test_group_tool_completes_its_part():
    group = _GROUP["quality"]
    tool = make_group_fill_tool(group)
    ctx = _tool_context()
    results = [tool(t, "usage", _fields(t), ctx) for t in group.sections]

    assert results[-1]["status"] == "complete"
    assert tool(group.sections[0], "usage", _fields("x"), ctx)["status"] == "error"


def test_sequential_tool_still_fills_the_whole_tz_in_order():
    ctx = _tool_context()
    results = [fill_tz_section(t, "usage", _fields(t), ctx) for t in CANONICAL_BLOCKS]

    assert [r["status"] for r in results[:-1]] == ["ok"] * (len(CANONICAL_BLOCKS) - 1)
    assert results[-1]["status"] == "complete"
    tz = load_tz(ctx.state[TZ_STATE_KEY])
    assert [b.title for b in tz.blocks] == list(CANONICAL_BLOCKS)
    assert tz.original_request == REQUEST


def _full_tz_state():
    ctx = _tool_context()
    for t in CANONICAL_BLOCKS:
        fill_tz_section(t, "usage", [
            {"name": _field(t), "value": "Не задано", "status": "не задано"}
        ], ctx)
    return ctx


def test_fill_request_is_shared_out_by_part_and_merged_back():
    request = agent_fill_request("inv-1", [
        ("Целевой продукт", ["a"]), ("Критерии качества", ["b"]),
        ("Аналитические методы", ["c"]), ("Форма результата", ["d"]),
    ])
    state = group_fill_delta(request)

    task, quality, limits = (state[group_fill_key(_GROUP[k])] for k in ("task", "quality", "limits"))
    assert [p["section"] for p in task["pending"]] == ["Целевой продукт", "Форма результата"]
    assert [p["section"] for p in quality["pending"]] == ["Критерии качества", "Аналитические методы"]
    assert limits is None
    merged = agent_fill_pending(state, "inv-1")
    assert merged["total"] == 4
    assert [p["section"] for p in merged["pending"]] == [
        "Целевой продукт", "Критерии качества", "Аналитические методы", "Форма результата",
    ]
    assert agent_fill_pending(state, "another-invocation") is None


def test_group_fill_tool_keeps_values_in_its_share():
    from CoScientist.hitl.field_status import AGENT_FILLED_STATUS

    ctx = _full_tz_state()
    section = "Критерии качества"
    ctx.state.update(group_fill_delta(agent_fill_request("inv-1", [(section, [_field(section)])])))
    tool = make_group_agent_fill_tool(_GROUP["quality"])

    result = tool(section, [{"name": _field(section), "value": "99 %"}], ctx)

    assert result["status"] == "complete"
    tz = load_tz(ctx.state[TZ_STATE_KEY])
    assert _agent_value(tz, section) == ("Не задано", "не задано")  # ТЗ untouched
    assert agent_fill_pending(ctx.state, "inv-1") is None
    filled = apply_group_fills(ctx.state, "inv-1", tz)
    assert _agent_value(filled, section) == ("99 %", AGENT_FILLED_STATUS)
    assert apply_group_fills(ctx.state, "inv-1", filled) == filled  # idempotent


def test_group_fill_tool_refuses_fields_of_another_part():
    ctx = _full_tz_state()
    ctx.state.update(group_fill_delta(agent_fill_request("inv-1", [
        ("Целевой продукт", [_field("Целевой продукт")]),
    ])))
    tool = make_group_agent_fill_tool(_GROUP["quality"])

    result = tool("Целевой продукт", [{"name": _field("Целевой продукт"), "value": "x"}], ctx)

    assert result["status"] == "error"
    assert "в вашей части" in result["errors"][0]


# ── end to end, through the real ADK flow ────────────────────────────────────

class _SectionLlm(BaseLlm):
    """Fills the sections its prompt assigns to it — one per call, the one the
    last tool answer named. Records who called, how many calls overlapped and
    every tool error, and can fail one worker's n-th call."""

    calls: dict = {}
    errors: list = []
    in_flight: int = 0
    max_in_flight: int = 0
    fail_at: dict = {}
    saw_corrections: dict = {}
    parent_context: list = []
    fill_instructions: list = []
    fill_in_flight: int = 0
    fill_max_in_flight: int = 0

    async def generate_content_async(self, llm_request, stream: bool = False):
        instruction = str(llm_request.config.system_instruction or "")
        group = next(
            (g for g in SECTION_GROUPS if f"ТВОЯ ЧАСТЬ — «{g.title}»" in instruction),
            None,
        )
        filling = "Часть полей он оставил ПУСТЫМИ" in instruction
        key = (f"{group.key}_fill" if filling else group.key) if group else "sequential"
        order = group.sections if group else CANONICAL_BLOCKS
        self.calls[key] = self.calls.get(key, 0) + 1

        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.fill_in_flight += filling
        self.fill_max_in_flight = max(self.fill_max_in_flight, self.fill_in_flight)
        try:
            await asyncio.sleep(0.02)  # let the other workers' calls overlap
        finally:
            self.in_flight -= 1
            self.fill_in_flight -= filling
        if self.fail_at.get(key) == self.calls[key]:
            raise RuntimeError(f"LLM outage for {key}")

        if filling:
            # A part's worker filling operator-left fields: its prompt always
            # lists what is still left, the next section first.
            self.fill_instructions.append(instruction)
            left = re.search(r"^- «(.+?)»: (.+)$", instruction, re.M)
            if left is None:
                yield _text("Поля моей части дозаполнены.")
                return
            yield _agent_fill_call(left.group(1), re.findall(r"«(.+?)»", left.group(2)))
            return

        # The tool answers since the operator's last corrections: a rewrite
        # starts the part over.
        responses = []
        agent_fill = None
        for part in (p for c in llm_request.contents or [] for p in (c.parts or [])):
            if part.text and "Оператор прислал правки" in part.text:
                self.saw_corrections[key] = True
                responses = []
            elif part.text and "Оператор проверил ТЗ" in part.text:
                agent_fill, responses = part.text, []
            elif part.function_response:
                responses.append(part.function_response.response)

        if agent_fill is not None:
            # The ТЗ agent itself, filling the fields the operator left empty.
            self.parent_context.append(" ".join(
                p.text or "" for c in llm_request.contents or [] for p in (c.parts or [])
            ))
            if responses and responses[-1].get("status") == "complete":
                yield _text("Поля дозаполнены.")
                return
            section, names = re.search(r"— «(.+?)», поля: (.+?) \(вызов", agent_fill).groups()
            yield _agent_fill_call(section, re.findall(r"«(.+?)»", names))
            return
        for response in responses:
            if response.get("status") == "error":
                self.errors.append((key, response))

        last = responses[-1] if responses else None
        if last and last.get("status") == "complete":
            yield _text("Готово.")
            return
        if last and last.get("status") == "ok":
            title = last["next_section"]
        elif last and last.get("status") == "error" and last.get("expected_section"):
            title = last["expected_section"]
        else:
            title = order[0]
        yield _call(title)


def _call(title):
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(
        function_call=types.FunctionCall(
            name="fill_tz_section",
            args={"section": title, "usage": "дальше по пайплайну", "fields": _fields(title)},
        )
    )]))


def _agent_fill_call(section, names):
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(
        function_call=types.FunctionCall(
            name="fill_agent_fields",
            args={"section": section,
                  "fields": [{"name": n, "value": "рабочее значение"} for n in names]},
        )
    )]))


def _text(text):
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _model(**kwargs):
    return _SectionLlm(
        model="scripted", calls={}, errors=[], fail_at={}, saw_corrections={},
        parent_context=[], fill_instructions=[], **kwargs
    )


# The ТЗ agent as the runner's root goes through ADK's node runtime; wrapped
# in a SequentialAgent (as in the profile, where an AgentTool runs module A) it
# goes through the classic one. Both must hold.
RUNTIMES = pytest.mark.parametrize("wrapped", [False, True], ids=["node", "sequential"])


def _run(agent, wrapped=False):
    from google.adk.agents import SequentialAgent
    from google.adk.runners import InMemoryRunner

    root = SequentialAgent(name="TZAgent", sub_agents=[agent]) if wrapped else agent

    async def drive():
        runner = InMemoryRunner(agent=root, app_name="t")
        session = await runner.session_service.create_session(app_name="t", user_id="u")
        async for _ in runner.run_async(
            user_id="u", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=REQUEST)]),
        ):
            pass
        return await runner.session_service.get_session(
            app_name="t", user_id="u", session_id=session.id
        )

    return asyncio.run(drive())


def _agent(model, **kwargs):
    from google.adk.tools import FunctionTool
    from CoScientist.microfluidics.tz_builder import fill_agent_fields

    return TZSessionAgent(
        name="TZSpecAgent", model=model, instruction="Заполни ТЗ.",
        tools=[FunctionTool(fill_tz_section), FunctionTool(fill_agent_fields)],
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _documents_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(tz_agent, "TZ_DOCUMENTS_DIR", tmp_path)


@RUNTIMES
def test_workers_fill_their_parts_at_the_same_time(wrapped):
    model = _model()
    session = _run(_agent(model), wrapped)

    tz = load_tz(session.state[TZ_STATE_KEY])
    assert [b.title for b in tz.blocks] == list(CANONICAL_BLOCKS)
    assert tz.original_request == REQUEST
    # Every worker saw only its own branch: no call was ever rejected.
    assert model.errors == []
    # One call per section plus the closing line, per worker — no sequential pass.
    assert model.calls == {g.key: len(g.sections) + 1 for g in SECTION_GROUPS}
    assert model.max_in_flight == len(SECTION_GROUPS)


def test_a_failed_worker_is_rerun_alone_from_where_it_stopped():
    model = _model()
    model.fail_at = {"quality": 2}  # one section saved, then the LLM fails
    session = _run(_agent(model))

    tz = load_tz(session.state[TZ_STATE_KEY])
    assert [b.title for b in tz.blocks] == list(CANONICAL_BLOCKS)
    assert model.errors == []
    quality = len(_GROUP["quality"].sections)
    assert model.calls == {
        "task": len(_GROUP["task"].sections) + 1,
        "limits": len(_GROUP["limits"].sections) + 1,
        # 1 saved + the failed call, then the remaining sections + closing line.
        "quality": 2 + (quality - 1) + 1,
    }


def test_sequential_build_is_kept_behind_the_flag():
    model = _model()
    session = _run(_agent(model, parallel_build=False))

    tz = load_tz(session.state[TZ_STATE_KEY])
    assert [b.title for b in tz.blocks] == list(CANONICAL_BLOCKS)
    assert model.calls == {"sequential": len(CANONICAL_BLOCKS) + 1}
    assert model.errors == []


class _EditThenApprove(AbstractHITLHandler):
    """The console flow: free-text corrections first, then approval."""

    def __init__(self):
        self.requests = []

    async def handle_request(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            return HITLResponse(action=HITLAction.EDIT, instructions="Масса образца — 5 г.")
        return HITLResponse(action=HITLAction.APPROVE, approved=True)


@RUNTIMES
def test_corrections_rebuild_every_part_with_the_workers(monkeypatch, wrapped):
    from CoScientist.config import get_settings

    monkeypatch.setattr(get_settings().web, "hitl_enabled", True)
    model = _model()
    handler = _EditThenApprove()
    session = _run(_agent(model, hitl_handler=handler), wrapped)

    assert len(handler.requests) == 2
    tz = load_tz(session.state[TZ_STATE_KEY])
    assert [b.title for b in tz.blocks] == list(CANONICAL_BLOCKS)
    # Each worker ran its part twice and saw the operator's corrections.
    assert model.calls == {g.key: 2 * (len(g.sections) + 1) for g in SECTION_GROUPS}
    assert model.saw_corrections == {g.key: True for g in SECTION_GROUPS}
    assert model.errors == []


class _LeaveFieldsThenApprove(AbstractHITLHandler):
    """The web form: the operator clears fields for the agent, then approves."""

    def __init__(self, *sections):
        self.sections = sections
        self.requests = []

    async def handle_request(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            return HITLResponse(
                action=HITLAction.APPROVE, approved=True,
                form_values={s: {_field(s): ""} for s in self.sections},
            )
        return HITLResponse(action=HITLAction.APPROVE, approved=True)


def _field(section):
    return f"Поле раздела {section}"


def _agent_value(tz, section):
    row = next(f for f in tz.block(section).fields if f.name == _field(section))
    return row.value, row.status


@RUNTIMES
def test_fields_left_by_the_operator_are_filled_by_the_part_workers(monkeypatch, wrapped):
    from CoScientist.config import get_settings
    from CoScientist.hitl.field_status import AGENT_FILLED_STATUS

    monkeypatch.setattr(get_settings().web, "hitl_enabled", True)
    # One field in «Задача и продукт», one in «Свойства и качество».
    sections = ("Целевой продукт", "Аналитические методы")
    model = _model()
    handler = _LeaveFieldsThenApprove(*sections)
    session = _run(_agent(model, hitl_handler=handler), wrapped)

    assert len(handler.requests) == 2
    tz = load_tz(session.state[TZ_STATE_KEY])
    for section in sections:
        assert _agent_value(tz, section) == ("рабочее значение", AGENT_FILLED_STATUS)
    # The two parts' fill workers ran at the same time: one section + the
    # closing line each; the ТЗ agent's own LLM was never called.
    assert model.calls == {
        **{g.key: len(g.sections) + 1 for g in SECTION_GROUPS},
        "task_fill": 2,
        "quality_fill": 2,
    }
    assert model.fill_max_in_flight == 2
    assert model.errors == []
    # A fill worker sees the whole current ТЗ, other parts included.
    assert "Поле раздела Ограничения по сырью" in model.fill_instructions[0]
    # The second review round shows the fields as filled by the agent.
    fields = {
        f["name"]: f for s in handler.requests[1].form["sections"] for f in s["fields"]
    }
    assert all(fields[_field(s)]["agent_filled"] for s in sections)


def test_sequential_agent_fill_is_kept_behind_the_flag(monkeypatch):
    from CoScientist.config import get_settings
    from CoScientist.hitl.field_status import AGENT_FILLED_STATUS

    monkeypatch.setattr(get_settings().web, "hitl_enabled", True)
    section = "Целевой продукт"
    model = _model()
    handler = _LeaveFieldsThenApprove(section)
    session = _run(_agent(model, hitl_handler=handler, parallel_build=False))

    tz = load_tz(session.state[TZ_STATE_KEY])
    assert _agent_value(tz, section) == ("рабочее значение", AGENT_FILLED_STATUS)
    # The ТЗ agent's own LLM: 16 sections + closing line, then 1 fill + closing.
    assert model.calls == {"sequential": len(CANONICAL_BLOCKS) + 1 + 2}
    assert model.errors == []


def test_a_failed_fill_worker_is_rerun_alone(monkeypatch):
    from CoScientist.config import get_settings
    from CoScientist.hitl.field_status import AGENT_FILLED_STATUS

    monkeypatch.setattr(get_settings().web, "hitl_enabled", True)
    sections = ("Целевой продукт", "Аналитические методы")
    model = _model()
    model.fail_at = {"task_fill": 1}
    handler = _LeaveFieldsThenApprove(*sections)
    session = _run(_agent(model, hitl_handler=handler))

    tz = load_tz(session.state[TZ_STATE_KEY])
    for section in sections:
        assert _agent_value(tz, section) == ("рабочее значение", AGENT_FILLED_STATUS)
    assert model.calls["quality_fill"] == 2  # not run again
    assert model.calls["task_fill"] == 1 + 2  # the failed call, then the rerun


class _LeaveOneMarkOneThenApprove(AbstractHITLHandler):
    """Round 1: one field left to the agent, one marked «не задавать».
    Round 2: the form is sent back as shown."""

    def __init__(self, to_agent, not_required):
        self.to_agent, self.not_required = to_agent, not_required
        self.requests = []

    async def handle_request(self, request):
        from CoScientist.hitl.field_status import NOT_REQUIRED_VALUE

        self.requests.append(request)
        if len(self.requests) == 1:
            return HITLResponse(action=HITLAction.APPROVE, approved=True, form_values={
                self.to_agent: {_field(self.to_agent): ""},
                self.not_required: {_field(self.not_required): NOT_REQUIRED_VALUE},
            })
        fields = {
            s["title"]: {f["name"]: f["value"] for f in s["fields"]}
            for s in request.form["sections"]
        }
        return HITLResponse(action=HITLAction.APPROVE, approved=True, form_values=fields)


def test_a_field_marked_not_required_is_never_filled_by_the_agent(monkeypatch):
    from CoScientist.config import get_settings
    from CoScientist.hitl.field_status import (
        AGENT_FILLED_STATUS,
        NOT_REQUIRED_STATUS,
        NOT_REQUIRED_VALUE,
    )

    monkeypatch.setattr(get_settings().web, "hitl_enabled", True)
    to_agent, not_required = "Целевой продукт", "Аналитические методы"
    model = _model()
    handler = _LeaveOneMarkOneThenApprove(to_agent, not_required)
    session = _run(_agent(model, hitl_handler=handler))

    assert len(handler.requests) == 2
    tz = load_tz(session.state[TZ_STATE_KEY])
    assert _agent_value(tz, to_agent) == ("рабочее значение", AGENT_FILLED_STATUS)
    assert _agent_value(tz, not_required) == (NOT_REQUIRED_VALUE, NOT_REQUIRED_STATUS)
    # Only the part with the field left to the agent had anything to fill.
    assert "quality_fill" not in model.calls
    assert model.calls["task_fill"] == 2
    # The second round shows it as not required, not as awaiting.
    field = next(
        f for s in handler.requests[1].form["sections"] for f in s["fields"]
        if f["name"] == _field(not_required)
    )
    assert field["not_required"] and not field["awaiting"]
