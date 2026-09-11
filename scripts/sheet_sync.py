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
