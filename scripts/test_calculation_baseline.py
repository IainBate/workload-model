"""
Calculation-correctness regression tests against the structured JSON baseline
(plan item B1).

These deliberately assert on *numbers only*, never on rendered HTML/CSS/wording.
A cosmetic change to a report must not fail these; a changed hour value must.
The complementary display-format checks live in test_format_baseline.py (B2).

If a failure here is an intended calculation change, review the reported diff
and re-export with:

    python main.py --export-baseline
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from calculation_baseline import (  # noqa: E402
    compare_to_baseline,
    load_baseline,
    result_to_dict,
)
from data_loader import load_all_data  # noqa: E402
from workload_calculator import calculate_workload  # noqa: E402

DATA_DIR = SCRIPTS_DIR.parent / "data"


@pytest.fixture(scope="module")
def results():
    """Full pipeline run, non-interactive so it can never block on input."""
    year_data = load_all_data(
        data_dir=str(DATA_DIR), unknown_callback=None, category_callback=None
    )
    return calculate_workload(year_data, validate_input=False)


@pytest.fixture(scope="module")
def baseline():
    data = load_baseline()
    if not data:
        pytest.skip(
            "No calculation baseline found - run 'python main.py --export-baseline' first"
        )
    return data


def test_baseline_matches_current_calculation(results, baseline):
    """Every staff member's numbers match the recorded baseline exactly."""
    differences = compare_to_baseline(results, baseline)
    assert not differences, (
        f"{len(differences)} calculation difference(s) vs baseline:\n  "
        + "\n  ".join(differences[:25])
        + ("\n  ..." if len(differences) > 25 else "")
    )


def test_baseline_covers_every_staff_member(results, baseline):
    """Guards against a baseline exported from a partial/filtered run."""
    assert baseline.get("staff_count") == len(results)
    assert set(baseline.get("staff", {})) == {r.name for r in results}


def test_category_totals_sum_to_total_hours(results):
    """Invariant: total = teaching + research + admin, for everyone.

    Independent of the baseline - catches a bad calculation even if the
    baseline was re-exported with that bug already baked in.
    """
    for r in results:
        expected = r.teaching_hours + r.research_hours + r.admin_hours
        assert r.total_hours == pytest.approx(expected, abs=0.05), (
            f"{r.name}: total {r.total_hours} != "
            f"{r.teaching_hours} + {r.research_hours} + {r.admin_hours}"
        )


def test_no_negative_hours(results):
    """Invariant: no category ever goes negative."""
    for r in results:
        for field in ("total_hours", "teaching_hours", "research_hours", "admin_hours"):
            assert getattr(r, field) >= 0, f"{r.name}.{field} is negative"


def test_teaching_breakdown_sums_to_teaching_hours(results):
    """Invariant: the teaching breakdown accounts for all teaching hours.

    This is the check that would have caught the historical
    'per-module teaching never aggregated into the staff-level breakdown' bug.
    """
    for r in results:
        if not r.teaching_breakdown:
            continue
        breakdown_sum = sum(
            v for v in r.teaching_breakdown.values() if isinstance(v, (int, float))
        )
        assert breakdown_sum == pytest.approx(r.teaching_hours, abs=0.05), (
            f"{r.name}: teaching_breakdown sums to {breakdown_sum} "
            f"but teaching_hours is {r.teaching_hours}"
        )


def test_research_breakdown_sums_to_research_hours(results):
    """Invariant: research breakdown (incl. nested grants/PhD) accounts for the total.

    This is the check that would have caught the historical
    'PhD supervision double-counted in research_breakdown' bug.
    """
    def _sum_nested(value):
        if isinstance(value, dict):
            return sum(_sum_nested(v) for v in value.values())
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

    for r in results:
        if not r.research_breakdown:
            continue
        breakdown_sum = _sum_nested(r.research_breakdown)
        assert breakdown_sum == pytest.approx(r.research_hours, abs=0.05), (
            f"{r.name}: research_breakdown sums to {breakdown_sum} "
            f"but research_hours is {r.research_hours}"
        )


def test_result_serialization_excludes_display_strings(results):
    """The baseline must not capture wording, or cosmetic edits would fail it."""
    serialized = result_to_dict(results[0])
    for display_field in (
        "teaching_detail", "research_detail", "admin_detail",
        "module_details", "supervision_details",
    ):
        assert display_field not in serialized
