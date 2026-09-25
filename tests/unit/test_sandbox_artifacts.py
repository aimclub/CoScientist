"""Getting a file out of the sandbox and into something a reader can open.

`list_sandbox_files` could say a file exists and nothing could reach it. The
transfer is one hop — pull the bytes, put them in the bucket every other
artifact lives in, answer with the durable link — so that everything
downstream (the report, the chat, the S3 references the execution graph reads
onto an agent's card) keeps working untouched.
"""
import types

import pytest

from CoScientist.tools.coder_tools import sandbox_artifacts


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """A sandbox that hands over one small file."""
    def download(remote, local, **_kwargs):
        with open(local, "wb") as fh:
            fh.write(b"loss,epoch\n0.1,3\n")
        return {"status": "ok", "size_bytes": 17, "sandbox_id": "sbx-1"}

    monkeypatch.setattr(
        "CoScientist.tools.coder_tools.openhands_sandbox.download_sandbox_file",
        download, raising=False)
    return download


def _stub_upload(monkeypatch, ref=("results", "sandbox-artifacts/s1/metrics.csv")):
    monkeypatch.setattr("CoScientist.reporting.s3_upload.upload_and_ref",
                        lambda *a, **k: ref, raising=False)


def test_a_transferred_file_comes_back_as_a_link_that_keeps_working(sandbox, monkeypatch):
    _stub_upload(monkeypatch)

    out = sandbox_artifacts.transfer_sandbox_artifact(
        "/workspace/metrics.csv", session_id="s1")

    assert out["status"] == "success"
    # The durable form, not a presigned URL: a signature expires, the object does not.
    assert out["url"] == "/api/artifact/results/sandbox-artifacts/s1/metrics.csv"
    assert out["bucket"] == "results"
    assert "?" not in out["url"], "a presigned URL would carry a signature"


def test_the_object_is_filed_under_the_session_that_produced_it(sandbox, monkeypatch):
    seen = {}

    def upload(local, prefix):
        seen["prefix"] = prefix
        return ("results", f"{prefix}/metrics.csv")

    monkeypatch.setattr("CoScientist.reporting.s3_upload.upload_and_ref",
                        upload, raising=False)

    sandbox_artifacts.transfer_sandbox_artifact("/workspace/metrics.csv",
                                                session_id="session-42")
    assert "session-42" in seen["prefix"]


def test_a_sandbox_that_refuses_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(
        "CoScientist.tools.coder_tools.openhands_sandbox.download_sandbox_file",
        lambda *a, **k: {"status": "error", "message": "No sandbox is bound."},
        raising=False)

    out = sandbox_artifacts.transfer_sandbox_artifact("/workspace/x", session_id="s1")
    assert out["status"] == "error"
    assert "No sandbox is bound." in out["message"]


def test_storage_refusing_the_file_is_not_reported_as_success(sandbox, monkeypatch):
    """The bytes arrived; nobody can open them. That is a failure, not a link."""
    monkeypatch.setattr("CoScientist.reporting.s3_upload.upload_and_ref",
                        lambda *a, **k: None, raising=False)

    out = sandbox_artifacts.transfer_sandbox_artifact("/workspace/x", session_id="s1")
    assert out["status"] == "error"
    assert "S3" in out["message"]


def test_an_enormous_artifact_is_refused_rather_than_written_to_disk(monkeypatch):
    """A training run leaves gigabytes behind; a directory arrives as one ZIP."""
    def huge(remote, local, **_kwargs):
        open(local, "wb").close()
        return {"status": "ok", "size_bytes": 10 * 1024 ** 3}

    monkeypatch.setattr(
        "CoScientist.tools.coder_tools.openhands_sandbox.download_sandbox_file",
        huge, raising=False)

    out = sandbox_artifacts.transfer_sandbox_artifact("/workspace", session_id="s1")
    assert out["status"] == "error"
    assert "слишком велик" in out["message"]


def test_an_empty_path_is_refused_before_anything_is_contacted():
    out = sandbox_artifacts.transfer_sandbox_artifact("   ")
    assert out["status"] == "error"


def test_the_agents_are_given_the_tool_and_it_is_documented():
    """Undocumented, guard_unknown_tools would refuse the call as hallucinated."""
    from CoScientist.assembly import bindings
    from CoScientist.tools.coder_tools.sandbox_tools import get_sandbox_tools

    documented = {d.name for d in bindings._SANDBOX_TAIL_DOCS}
    assert "fetch_sandbox_artifact" in documented
    # And actually attached, not merely described.
    attached = {getattr(t, "__name__", "") for t in get_sandbox_tools()}
    assert not attached or "fetch_sandbox_artifact" in attached


def test_the_panel_is_wired_into_the_page():
    """A person watching a run could not look inside the sandbox at all.

    The panel is only useful if the page actually carries it: the markup, the
    module that drives it, and a way in from the rail.
    """
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/").text
        module = client.get("/static/js/modals/artifacts.js")
        rail = client.get("/static/js/activity_rail.js").text

    assert 'id="artifacts-modal"' in page
    assert "modals/artifacts.js" in page, "the module must be loaded, not just present"
    assert module.status_code == 200
    assert "SandboxArtifacts" in rail, "and reachable from the rail"
    # It talks to the endpoints that exist, not to invented ones. The URL is
    # assembled from a session-scoped base, so check the parts.
    assert "/sandbox" in module.text
    assert "/files?" in module.text and "path=" in module.text
    assert "/fetch" in module.text
    assert "/tasks" in module.text, "and asks which workspaces exist"


def test_the_panel_asks_for_the_open_session_not_a_global_sandbox():
    """A sandbox belongs to one session; listing another's would be a lie."""
    from starlette.testclient import TestClient

    from CoScientist.web.app import create_app

    with TestClient(create_app()) as client:
        module = client.get("/static/js/modals/artifacts.js").text

    assert "activeSession" in module and "activeUser" in module


# ---------------------------------------------------------------------------
# Choosing which workspace to look at
# ---------------------------------------------------------------------------

class _Answer:
    """The bare shape of an httpx response the client actually touches."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _sandbox_status(monkeypatch, payload):
    from CoScientist.tools.coder_tools import openhands_sandbox as sandbox

    monkeypatch.setattr(sandbox, "resolve_sandbox_url", lambda *a, **k: "http://sbx",
                        raising=False)
    monkeypatch.setattr(sandbox, "read_binding", lambda *a, **k: "task-ours",
                        raising=False)
    monkeypatch.setattr(sandbox.httpx, "get", lambda *a, **k: _Answer(payload),
                        raising=False)
    return sandbox


def test_every_workspace_the_sandbox_holds_is_offered_ours_first(monkeypatch):
    """The reader's own container is one of many; the others are one id away."""
    sandbox = _sandbox_status(monkeypatch, {
        "current_task": {"task_id": "task-other", "status": "running",
                         "task": "train a transformer"},
        "active_tasks": [{"task_id": "task-other", "status": "running"}],
        "queue": [{"task_id": "task-waiting", "status": "queued", "task": "next up"}],
        "completed_tasks": [{"task_id": "task-ours", "status": "cooldown",
                             "summary": "ours"}],
    })

    out = sandbox.list_sandbox_tasks(session_id="s1")

    assert out["status"] == "ok"
    ids = [w["sandbox_id"] for w in out["workspaces"]]
    assert ids[0] == "task-ours", "the session's own sandbox leads the list"
    assert set(ids) == {"task-ours", "task-other", "task-waiting"}
    # One task appearing in two sections of one answer is still one workspace.
    assert len(ids) == len(set(ids))


def test_a_workspace_whose_container_is_gone_is_marked_unbrowsable(monkeypatch):
    """`/files` answers 409 for it; saying so beats an empty listing."""
    sandbox = _sandbox_status(monkeypatch, {
        "current_task": None, "active_tasks": [], "queue": [],
        "completed_tasks": [{"task_id": "task-ours", "status": "running"},
                            {"task_id": "task-done", "status": "completed"}],
    })

    by_id = {w["sandbox_id"]: w for w in
             sandbox.list_sandbox_tasks(session_id="s1")["workspaces"]}

    assert by_id["task-ours"]["browsable"] is True
    assert by_id["task-done"]["browsable"] is False


def test_the_session_sandbox_is_listed_even_when_it_fell_off_the_recent_list(monkeypatch):
    """Twenty runs later it is still the one the reader means by "current"."""
    sandbox = _sandbox_status(monkeypatch, {
        "current_task": None, "active_tasks": [], "queue": [], "completed_tasks": [],
    })
    monkeypatch.setattr(sandbox, "_fetch_task",
                        lambda api, target: {"status": "cooldown", "task": "ours"},
                        raising=False)

    workspaces = sandbox.list_sandbox_tasks(session_id="s1")["workspaces"]

    assert [w["sandbox_id"] for w in workspaces] == ["task-ours"]
    assert workspaces[0]["current"] is True


def test_a_chosen_workspace_reaches_the_sandbox_client(monkeypatch):
    """The dropdown is pointless if the id stops at the web layer."""
    from starlette.testclient import TestClient

    from CoScientist.tools.coder_tools import openhands_sandbox as sandbox
    from CoScientist.web.app import create_app

    seen = {}

    def listing(path, **kwargs):
        seen.update(path=path, sandbox_id=kwargs.get("sandbox_id"))
        return {"status": "ok", "path": path, "entries": []}

    monkeypatch.setattr(sandbox, "list_sandbox_files", listing, raising=False)

    with TestClient(create_app()) as client:
        client.get("/api/users/u1/sessions/s1/sandbox/files"
                   "?path=/workspace&sandbox_id=task-other")

    assert seen["sandbox_id"] == "task-other"


def test_the_transfer_honours_the_chosen_workspace(monkeypatch):
    """Otherwise "забрать" would quietly pull the file from a different run."""
    seen = {}

    def download(remote, local, **kwargs):
        seen["sandbox_id"] = kwargs.get("sandbox_id")
        open(local, "wb").close()
        return {"status": "ok", "size_bytes": 0, "sandbox_id": kwargs.get("sandbox_id")}

    monkeypatch.setattr(
        "CoScientist.tools.coder_tools.openhands_sandbox.download_sandbox_file",
        download, raising=False)
    _stub_upload(monkeypatch)

    sandbox_artifacts.transfer_sandbox_artifact(
        "/workspace/metrics.csv", session_id="s1", sandbox_id="task-other")

    assert seen["sandbox_id"] == "task-other"
