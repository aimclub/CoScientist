"""Work Order tools: how a contract is put before the human, and what the agent
is told back."""
import asyncio
from types import SimpleNamespace

import pytest

from CoScientist.config import get_settings
from CoScientist.hitl.models import HITLAction, HITLResponse
from CoScientist.hitl.work_order import load_order, usage_key
from CoScientist.hitl.work_order_tools import WorkOrderToolset

AGENT = "DatasetCollectorAgent"
TOOLS = ["tavily_search", "execute_bash", "read_file", "install_package", "research_commit"]


class _Handler:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.notices = []

    async def handle_request(self, request):
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else HITLResponse(
            action=HITLAction.APPROVE, approved=True
        )

    async def notify(self, payload):
        self.notices.append(payload)


def _context(state=None):
    state = {} if state is None else state
    session = SimpleNamespace(id="s1", user_id="u1", state=state)
    return SimpleNamespace(state=state, session=session,
                           _invocation_context=SimpleNamespace(session=session))


@pytest.fixture
def hitl_on(monkeypatch):
    web = get_settings().web
    monkeypatch.setattr(web, "hitl_enabled", True)
    monkeypatch.setattr(web, "work_order_enabled", True)
    monkeypatch.setattr(web, "work_order_veto_seconds", 30)
    monkeypatch.setattr(web, "work_order_max_amendments", 3)
    return web


def _declare(toolset, ctx, **overrides):
    args = dict(
        goal="Collect BTK inhibitors with IC50 from ChEMBL",
        done_criteria="A CSV with >= 500 unique compounds",
        assumptions=[
            {"text": "IC50 in nM", "confidence": "high"},
            {"text": "Only human BTK (CHEMBL5251)", "confidence": "medium"},
        ],
        steps=[
            {"title": "Download activities", "tools": ["execute_bash"],
             "expected_outcome": "~2k rows"},
            {"title": "Deduplicate", "tools": ["execute_bash"]},
        ],
        planned_tools=["execute_bash"],
        tool_context=ctx,
    )
    args.update(overrides)
    return asyncio.run(toolset.declare_work_order(**args))


def test_switched_off_approves_without_asking_but_still_records_the_order(monkeypatch):
    monkeypatch.setattr(get_settings().web, "hitl_enabled", False)
    handler = _Handler()
    ctx = _context()
    result = _declare(WorkOrderToolset(AGENT, TOOLS, handler), ctx)

    assert result["status"] == "approved"
    assert result["mode"] == "autonomous"
    assert handler.requests == [] and handler.notices == []
    assert load_order(ctx.state, AGENT).status == "approved"


def test_read_tier_is_a_notice_not_a_question(hitl_on):
    handler = _Handler()
    ctx = _context()
    result = _declare(WorkOrderToolset(AGENT, TOOLS, handler), ctx,
                      steps=[{"title": "Search", "tools": ["tavily_search"]}],
                      planned_tools=["tavily_search"])

    assert result["status"] == "approved"
    assert handler.requests == []
    assert handler.notices[0]["kind"] == "declared"
    assert handler.notices[0]["_session"] == {"user_id": "u1", "session_id": "s1"}


def test_compute_tier_gets_the_veto_window(hitl_on):
    handler = _Handler()
    _declare(WorkOrderToolset(AGENT, TOOLS, handler), _context())

    request = handler.requests[0]
    assert request.trigger == "work_order"
    assert request.timeout_seconds == 30
    assert request.context["tier"] == "compute"
    order = request.context["work_order"]
    assert [a["id"] for a in order["assumptions"]] == ["A1", "A2"]
    assert order["assumptions"][0] == {
        "id": "A1", "text": "IC50 in nM", "confidence": "high", "rejected": False,
    }
    assert [s["id"] for s in order["steps"]] == ["S1", "S2"]


def test_compute_tier_without_veto_window_waits_for_the_human(hitl_on, monkeypatch):
    monkeypatch.setattr(hitl_on, "work_order_veto_seconds", -1)
    handler = _Handler()
    _declare(WorkOrderToolset(AGENT, TOOLS, handler), _context())

    # A non-positive timeout means no deadline in the handler (not the global timeout).
    assert handler.requests[0].timeout_seconds == -1


def test_side_effect_tier_blocks_under_the_global_timeout(hitl_on):
    handler = _Handler()
    ctx = _context()
    _declare(WorkOrderToolset(AGENT, TOOLS, handler), ctx,
             planned_tools=["execute_bash", "install_package"])

    request = handler.requests[0]
    assert request.timeout_seconds is None
    assert request.context["tier"] == "side_effect"
    # install_package declares its own side effect.
    assert request.context["work_order"]["side_effects"][0]["kind"] == "package_install"


def test_approval_carries_rejected_assumptions_and_operator_notes(hitl_on):
    handler = _Handler(HITLResponse(
        action=HITLAction.APPROVE, approved=True,
        instructions="Use only pChEMBL values",
        form_values={"rejected_assumption_ids": ["A2"]},
    ))
    ctx = _context()
    result = _declare(WorkOrderToolset(AGENT, TOOLS, handler), ctx)

    assert result["status"] == "approved"
    assert result["rejected_assumptions"] == ["Only human BTK (CHEMBL5251)"]
    assert result["operator_notes"] == "Use only pChEMBL values"
    order = load_order(ctx.state, AGENT)
    assert [a.rejected for a in order.assumptions] == [False, True]
    assert ctx.state[usage_key(AGENT)] == {}


def test_revise_asks_for_a_new_declaration_and_records_nothing(hitl_on):
    handler = _Handler(HITLResponse(action=HITLAction.EDIT, approved=False,
                                    instructions="Add PubChem as a second source"))
    ctx = _context()
    result = _declare(WorkOrderToolset(AGENT, TOOLS, handler), ctx)

    assert result["status"] == "revise"
    assert result["feedback"] == "Add PubChem as a second source"
    assert load_order(ctx.state, AGENT) is None


def test_reject_records_a_rejected_order_that_cannot_be_redeclared(hitl_on):
    handler = _Handler(HITLResponse(action=HITLAction.REJECT, approved=False,
                                    instructions="Not needed"))
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, handler)
    result = _declare(toolset, ctx)

    assert result["status"] == "rejected"
    assert load_order(ctx.state, AGENT).status == "rejected"
    assert _declare(toolset, ctx)["status"] == "rejected"
    assert len(handler.requests) == 1


def test_unknown_tools_are_refused(hitl_on):
    toolset = WorkOrderToolset(AGENT, TOOLS, _Handler())
    unknown = _declare(toolset, _context(), planned_tools=["execute_bash", "git_push"])
    assert unknown["status"] == "error" and "git_push" in unknown["message"]


def test_step_tools_join_the_planned_tools(hitl_on):
    ctx = _context()
    _declare(WorkOrderToolset(AGENT, TOOLS, _Handler()), ctx,
             steps=[{"title": "Read", "tools": ["read_file"]}],
             planned_tools=["execute_bash"])
    assert load_order(ctx.state, AGENT).planned_tools == ["execute_bash", "read_file"]


def test_an_approved_order_is_amended_not_redeclared(hitl_on):
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, _Handler())
    _declare(toolset, ctx)
    again = _declare(toolset, ctx)
    assert again["status"] == "error" and "update_work_order" in again["message"]


def test_amendment_is_reviewed_by_the_tier_of_what_it_adds(hitl_on):
    handler = _Handler()
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, handler)
    _declare(toolset, ctx)

    # Adding a read tool: a notice, no question.
    result = asyncio.run(toolset.update_work_order(
        reason="Need the ChEMBL target id", add_tools=["tavily_search"],
        tool_context=ctx,
    ))
    assert result == {"status": "approved", "revision": 2,
                      "message": "Amendment approved. Proceed within the updated work order."}
    assert handler.notices[-1]["kind"] == "amended"
    assert handler.notices[-1]["diff"]["added_tools"] == ["tavily_search"]

    # Adding a side effect: a blocking review showing the diff and the reason.
    asyncio.run(toolset.update_work_order(
        reason="rdkit is missing", add_tools=["install_package"], tool_context=ctx,
    ))
    request = handler.requests[-1]
    assert request.trigger == "work_order_amendment"
    assert request.timeout_seconds is None
    assert request.context["reason"] == "rdkit is missing"
    assert request.context["diff"]["added_side_effects"][0]["kind"] == "package_install"

    order = load_order(ctx.state, AGENT)
    assert order.revision == 3
    assert [a["revision"] for a in order.amendments] == [2, 3]


def test_amendments_past_the_limit_always_block(hitl_on, monkeypatch):
    monkeypatch.setattr(hitl_on, "work_order_max_amendments", 1)
    handler = _Handler()
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, handler)
    _declare(toolset, ctx)

    asyncio.run(toolset.update_work_order(reason="r1", add_tools=["tavily_search"], tool_context=ctx))
    assert handler.requests[1:] == []  # read-tier delta: a notice
    asyncio.run(toolset.update_work_order(reason="r2", add_tools=["read_file"], tool_context=ctx))
    assert handler.requests[-1].trigger == "work_order_amendment"
    assert handler.requests[-1].timeout_seconds is None


def test_rejected_amendment_keeps_the_current_order(hitl_on):
    handler = _Handler(
        HITLResponse(action=HITLAction.APPROVE, approved=True),
        HITLResponse(action=HITLAction.REJECT, approved=False, instructions="No installs"),
    )
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, handler)
    _declare(toolset, ctx)
    result = asyncio.run(toolset.update_work_order(
        reason="need rdkit", add_tools=["install_package"], tool_context=ctx,
    ))
    assert result["status"] == "rejected"
    order = load_order(ctx.state, AGENT)
    assert order.status == "approved" and order.revision == 1
    assert "install_package" not in order.planned_tools


def test_empty_amendment_is_refused(hitl_on):
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, _Handler())
    _declare(toolset, ctx)
    result = asyncio.run(toolset.update_work_order(
        reason="nothing", add_tools=["execute_bash"], tool_context=ctx,
    ))
    assert result["status"] == "error"


def test_step_progress_is_saved_and_announced(hitl_on):
    handler = _Handler()
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, handler)
    _declare(toolset, ctx)

    result = asyncio.run(toolset.update_work_step("S1", "done", tool_context=ctx, note="2143 rows"))
    assert result == {"status": "ok", "step": "S1", "step_status": "done"}
    assert load_order(ctx.state, AGENT).step("S1").note == "2143 rows"
    assert handler.notices[-1]["kind"] == "progress"
    assert handler.notices[-1]["step"]["status"] == "done"

    assert asyncio.run(toolset.update_work_step("S9", "done", tool_context=ctx))["status"] == "error"
    assert asyncio.run(toolset.update_work_step("S1", "finished", tool_context=ctx))["status"] == "error"


def test_tools_build_valid_function_declarations():
    names = []
    for tool in WorkOrderToolset(AGENT, TOOLS).tools():
        assert tool._get_declaration() is not None
        names.append(tool.name)
    assert names == ["declare_work_order", "update_work_order", "update_work_step"]


def test_string_assumptions_are_rejected(monkeypatch):
    monkeypatch.setattr(get_settings().web, "hitl_enabled", False)
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, _Handler())
    result = _declare(toolset, ctx, assumptions=["IC50 in nM"])
    assert result["status"] == "error"
    assert "must be a dict" in result["message"]


def test_invalid_assumption_format_errors(monkeypatch):
    monkeypatch.setattr(get_settings().web, "hitl_enabled", False)
    ctx = _context()
    toolset = WorkOrderToolset(AGENT, TOOLS, _Handler())

    # Empty text
    res1 = _declare(toolset, ctx, assumptions=[{"text": "  ", "confidence": "high"}])
    assert res1["status"] == "error"
    assert "non-empty 'text'" in res1["message"]

    # Invalid confidence
    res2 = _declare(toolset, ctx, assumptions=[{"text": "valid", "confidence": "unknown"}])
    assert res2["status"] == "error"
    assert "invalid confidence" in res2["message"]

    # Missing confidence defaults to medium
    res3 = _declare(toolset, ctx, assumptions=[{"text": "valid"}])
    assert res3["status"] == "approved"
    order = load_order(ctx.state, AGENT)
    assert order.assumptions[0].confidence == "medium"
