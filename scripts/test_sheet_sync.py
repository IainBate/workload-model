"""Tests for sheet_sync.py - the Google Sheets sync-check tool.

Network calls are never made in tests: fetch_sheet_csv() is tested by
monkeypatching urllib.request.urlopen with a fake response, never by
hitting the real network.
"""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import sheet_sync  # noqa: E402


class TestExportUrl:
    def test_builds_export_url_from_plain_id_url(self):
        url = sheet_sync.export_url("https://docs.google.com/spreadsheets/d/ABC123")
        assert url == "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv"

    def test_strips_edit_suffix(self):
        url = sheet_sync.export_url(
            "https://docs.google.com/spreadsheets/d/ABC123/edit?usp=sharing"
        )
        assert url == "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv"

    def test_includes_gid_when_given(self):
        url = sheet_sync.export_url("https://docs.google.com/spreadsheets/d/ABC123", gid="999")
        assert url == "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv&gid=999"

    def test_raises_when_no_id_found(self):
        with pytest.raises(ValueError):
            sheet_sync.export_url("https://example.com/not-a-sheet")


class TestFetchSheetCsv:
    def _fake_urlopen(self, monkeypatch, body: bytes, raise_error=None):
        def fake(url, timeout=None):
            if raise_error:
                raise raise_error
            response = MagicMock()
            response.read.return_value = body
            response.__enter__ = lambda self: response
            response.__exit__ = lambda self, *a: False
            return response
        monkeypatch.setattr(sheet_sync.urllib.request, "urlopen", fake)

    def test_returns_decoded_csv_text(self, monkeypatch):
        self._fake_urlopen(monkeypatch, b"a,b,c\n1,2,3\n")
        text = sheet_sync.fetch_sheet_csv("https://docs.google.com/spreadsheets/d/ABC123")
        assert text == "a,b,c\n1,2,3\n"

    def test_raises_fetch_error_on_html_response(self, monkeypatch):
        """An HTML page instead of CSV is the signature of a sharing-
        permission problem - Google serves a sign-in page, not the export."""
        self._fake_urlopen(monkeypatch, b"<!DOCTYPE html><html>sign in</html>")
        with pytest.raises(sheet_sync.FetchError, match="HTML"):
            sheet_sync.fetch_sheet_csv("https://docs.google.com/spreadsheets/d/ABC123")

    def test_raises_fetch_error_on_http_error(self, monkeypatch):
        import urllib.error
        self._fake_urlopen(
            monkeypatch, b"",
            raise_error=urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
        )
        with pytest.raises(sheet_sync.FetchError, match="401"):
            sheet_sync.fetch_sheet_csv("https://docs.google.com/spreadsheets/d/ABC123")

    def test_raises_fetch_error_on_url_error(self, monkeypatch):
        import urllib.error
        self._fake_urlopen(monkeypatch, b"", raise_error=urllib.error.URLError("no route"))
        with pytest.raises(sheet_sync.FetchError, match="could not reach"):
            sheet_sync.fetch_sheet_csv("https://docs.google.com/spreadsheets/d/ABC123")


class TestParseCsvRows:
    def test_parses_simple_csv(self):
        rows = sheet_sync.parse_csv_rows("a,b\n1,2\n")
        assert rows == [["a", "b"], ["1", "2"]]

    def test_handles_quoted_commas(self):
        rows = sheet_sync.parse_csv_rows('a,"b,c"\n')
        assert rows == [["a", "b,c"]]


class TestDiffResult:
    def test_has_differences_false_when_empty(self):
        diff = sheet_sync.DiffResult(added=[], removed=[], changed=[])
        assert diff.has_differences is False

    def test_has_differences_true_when_any_present(self):
        diff = sheet_sync.DiffResult(added=[(0, ["x"])], removed=[], changed=[])
        assert diff.has_differences is True

    def test_summary_lines_formats_each_kind(self):
        diff = sheet_sync.DiffResult(
            added=[(2, ["new", "row"])],
            removed=[(1, ["old", "row"])],
            changed=[(0, ["a"], ["b"])],
        )
        lines = diff.summary_lines()
        assert any(line.startswith("  + ") for line in lines)
        assert any(line.startswith("  - ") for line in lines)
        assert any(line.startswith("  ~ ") for line in lines)

    def test_summary_lines_caps_at_limit(self):
        diff = sheet_sync.DiffResult(
            added=[(i, [str(i)]) for i in range(30)], removed=[], changed=[]
        )
        lines = diff.summary_lines(limit=5)
        assert len(lines) == 6  # 5 shown + 1 "... and N more"
        assert "and 25 more" in lines[-1]


class TestCompareExact:
    def test_identical_content_has_no_differences(self):
        diff = sheet_sync.compare_exact("a,b\n1,2\n", "a,b\n1,2\n")
        assert diff.has_differences is False

    def test_changed_row_detected(self):
        diff = sheet_sync.compare_exact("a,b\n1,2\n", "a,b\n1,9\n")
        assert len(diff.changed) == 1
        key, local_row, live_row = diff.changed[0]
        assert key == 1
        assert local_row == ["1", "9"]
        assert live_row == ["1", "2"]

    def test_added_row_detected_when_live_is_longer(self):
        diff = sheet_sync.compare_exact("a\nb\nc\n", "a\nb\n")
        assert diff.added == [(2, ["c"])]
        assert diff.removed == []

    def test_removed_row_detected_when_local_is_longer(self):
        diff = sheet_sync.compare_exact("a\nb\n", "a\nb\nc\n")
        assert diff.removed == [(2, ["c"])]
        assert diff.added == []
