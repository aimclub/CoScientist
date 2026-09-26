"""Keep unit tests off state the developer actually uses.

Two stores now persist to disk: the session registry (WEB_STATE_DIR, default
graph_runs/web_state) and the sandbox bindings (SANDBOX_BINDINGS_FILE, default
graph_runs/sandbox_bindings.json). Without isolation a test both pollutes real
state and inherits from earlier runs — nickname-uniqueness tests failed with 409
on a second run, and binding tests wrote fake container ids into the file the
running system reads to decide which sandbox to continue in.
"""
import pytest

from CoScientist.config import get_settings


@pytest.fixture(autouse=True)
def _isolated_web_state(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_STATE_DIR", str(tmp_path / "web_state"))
    monkeypatch.setenv("SANDBOX_BINDINGS_FILE",
                       str(tmp_path / "sandbox_bindings.json"))


@pytest.fixture(autouse=True)
def _let_caplog_see_our_logs():
    """Let pytest's caplog capture the application's own logger.

    ``CoScientist.logging.logger`` sets ``propagate = False`` deliberately: the
    application owns its file handler and must not hijack the root logger for
    every third-party library. But caplog listens on root, so with propagation
    off a test asserting on a warning we do emit sees an empty log — and which
    tests hit it depends on whether anything imported the logging module first,
    which is not something a test should depend on.
    """
    import logging

    app_logger = logging.getLogger("CoScientist")
    previous = app_logger.propagate
    app_logger.propagate = True
    try:
        yield
    finally:
        app_logger.propagate = previous


@pytest.fixture(autouse=True)
def _auth_disabled_by_default(monkeypatch):
    """Let every other test go on testing what it was written to test.

    ``create_app`` now installs a deny-by-default gate, so a TestClient without
    a session gets 401 on every route. Tests about graph scoping or report
    links have nothing to say about authentication, and threading a cookie
    through each of them would only obscure what they assert.

    The gate itself is covered by tests/unit/test_web_auth.py, whose own
    autouse fixture turns it back on — a module fixture runs after this one, so
    it wins.
    """
    monkeypatch.setattr(get_settings().auth, "enabled", False)
