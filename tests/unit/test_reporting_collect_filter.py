"""Unit tests for binary/document filtering in reporting/collect.py."""
from __future__ import annotations

from pathlib import Path

from CoScientist.reporting.collect import _TABLE_EXTS, _looks_like, _table_to_markdown


def test_table_exts_excludes_binary_and_html():
    for ext in (".pdf", ".zip", ".tar.gz", ".html", ".bin"):
        assert ext not in _TABLE_EXTS
        assert not _looks_like(f"http://example.com/artifact{ext}", _TABLE_EXTS)


def test_non_table_and_binary_files_rejected_by_table_to_markdown(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")
    assert _table_to_markdown(pdf) is None

    zip_file = tmp_path / "archive.zip"
    zip_file.write_bytes(b"PK\x03\x04 fake zip content \x00")
    assert _table_to_markdown(zip_file) is None

    html = tmp_path / "index.html"
    html.write_text("<!DOCTYPE html><html><body><h1>Doc</h1></body></html>", encoding="utf-8")
    assert _table_to_markdown(html) is None

    # Binary file with .csv extension (e.g. corrupt or misnamed binary) is rejected by null byte check
    fake_csv = tmp_path / "corrupt.csv"
    fake_csv.write_bytes(b"header1,header2\x00\x01\x02binarydata")
    assert _table_to_markdown(fake_csv) is None
