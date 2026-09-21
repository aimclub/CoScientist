"""The two FEDOT rows in the activity rail, and where they lead.

PR 368 added the rows and nothing added their labels, so a Russian operator
got `FEDOT.MAS Demo (agent graph)` in Latin — the array's own fallback string,
which `applyLanguage` leaves in place when the key is missing. Every other row
in that rail is translated, so the two new ones read as unfinished.

And the demo row is a reverse proxy to a process that is not running by
default. `httpx.ConnectError` came back as a JSON body with status 502, which
in the new browser tab the row opens is a page of raw JSON.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "CoScientist" / "web" / "static" / "js"


def _read(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


# ── the rail ────────────────────────────────────────────────────────────────

def test_every_row_in_the_rail_has_a_translated_label():
    """`initAgentNav` renders `data-i18n="agent.<name>.desc"` for each row and
    calls `applyLanguage()`; a name with no key keeps the English fallback
    baked into the array."""
    rail = _read(JS / "activity_rail.js")
    i18n = _read(JS / "i18n.js")

    block = rail[rail.index("const AGENTS = ["):rail.index("];", rail.index("const AGENTS = ["))]
    names = re.findall(r"\{\s*name:\s*\"([A-Za-z_]+)\"", block)
    assert "FedotTrace" in names and "FedotDemo" in names, names

    missing = [n for n in names
               if f"'agent.{n}.desc'" not in i18n and n != "__settings__"]
    assert not missing, f"no agent.<name>.desc in i18n.js for: {missing}"

    # Both languages, or one of them silently shows the other's text.
    for name in ("FedotTrace", "FedotDemo"):
        row = i18n[i18n.index(f"'agent.{name}.desc'"):]
        row = row[:row.index("\n")]
        assert "en:" in row and "ru:" in row, row


def test_a_rail_row_that_opens_a_page_is_actually_handled():
    """A row with an href still goes through `onAgentClick`, and a name that
    falls off the end of that chain opens nothing at all."""
    rail = _read(JS / "activity_rail.js")
    handler = rail[rail.index("function onAgentClick"):]
    handler = handler[:handler.index("\n    }")]
    for name in ("FedotTrace", "FedotDemo"):
        assert f'name === "{name}"' in handler, f"{name} has no branch"


# ── where the demo row leads when the demo is not running ───────────────────

class _Refusing:
    """An httpx client that cannot reach the gui-demo, like a stopped one."""

    def __init__(self, *_a, **_k):
        pass

    def build_request(self, *_a, **_k):
        return object()

    async def send(self, *_a, **_k):
        raise httpx.ConnectError("nobody is listening")

    async def aclose(self):
        return None


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_SNAPSHOT_DIR", str(tmp_path / "execution"))
    monkeypatch.setenv("WEB_STATE_DIR", str(tmp_path / "web_state"))
    monkeypatch.setattr(httpx, "AsyncClient", _Refusing)

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as c:
        yield c


def test_a_browser_gets_a_page_and_a_script_gets_json(client):
    page = client.get("/fedot-demo/", headers={"Accept": "text/html,*/*"})
    assert page.status_code == 502, "a missing demo is not a working one"
    assert page.headers["content-type"].startswith("text/html")
    body = page.text
    # What the operator needs in order to do something about it.
    assert "git submodule update --init infrastructure/fedot-mas-gui" in body
    assert "FEDOT_GUI_URL" in body and "127.0.0.1:4173" in body
    assert "/fedot-trace" in body, "no way back to the thing that does work"

    data = client.get("/fedot-demo/api/run", headers={"Accept": "application/json"})
    assert data.status_code == 502
    assert data.headers["content-type"].startswith("application/json")
    assert "not answering" in data.json()["detail"]


def test_the_page_says_which_address_it_tried(client, monkeypatch):
    """The default is not the only one: a demo may run anywhere."""
    monkeypatch.setenv("FEDOT_GUI_URL", "http://10.0.0.9:9999")
    from CoScientist.web.app import create_app

    with TestClient(create_app()) as fresh:
        body = fresh.get("/fedot-demo/", headers={"Accept": "text/html"}).text
    assert "10.0.0.9:9999" in body and "127.0.0.1:4173" not in body


def test_the_trace_page_and_the_live_stream_stand_on_their_own(client):
    """Neither depends on the gui-demo: the trace page reads Langfuse, and the
    stream is fed by fedot_tool itself."""
    page = client.get("/fedot-trace")
    assert page.status_code == 200 and "FEDOT.MAS Trace" in page.text
    # Self-hosted typography, like every other page.
    assert "/static/css/fonts.css" in page.text

    trace = client.get("/api/fedot-langfuse-trace")
    assert trace.status_code == 200
    # Unconfigured is an empty state, never an error the page has to handle.
    assert trace.json()["status"] in {"unconfigured", "empty", "ok", "error"}
