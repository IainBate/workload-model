"""Tests for sheet_sync.py - the Google Sheets sync-check tool.

Network calls are never made in tests: fetch_sheet_csv() is tested by
monkeypatching urllib.request.urlopen with a fake response, never by
hitting the real network.
"""

import json
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

    def test_column_missing_from_live_header_is_reported(self):
        """The motivating bug for this tool was a renamed/dropped CSV
        column - compare_fte_tolerant must not silently ignore a column
        that exists locally (with actual data) but is missing from the
        live sheet's header entirely."""
        live = "Project ID,Staff,% FTE\nP1,Alice,20\n"
        local = self.HEADER + "P1,Alice,20,important note\n"
        diff = sheet_sync.compare_fte_tolerant(live, local)
        assert diff.has_differences is True

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


class TestSyncMultiTabSourceAccessibility:
    def test_inaccessible_multi_tab_source_reports_and_never_fetches(self, tmp_path, monkeypatch):
        """Defense in depth: sync_multi_tab_source() must honor 'accessible'
        itself, matching the pattern already in sync_source() - it must not
        rely solely on a caller checking first."""
        out = _Recorder()
        called = []
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: called.append(1))
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC",
             "tabs": {"Advisor Loads": "123"}, "accessible": False},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert called == []
        assert "not accessible" in out.text()


class TestSyncOneSourceAccessibilityOrdering:
    """main() had a latent ordering bug: it checked 'tabs' in config before
    checking 'accessible', so a multi-tab source marked accessible: false
    would still get fetched (sync_multi_tab_source never checked that flag).
    The accessible check must run before the tabs-vs-single-file dispatch."""

    def test_inaccessible_multi_tab_source_never_calls_fetch(self, tmp_path, monkeypatch):
        out = _Recorder()
        called = []
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: called.append(1))
        sheet_sync._sync_one_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC",
             "tabs": {"Advisor Loads": "123"}, "accessible": False},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert called == []
        assert "not accessible" in out.text()


class TestMain:
    def test_main_dispatches_all_sources_then_runs_check_coverage(self, tmp_path, monkeypatch):
        sources_path = tmp_path / "google_sheets_sources.json"
        sheet_sync.save_sources(
            {
                "A.csv": {"url": "https://docs.google.com/spreadsheets/d/AAA"},
                "B.csv": {"url": "https://docs.google.com/spreadsheets/d/BBB"},
            },
            path=sources_path,
        )
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        # An unmapped file, so check_coverage has something to report -
        # lets us prove ordering (loop dispatch happens before this prompt).
        (tmp_path / "C.csv").write_text("x\n")

        events = []
        out = lambda line: events.append(("out", line))

        def prompt(p):
            events.append(("prompt", p))
            return "y"

        sheet_sync.main(prompt=prompt, out=out, data_dir=tmp_path)

        assert (tmp_path / "A.csv").read_text() == "a,b\n1,2\n"
        assert (tmp_path / "B.csv").read_text() == "a,b\n1,2\n"

        prompt_events = [p for kind, p in events if kind == "prompt"]
        assert len(prompt_events) == 1
        assert "C.csv" in prompt_events[0]
        # check_coverage's prompt must come after both sources were synced.
        out_before_prompt = "\n".join(
            line for kind, line in events[: events.index(("prompt", prompt_events[0]))]
            if kind == "out"
        )
        assert "A.csv" in out_before_prompt
        assert "B.csv" in out_before_prompt

    def test_main_reports_when_no_sources_configured(self, tmp_path):
        out = _Recorder()
        sheet_sync.main(prompt=lambda p: "", out=out, data_dir=tmp_path)
        assert "No sources configured" in out.text()


class TestLoadSaveSources:
    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert sheet_sync.load_sources(tmp_path / "nope.json") == {}

    def test_save_then_load_round_trips(self, tmp_path):
        path = tmp_path / "sources.json"
        sheet_sync.save_sources({"X.csv": {"url": "https://example.com"}}, path=path)
        assert sheet_sync.load_sources(path) == {"X.csv": {"url": "https://example.com"}}

    def test_save_preserves_insertion_order_not_alphabetical(self, tmp_path):
        """The spec says sources are processed 'in the order given in the
        JSON file' - save_sources() must not silently reorder them
        alphabetically on the first coverage-check addition."""
        path = tmp_path / "sources.json"
        sheet_sync.save_sources(
            {"Zebra.csv": {"url": "https://example.com/z"},
             "Apple.csv": {"url": "https://example.com/a"}},
            path=path,
        )
        assert list(sheet_sync.load_sources(path).keys()) == ["Zebra.csv", "Apple.csv"]


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

    def test_supplementary_file_of_a_configured_source_is_excluded(self, tmp_path):
        """WAW_supplementary.csv (and any future supplementary file) can
        never have a Google Sheet of its own by design - it must not be
        flagged as needing one, forever, by check_coverage()."""
        (tmp_path / "WAW.csv").write_text("a\n")
        (tmp_path / "WAW_supplementary.csv").write_text("a\n")
        sources = {
            "WAW.csv": {
                "url": "https://docs.google.com/spreadsheets/d/ABC",
                "supplementary_file": "WAW_supplementary.csv",
            }
        }
        assert sheet_sync.find_unmapped_files(sources, data_dir=tmp_path) == []


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

    def test_non_url_response_is_rejected_and_not_added(self, tmp_path):
        """Regression test - a live smoke test once misfired because
        check_coverage() accepted any non-blank string as a URL."""
        (tmp_path / "new_file.csv").write_text("a\n")
        sources = {}
        out = _Recorder()
        sheet_sync.check_coverage(
            sources, data_dir=tmp_path, prompt=lambda p: "not a url",
            out=out, sources_path=tmp_path / "sources.json",
        )
        assert "new_file.csv" not in sources
        assert "not a URL" in out.text()
        assert not (tmp_path / "sources.json").exists()

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


class TestListSheetTabs:
    """list_sheet_tabs() - optional, API-key-based tab discovery (no OAuth,
    but requires a GOOGLE_SHEETS_API_KEY the CSV-export path never needed).
    Used to flag a tab that exists live but isn't yet in
    google_sheets_sources.json's "tabs" config, without ever guessing which
    tab is "current"."""

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

    def test_returns_title_to_gid_mapping(self, monkeypatch):
        body = json.dumps({
            "sheets": [
                {"properties": {"sheetId": 1402610559, "title": "2026-7"}},
                {"properties": {"sheetId": 177948210, "title": "Allocation"}},
            ]
        }).encode("utf-8")
        self._fake_urlopen(monkeypatch, body)
        tabs = sheet_sync.list_sheet_tabs("https://docs.google.com/spreadsheets/d/ABC123", "fake-key")
        assert tabs == {"2026-7": "1402610559", "Allocation": "177948210"}

    def test_api_key_included_in_request_url(self, monkeypatch):
        captured = {}

        def fake(url, timeout=None):
            captured["url"] = url
            response = MagicMock()
            response.read.return_value = json.dumps({"sheets": []}).encode("utf-8")
            response.__enter__ = lambda self: response
            response.__exit__ = lambda self, *a: False
            return response
        monkeypatch.setattr(sheet_sync.urllib.request, "urlopen", fake)

        sheet_sync.list_sheet_tabs("https://docs.google.com/spreadsheets/d/ABC123", "my-key-123")
        assert "key=my-key-123" in captured["url"]
        assert "ABC123" in captured["url"]

    def test_raises_fetch_error_on_http_error(self, monkeypatch):
        import urllib.error
        self._fake_urlopen(
            monkeypatch, b"",
            raise_error=urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        )
        with pytest.raises(sheet_sync.FetchError, match="403"):
            sheet_sync.list_sheet_tabs("https://docs.google.com/spreadsheets/d/ABC123", "fake-key")

    def test_raises_fetch_error_on_url_error(self, monkeypatch):
        import urllib.error
        self._fake_urlopen(monkeypatch, b"", raise_error=urllib.error.URLError("no route"))
        with pytest.raises(sheet_sync.FetchError, match="could not reach"):
            sheet_sync.list_sheet_tabs("https://docs.google.com/spreadsheets/d/ABC123", "fake-key")

    def test_raises_value_error_when_no_sheet_id_in_url(self):
        with pytest.raises(ValueError):
            sheet_sync.list_sheet_tabs("https://example.com/not-a-sheet", "fake-key")


class TestFindUnconfiguredTabs:
    def test_tab_present_live_but_not_in_config_is_flagged(self):
        result = sheet_sync.find_unconfigured_tabs(
            configured_tabs={"2026-7": "1402610559"},
            live_tabs={"2026-7": "1402610559", "2025-6": "1144909221"},
        )
        assert result == {"2025-6": "1144909221"}

    def test_configured_tab_with_null_gid_is_not_flagged_as_new(self):
        """A tab already listed in config (even with a not-yet-filled-in
        null gid) is "known about", not "new" - only a title with no key
        in configured_tabs at all counts as newly discovered."""
        result = sheet_sync.find_unconfigured_tabs(
            configured_tabs={"2026-7": "1402610559", "2025-6": None},
            live_tabs={"2026-7": "1402610559", "2025-6": "1144909221"},
        )
        assert result == {}

    def test_nothing_flagged_when_everything_configured(self):
        result = sheet_sync.find_unconfigured_tabs(
            configured_tabs={"2026-7": "1402610559"},
            live_tabs={"2026-7": "1402610559"},
        )
        assert result == {}

    def test_ignored_tab_is_not_flagged(self):
        """A tab a human has already looked at and judged irrelevant (e.g.
        Allocation, General Checking) stays silent from then on - it's been
        reviewed, so it's no longer "unknown", just deliberately excluded."""
        result = sheet_sync.find_unconfigured_tabs(
            configured_tabs={"2026-7": "1402610559"},
            live_tabs={"2026-7": "1402610559", "Allocation": "177948210"},
            ignored_tabs=["Allocation"],
        )
        assert result == {}

    def test_unreviewed_tab_still_flagged_even_with_an_ignore_list_present(self):
        """The ignore list only silences tabs explicitly named in it - a
        genuinely new, never-reviewed tab must still surface even when other
        tabs are being ignored."""
        result = sheet_sync.find_unconfigured_tabs(
            configured_tabs={"2026-7": "1402610559"},
            live_tabs={"2026-7": "1402610559", "Allocation": "177948210", "2027-8": "555"},
            ignored_tabs=["Allocation"],
        )
        assert result == {"2027-8": "555"}


class TestSyncMultiTabSourceNewTabDetection:
    def test_no_api_key_skips_new_tab_check_entirely(self, tmp_path, monkeypatch):
        """Default behaviour (no api_key passed) must be unchanged from
        before this feature existed - list_sheet_tabs must not even be
        called."""
        called = []
        monkeypatch.setattr(sheet_sync, "list_sheet_tabs", lambda *a, **k: called.append(1))
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        out = _Recorder()
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {"2026-7": "123"}},
            data_dir=tmp_path, prompt=lambda p: "y", out=out,
        )
        assert called == []

    def test_api_key_present_flags_new_tab(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        monkeypatch.setattr(
            sheet_sync, "list_sheet_tabs",
            lambda url, key, **k: {"2026-7": "123", "2025-6": "999"},
        )
        out = _Recorder()
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {"2026-7": "123"}},
            data_dir=tmp_path, prompt=lambda p: "y", out=out, api_key="fake-key",
        )
        assert "2025-6" in out.text()
        assert "999" in out.text()

    def test_api_key_present_and_nothing_new_reports_nothing_extra(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        monkeypatch.setattr(
            sheet_sync, "list_sheet_tabs",
            lambda url, key, **k: {"2026-7": "123"},
        )
        out = _Recorder()
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {"2026-7": "123"}},
            data_dir=tmp_path, prompt=lambda p: "y", out=out, api_key="fake-key",
        )
        assert "new tab" not in out.text()

    def test_new_tab_check_runs_even_when_no_tabs_configured_yet(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: called.append(1))
        monkeypatch.setattr(
            sheet_sync, "list_sheet_tabs",
            lambda url, key, **k: {"2026-7": "123"},
        )
        out = _Recorder()
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {}},
            data_dir=tmp_path, prompt=lambda p: "y", out=out, api_key="fake-key",
        )
        assert called == []  # still never fetches CSV content for an unconfigured tab
        assert "2026-7" in out.text()
        assert "123" in out.text()

    def test_list_tabs_fetch_error_is_reported_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sheet_sync, "fetch_sheet_csv", lambda *a, **k: "a,b\n1,2\n")
        monkeypatch.setattr(
            sheet_sync, "list_sheet_tabs",
            lambda url, key, **k: (_ for _ in ()).throw(sheet_sync.FetchError("HTTP 403")),
        )
        out = _Recorder()
        sheet_sync.sync_multi_tab_source(
            "Book.xlsx",
            {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {"2026-7": "123"}},
            data_dir=tmp_path, prompt=lambda p: "y", out=out, api_key="fake-key",
        )
        assert "could not check for new tabs" in out.text()


class TestMainThreadsApiKey:
    def test_main_reads_api_key_from_environment_when_not_passed(self, tmp_path, monkeypatch):
        sheet_sync.save_sources(
            {"Book.xlsx": {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {}}},
            path=tmp_path / "google_sheets_sources.json",
        )
        captured = {}

        def fake_sync_multi_tab_source(name, config, data_dir=None, prompt=None, out=None, api_key=None):
            captured["api_key"] = api_key
        monkeypatch.setattr(sheet_sync, "sync_multi_tab_source", fake_sync_multi_tab_source)
        monkeypatch.setenv("GOOGLE_SHEETS_API_KEY", "env-key-value")

        sheet_sync.main(prompt=lambda p: "", out=lambda l: None, data_dir=tmp_path)
        assert captured["api_key"] == "env-key-value"

    def test_explicit_api_key_argument_overrides_environment(self, tmp_path, monkeypatch):
        sheet_sync.save_sources(
            {"Book.xlsx": {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {}}},
            path=tmp_path / "google_sheets_sources.json",
        )
        captured = {}

        def fake_sync_multi_tab_source(name, config, data_dir=None, prompt=None, out=None, api_key=None):
            captured["api_key"] = api_key
        monkeypatch.setattr(sheet_sync, "sync_multi_tab_source", fake_sync_multi_tab_source)
        monkeypatch.setenv("GOOGLE_SHEETS_API_KEY", "env-key-value")

        sheet_sync.main(prompt=lambda p: "", out=lambda l: None, data_dir=tmp_path, api_key="explicit-key")
        assert captured["api_key"] == "explicit-key"

    def test_no_env_var_and_no_argument_means_none(self, tmp_path, monkeypatch):
        sheet_sync.save_sources(
            {"Book.xlsx": {"url": "https://docs.google.com/spreadsheets/d/ABC", "tabs": {}}},
            path=tmp_path / "google_sheets_sources.json",
        )
        captured = {}

        def fake_sync_multi_tab_source(name, config, data_dir=None, prompt=None, out=None, api_key=None):
            captured["api_key"] = api_key
        monkeypatch.setattr(sheet_sync, "sync_multi_tab_source", fake_sync_multi_tab_source)
        monkeypatch.delenv("GOOGLE_SHEETS_API_KEY", raising=False)

        sheet_sync.main(prompt=lambda p: "", out=lambda l: None, data_dir=tmp_path)
        assert captured["api_key"] is None
