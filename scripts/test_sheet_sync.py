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


class TestCompareFteTolerant:
    HEADER = "Project ID,Staff,% FTE,Comments\n"

    def test_small_fte_difference_within_tolerance_is_ignored(self):
        live = self.HEADER + "P1,Alice,19,\n"
        local = self.HEADER + "P1,Alice,19.09,\n"
        diff = sheet_sync.compare_fte_tolerant(live, local)
        assert diff.has_differences is False

    def test_large_fte_difference_is_reported(self):
        live = self.HEADER + "P1,Alice,20,\n"
        local = self.HEADER + "P1,Alice,10,\n"
        diff = sheet_sync.compare_fte_tolerant(live, local)
        assert len(diff.changed) == 1

    def test_difference_in_non_fte_column_is_reported_even_if_fte_matches(self):
        live = self.HEADER + "P1,Alice,20,new comment\n"
        local = self.HEADER + "P1,Alice,20,\n"
        diff = sheet_sync.compare_fte_tolerant(live, local)
        assert len(diff.changed) == 1

    def test_row_only_on_live_side_is_added(self):
        live = self.HEADER + "P1,Alice,20,\nP2,Bob,10,\n"
        local = self.HEADER + "P1,Alice,20,\n"
        diff = sheet_sync.compare_fte_tolerant(live, local)
        assert len(diff.added) == 1
        assert diff.added[0][0] == ("P2", "Bob")

    def test_row_only_on_local_side_is_removed(self):
        live = self.HEADER + "P1,Alice,20,\n"
        local = self.HEADER + "P1,Alice,20,\nP2,Bob,10,\n"
        diff = sheet_sync.compare_fte_tolerant(live, local)
        assert len(diff.removed) == 1
        assert diff.removed[0][0] == ("P2", "Bob")

    def test_custom_tolerance_respected(self):
        live = self.HEADER + "P1,Alice,20,\n"
        local = self.HEADER + "P1,Alice,15,\n"
        assert sheet_sync.compare_fte_tolerant(live, local, tolerance=10.0).has_differences is False
        assert sheet_sync.compare_fte_tolerant(live, local, tolerance=1.0).has_differences is True

    def test_non_numeric_fte_falls_back_to_string_comparison(self):
        live = self.HEADER + "P1,Alice,n/a,\n"
        local = self.HEADER + "P1,Alice,20,\n"
        diff = sheet_sync.compare_fte_tolerant(live, local)
        assert len(diff.changed) == 1


class TestMergeSupplementary:
    def test_appends_supplementary_rows_after_live_rows(self):
        result = sheet_sync.merge_supplementary(
            live_text="Role,Person,,,\nHead of Department,Iain Bate,,,\n",
            supplementary_text="Union,Chris Crispin-Bailey,,,\n",
        )
        rows = sheet_sync.parse_csv_rows(result)
        assert rows == [
            ["Role", "Person", "", "", ""],
            ["Head of Department", "Iain Bate", "", "", ""],
            ["Union", "Chris Crispin-Bailey", "", "", ""],
        ]

    def test_empty_supplementary_returns_live_content_unchanged_in_rows(self):
        result = sheet_sync.merge_supplementary(
            live_text="a,b\n1,2\n", supplementary_text=""
        )
        assert sheet_sync.parse_csv_rows(result) == [["a", "b"], ["1", "2"]]


class _Recorder:
    """Fake `out` callable that records every printed line, for assertions."""
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)

    def text(self):
        return "\n".join(self.lines)


class TestReadWriteLocalFile:
    def test_read_missing_file_returns_none(self, tmp_path):
        assert sheet_sync.read_local_file(tmp_path / "nope.csv") is None

    def test_write_then_read_round_trips(self, tmp_path):
        path = tmp_path / "f.csv"
        sheet_sync.write_local_file(path, "a,b\n1,2\n")
        assert sheet_sync.read_local_file(path) == "a,b\n1,2\n"


class TestResolveCompareFn:
    def test_defaults_to_exact(self):
        assert sheet_sync.resolve_compare_fn({}) is sheet_sync.compare_exact

    def test_uses_named_strategy(self):
        assert sheet_sync.resolve_compare_fn({"compare": "fte_tolerant"}) is sheet_sync.compare_fte_tolerant


class TestSyncSource:
    def test_inaccessible_source_reports_and_does_nothing(self, tmp_path, monkeypatch):
        out = _Recorder()
        called = []
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: called.append(1))
        sheet_sync.sync_source(
            "X.csv", {"url": "https://docs.google.com/spreadsheets/d/ABC", "accessible": False},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert called == []
        assert "not accessible" in out.text()

    def test_no_local_file_yet_creates_it_without_prompting(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        prompted = []
        sheet_sync.sync_source(
            "X.csv", {"url": "https://docs.google.com/spreadsheets/d/ABC"},
            data_dir=tmp_path, prompt=lambda p: prompted.append(p) or "y", out=lambda l: None,
        )
        assert prompted == []
        assert (tmp_path / "X.csv").read_text() == "a,b\n1,2\n"

    def test_fetch_error_is_reported_and_local_file_untouched(self, tmp_path, monkeypatch):
        (tmp_path / "X.csv").write_text("original\n")
        monkeypatch.setattr(
            sheet_sync, "fetch_sheet_csv",
            lambda *a, **k: (_ for _ in ()).throw(sheet_sync.FetchError("HTTP 401 ...")),
        )
        out = _Recorder()
        sheet_sync.sync_source(
            "X.csv", {"url": "https://docs.google.com/spreadsheets/d/ABC"},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert "could not fetch" in out.text()
        assert (tmp_path / "X.csv").read_text() == "original\n"

    def test_up_to_date_reports_and_writes_nothing(self, tmp_path, monkeypatch):
        (tmp_path / "X.csv").write_text("a,b\n1,2\n")
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        out = _Recorder()
        sheet_sync.sync_source(
            "X.csv", {"url": "https://docs.google.com/spreadsheets/d/ABC"},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert "up to date" in out.text()

    def test_difference_declined_leaves_local_file_unchanged(self, tmp_path, monkeypatch):
        (tmp_path / "X.csv").write_text("a,b\n1,2\n")
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,9\n")
        sheet_sync.sync_source(
            "X.csv", {"url": "https://docs.google.com/spreadsheets/d/ABC"},
            data_dir=tmp_path, prompt=lambda p: "n", out=lambda l: None,
        )
        assert (tmp_path / "X.csv").read_text() == "a,b\n1,2\n"

    def test_difference_confirmed_overwrites_local_file(self, tmp_path, monkeypatch):
        (tmp_path / "X.csv").write_text("a,b\n1,2\n")
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,9\n")
        sheet_sync.sync_source(
            "X.csv", {"url": "https://docs.google.com/spreadsheets/d/ABC"},
            data_dir=tmp_path, prompt=lambda p: "y", out=lambda l: None,
        )
        assert (tmp_path / "X.csv").read_text() == "a,b\n1,9\n"

    def test_empty_prompt_response_defaults_to_no(self, tmp_path, monkeypatch):
        (tmp_path / "X.csv").write_text("a,b\n1,2\n")
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,9\n")
        sheet_sync.sync_source(
            "X.csv", {"url": "https://docs.google.com/spreadsheets/d/ABC"},
            data_dir=tmp_path, prompt=lambda p: "", out=lambda l: None,
        )
        assert (tmp_path / "X.csv").read_text() == "a,b\n1,2\n"

    def test_confirmed_waw_sync_appends_supplementary_file(self, tmp_path, monkeypatch):
        (tmp_path / "WAW.csv").write_text("Head,Alice,,,\n")
        (tmp_path / "WAW_supplementary.csv").write_text("Union,Bob,,,\n")
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "Head,Carol,,,\n")
        sheet_sync.sync_source(
            "WAW.csv",
            {"url": "https://docs.google.com/spreadsheets/d/ABC",
             "supplementary_file": "WAW_supplementary.csv"},
            data_dir=tmp_path, prompt=lambda p: "y", out=lambda l: None,
        )
        result = (tmp_path / "WAW.csv").read_text()
        assert "Carol" in result
        assert "Bob" in result
        assert "Alice" not in result

    def test_waw_sync_is_idempotent_on_second_run_with_no_upstream_change(self, tmp_path, monkeypatch):
        """Regression test for the bug where sync_source() compared raw
        live_text against local_text but wrote merge_supplementary(live_text,
        supplementary_text) - a different document. That mismatch meant a
        WAW-style source could never settle into 'up to date', because every
        run's compare was against the pre-merge document while the file on
        disk held the post-merge one. Running sync_source twice with the
        exact same fetch must report 'up to date' (no prompt) the second
        time."""
        (tmp_path / "WAW.csv").write_text("Head,Alice,,,\n")
        (tmp_path / "WAW_supplementary.csv").write_text("Union,Bob,,,\n")
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "Head,Carol,,,\n")

        config = {
            "url": "https://docs.google.com/spreadsheets/d/ABC",
            "supplementary_file": "WAW_supplementary.csv",
        }

        # First run: there's a real difference (Alice -> Carol), confirm it.
        sheet_sync.sync_source(
            "WAW.csv", config, data_dir=tmp_path, prompt=lambda p: "y", out=lambda l: None,
        )

        # Second run: identical fetch, no upstream change - must be a no-op,
        # with no prompt needed (an unexpected prompt() call fails the test).
        def fail_prompt(p):
            raise AssertionError(f"prompt() should not be called on an idempotent second run: {p!r}")

        out = _Recorder()
        sheet_sync.sync_source(
            "WAW.csv", config, data_dir=tmp_path, prompt=fail_prompt, out=out,
        )
        assert "up to date" in out.text()


class TestSyncMultiTabSource:
    def test_no_configured_tabs_reports_skipped(self, tmp_path, monkeypatch):
        out = _Recorder()
        called = []
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: called.append(1))
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx", {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {}},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert called == []
        assert "tabs not configured" in out.text()

    def test_null_gid_tabs_are_skipped_not_fetched(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: called.append(1))
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {"Sheet1": None}},
            data_dir=tmp_path, prompt=lambda p: "y", out=lambda l: None,
        )
        assert called == []

    def test_configured_tab_is_fetched_and_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        out = _Recorder()
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {"Advisor Loads": "123"}},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert "Advisor Loads" in out.text()
        assert "fetched" in out.text()


class TestLoadSaveSources:
    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert sheet_sync.load_sources(tmp_path / "nope.json") == {}

    def test_save_then_load_round_trips(self, tmp_path):
        path = tmp_path / "sources.json"
        sheet_sync.save_sources({"X.csv": {"url": "https://example.com"}}, path=path)
        assert sheet_sync.load_sources(path) == {"X.csv": {"url": "https://example.com"}}


class TestFindUnmappedFiles:
    def test_finds_csv_and_xlsx_not_in_sources(self, tmp_path):
        (tmp_path / "mapped.csv").write_text("a\n")
        (tmp_path / "unmapped.csv").write_text("a\n")
        (tmp_path / "unmapped.xlsx").write_bytes(b"")
        (tmp_path / "ignored.json").write_text("{}")
        unmapped = sheet_sync.find_unmapped_files({"mapped.csv": {}}, data_dir=tmp_path)
        assert unmapped == ["unmapped.csv", "unmapped.xlsx"]

    def test_no_unmapped_files_returns_empty_list(self, tmp_path):
        (tmp_path / "mapped.csv").write_text("a\n")
        assert sheet_sync.find_unmapped_files({"mapped.csv": {}}, data_dir=tmp_path) == []


class TestCheckCoverage:
    def test_pasted_url_is_added_to_sources_and_saved(self, tmp_path):
        (tmp_path / "new_file.csv").write_text("a\n")
        sources = {}
        sources_path = tmp_path / "sources.json"
        sheet_sync.check_coverage(
            sources, data_dir=tmp_path,
            prompt=lambda p: "https://docs.google.com/spreadsheets/d/XYZ",
            out=lambda l: None, sources_path=sources_path,
        )
        assert sources["new_file.csv"]["url"] == "https://docs.google.com/spreadsheets/d/XYZ"
        saved = sheet_sync.load_sources(sources_path)
        assert saved["new_file.csv"]["url"] == "https://docs.google.com/spreadsheets/d/XYZ"

    def test_empty_response_skips_without_adding(self, tmp_path):
        (tmp_path / "new_file.csv").write_text("a\n")
        sources = {}
        sheet_sync.check_coverage(
            sources, data_dir=tmp_path, prompt=lambda p: "",
            out=lambda l: None, sources_path=tmp_path / "sources.json",
        )
        assert "new_file.csv" not in sources

    def test_no_unmapped_files_never_prompts(self, tmp_path):
        prompted = []
        sheet_sync.check_coverage(
            {}, data_dir=tmp_path, prompt=lambda p: prompted.append(p) or "",
            out=lambda l: None, sources_path=tmp_path / "sources.json",
        )
        assert prompted == []


class TestSyncOneSourceErrorIsolation:
    """main()'s loop must not let one bad source's config abort every other
    source's check - see task-8 review finding."""

    def test_missing_url_key_reports_error_and_does_not_raise(self, tmp_path):
        out = _Recorder()
        sheet_sync._sync_one_source(
            "Bad.csv", {}, data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert "unexpected error" in out.text()
        assert "Bad.csv" in out.text()

    def test_url_with_no_sheet_id_reports_error_and_does_not_raise(self, tmp_path):
        out = _Recorder()
        sheet_sync._sync_one_source(
            "Bad.csv", {"url": "https://example.com/not-a-sheet"},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert "unexpected error" in out.text()
        assert "Bad.csv" in out.text()

    def test_second_source_still_processed_after_first_source_errors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        out = _Recorder()
        sources = {
            "Bad.csv": {},  # missing 'url' - must not abort the loop
            "Good.csv": {"url": "https://docs.google.com/spreadsheets/d/ABC"},
        }
        for name, config in sources.items():
            sheet_sync._sync_one_source(name, config, data_dir=tmp_path, prompt=lambda p: "y", out=out)
        assert "Bad.csv: unexpected error" in out.text()
        assert (tmp_path / "Good.csv").read_text() == "a,b\n1,2\n"
