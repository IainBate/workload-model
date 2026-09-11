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
