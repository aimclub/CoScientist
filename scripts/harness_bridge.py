"""Connect an external chat harness to the same CoScientist web session as its GUI.

No CoScientist imports are needed: the server's public HTTP/WebSocket protocol
is the integration boundary.  Use the project's .venv Python for ``send``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


STATE_FILE = Path(__file__).resolve().parents[1] / ".coscientist-harness.json"
DEFAULT_URL = "http://127.0.0.1:8000"


def api(base: str, path: str, *, data: dict | None = None) -> dict:
    payload = None if data is None else json.dumps(data).encode("utf-8")
    request = Request(
        base.rstrip("/") + path,
        data=payload,
        headers={"Content-Type": "application/json"} if payload else {},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CoScientist HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"CoScientist is not reachable at {base}: {exc.reason}") from exc


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        raise RuntimeError("No harness session. Start the web server, then run 'init'.") from None


def save_state(state: dict) -> None:
    temporary = STATE_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, STATE_FILE)


def init(base: str, nickname: str, title: str,
         requested_session_id: str | None = None) -> dict:
    base = base.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("--url must be an HTTP(S) URL")
    users_data = api(base, "/api/users")
    users = users_data["users"]
    user = next((u for u in users if u["nickname"].casefold() == nickname.casefold()), None)
    if user is None:
        user = api(base, "/api/users", data={"nickname": nickname})["user"]

    previous = None
    try:
        previous = load_state()
    except RuntimeError:
        pass
    session = None
    if requested_session_id or (previous and previous.get("url") == base
            and previous.get("boot_id") == users_data.get("serverBootId")
            and previous.get("user_id") == user["id"]):
        sessions = api(base, f"/api/users/{quote(user['id'])}/sessions")["sessions"]
        wanted = requested_session_id or previous["session_id"]
        session = next((s for s in sessions if s["id"] == wanted), None)
        if requested_session_id and session is None:
            raise RuntimeError("Requested session does not belong to this user/server")
    if session is None:
        session = api(base, f"/api/users/{quote(user['id'])}/sessions",
                      data={"title": title})["session"]

    state = {"url": base, "boot_id": users_data.get("serverBootId"),
             "user_id": user["id"], "session_id": session["id"]}
    if previous and all(previous.get(k) == state[k] for k in state):
        state.update({k: previous[k] for k in ("event_cursor",) if k in previous})
    save_state(state)
    return {**state, "nickname": user["nickname"], "title": session["title"],
            "gui_url": f"{base}/?user_id={quote(user['id'])}&session_id={quote(session['id'])}"}


def session_path(state: dict) -> str:
    return (f"/api/users/{quote(state['user_id'])}/sessions/"
            f"{quote(state['session_id'])}")


def status(state: dict) -> dict:
    base = state["url"]
    path = session_path(state)
    session = api(base, path)["session"]
    events = api(base, path + "/events")["events"]
    latest = next((event for event in reversed(events)
                   if event.get("type") in ("final_response", "error")), None)
    reviews = pending_reviews(events)
    latest_agent = next((event for event in reversed(events)
                         if event.get("type") in ("agent_event", "agent_output")
                         and event.get("content")), None)
    return {"session": session, "event_count_recent": len(events),
            "latest_result": latest, "latest_agent_message": latest_agent,
            "pending_review_requests": reviews}


def pending_reviews(events: list[dict]) -> list[dict]:
    pending = {}
    for event in events:
        request_id = event.get("request_id")
        if not request_id:
            continue
        if event.get("type") == "hitl_request":
            pending[request_id] = event
        elif event.get("type") in ("hitl_response", "hitl_timeout", "hitl_cancelled"):
            pending.pop(request_id, None)
    return list(pending.values())


def _event_key(event: dict) -> str:
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _public_event(event: dict, *, verbose: bool) -> dict | None:
    kind = event.get("type")
    if kind == "tool_activity":
        if event.get("phase") not in ("agent_start", "agent_end") and not verbose:
            return None
        # Tool arguments and results can contain private data: never echo them.
        return {k: event[k] for k in ("type", "phase", "author", "tool", "timestamp")
                if k in event}
    if kind == "agent_event" and not event.get("content"):
        return None
    if kind not in ("agent_event", "agent_output", "hitl_request", "hitl_response",
                    "hitl_timeout", "hitl_cancelled", "work_order_notice",
                    "final_response", "error"):
        return None
    public = dict(event)
    content = public.get("content")
    if isinstance(content, str) and len(content) > 2500:
        public["content"] = content[:2500]
        public["content_truncated"] = True
    return public


def feed(state: dict, *, verbose: bool = False, replay: bool = False) -> dict:
    events = api(state["url"], session_path(state) + "/events")["events"]
    cursor = None if replay else state.get("event_cursor")
    match = next((i for i in range(len(events) - 1, -1, -1)
                  if _event_key(events[i]) == cursor), None) if cursor else None
    # The server exposes only its last 100 events; report a gap if the cursor
    # fell out of that window instead of pretending the feed is complete.
    gap = bool(cursor and match is None)
    unseen = events[match + 1:] if match is not None else events
    visible = [_public_event(event, verbose=verbose) for event in unseen]
    if events and not replay:
        state["event_cursor"] = _event_key(events[-1])
        save_state(state)
    return {"events": [event for event in visible if event is not None],
            "raw_event_count": len(unseen), "history_gap": gap,
            "pending_review_requests": pending_reviews(events)}


def hitl_action(state: dict, request_id: str, action: str, *, message: str = "",
                option: str = "") -> dict:
    from websockets.sync.client import connect

    events = api(state["url"], session_path(state) + "/events")["events"]
    request = next((item for item in pending_reviews(events)
                    if item["request_id"] == request_id), None)
    if request is None:
        raise ValueError("Request is not pending in this session; no response sent")
    if action in ("edit", "provide_input") and not message.strip():
        raise ValueError(f"{action} requires --message")
    if action == "select" and not option.strip():
        raise ValueError("select requires --option")
    parsed = urlparse(state["url"])
    scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = (f"{scheme}://{parsed.netloc}/ws?user_id={quote(state['user_id'])}"
              f"&session_id={quote(state['session_id'])}")
    with connect(ws_url, open_timeout=10, max_size=None) as ws:
        for expected in ("connected", "session_snapshot"):
            actual = json.loads(ws.recv(timeout=10)).get("type")
            if actual != expected:
                raise RuntimeError(f"Unexpected CoScientist WebSocket handshake: {actual}")
        payload = {"type": "hitl_hold" if action == "hold" else "hitl_response",
                   "request_id": request_id}
        if action != "hold":
            payload.update(action=action, approved=action in ("approve", "provide_input", "select"),
                           instructions=message or option or None,
                           free_input=message or option or None,
                           selected_option=option or None)
        ws.send(json.dumps(payload, ensure_ascii=False))
    return {"state": "sent_unconfirmed", "request_id": request_id, "action": action,
            "note": "Check the next feed/status for a recorded response; never retry blindly."}


def send(state: dict, message: str, wait_seconds: float) -> dict:
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    if not message.strip():
        raise ValueError("Message cannot be empty")
    base = state["url"]
    parsed = urlparse(base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = (f"{scheme}://{parsed.netloc}/ws?user_id={quote(state['user_id'])}"
              f"&session_id={quote(state['session_id'])}")
    # Timeout starts after connecting; the request keeps running on the server
    # when this client leaves. The GUI remains connected to the same session.
    with connect(ws_url, open_timeout=10, max_size=None) as ws:
        snapshot = json.loads(ws.recv(timeout=10))
        if snapshot.get("type") == "error":
            raise RuntimeError(snapshot.get("message", "WebSocket session error"))
        snapshot = json.loads(ws.recv(timeout=10))
        if snapshot.get("type") != "session_snapshot":
            raise RuntimeError("Unexpected CoScientist WebSocket handshake")
        ws.send(json.dumps({"type": "chat_message", "message": message}))
        deadline = time.monotonic() + max(0, wait_seconds)
        accepted = False
        while True:
            remaining = deadline - time.monotonic()
            if accepted and remaining <= 0:
                return {"state": "running", "session_id": state["session_id"]}
            try:
                event = json.loads(ws.recv(timeout=max(0.1, remaining) if accepted else 10))
            except TimeoutError:
                if accepted:
                    return {"state": "running", "session_id": state["session_id"]}
                raise RuntimeError("No acknowledgement from CoScientist") from None
            except ConnectionClosed as exc:
                raise RuntimeError(f"CoScientist connection closed: {exc}") from exc
            kind = event.get("type")
            if kind == "chat_rejected":
                return {"state": "rejected", "message": event.get("message")}
            if kind == "chat_accepted":
                accepted = True
            elif kind == "final_response":
                return {"state": "complete", "content": event.get("content", "")}
            elif kind == "error" and accepted:
                return {"state": "error", "message": event.get("message", "")}
            elif kind == "hitl_request" and accepted:
                return {"state": "review_required", "request": event,
                        "note": "Review this request in the GUI; the run continues there."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("init", help="Create or reuse a shared GUI/harness session")
    setup.add_argument("--url", default=DEFAULT_URL)
    setup.add_argument("--nickname", default="Codex Harness")
    setup.add_argument("--title", default="Harness research")
    setup.add_argument("--session-id", help="Reattach a known session after a server restart")
    sub.add_parser("status", help="Read session state and latest saved result")
    follow = sub.add_parser("feed", help="Read new chat-facing events and pending HITL requests")
    follow.add_argument("--verbose", action="store_true", help="Include tool names, never tool arguments/results")
    follow.add_argument("--replay", action="store_true", help="Show recent history without advancing the cursor")
    respond = sub.add_parser("hitl", help="Send a user-reviewed decision to a pending request")
    respond.add_argument("request_id")
    respond.add_argument("action", choices=("hold", "approve", "reject", "edit", "provide_input", "select"))
    respond.add_argument("--message", default="")
    respond.add_argument("--option", default="")
    submit = sub.add_parser("send", help="Send a message into the shared session")
    submit.add_argument("message")
    submit.add_argument("--wait", type=float, default=15,
                        help="Seconds to await a result (default: 15)")
    args = parser.parse_args(argv)
    try:
        result = (init(args.url, args.nickname, args.title, args.session_id)
                  if args.command == "init"
                  else status(load_state()) if args.command == "status"
                  else feed(load_state(), verbose=args.verbose, replay=args.replay)
                  if args.command == "feed"
                  else hitl_action(load_state(), args.request_id, args.action,
                                   message=args.message, option=args.option)
                  if args.command == "hitl"
                  else send(load_state(), args.message, args.wait))
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    # JSON escapes make stdout independent of a Windows console code page.
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
