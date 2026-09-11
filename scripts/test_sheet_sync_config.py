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
