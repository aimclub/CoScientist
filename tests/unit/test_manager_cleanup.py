"""CoScientist manager cleanup must not delay the A2A terminal response."""

import asyncio
import threading
from types import SimpleNamespace

from CoScientist.cleanup import has_uploaded_papers, run_bounded_cleanup


def test_manager_close_bounds_s3_cleanup(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_cleanup(*_args):
        started.set()
        release.wait(timeout=1)

    try:
        asyncio.run(run_bounded_cleanup(blocking_cleanup, "tenant", "run", 0.01))
        assert started.is_set()
    finally:
        release.set()


def test_has_uploaded_papers_requires_a_non_empty_upload_registry():
    """The ordinary chat path must not touch S3 just to discover an empty prefix."""
    assert not has_uploaded_papers(None)
    assert not has_uploaded_papers(SimpleNamespace(state=None))
    assert not has_uploaded_papers(SimpleNamespace(state={}))
    assert not has_uploaded_papers(SimpleNamespace(state={"uploaded_paper_s3_keys": []}))
    assert has_uploaded_papers(SimpleNamespace(state={"uploaded_paper_s3_keys": ["key"]}))
