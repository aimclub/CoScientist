"""Unit tests for make_hitl_before_tool_callback and Web UI HITL routing."""

import asyncio
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from CoScientist.config import get_settings
from CoScientist.hitl.callbacks import make_hitl_before_tool_callback
from CoScientist.hitl.handler import AbstractHITLHandler
from CoScientist.hitl.models import HITLAction, HITLRequest, HITLResponse
from CoScientist.web.handler import WebHITLHandler


class _MockHandler(AbstractHITLHandler):
    def __init__(self, approved: bool = True, feedback: Optional[str] = None):
        self.requests = []
        self.approved = approved
        self.feedback = feedback

    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        self.requests.append(request)
        return HITLResponse(
            action=HITLAction.APPROVE if self.approved else HITLAction.REJECT,
            approved=self.approved,
            instructions=self.feedback,
            free_input=self.feedback,
        )


def _make_context(user_id: str = "test-user", session_id: str = "test-session", agent_name: str = "CoderAgent"):
    state = {"graph_scope_user_id": user_id, "graph_scope_session_id": session_id}
    session = SimpleNamespace(id=session_id, user_id=user_id, state=state)
    inv_ctx = SimpleNamespace(session=session, agent=SimpleNamespace(name=agent_name))
    return SimpleNamespace(
        agent_name=agent_name,
        state=state,
        session=session,
        _invocation_context=inv_ctx,
    )


def test_hitl_before_tool_disabled_when_flag_false(monkeypatch):
    """When hitl_enabled is False, callback passes through without calling handler."""
    settings = get_settings()
    monkeypatch.setattr(settings.web, "hitl_enabled", False)

    handler = _MockHandler(approved=False)
    cb = make_hitl_before_tool_callback(handler, target_tools=("sandbox",))

    tool = SimpleNamespace(name="run_sandbox_task")
    args = {"task": "Train model"}
    ctx = _make_context()

    result = asyncio.run(cb(tool, args, ctx))
    assert result is None
    assert len(handler.requests) == 0


def test_hitl_before_tool_filters_non_sandbox_tools(monkeypatch):
    """Non-sandbox tools (execute_bash, write_file, etc.) must not trigger HITL."""
    settings = get_settings()
    monkeypatch.setattr(settings.web, "hitl_enabled", True)

    handler = _MockHandler(approved=False)
    cb = make_hitl_before_tool_callback(handler, target_tools=("sandbox",))
    ctx = _make_context()

    non_sandbox_tools = [
        "execute_bash",
        "write_file",
        "read_file",
        "edit_file",
        "list_dir",
        "install_package",
        "validate_dataset",
        "download_file",
        "research_commit",
    ]
    for tool_name in non_sandbox_tools:
        tool = SimpleNamespace(name=tool_name)
        result = asyncio.run(cb(tool, {"command": "echo test"}, ctx))
        assert result is None, f"{tool_name} should have passed through without HITL"

    # Handler should not have received any requests
    assert len(handler.requests) == 0


def test_hitl_before_tool_intercepts_sandbox_tools(monkeypatch):
    """run_sandbox_task and sandbox tools must trigger HITL."""
    settings = get_settings()
    monkeypatch.setattr(settings.web, "hitl_enabled", True)

    handler = _MockHandler(approved=True)
    cb = make_hitl_before_tool_callback(handler, target_tools=("sandbox",))
    ctx = _make_context(user_id="alice", session_id="sess-123")

    tool = SimpleNamespace(name="run_sandbox_task")
    args = {"task": "Fine-tune transformer", "dataset_url": "http://example.com/data.zip"}

    result = asyncio.run(cb(tool, args, ctx))
    assert result is None
    assert len(handler.requests) == 1

    req = handler.requests[0]
    assert req.agent_name == "CoderAgent"
    assert req.action_type == HITLAction.APPROVE
    assert req.context["tool"] == "run_sandbox_task"
    assert req.context["args"] == args
    assert "Fine-tune transformer" in req.context["output"]
    assert req.context["_session"] == {"user_id": "alice", "session_id": "sess-123"}


def test_hitl_before_tool_excludes_hitl_interaction_tools(monkeypatch):
    """Calling request_approval or request_selection must never be blocked by HITL."""
    settings = get_settings()
    monkeypatch.setattr(settings.web, "hitl_enabled", True)

    handler = _MockHandler(approved=False)
    # Even with target_tools=None (intercept all), HITL tools are excluded
    cb = make_hitl_before_tool_callback(handler, target_tools=None)
    ctx = _make_context()

    for tool_name in ("request_approval", "request_selection", "request_input"):
        tool = SimpleNamespace(name=tool_name)
        result = asyncio.run(cb(tool, {"message": "hello"}, ctx))
        assert result is None

    assert len(handler.requests) == 0


def test_hitl_before_tool_rejected_returns_denied_dict(monkeypatch):
    """When human rejects sandbox task, callback returns denied dict with reason."""
    settings = get_settings()
    monkeypatch.setattr(settings.web, "hitl_enabled", True)

    handler = _MockHandler(approved=False, feedback="Do not run this heavy experiment")
    cb = make_hitl_before_tool_callback(handler, target_tools=("sandbox",))

    tool = SimpleNamespace(name="run_sandbox_task")
    args = {"task": "heavy training job"}
    ctx = _make_context()

    result = asyncio.run(cb(tool, args, ctx))
    assert isinstance(result, dict)
    assert result["status"] == "denied"
    assert result["blocked_by"] == "human"
    assert "rejected by human operator" in result["message"]
    assert "Do not run this heavy experiment" in result["message"]


def test_hitl_before_tool_target_tools_none_intercepts_all(monkeypatch):
    """When target_tools is None, all regular tools are intercepted."""
    settings = get_settings()
    monkeypatch.setattr(settings.web, "hitl_enabled", True)

    handler = _MockHandler(approved=True)
    cb = make_hitl_before_tool_callback(handler, target_tools=None)
    ctx = _make_context()

    tool = SimpleNamespace(name="execute_bash")
    args = {"command": "ls -la"}
    result = asyncio.run(cb(tool, args, ctx))
    assert result is None
    assert len(handler.requests) == 1
    assert handler.requests[0].context["tool"] == "execute_bash"


def test_hitl_before_tool_keyword_args_compatibility(monkeypatch):
    """Supports both positional and keyword invocations from ADK / runners."""
    settings = get_settings()
    monkeypatch.setattr(settings.web, "hitl_enabled", True)

    handler = _MockHandler(approved=True)
    cb = make_hitl_before_tool_callback(handler, target_tools=("sandbox",))

    tool = SimpleNamespace(name="run_sandbox_task")
    args = {"task": "build pipeline"}
    ctx = _make_context()

    # Keyword call: tool, tool_args, tool_context
    res1 = asyncio.run(cb(tool=tool, tool_args=args, tool_context=ctx))
    assert res1 is None
    assert len(handler.requests) == 1

    # Positional call
    res2 = asyncio.run(cb(tool, args, ctx))
    assert res2 is None
    assert len(handler.requests) == 2


def test_hitl_before_tool_web_handler_routing():
    """WebHITLHandler correctly routes request to session tabs and serializes payload."""
    handler = WebHITLHandler()
    ctx = _make_context(user_id="user_web", session_id="sess_web")

    cb = make_hitl_before_tool_callback(handler, target_tools=("sandbox",))
    tool = SimpleNamespace(name="run_sandbox_task")
    args = {"task": "run simulation in sandbox"}

    # Mock handler._broadcast and auto-resolve future
    broadcast_mock = AsyncMock(return_value=1)
    handler._broadcast = broadcast_mock

    async def scenario():
        # Run handle_request in background task and immediately resolve future
        task = asyncio.create_task(cb(tool, args, ctx))
        # Yield control to let cb initiate request and register pending future
        await asyncio.sleep(0.01)

        assert len(handler._pending) == 1
        req_id, pending_entry = next(iter(handler._pending.items()))

        # Verify broadcast payload
        assert broadcast_mock.called
        payload, session_key_arg = broadcast_mock.call_args[0]
        assert payload["type"] == "hitl_request"
        assert payload["agent_name"] == "CoderAgent"
        assert payload["action_type"] == "approve"
        assert payload["context"]["tool"] == "run_sandbox_task"
        assert "Tool: run_sandbox_task" in payload["context"]["output"]
        assert session_key_arg == ("user_web", "sess_web")

        # Simulate web socket client approving
        handler.submit_response(req_id, {"action": "approve", "approved": True})
        res = await task
        assert res is None

    asyncio.run(scenario())
