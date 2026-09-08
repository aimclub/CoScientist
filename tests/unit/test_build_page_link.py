"""What a build hands back about itself.

The agent acts on these fields, so they must not point at a page that is not
there or invite it to look for the build somewhere else on the machine.
"""

import pytest

from CoScientist.tools import alembic_tools


@pytest.fixture
def job(tmp_path):
    return {
        "job_id": "gget-938c68",
        "repo_url": "https://github.com/pachterlab/gget",
        "status": "running",
        "started_at": 0.0,
        "log_file": str(tmp_path / "build.log"),
    }


def test_no_web_ui_configured_means_no_link_to_one(job, monkeypatch):
    """The build page exists only while the web UI runs. A link that does not
    open sends the agent hunting for the build elsewhere."""
    monkeypatch.setattr(alembic_tools, "_WEB_BASE_URL", "")

    out = alembic_tools._snapshot(job)

    assert "progress_url" not in out
    assert out["progress_page"] == "/builds/gget-938c68"  # the web layer resolves it


def test_a_configured_web_ui_is_linked_absolutely(job, monkeypatch):
    monkeypatch.setattr(alembic_tools, "_WEB_BASE_URL", "http://box:8000")

    out = alembic_tools._snapshot(job)

    assert out["progress_url"] == "http://box:8000/builds/gget-938c68"


def test_a_running_build_is_told_where_its_result_comes_from(job):
    """A live run watched an agent validate a leftover container from an earlier
    build and call the task done. The note says not to."""
    note = alembic_tools._snapshot(job)["note"]

    assert "check_mcp_build('gget-938c68')" in note
    assert "only source" in note
