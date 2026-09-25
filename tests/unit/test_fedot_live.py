"""FEDOT.MAS live runs are bound to the web session that launched them.

The /fedot-demo page used to follow one global stream: it drew whichever session's
run happened last, showed nothing to a tab opened after the run started, and had
no notion of which run an event belonged to. A run now lives in its session's
channel, with its history kept for late viewers.
"""
from types import SimpleNamespace

import pytest

from CoScientist.graph.session_scope import GRAPH_SCOPE_SESSION_KEY, GRAPH_SCOPE_USER_KEY
from CoScientist.tools import fedot_live as fl
from CoScientist.tools.fedot_live import FedotLiveBroadcaster

A = ("user_a", "session_a")
B = ("user_b", "session_b")


def _drain(queue):
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def _types(items):
    return [i["type"] for i in items]


def _finished_run(bus, key, *, agents=("Analyst",)):
    run = bus.begin_run(key)
    run.event({"type": "run_start"})
    run.publish_config({"agents": [{"name": n} for n in agents]})
    for name in agents:
        run.event({"type": "agent_start", "agent": name})
        run.event({"type": "agent_done", "agent": name})
    run.event({"type": "run_end", "status": "success"})
    return run


# ── one channel per web session ──────────────────────────────────────────────

def test_a_viewer_bound_to_a_session_sees_only_that_sessions_runs():
    bus = FedotLiveBroadcaster()
    a_view, b_view = bus.subscribe(A), bus.subscribe(B)

    _finished_run(bus, A)
    _finished_run(bus, B, agents=("Critic", "Writer"))

    assert _types(_drain(a_view)) == ["run_start", "config", "agent_start", "agent_done", "run_end"]
    b_events = _drain(b_view)
    assert [e["agent"] for e in b_events if e["type"] == "agent_start"] == ["Critic", "Writer"]


def test_a_viewer_naming_no_session_follows_every_session():
    bus = FedotLiveBroadcaster()
    everything = bus.subscribe(None)
    _finished_run(bus, A)
    _finished_run(bus, B)
    assert _types(_drain(everything)).count("run_start") == 2


def test_events_carry_the_run_id_and_a_wall_clock():
    bus = FedotLiveBroadcaster()
    run = _finished_run(bus, A)
    other = _finished_run(bus, A)
    events = run.history
    assert {e["run_id"] for e in events} == {run.run_id}
    assert run.run_id != other.run_id
    assert all(isinstance(e["ts"], float) for e in events)


# ── a late viewer gets the run from its start ────────────────────────────────

def test_a_page_opened_after_the_run_ended_replays_all_of_it_in_order():
    bus = FedotLiveBroadcaster()
    _finished_run(bus, A, agents=("Analyst", "Critic"))

    late = bus.subscribe(A)
    assert _types(_drain(late)) == [
        "run_start", "config",
        "agent_start", "agent_done", "agent_start", "agent_done",
        "run_end",
    ]


def test_a_page_opened_mid_run_replays_so_far_then_follows_live():
    bus = FedotLiveBroadcaster()
    run = bus.begin_run(A)
    run.event({"type": "run_start"})
    run.publish_config({"agents": [{"name": "Analyst"}]})
    run.event({"type": "agent_start", "agent": "Analyst"})

    late = bus.subscribe(A)
    assert _types(_drain(late)) == ["run_start", "config", "agent_start"]

    run.event({"type": "agent_done", "agent": "Analyst"})
    run.event({"type": "run_end", "status": "success"})
    assert _types(_drain(late)) == ["agent_done", "run_end"]


def test_only_the_latest_run_of_a_session_is_replayed():
    bus = FedotLiveBroadcaster()
    _finished_run(bus, A, agents=("Old",))
    new = _finished_run(bus, A, agents=("New",))

    replay = _drain(bus.subscribe(A))
    assert {e["run_id"] for e in replay} == {new.run_id}
    assert [e["agent"] for e in replay if e["type"] == "agent_start"] == ["New"]


def test_a_session_without_runs_replays_nothing_and_a_bare_viewer_gets_the_latest_anywhere():
    bus = FedotLiveBroadcaster()
    assert bus.subscribe(A).empty()

    _finished_run(bus, B)
    assert bus.subscribe(A).empty()                      # still not B's business
    assert _types(_drain(bus.subscribe(None)))[0] == "run_start"


def test_unsubscribing_stops_delivery():
    bus = FedotLiveBroadcaster()
    view = bus.subscribe(A)
    bus.unsubscribe(view)
    _finished_run(bus, A)
    assert view.empty()


# ── bounded memory ───────────────────────────────────────────────────────────

def test_a_long_run_keeps_its_start_config_and_end(monkeypatch):
    monkeypatch.setattr(fl, "_MAX_TAIL_EVENTS", 5)
    bus = FedotLiveBroadcaster()
    run = bus.begin_run(A)
    run.event({"type": "run_start"})
    run.publish_config({"agents": []})
    for i in range(50):
        run.event({"type": "text", "agent": "Analyst", "text": str(i)})
    run.event({"type": "run_end", "status": "success"})

    kinds = _types(run.history)
    assert kinds[:2] == ["run_start", "config"] and kinds[-1] == "run_end"
    assert len(kinds) == 2 + 5
    # A viewer connected the whole time still saw everything.
    live = bus.subscribe(A)
    assert _types(_drain(live)) == kinds


def test_old_runs_and_old_sessions_are_dropped(monkeypatch):
    monkeypatch.setattr(fl, "_MAX_RUNS_PER_SESSION", 2)
    monkeypatch.setattr(fl, "_MAX_SESSIONS", 2)
    bus = FedotLiveBroadcaster()

    runs = [_finished_run(bus, A) for _ in range(3)]
    assert bus.latest_run(A) is runs[-1]
    assert len(bus._runs[A]) == 2

    _finished_run(bus, B)
    _finished_run(bus, ("user_c", "session_c"))
    assert A not in bus._runs and B in bus._runs         # least recently active goes first


# ── fedot_tool publishes into the session that launched it ───────────────────

def _stub_fedot(monkeypatch, bus):
    from CoScientist.tools import fedotmas_tools as ft

    class _Config:
        def model_dump(self):
            return {"agents": [{"name": "Analyst"}]}

    class _MAW:
        def __init__(self, mcp_servers=None, plugins=None):
            self.plugins = plugins

        async def generate_config(self, task):
            return _Config()

        async def build_and_run(self, config, task, timeout=None):
            return {"answer": "42"}

        def _finalize_langfuse(self):
            return None

    class _PG:
        def __init__(self, *a, **k):
            pass

        async def initialize(self):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(ft, "PostgresClient", _PG)
    monkeypatch.setattr(ft, "MAW", _MAW)
    monkeypatch.setattr(ft, "run_config_guardrails", lambda config: [])
    monkeypatch.setattr(ft, "fedot_live", bus)
    return ft


def _run_tool(ft, state):
    import asyncio

    tool_context = SimpleNamespace(state=state)
    asyncio.run(ft.fedot_toolset.fedot_tool("do the thing", tool_context=tool_context))


def test_fedot_tool_draws_in_the_session_that_launched_it(monkeypatch):
    bus = FedotLiveBroadcaster()
    ft = _stub_fedot(monkeypatch, bus)
    mine, theirs = bus.subscribe(A), bus.subscribe(B)

    # AgentTool's child session is a fresh random id; the web session rides in state.
    _run_tool(ft, {GRAPH_SCOPE_USER_KEY: A[0], GRAPH_SCOPE_SESSION_KEY: A[1]})

    events = _drain(mine)
    assert _types(events) == ["run_start", "config", "run_end"]
    assert events[0]["session"] == {"user_id": A[0], "session_id": A[1]}
    assert events[-1]["status"] == "success" and events[-1]["state"] == {"answer": "42"}
    assert theirs.empty()


def test_a_page_opened_after_fedot_tool_finished_still_shows_the_run(monkeypatch):
    bus = FedotLiveBroadcaster()
    ft = _stub_fedot(monkeypatch, bus)
    _run_tool(ft, {GRAPH_SCOPE_USER_KEY: A[0], GRAPH_SCOPE_SESSION_KEY: A[1]})

    assert _types(_drain(bus.subscribe(A))) == ["run_start", "config", "run_end"]


def test_a_pipeline_the_guardrails_reject_is_still_drawn_and_the_reason_shown(monkeypatch):
    """Observed: pool_generator and pipeline_generator both finished, the guardrails
    rejected the config ("Unused agents … ['summarizer']"), and the page — which
    draws on the `config` event — showed an empty canvas for a pipeline that existed."""
    bus = FedotLiveBroadcaster()
    ft = _stub_fedot(monkeypatch, bus)
    reason = "Unused agents not referenced in pipeline: ['summarizer']"
    monkeypatch.setattr(ft, "run_config_guardrails", lambda config: [reason])
    view = bus.subscribe(A)

    import asyncio

    tool_context = SimpleNamespace(state={GRAPH_SCOPE_USER_KEY: A[0], GRAPH_SCOPE_SESSION_KEY: A[1]})
    result = asyncio.run(ft.fedot_toolset.fedot_tool("do the thing", tool_context=tool_context))

    events = _drain(view)
    assert _types(events) == ["run_start", "config", "run_end"]
    assert events[1]["config"]["agents"], "the rejected config is what gets drawn"
    assert events[-1]["status"] == "error" and reason in events[-1]["error"]
    assert result["status"] == "error" and "result" not in result   # nothing was run


def test_a_run_with_no_session_goes_to_the_shared_default_channel(monkeypatch):
    from CoScientist.graph.session_scope import DEFAULT_SESSION_KEY

    bus = FedotLiveBroadcaster()
    ft = _stub_fedot(monkeypatch, bus)
    _run_tool(ft, {})
    assert bus.latest_run(DEFAULT_SESSION_KEY) is not None
    assert bus.subscribe(A).empty()


# ── the endpoint's argument checks ───────────────────────────────────────────

def test_stream_rejects_half_a_scope_and_an_unknown_session():
    from fastapi.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        assert client.get("/api/fedot-live-stream?user_id=only_user").status_code == 400
        assert client.get("/api/fedot-live-stream?session_id=only_session").status_code == 400
        assert client.get("/api/fedot-live-stream?user_id=nobody&session_id=nothing").status_code == 404
