# Google Sheets Sync-Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone, on-demand script (`python sync_sheets.py`) that fetches every known Google Sheets source, diffs each against its local `data/` counterpart, and asks before writing any change - so drift like the header-rename bug found this session (which silently zeroed every research grant hour) gets caught instead of discovered by accident.

**Architecture:** A new `scripts/sheet_sync.py` module holds everything: a thin unauthenticated-fetch layer (CSV export URL, no OAuth), two pure comparison strategies (exact match; a numeric-tolerance variant for one known file), a pure supplementary-file merge for WAW.csv, and an orchestration layer that reads `data/google_sheets_sources.json`, loops sources, and prompts before writing. A small, targeted fix lands in the existing `scripts/data_loader.py` (`_load_waw_roles()`) so WAW.csv's "Research Group Leader"/"Research Mentor" sections - which use a blank-cell-means-same-as-above convention this parser has never had to handle - actually parse. `scripts/sync_sheets.py` (thin, at the repo's scripts root next to `main.py`) is the entry point.

**Tech Stack:** Python 3, standard library only (`csv`, `json`, `urllib.request`, `re`) - no new dependency. `pytest` for tests, following this repo's existing `tmp_path`/`monkeypatch` fixture style (see `test_data_loader.py`'s `TestStaffCategoriesModelledAndEmailParsing` class for the pattern this plan's tests mirror).

**Spec:** `docs/superpowers/specs/2026-09-11-google-sheets-sync-design.md`

## Global Constraints

- No OAuth anywhere in this feature - every fetch is a plain HTTP GET against a sheet's public CSV export URL.
- `main.py`'s calculation run is never touched by this feature - it stays fully offline. This is a separate script.
- No new third-party dependency - standard library only.
- Every propagate decision is an explicit `y`/`N` prompt; default on empty input is **No** (nothing is ever written without an explicit `y`).
- `% FTE for CS.csv`'s FTE-tolerance default is 1.0 percentage points (matches the rounding noise already observed this session; confirmed no observed legitimate difference is under ~0.1 or this tolerant).
- Full xlsx tab-by-tab comparison/write-back (`CS WTW Who Teaches What.xlsx`, `ProjectLoads 2025-26.xlsx`) is **out of scope for this plan** - both sources currently have unconfigured tab gids anyway, so this pass implements "fetch a configured tab and print it for manual review," not an automatic local-xlsx diff/write. Wiring full xlsx support in is explicitly deferred, not silently attempted.

---

### Task 1: Source config and WAW supplementary data files

**Files:**
- Create: `data/google_sheets_sources.json`
- Create: `data/WAW_supplementary.csv`
- Test: `scripts/test_sheet_sync_config.py`

**Interfaces:**
- Produces: `data/google_sheets_sources.json` - the JSON file every later task's `load_sources()` reads. Schema: `{local_filename: {"url": str, optionally "gid": str, "tabs": {tab_name: gid_or_null}, "compare": str, "supplementary_file": str, "accessible": bool}}`.
- Produces: `data/WAW_supplementary.csv` - same 5-column shape as `data/WAW.csv` (`Role,Person,,,`), holding the Union row.

- [ ] **Step 1: Write the failing test**

```python
# scripts/test_sheet_sync_config.py
"""Guards the shape of data/google_sheets_sources.json - a typo here would
silently break sync_sheets.py for that one source."""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

DATA_DIR = SCRIPTS_DIR.parent / "data"
SOURCES_FILE = DATA_DIR / "google_sheets_sources.json"


def test_sources_file_is_valid_json():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    assert len(data) == 9


@pytest.mark.parametrize("name", [
    "WAW.csv",
    "% FTE for CS.csv",
    "CS Module Numbers.csv",
    "PhD Supervision Data.csv",
    "workload_adjustments.csv",
    "CS Research Groups.csv",
    "CS Module Assessment Numbers.csv",
    "CS WTW Who Teaches What.xlsx",
    "ProjectLoads 2025-26.xlsx",
])
def test_every_known_source_present(name):
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert name in data
    assert data[name]["url"].startswith("https://docs.google.com/spreadsheets/d/")


def test_waw_has_supplementary_file_configured():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["WAW.csv"]["supplementary_file"] == "WAW_supplementary.csv"


def test_fte_uses_tolerant_comparison():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["% FTE for CS.csv"]["compare"] == "fte_tolerant"


def test_module_assessment_numbers_marked_inaccessible():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["CS Module Assessment Numbers.csv"]["accessible"] is False


def test_waw_supplementary_file_has_union_row():
    content = (DATA_DIR / "WAW_supplementary.csv").read_text(encoding="utf-8")
    assert "Union" in content
    assert "Chris Crispin-Bailey" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python3 -m pytest test_sheet_sync_config.py -v`
Expected: FAIL - `data/google_sheets_sources.json` doesn't exist yet (`FileNotFoundError`).

- [ ] **Step 3: Create `data/google_sheets_sources.json`**

```json
{
  "WAW.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1mMEwW5UUkOguRDdtDNjA-1yRigPO3633F7YQf3C0o4s",
    "gid": "991769073",
    "supplementary_file": "WAW_supplementary.csv"
  },
  "% FTE for CS.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1LoF95Hy0J1aHYiy4bC_1FstG1MwnzDZQnxg3rw7jW6Q",
    "compare": "fte_tolerant"
  },
  "CS Module Numbers.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1WaS8snhkSZiIlCqYtWlD3iwk5GuefNj0GnKzJXiWhY8"
  },
  "PhD Supervision Data.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1DrPBAn-LKFxXzetkoEahzo2hLcMRRkT1gduLoWQ252Y"
  },
  "workload_adjustments.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1A9QYHbOArZc8l05gUt8Rs8TNwuZ-a5v5D000z2MvTlo"
  },
  "CS Research Groups.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1Akv7KO91jLj5JlRmB8vSlRwWHF1cuLH9XeQPrAhLC4M"
  },
  "CS Module Assessment Numbers.csv": {
    "url": "https://docs.google.com/spreadsheets/d/1Nb_og04ZA1egQhia2uoekvuWX1BdpjKLvG-EohJkni0",
    "accessible": false
  },
  "CS WTW Who Teaches What.xlsx": {
    "url": "https://docs.google.com/spreadsheets/d/1QlWKgsuH_x6qI5tdmpcsf7_y2R0QbAtbBwZNAYvxLVw",
    "tabs": {}
  },
  "ProjectLoads 2025-26.xlsx": {
    "url": "https://docs.google.com/spreadsheets/d/1J2XRbGXz3JFAUPel3jeGS0JRAmNOo2yx",
    "tabs": { "Advisor Loads": null }
  }
}
```

- [ ] **Step 4: Create `data/WAW_supplementary.csv`**

```csv
Union,Chris Crispin-Bailey,,,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd scripts && python3 -m pytest test_sheet_sync_config.py -v`
Expected: PASS (all 11 tests)

- [ ] **Step 6: Commit**

```bash
git add data/google_sheets_sources.json data/WAW_supplementary.csv scripts/test_sheet_sync_config.py
git commit -m "Add Google Sheets source mapping and WAW supplementary data

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjPpmKMbkCVkksxSiupx2X"
```

---

### Task 2: Fix `_load_waw_roles()` to handle blank-cell-inherits-role, and map current section wording

**Files:**
- Modify: `scripts/data_loader.py` (the `_load_waw_roles()` function, and the `_WAW_ROLE_MAPPING` dict)
- Test: `scripts/test_data_loader.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_load_waw_roles()` keeps its existing signature and return type (`Dict[str, list]`, `{role_name: [staff_name, ...]}`) - this task only changes its parsing behavior, not its interface. `_WAW_ROLE_MAPPING` gains two new keys: `"Research Group Leads"` and `"Research Grant Mentors"`.

- [ ] **Step 1: Write the failing tests**

Add to `scripts/test_data_loader.py` (find `class TestModuleVariantMerging` and insert a new class immediately before it):

```python
class TestWAWRolesBlankCellCarryForward:
    """_load_waw_roles() - a blank role cell (column A) inherits the role
    from the nearest non-blank role above it, as long as no fully-blank
    separator row comes between them. This is what a merged Google Sheets
    cell looks like once exported to CSV; the sheet author has started using
    it for the Research Group Leader / Research Mentor sections."""

    def _write(self, path, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for row in rows:
                writer.writerow(row)

    def test_blank_role_inherits_previous_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        self._write(tmp_path / "WAW.csv", [
            ["Research Group Leader", "Alice", "", ""],
            ["", "Bob", "", ""],
            ["", "Carol", "", ""],
        ])
        roles = dl._load_waw_roles()
        assert roles == {"Research Group Leader": ["Alice", "Bob", "Carol"]}

    def test_fully_blank_row_resets_carry_forward(self, tmp_path, monkeypatch):
        """A blank separator row between two unrelated blocks must not let a
        role leak from the first block into rows of the second."""
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        self._write(tmp_path / "WAW.csv", [
            ["Research Group Leader", "Alice", "", ""],
            ["", "", "", ""],
            ["", "Bob", "", ""],
        ])
        roles = dl._load_waw_roles()
        assert roles == {"Research Group Leader": ["Alice"]}

    def test_existing_repeat_every_row_style_still_works(self, tmp_path, monkeypatch):
        """Every pre-existing block in WAW.csv repeats the role on every row
        (e.g. 'Ethics Committee members') rather than leaving it blank -
        that style must keep working unchanged."""
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        self._write(tmp_path / "WAW.csv", [
            ["Ethics Committee members", "Alice", "", ""],
            ["Ethics Committee members", "Bob", "", ""],
        ])
        roles = dl._load_waw_roles()
        assert roles == {"Ethics Committee members": ["Alice", "Bob"]}

    def test_research_grant_mentors_section_parses_with_current_mapping(self, tmp_path, monkeypatch):
        """Reproduces the live sheet's current 'Research Grant Mentors'
        block shape exactly (role blank after the first row, person in
        column B) - this should now parse into 'Research Mentor' once
        combined with the _WAW_ROLE_MAPPING entry from this task."""
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        self._write(tmp_path / "WAW.csv", [
            ["Research Grant Mentors", "Pengcheng Liu", "", ""],
            ["", "Radu Calinescu", "", ""],
        ])
        roles = dl._load_waw_roles()
        assert roles == {"Research Grant Mentors": ["Pengcheng Liu", "Radu Calinescu"]}
        assert dl._WAW_ROLE_MAPPING["Research Grant Mentors"] == "Research Mentor"

    def test_research_group_leads_mapping_entry_present(self):
        assert dl._WAW_ROLE_MAPPING["Research Group Leads"] == "Research Group Leader"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python3 -m pytest test_data_loader.py -k WAWRolesBlankCellCarryForward -v`
Expected: FAIL - `test_blank_role_inherits_previous_row` and `test_fully_blank_row_resets_carry_forward` fail because today's `_load_waw_roles()` treats a blank-role row as `if not role: continue` (skips it entirely, doesn't inherit); `test_research_grant_mentors_section_parses_with_current_mapping` and `test_research_group_leads_mapping_entry_present` fail with `KeyError` (mapping entries don't exist yet).

- [ ] **Step 3: Modify `_load_waw_roles()` in `scripts/data_loader.py`**

Find the current implementation:

```python
def _load_waw_roles(filepath: str = "WAW.csv") -> Dict[str, list]:
    """Load departmental roles from WAW.csv. Returns {role_name: [(staff_name, percentage)]}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    # Parse the WAW CSV which has a specific structure
    roles = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            role = row[0].strip()
            # WAW structure: col0=role, col1=on-campus staff, col2=empty, col3=online staff
            staff_on_campus = row[1].strip() if len(row) > 1 else ""
            staff_online = row[3].strip() if len(row) > 3 else ""
            # Skip header and non-role rows
            if not role or role.startswith("Departmental") or role.startswith("Green"):
                continue
            if role.startswith("Red indicates"):
                continue
            # Cross-reference rows point the reader at a role recorded elsewhere in
            # the file ("see main roles below"); they are not assignments, so they
            # must not become roles - otherwise every one raises a spurious unknown
            # -role warning once unrecognised names are flagged.
            if staff_on_campus.lower().startswith("see main roles"):
                continue
            # Only include on-campus staff (skip online team)
            if staff_on_campus:
                roles.setdefault(role, []).append(staff_on_campus)
    return roles
```

Replace with:

```python
def _load_waw_roles(filepath: str = "WAW.csv") -> Dict[str, list]:
    """Load departmental roles from WAW.csv. Returns {role_name: [(staff_name, percentage)]}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    # Parse the WAW CSV which has a specific structure
    roles = {}
    last_role = None
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            role = row[0].strip()
            # WAW structure: col0=role, col1=on-campus staff, col2=empty, col3=online staff
            staff_on_campus = row[1].strip() if len(row) > 1 else ""
            staff_online = row[3].strip() if len(row) > 3 else ""

            # A fully-blank row (role AND person both empty) is a section
            # separator - reset carry-forward so a role can't leak from one
            # block into an unrelated block below it.
            if not role and not staff_on_campus:
                last_role = None
                continue

            # A blank role cell (but a person present) is what a merged
            # Google Sheets cell looks like once exported to CSV - it means
            # "same role as the row above" (e.g. Research Group Leader /
            # Research Mentor, each listed once per person on its own row).
            if not role:
                role = last_role
            else:
                last_role = role

            if not role:
                continue

            # Skip header and non-role rows
            if role.startswith("Departmental") or role.startswith("Green"):
                continue
            if role.startswith("Red indicates"):
                continue
            # Cross-reference rows point the reader at a role recorded elsewhere in
            # the file ("see main roles below"); they are not assignments, so they
            # must not become roles - otherwise every one raises a spurious unknown
            # -role warning once unrecognised names are flagged.
            if staff_on_campus.lower().startswith("see main roles"):
                continue
            # Only include on-campus staff (skip online team)
            if staff_on_campus:
                roles.setdefault(role, []).append(staff_on_campus)
    return roles
```

- [ ] **Step 4: Add the two new `_WAW_ROLE_MAPPING` entries**

Find (near the end of the `_WAW_ROLE_MAPPING` dict definition):

```python
    "Deputy Director of Admissions (UG Admissions)": "Deputy Director of Admissions (UG Admissions)",
}
```

Replace with:

```python
    "Deputy Director of Admissions (UG Admissions)": "Deputy Director of Admissions (UG Admissions)",
    # Current WAW.csv section wording (2026-09) for these two blocks -
    # "Leads"/"Grant Mentors" rather than the singular "Leader"/"Mentor"
    # workload_parameters.yaml actually uses.
    "Research Group Leads": "Research Group Leader",
    "Research Grant Mentors": "Research Mentor",
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd scripts && python3 -m pytest test_data_loader.py -k WAWRolesBlankCellCarryForward -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run the full data_loader test suite to check for regressions**

Run: `cd scripts && python3 -m pytest test_data_loader.py -v`
Expected: PASS (all tests, including the pre-existing `TestCategoryResolution`/WAW-adjacent tests - the carry-forward logic is additive and every existing WAW.csv block already repeats its role on every row, matching `test_existing_repeat_every_row_style_still_works` above)

- [ ] **Step 7: Run the full project test suite**

Run: `cd scripts && python3 -m pytest -q`
Expected: PASS. If `test_calculation_baseline.py` or `test_format_baseline.py` fail, that means this change altered a real calculated number (someone's Research Group Leader / Research Mentor admin hours are now counted where they weren't before, since the live `data/WAW.csv` may already have these blank-role-per-row blocks in it) - re-export both baselines:
```bash
python3 main.py --export-baseline
python3 generate_baseline.py
python3 -m pytest -q
```
This is expected and correct if it happens - it means the fix is working end-to-end against the real file, not just the synthetic tests above.

- [ ] **Step 8: Commit**

```bash
git add scripts/data_loader.py scripts/test_data_loader.py
git commit -m "Fix _load_waw_roles() to handle blank-cell role carry-forward

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjPpmKMbkCVkksxSiupx2X"
```

(If Step 7 required a baseline re-export, `git add baseline/ output/` those too before committing, or commit them as a separate immediately-following commit - either is fine, just don't leave the working tree with stale baselines uncommitted.)

---

### Task 3: `scripts/sheet_sync.py` - fetch layer

**Files:**
- Create: `scripts/sheet_sync.py`
- Test: `scripts/test_sheet_sync.py`

**Interfaces:**
- Produces: `export_url(sheet_url: str, gid: Optional[str] = None) -> str`; `fetch_sheet_csv(sheet_url: str, gid: Optional[str] = None, timeout: float = 15.0) -> str`; `class FetchError(Exception)`. Also module constants `SCRIPT_DIR`, `DATA_DIR`, `SOURCES_FILE` (used by every later task in this file).

- [ ] **Step 1: Write the failing tests**

```python
# scripts/test_sheet_sync.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -v`
Expected: FAIL - `ModuleNotFoundError: No module named 'sheet_sync'`

- [ ] **Step 3: Create `scripts/sheet_sync.py` with the fetch layer**

```python
"""
Google Sheets sync-check for the Workload Model.

Standalone, on-demand tool (run as `python sync_sheets.py`, which is a thin
wrapper calling main() here) that fetches every source listed in
data/google_sheets_sources.json, compares each against its local data/ file,
and asks before writing any change. Never runs as part of main.py's
calculation - that stays fully offline and reproducible.

No OAuth: every source is a Google Sheet shared "anyone with the link can
view", read via its CSV export URL - a plain unauthenticated HTTP GET.

See docs/superpowers/specs/2026-09-11-google-sheets-sync-design.md for the
full design.
"""

import csv
import io
import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
SOURCES_FILE = DATA_DIR / "google_sheets_sources.json"

_SHEET_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")


class FetchError(Exception):
    """Raised when a sheet's CSV export couldn't be fetched or wasn't CSV."""


def export_url(sheet_url: str, gid: Optional[str] = None) -> str:
    """Build a CSV export URL from a Google Sheets URL (with any /edit...
    suffix ignored - only the /d/<id> segment matters) and an optional tab gid.
    """
    m = _SHEET_ID_RE.search(sheet_url)
    if not m:
        raise ValueError(f"Could not find a spreadsheet ID in URL: {sheet_url}")
    sheet_id = m.group(1)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        url += f"&gid={gid}"
    return url


def fetch_sheet_csv(sheet_url: str, gid: Optional[str] = None, timeout: float = 15.0) -> str:
    """Fetch a Google Sheet's CSV export. Raises FetchError on any failure:
    an HTTP error, a network error, or a non-CSV (HTML) response - the last
    of which is the signature of a sharing-permission problem, since Google
    serves an HTML sign-in page instead of the export for a private sheet.
    """
    url = export_url(sheet_url, gid)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"could not reach {url}: {e.reason}") from e

    text = raw.decode("utf-8-sig", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("<!DOCTYPE") or stripped.startswith("<html"):
        raise FetchError(
            f"got an HTML page instead of CSV from {url} - "
            f"sheet is probably not shared as 'anyone with the link can view'"
        )
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/sheet_sync.py scripts/test_sheet_sync.py
git commit -m "Add sheet_sync.py fetch layer for Google Sheets sync-check

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjPpmKMbkCVkksxSiupx2X"
```

---

### Task 4: Exact-match comparison strategy

**Files:**
- Modify: `scripts/sheet_sync.py`
- Test: `scripts/test_sheet_sync.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `parse_csv_rows(text: str) -> List[List[str]]`; `class DiffResult` with `.added`, `.removed`, `.changed` (each a list of tuples: `(key, live_row)` for added, `(key, local_row)` for removed, `(key, local_row, live_row)` for changed), `.has_differences -> bool` property, `.summary_lines(limit: int = 20) -> List[str]` method; `compare_exact(live_text: str, local_text: str) -> DiffResult`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_sheet_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k "ParseCsvRows or DiffResult or CompareExact" -v`
Expected: FAIL - `AttributeError: module 'sheet_sync' has no attribute 'parse_csv_rows'` (etc.)

- [ ] **Step 3: Add to `scripts/sheet_sync.py`**

```python
def parse_csv_rows(text: str) -> List[List[str]]:
    """Parse CSV text into a list of rows (each a list of field strings)."""
    return list(csv.reader(io.StringIO(text)))


class DiffResult:
    """The result of comparing a live (fetched) source against a local file.

    added/removed/changed entries use `key` to identify a row - a row index
    (int) for compare_exact, or a (Project ID, Staff) tuple for
    compare_fte_tolerant - whatever the comparison strategy used to match
    rows between the two sides.
    """

    def __init__(self, added: List[Tuple[Any, Any]], removed: List[Tuple[Any, Any]],
                 changed: List[Tuple[Any, Any, Any]]):
        self.added = added      # (key, live_row)
        self.removed = removed  # (key, local_row)
        self.changed = changed  # (key, local_row, live_row)

    @property
    def has_differences(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def summary_lines(self, limit: int = 20) -> List[str]:
        lines = []
        for key, live_row in self.added:
            lines.append(f"  + {key}: {live_row}")
        for key, local_row in self.removed:
            lines.append(f"  - {key}: {local_row}")
        for key, local_row, live_row in self.changed:
            lines.append(f"  ~ {key}: {local_row} -> {live_row}")
        if len(lines) > limit:
            remaining = len(lines) - limit
            lines = lines[:limit] + [f"  ... and {remaining} more"]
        return lines


def compare_exact(live_text: str, local_text: str) -> DiffResult:
    """Row-for-row exact comparison, keyed by row index. A row present past
    the end of the shorter side is added/removed; a differing row at the
    same index is changed.
    """
    live_rows = parse_csv_rows(live_text)
    local_rows = parse_csv_rows(local_text)
    added: List[Tuple[Any, Any]] = []
    removed: List[Tuple[Any, Any]] = []
    changed: List[Tuple[Any, Any, Any]] = []
    max_len = max(len(live_rows), len(local_rows))
    for i in range(max_len):
        live_row = live_rows[i] if i < len(live_rows) else None
        local_row = local_rows[i] if i < len(local_rows) else None
        if local_row is None:
            added.append((i, live_row))
        elif live_row is None:
            removed.append((i, local_row))
        elif live_row != local_row:
            changed.append((i, local_row, live_row))
    return DiffResult(added=added, removed=removed, changed=changed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k "ParseCsvRows or DiffResult or CompareExact" -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/sheet_sync.py scripts/test_sheet_sync.py
git commit -m "Add exact-match comparison strategy to sheet_sync.py

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjPpmKMbkCVkksxSiupx2X"
```

---

### Task 5: FTE-tolerant comparison strategy

**Files:**
- Modify: `scripts/sheet_sync.py`
- Test: `scripts/test_sheet_sync.py`

**Interfaces:**
- Consumes: `DiffResult` from Task 4.
- Produces: `compare_fte_tolerant(live_text: str, local_text: str, tolerance: float = 1.0) -> DiffResult`; module constant `FTE_TOLERANCE = 1.0`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_sheet_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k CompareFteTolerant -v`
Expected: FAIL - `AttributeError: module 'sheet_sync' has no attribute 'compare_fte_tolerant'`

- [ ] **Step 3: Add to `scripts/sheet_sync.py`**

```python
FTE_TOLERANCE = 1.0  # percentage points - matches observed rounding noise


def _fte_row_key(row: Dict[str, str]) -> Tuple[str, str]:
    return (row.get("Project ID", ""), row.get("Staff", ""))


def _fte_rows_differ(live_row: Dict[str, str], local_row: Dict[str, str], tolerance: float) -> bool:
    for col in live_row:
        if col == "% FTE":
            continue
        if live_row.get(col, "") != local_row.get(col, ""):
            return True
    try:
        live_fte = float(live_row.get("% FTE", "0") or "0")
        local_fte = float(local_row.get("% FTE", "0") or "0")
    except ValueError:
        return live_row.get("% FTE") != local_row.get("% FTE")
    return abs(live_fte - local_fte) > tolerance


def compare_fte_tolerant(live_text: str, local_text: str, tolerance: float = FTE_TOLERANCE) -> DiffResult:
    """Row-matched by (Project ID, Staff) rather than position, with the
    '% FTE' column compared within `tolerance` percentage points (rounding
    noise). Any other column differing, or a row present on only one side,
    is still reported as a real difference.
    """
    live_rows = list(csv.DictReader(io.StringIO(live_text)))
    local_rows = list(csv.DictReader(io.StringIO(local_text)))

    live_by_key = {_fte_row_key(r): r for r in live_rows}
    local_by_key = {_fte_row_key(r): r for r in local_rows}

    added: List[Tuple[Any, Any]] = []
    removed: List[Tuple[Any, Any]] = []
    changed: List[Tuple[Any, Any, Any]] = []

    for key, live_row in live_by_key.items():
        if key not in local_by_key:
            added.append((key, live_row))
            continue
        local_row = local_by_key[key]
        if _fte_rows_differ(live_row, local_row, tolerance):
            changed.append((key, local_row, live_row))

    for key, local_row in local_by_key.items():
        if key not in live_by_key:
            removed.append((key, local_row))

    return DiffResult(added=added, removed=removed, changed=changed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k CompareFteTolerant -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/sheet_sync.py scripts/test_sheet_sync.py
git commit -m "Add FTE-tolerant comparison strategy to sheet_sync.py

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjPpmKMbkCVkksxSiupx2X"
```

---

### Task 6: WAW.csv supplementary-file merge

**Files:**
- Modify: `scripts/sheet_sync.py`
- Test: `scripts/test_sheet_sync.py`

**Interfaces:**
- Consumes: `parse_csv_rows()` from Task 4.
- Produces: `merge_supplementary(live_text: str, supplementary_text: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_sheet_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k MergeSupplementary -v`
Expected: FAIL - `AttributeError: module 'sheet_sync' has no attribute 'merge_supplementary'`

- [ ] **Step 3: Add to `scripts/sheet_sync.py`**

```python
def merge_supplementary(live_text: str, supplementary_text: str) -> str:
    """Concatenate the live sheet's CSV rows with a supplementary CSV file's
    rows (used for WAW.csv - content that has only ever lived in the local
    file, e.g. the Union role, never the sheet). Result is re-serialized so
    line endings are consistent regardless of either input's source.
    """
    live_rows = parse_csv_rows(live_text)
    supplementary_rows = parse_csv_rows(supplementary_text) if supplementary_text else []
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in live_rows + supplementary_rows:
        writer.writerow(row)
    return out.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k MergeSupplementary -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/sheet_sync.py scripts/test_sheet_sync.py
git commit -m "Add WAW.csv supplementary-file merge to sheet_sync.py

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjPpmKMbkCVkksxSiupx2X"
```

---

### Task 7: Per-source sync orchestration

**Files:**
- Modify: `scripts/sheet_sync.py`
- Test: `scripts/test_sheet_sync.py`

**Interfaces:**
- Consumes: `fetch_sheet_csv`, `FetchError` (Task 3); `compare_exact`, `DiffResult` (Task 4); `compare_fte_tolerant` (Task 5); `merge_supplementary` (Task 6).
- Produces: `read_local_file(local_path: Path) -> Optional[str]`; `write_local_file(local_path: Path, content: str) -> None`; `resolve_compare_fn(config: dict) -> Callable[[str, str], DiffResult]`; `sync_source(name: str, config: dict, data_dir: Path = DATA_DIR, prompt: Callable[[str], str] = input, out: Callable[[str], None] = print) -> None`; `sync_multi_tab_source(name: str, config: dict, data_dir: Path = DATA_DIR, prompt=input, out=print) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_sheet_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k "ReadWriteLocalFile or ResolveCompareFn or SyncSource or SyncMultiTabSource" -v`
Expected: FAIL - `AttributeError` for each undefined function

- [ ] **Step 3: Add to `scripts/sheet_sync.py`**

```python
def read_local_file(local_path: Path) -> Optional[str]:
    """Read a local data file's text, or None if it doesn't exist yet."""
    if not local_path.exists():
        return None
    with open(local_path, "r", encoding="utf-8-sig") as f:
        return f.read()


def write_local_file(local_path: Path, content: str) -> None:
    with open(local_path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


_COMPARE_STRATEGIES: Dict[str, Callable[[str, str], DiffResult]] = {
    "fte_tolerant": compare_fte_tolerant,
}


def resolve_compare_fn(config: dict) -> Callable[[str, str], DiffResult]:
    name = config.get("compare")
    if name:
        return _COMPARE_STRATEGIES[name]
    return compare_exact


def sync_source(name: str, config: dict, data_dir: Path = DATA_DIR,
                 prompt: Callable[[str], str] = input,
                 out: Callable[[str], None] = print) -> None:
    """Fetch, compare, and (if confirmed) write one CSV-backed source."""
    if config.get("accessible", True) is False:
        out(f"{name}: not accessible (sharing) - flip to 'anyone with link can "
            f"view' to enable, or update the CSV by hand as before")
        return

    try:
        live_text = fetch_sheet_csv(config["url"], gid=config.get("gid"))
    except FetchError as e:
        out(f"{name}: could not fetch: {e}")
        return

    local_path = data_dir / name
    local_text = read_local_file(local_path)
    if local_text is None:
        out(f"{name}: no local file yet - creating from sheet")
        write_local_file(local_path, live_text)
        return

    compare_fn = resolve_compare_fn(config)
    diff = compare_fn(live_text, local_text)
    if not diff.has_differences:
        out(f"{name}: up to date")
        return

    total = len(diff.added) + len(diff.removed) + len(diff.changed)
    out(f"{name}: {total} difference(s)")
    for line in diff.summary_lines():
        out(line)

    answer = prompt(f"Propagate these changes to data/{name}? [y/N] ").strip().lower()
    if answer != "y":
        return

    supplementary_name = config.get("supplementary_file")
    if supplementary_name:
        supplementary_text = read_local_file(data_dir / supplementary_name) or ""
        final_text = merge_supplementary(live_text, supplementary_text)
    else:
        final_text = live_text
    write_local_file(local_path, final_text)
    out(f"  written to data/{name}")


def sync_multi_tab_source(name: str, config: dict, data_dir: Path = DATA_DIR,
                           prompt: Callable[[str], str] = input,
                           out: Callable[[str], None] = print) -> None:
    """Multi-tab workbook sources (CS WTW Who Teaches What.xlsx, ProjectLoads
    2025-26.xlsx). Full local-.xlsx comparison/write-back is out of scope for
    this pass (see the plan's Global Constraints) - a configured tab is
    fetched and reported for manual review, not automatically diffed or
    written.
    """
    tabs = config.get("tabs", {})
    configured = {tab: gid for tab, gid in tabs.items() if gid}
    if not configured:
        out(f"{name}: skipped - tabs not configured (edit google_sheets_sources.json)")
        return
    for tab, gid in configured.items():
        try:
            live_text = fetch_sheet_csv(config["url"], gid=gid)
        except FetchError as e:
            out(f"{name} [{tab}]: could not fetch: {e}")
            continue
        row_count = len(parse_csv_rows(live_text))
        out(f"{name} [{tab}]: fetched ({row_count} rows) - this tool doesn't "
            f"yet compare/write .xlsx content automatically; review by hand")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k "ReadWriteLocalFile or ResolveCompareFn or SyncSource or SyncMultiTabSource" -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/sheet_sync.py scripts/test_sheet_sync.py
git commit -m "Add per-source sync orchestration to sheet_sync.py

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjPpmKMbkCVkksxSiupx2X"
```

---

### Task 8: Source config loading, coverage check, and `main()`

**Files:**
- Modify: `scripts/sheet_sync.py`
- Create: `scripts/sync_sheets.py` (thin CLI entry point at the scripts root, alongside `main.py`)
- Test: `scripts/test_sheet_sync.py`

**Interfaces:**
- Consumes: `sync_source`, `sync_multi_tab_source` (Task 7); `SOURCES_FILE`, `DATA_DIR` (Task 3).
- Produces: `load_sources(path: Path = SOURCES_FILE) -> Dict[str, dict]`; `save_sources(sources: Dict[str, dict], path: Path = SOURCES_FILE) -> None`; `find_unmapped_files(sources: Dict[str, dict], data_dir: Path = DATA_DIR) -> List[str]`; `check_coverage(sources: Dict[str, dict], data_dir: Path = DATA_DIR, prompt=input, out=print, sources_path: Path = SOURCES_FILE) -> None`; `main() -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_sheet_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k "LoadSaveSources or FindUnmappedFiles or CheckCoverage" -v`
Expected: FAIL - `AttributeError` for each undefined function

- [ ] **Step 3: Add to `scripts/sheet_sync.py`**

```python
_DATA_FILE_EXTENSIONS = {".csv", ".xlsx"}


def load_sources(path: Path = SOURCES_FILE) -> Dict[str, dict]:
    """Load the sheet-to-local-file mapping JSON. Returns {} if missing."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_sources(sources: Dict[str, dict], path: Path = SOURCES_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sources, f, indent=2, sort_keys=True)
        f.write("\n")


def find_unmapped_files(sources: Dict[str, dict], data_dir: Path = DATA_DIR) -> List[str]:
    """Local data/ files (.csv or .xlsx) with no entry in `sources`."""
    mapped = set(sources.keys())
    return sorted(
        p.name for p in data_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _DATA_FILE_EXTENSIONS and p.name not in mapped
    )


def check_coverage(sources: Dict[str, dict], data_dir: Path = DATA_DIR,
                    prompt: Callable[[str], str] = input,
                    out: Callable[[str], None] = print,
                    sources_path: Path = SOURCES_FILE) -> None:
    """Ask about any local data file with no registered sheet. A pasted URL
    is added to `sources` (mutated in place) and the file is saved
    immediately, so the very next run picks it up.
    """
    unmapped = find_unmapped_files(sources, data_dir=data_dir)
    if not unmapped:
        return
    changed = False
    for name in unmapped:
        answer = prompt(
            f"No Google Sheet registered for data/{name} - "
            f"paste a share link now, or press Enter to skip: "
        ).strip()
        if answer:
            sources[name] = {"url": answer}
            out(f"  added data/{name} -> {answer}")
            changed = True
    if changed:
        save_sources(sources, path=sources_path)


def main() -> None:
    sources = load_sources()
    if not sources:
        print(f"No sources configured yet - create {SOURCES_FILE} to get started.")
        return
    for name, config in sources.items():
        if "tabs" in config:
            sync_multi_tab_source(name, config)
        else:
            sync_source(name, config)
        print()
    check_coverage(sources)
```

- [ ] **Step 4: Create `scripts/sync_sheets.py`**

```python
#!/usr/bin/env python3
"""
Entry point for the Google Sheets sync-check.

Usage: python sync_sheets.py

Fetches every source in data/google_sheets_sources.json, compares each
against its local data/ file, and asks before writing any change. Never run
automatically by main.py - this is a separate, on-demand step. See
docs/superpowers/specs/2026-09-11-google-sheets-sync-design.md for the
design.
"""

from sheet_sync import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py -k "LoadSaveSources or FindUnmappedFiles or CheckCoverage" -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Run the full new test file, then the full project suite**

Run: `cd scripts && python3 -m pytest test_sheet_sync.py test_sheet_sync_config.py -v`
Expected: PASS (all tests from Tasks 1, 3-8)

Run: `cd scripts && python3 -m pytest -q`
Expected: PASS (no regressions - this task only adds new files/functions, doesn't modify calculation code)

- [ ] **Step 7: Commit**

```bash
git add scripts/sheet_sync.py scripts/sync_sheets.py scripts/test_sheet_sync.py
git commit -m "Add source config loading, coverage check, and CLI entry point

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KjPpmKMbkCVkksxSiupx2X"
```

---

### Task 9: End-to-end manual smoke test against the real sources

**Files:**
- None created or modified - this task validates Tasks 1-8 against the real network and real data files.

**Interfaces:**
- Consumes: everything from Tasks 1-8.
- Produces: nothing new; this is a validation task.

- [ ] **Step 1: Run the tool against the real sources**

Run: `cd scripts && python3 sync_sheets.py`

Expected output shape (exact numbers will vary since data may have changed since this plan was written):
- `WAW.csv: N difference(s)` or `up to date`, followed by a prompt - **answer `n`** for this smoke test run (don't actually propagate anything unreviewed).
- `CS WTW Who Teaches What.xlsx: skipped - tabs not configured (edit google_sheets_sources.json)`
- `% FTE for CS.csv: up to date` (Task in this plan doesn't change `data/% FTE for CS.csv`, and it was already synced to the live sheet earlier this session)
- `CS Module Numbers.csv: up to date`
- `PhD Supervision Data.csv: up to date`
- `CS Module Assessment Numbers.csv: not accessible (sharing) - flip to 'anyone with link can view' to enable, or update the CSV by hand as before`
- `workload_adjustments.csv: up to date` or a small difference from normal auto-sync churn - answer `n`
- `ProjectLoads 2025-26.xlsx: fetched (N rows) - this tool doesn't yet compare/write .xlsx content automatically; review by hand` (the "Advisor Loads" tab, since its gid is already configured in Task 1's `google_sheets_sources.json`)
- `CS Research Groups.csv: up to date`
- Then the coverage check: `No Google Sheet registered for data/pastoral_load.csv - ...` and similarly for `Staff Categories and FTE.csv` - **press Enter (skip)** for both during this smoke test, since neither has a known sheet to register yet.

- [ ] **Step 2: Verify no local file was modified**

Run: `git status --short data/`
Expected: no changes to any `data/` file (everything above was answered `n`/Enter, and `up to date` sources never write anything) - except possibly `data/google_sheets_sources.json` if Step 1 accidentally recorded something during the coverage check; if so, `git diff data/google_sheets_sources.json` to confirm it's empty/expected, `git checkout -- data/google_sheets_sources.json` if not.

- [ ] **Step 3: Re-run once more answering `y` to the WAW.csv prompt specifically (if it showed a difference)**

This validates the full read-fetch-diff-confirm-write path against real data, not just synthetic tests. If the WAW.csv diff includes the Research Group Leader / Research Mentor blocks now parsing correctly (Task 2's fix), or the Union role being present via the supplementary file, inspect `git diff data/WAW.csv` to confirm it looks right before deciding whether to keep the change or `git checkout -- data/WAW.csv` to revert it back to what it was for a later, deliberate decision.

- [ ] **Step 4: If `data/WAW.csv` changed and was kept, re-run the calculation pipeline**

```bash
cd scripts
python3 main.py --export-baseline
python3 generate_baseline.py
python3 -m pytest -q
python3 main.py
```

Expected: all tests pass; `output/` reflects whatever WAW.csv role changes were propagated.

- [ ] **Step 5: Report back**

Summarize for the user: which sources were up to date, which had real differences (and whether they were propagated), whether `CS WTW Who Teaches What.xlsx`'s tabs still need their gids filled in, and remind them `CS Module Assessment Numbers.csv` still needs its sharing fixed (or continues to be updated by hand) since it's permanently `accessible: false` until then.

---

## Self-Review Notes

- **Spec coverage:** every section of the spec maps to a task - source mapping (Task 1), WAW carry-forward + mapping (Task 2), fetch layer (Task 3), exact comparison (Task 4), fte_tolerant comparison (Task 5), WAW supplementary merge (Task 6), per-source orchestration incl. the "propagate" prompt and multi-tab skip behavior (Task 7), source loading + coverage check + CLI entry point (Task 8), and the real-network validation the spec's CLI-shape example implies (Task 9).
- **Placeholder scan:** no TBD/TODO/"add error handling" left in any step; every code block is complete and directly runnable. The one intentionally-deferred piece (xlsx tab comparison/write-back) is called out explicitly as out of scope in Global Constraints and Task 7's docstring, not left as a vague "handle xlsx" step.
- **Type/signature consistency:** `DiffResult` (Task 4) is used identically by `compare_exact` (Task 4) and `compare_fte_tolerant` (Task 5) - both populate `.added`/`.removed`/`.changed` with the same `(key, ...)` tuple shapes. `sync_source`'s `prompt`/`out` callables (Task 7) match the signatures `check_coverage` (Task 8) uses. `fetch_sheet_csv(sheet_url, gid=None, timeout=15.0)` (Task 3) is called consistently the same way in Tasks 7 and 8's `sync_multi_tab_source`/`sync_source`.
