"""Contract tests for the chat-to-web-session bridge (no LLM/services)."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "harness_bridge.py"
spec = importlib.util.spec_from_file_location("harness_bridge", SOURCE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def test_init_reuses_same_server_session(tmp_path):
    calls = []

    def fake_api(base, path, *, data=None):
        calls.append((path, data))
        if path == "/api/users":
            return {"serverBootId": "boot", "users": [{"id": "user", "nickname": "Codex Harness"}]}
        if path == "/api/users/user/sessions" and data is None:
            return {"sessions": [{"id": "session", "title": "Research"}]}
        if path == "/api/users/user/sessions":
            return {"session": {"id": "session", "title": data["title"]}}
        raise AssertionError(path)

    with patch.object(bridge, "STATE_FILE", tmp_path / "state.json"), patch.object(bridge, "api", fake_api):
        first = bridge.init("http://127.0.0.1:8000", "Codex Harness", "Research")
        second = bridge.init("http://127.0.0.1:8000", "Codex Harness", "Research")
    assert first["session_id"] == second["session_id"] == "session"
    assert first["gui_url"].endswith("/?user_id=user&session_id=session")
    assert sum(data is not None for path, data in calls if path.endswith("/sessions")) == 1


def test_init_can_reattach_existing_session_after_restart(tmp_path):
    def fake_api(base, path, *, data=None):
        if path == "/api/users":
            return {"serverBootId": "new-boot", "users": [{"id": "u", "nickname": "Codex Harness"}]}
        if path == "/api/users/u/sessions":
            assert data is None
            return {"sessions": [{"id": "old-study", "title": "Memory research"}]}
        raise AssertionError(path)

    with patch.object(bridge, "STATE_FILE", tmp_path / "state.json"), \
         patch.object(bridge, "api", fake_api):
        result = bridge.init("http://127.0.0.1:8000", "Codex Harness",
                             "unused", requested_session_id="old-study")
    assert result["session_id"] == "old-study"
    assert result["gui_url"].endswith("session_id=old-study")


def test_status_reads_saved_final_response():
    state = {"url": "http://127.0.0.1:8000", "user_id": "u", "session_id": "s"}

    def fake_api(base, path, *, data=None):
        if path.endswith("/events"):
            return {"events": [{"type": "user_message", "message": "question"},
                               {"type": "final_response", "content": "answer"}]}
        return {"session": {"status": "idle"}}

    with patch.object(bridge, "api", fake_api):
        result = bridge.status(state)
    assert result["latest_result"]["content"] == "answer"


def test_send_uses_shared_websocket_and_does_not_cancel_pending_run():
    class Socket:
        def __init__(self):
            self.sent = []
            self.incoming = iter([
                {"type": "connected"}, {"type": "session_snapshot"},
                {"type": "chat_accepted", "message_text": "hello"},
                {"type": "final_response", "content": "result"},
            ])

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def recv(self, *, timeout):
            return json.dumps(next(self.incoming))

        def send(self, value):
            self.sent.append(json.loads(value))

    socket = Socket()
    with patch("websockets.sync.client.connect", return_value=socket) as connect:
        result = bridge.send({"url": "http://127.0.0.1:8000",
                              "user_id": "u", "session_id": "s"}, "hello", 15)
    assert result == {"state": "complete", "content": "result"}
    assert socket.sent == [{"type": "chat_message", "message": "hello"}]
    assert connect.call_args.args[0].endswith("/ws?user_id=u&session_id=s")


def test_feed_deduplicates_and_never_echoes_tool_arguments(tmp_path):
    state = {"url": "http://127.0.0.1:8000", "user_id": "u", "session_id": "s"}
    events = [{"type": "tool_activity", "phase": "call", "tool": "fetch",
               "args": {"api_key": "private"}, "timestamp": "1"},
              {"type": "agent_output", "agent": "ResearchAgent",
               "content": "result", "timestamp": "2"},
              {"type": "hitl_request", "request_id": "request-1",
               "message": "Approve plan?", "timestamp": "3"}]
    with patch.object(bridge, "STATE_FILE", tmp_path / "state.json"), \
         patch.object(bridge, "api", return_value={"events": events}):
        first = bridge.feed(state)
        second = bridge.feed(state)
        replay = bridge.feed(state, replay=True)
    assert [e["type"] for e in first["events"]] == ["agent_output", "hitl_request"]
    assert first["pending_review_requests"][0]["request_id"] == "request-1"
    assert second["events"] == []
    assert replay["raw_event_count"] == 3
    assert "private" not in json.dumps(first)


def test_hitl_requires_pending_request_and_sends_only_explicit_decision():
    class Socket:
        def __init__(self):
            self.sent = []
            self.incoming = iter([{"type": "connected"}, {"type": "session_snapshot"}])

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def recv(self, *, timeout):
            return json.dumps(next(self.incoming))

        def send(self, payload):
            self.sent.append(json.loads(payload))

    state = {"url": "http://127.0.0.1:8000", "user_id": "u", "session_id": "s"}
    events = [{"type": "hitl_request", "request_id": "request-1", "message": "Approve?"}]
    socket = Socket()
    with patch.object(bridge, "api", return_value={"events": events}), \
         patch("websockets.sync.client.connect", return_value=socket):
        bridge.hitl_action(state, "request-1", "reject", message="Needs evidence")
    assert socket.sent == [{"type": "hitl_response", "request_id": "request-1",
                            "action": "reject", "approved": False,
                            "instructions": "Needs evidence", "free_input": "Needs evidence",
                            "selected_option": None}]
    events.append({"type": "hitl_response", "request_id": "request-1"})
    with patch.object(bridge, "api", return_value={"events": events}):
        try:
            bridge.hitl_action(state, "request-1", "approve")
        except ValueError as exc:
            assert "not pending" in str(exc)
        else:
            raise AssertionError("Resolved HITL request was accepted again")
