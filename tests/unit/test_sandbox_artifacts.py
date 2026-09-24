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
