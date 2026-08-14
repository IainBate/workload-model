"""
Structured JSON baseline for *calculation correctness* (plan item B1).

Why this exists
---------------
`check_against_baseline.py` compares rendered HTML/CSV/XLSX byte-for-byte. That
conflates two very different questions:

  1. "Did the numbers change?"      (a calculation regression - serious)
  2. "Did the wording/layout change?" (a display change - often intentional)

A one-line cosmetic edit currently invalidates 56 baseline HTML files, which
buries any real calculation change in the noise. This module snapshots only the
*numbers* from `WorkloadResult` into a single JSON file, so calculation
regressions can be detected independently of how anything is rendered.

Usage
-----
    python main.py --export-baseline        # write baseline/expected_results.json
    pytest test_calculation_baseline.py     # assert current calc matches it

Only re-export when a calculation change is intended and reviewed.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

SCRIPTS_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPTS_DIR.parent
DEFAULT_BASELINE_PATH = PROJECT_ROOT / "baseline" / "expected_results.json"

# Rounded before comparison so trivial floating-point drift (e.g. 1.0000000001)
# doesn't read as a calculation regression. 4dp is far finer than anything the
# reports display (1dp), so a real change is never masked.
ROUNDING_DP = 4


def _round_numbers(value: Any) -> Any:
    """Recursively round floats in nested dicts/lists for stable comparison."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, ROUNDING_DP)
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        return {k: _round_numbers(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_round_numbers(v) for v in value]
    return value


def result_to_dict(r) -> Dict[str, Any]:
    """Extract the calculation-relevant fields of a WorkloadResult.

    Deliberately excludes the human-readable *_detail strings and
    module_details/supervision_details: those are display concerns, and
    including them here would re-couple calculation testing to wording (the
    exact problem this file exists to solve).
    """
    return _round_numbers({
        "name": r.name,
        "fte": r.fte,
        "category": r.category,
        "nominal_hours": r.nominal_hours,
        "total_hours": r.total_hours,
        "teaching_hours": r.teaching_hours,
        "research_hours": r.research_hours,
        "admin_hours": r.admin_hours,
        "teaching_breakdown": dict(r.teaching_breakdown or {}),
        "teaching_module_breakdowns": dict(r.teaching_module_breakdowns or {}),
        "research_breakdown": dict(r.research_breakdown or {}),
        "admin_breakdown": dict(r.admin_breakdown or {}),
        "pastoral_breakdown": dict(r.pastoral_breakdown or {}),
        "project_breakdown": dict(r.project_breakdown or {}),
        "adjustments_breakdown": dict(r.adjustments_breakdown or {}),
        "assumptions": list(r.assumptions or ()),
        "missing_data": list(r.missing_data or ()),
    })


def results_to_baseline(results: List[Any], year_label: str = "") -> Dict[str, Any]:
    """Build the full baseline payload, keyed by staff name for stable diffs."""
    return {
        "year_label": year_label,
        "staff_count": len(results),
        "staff": {r.name: result_to_dict(r) for r in sorted(results, key=lambda x: x.name)},
    }


def export_baseline(results: List[Any], year_label: str = "", path: Path = None) -> Path:
    """Write the calculation baseline JSON. Returns the path written."""
    if path is None:
        path = DEFAULT_BASELINE_PATH
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = results_to_baseline(results, year_label)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    return path


def load_baseline(path: Path = None) -> Dict[str, Any]:
    """Load the calculation baseline JSON, or {} if it doesn't exist yet."""
    if path is None:
        path = DEFAULT_BASELINE_PATH
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_to_baseline(results: List[Any], baseline: Dict[str, Any]) -> List[str]:
    """Compare freshly-calculated results against a loaded baseline.

    Returns a list of human-readable difference descriptions (empty == match).
    Reports missing/extra staff and per-field value changes, so a failure says
    exactly which number moved rather than "files differ".
    """
    differences = []
    baseline_staff = baseline.get("staff", {})
    current_staff = {r.name: result_to_dict(r) for r in results}

    for name in sorted(set(baseline_staff) - set(current_staff)):
        differences.append(f"{name}: present in baseline but missing from current results")
    for name in sorted(set(current_staff) - set(baseline_staff)):
        differences.append(f"{name}: present in current results but missing from baseline")

    for name in sorted(set(baseline_staff) & set(current_staff)):
        expected = baseline_staff[name]
        actual = current_staff[name]
        for key in sorted(set(expected) | set(actual)):
            exp_val = expected.get(key)
            act_val = actual.get(key)
            if exp_val != act_val:
                differences.append(
                    f"{name}.{key}: expected {exp_val!r}, got {act_val!r}"
                )
    return differences
