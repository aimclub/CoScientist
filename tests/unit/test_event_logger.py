from __future__ import annotations

import io
import sys

from CoScientist.logging import event_logger


def test_file_trace_is_written_as_utf8(tmp_path, monkeypatch):
    log_path = tmp_path / "agent_events.log"
    monkeypatch.setattr(event_logger, "_LOG_FILE", str(log_path))
    monkeypatch.setattr(event_logger, "_log_fh", None)
    monkeypatch.setattr(event_logger, "_log_disabled", False)

    event_logger._emit("🧑 USER ► GSK-3β inhibitor")

    handle = event_logger._log_fh
    assert handle is not None
    handle.close()
    monkeypatch.setattr(event_logger, "_log_fh", None)
    assert log_path.read_text(encoding="utf-8") == "🧑 USER ► GSK-3β inhibitor\n"


def test_legacy_console_does_not_abort_unicode_trace(tmp_path, monkeypatch):
    log_path = tmp_path / "agent_events.log"
    monkeypatch.setattr(event_logger, "_LOG_FILE", str(log_path))
    monkeypatch.setattr(event_logger, "_log_fh", None)
    monkeypatch.setattr(event_logger, "_log_disabled", False)
    output = io.BytesIO()
    console = io.TextIOWrapper(output, encoding="cp1251", write_through=True)

    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", console)
        event_logger._emit("🧑 USER ► GSK-3β inhibitor")

    assert b"\\U0001f9d1" in output.getvalue()
    handle = event_logger._log_fh
    assert handle is not None
    handle.close()
    monkeypatch.setattr(event_logger, "_log_fh", None)
    assert log_path.read_text(encoding="utf-8") == "🧑 USER ► GSK-3β inhibitor\n"
