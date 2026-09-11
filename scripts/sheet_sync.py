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
