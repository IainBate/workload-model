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
