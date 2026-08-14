"""
Tests for the shared reporting helpers (plan items D7 and E2).

These cover the department summary statistics and the "needs attention" triage
filter independently of HTML generation, plus the normative-comparison logic
that both report surfaces now share.

Fixtures are hand-built stand-ins rather than real WorkloadResults, so the
expected values are obvious by inspection and don't move with the data.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import config  # noqa: E402
import reporting_helpers as rh  # noqa: E402

NOMINAL = config.NOMINAL_WORKING_HOURS_PER_YEAR


@dataclass
class FakeResult:
    """Minimal stand-in exposing only what the helpers read."""
    name: str
    category: str = "ART"
    fte: float = 1.0
    teaching_hours: float = 0.0
    research_hours: float = 0.0
    admin_hours: float = 0.0
    nominal_hours: float = NOMINAL
    assumptions: Tuple[str, ...] = field(default_factory=tuple)
    missing_data: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_hours(self):
        return self.teaching_hours + self.research_hours + self.admin_hours


def on_target_art(name="OnTarget"):
    """An ART member exactly on the 40/40/20 split, at nominal hours."""
    split = config.get_normative_split("ART")
    return FakeResult(
        name=name,
        category="ART",
        teaching_hours=NOMINAL * split["teaching_hours"],
        research_hours=NOMINAL * split["research_hours"],
        admin_hours=NOMINAL * split["admin_hours"],
    )


class TestDeviationBand:
    """The shared severity classification."""

    @pytest.mark.parametrize("pp", [0, 3, 5, -5, -3])
    def test_within_five_points_is_ok(self, pp):
        assert rh.deviation_band(pp) == "ok"

    @pytest.mark.parametrize("pp", [6, 10, -6, -10])
    def test_up_to_ten_points_is_moderate(self, pp):
        assert rh.deviation_band(pp) == "moderate"

    @pytest.mark.parametrize("pp", [11, 40, -11, -40])
    def test_beyond_ten_points_is_high(self, pp):
        assert rh.deviation_band(pp) == "high"

    def test_band_is_symmetric(self):
        """Over- and under-shooting by the same amount rank equally severe."""
        for pp in (3, 8, 25):
            assert rh.deviation_band(pp) == rh.deviation_band(-pp)


class TestCategoryDeviations:
    """Actual vs contract-target split."""

    def test_on_target_staff_have_no_deviation(self):
        deviations = rh.category_deviations(on_target_art())
        for category, d in deviations.items():
            assert d["deviation_pct"] == pytest.approx(0, abs=0.01), category

    def test_deviation_is_actual_minus_target(self):
        r = FakeResult("Skewed", category="ART", teaching_hours=800,
                       research_hours=100, admin_hours=100)
        deviations = rh.category_deviations(r)
        # 800/1000 = 80% actual teaching against a 40% target
        assert deviations["teaching"]["actual_pct"] == pytest.approx(80.0)
        assert deviations["teaching"]["target_pct"] == pytest.approx(40.0)
        assert deviations["teaching"]["deviation_pct"] == pytest.approx(40.0)

    def test_unmapped_category_returns_none_not_a_guess(self):
        """Critical: must degrade to 'no comparison', never invent a target."""
        assert rh.category_deviations(FakeResult("X", category="")) is None
        assert rh.category_deviations(FakeResult("X", category="Nonsense")) is None

    def test_zero_total_hours_returns_none(self):
        assert rh.category_deviations(FakeResult("Empty", category="ART")) is None

    def test_percentages_sum_to_one_hundred(self):
        r = FakeResult("Any", category="ART", teaching_hours=300,
                       research_hours=200, admin_hours=100)
        deviations = rh.category_deviations(r)
        assert sum(d["actual_pct"] for d in deviations.values()) == pytest.approx(100.0)

    def test_ts_and_art_get_different_targets(self):
        """The two contract types must not share a target split."""
        art = rh.category_deviations(FakeResult("A", category="ART", teaching_hours=500,
                                                research_hours=300, admin_hours=200))
        ts = rh.category_deviations(FakeResult("B", category="T and S", teaching_hours=500,
                                               research_hours=300, admin_hours=200))
        assert art["teaching"]["target_pct"] != ts["teaching"]["target_pct"]


class TestNominalVariance:
    def test_over_nominal_is_positive(self):
        r = FakeResult("Over", teaching_hours=NOMINAL * 1.25)
        assert rh.nominal_variance(r) == pytest.approx(0.25, abs=0.001)
        assert rh.is_over_or_under_nominal(r)

    def test_under_nominal_is_negative(self):
        r = FakeResult("Under", teaching_hours=NOMINAL * 0.5)
        assert rh.nominal_variance(r) == pytest.approx(-0.5, abs=0.001)
        assert rh.is_over_or_under_nominal(r)

    def test_within_threshold_not_flagged(self):
        r = FakeResult("Fine", teaching_hours=NOMINAL * 1.05)
        assert not rh.is_over_or_under_nominal(r)

    def test_zero_nominal_returns_none(self):
        assert rh.nominal_variance(FakeResult("NoNominal", nominal_hours=0)) is None


class TestNeedsAttention:
    """The department report's triage filter."""

    def test_flags_over_nominal(self):
        flagged = rh.needs_attention([FakeResult("Over", teaching_hours=NOMINAL * 1.5)])
        assert [f["name"] for f in flagged] == ["Over"]

    def test_flags_under_nominal(self):
        flagged = rh.needs_attention([FakeResult("Under", teaching_hours=NOMINAL * 0.4)])
        assert [f["name"] for f in flagged] == ["Under"]

    def test_ignores_staff_within_threshold(self):
        assert rh.needs_attention([FakeResult("Fine", teaching_hours=NOMINAL)]) == []

    def test_flags_data_quality_issues_even_when_on_target(self):
        """Someone at nominal hours still needs looking at if data is missing."""
        r = FakeResult("Flagged", teaching_hours=NOMINAL, missing_data=("No FTE",))
        flagged = rh.needs_attention([r])
        assert len(flagged) == 1
        assert flagged[0]["issues"] == "Missing Data"

    def test_flags_adjustment_conflict_even_when_on_target(self):
        """A workload_adjustments.csv conflict (e.g. an absolute override mixed
        with a delta for the same person+category) is recorded as missing_data
        by _apply_adjustments() and must still surface here even when the
        person's total_hours is otherwise right on nominal - the conflict is a
        data-quality issue independent of whether hours look "fine"."""
        r = FakeResult(
            "Conflicted", teaching_hours=NOMINAL,
            missing_data=("Teaching adjustment conflict: 1 absolute override(s) and "
                          "1 delta(s) in workload_adjustments.csv - no adjustment applied; "
                          "calculated value (500.0h) used.",),
        )
        flagged = rh.needs_attention([r])
        assert len(flagged) == 1
        assert flagged[0]["name"] == "Conflicted"
        assert flagged[0]["issues"] == "Missing Data"
        assert flagged[0]["deviation_pct"] == 0.0

    def test_reports_both_issue_types(self):
        r = FakeResult("Both", teaching_hours=NOMINAL,
                       assumptions=("a",), missing_data=("b",))
        assert rh.needs_attention([r])[0]["issues"] == "Assumptions, Missing Data"

    def test_sorted_by_deviation_magnitude(self):
        staff = [
            FakeResult("Small", teaching_hours=NOMINAL * 1.2),
            FakeResult("Huge", teaching_hours=NOMINAL * 2.0),
            FakeResult("Medium", teaching_hours=NOMINAL * 0.5),
        ]
        assert [f["name"] for f in rh.needs_attention(staff)] == ["Huge", "Medium", "Small"]

    def test_picks_out_only_the_right_people(self):
        """End-to-end filter behaviour over a mixed roster."""
        staff = [
            FakeResult("Fine", teaching_hours=NOMINAL),
            FakeResult("WayOver", teaching_hours=NOMINAL * 1.8),
            FakeResult("HasAssumption", teaching_hours=NOMINAL, assumptions=("x",)),
            FakeResult("AlsoFine", teaching_hours=NOMINAL * 1.02),
        ]
        assert {f["name"] for f in rh.needs_attention(staff)} == {"WayOver", "HasAssumption"}

    def test_deviation_pct_sign_matches_direction(self):
        over = rh.needs_attention([FakeResult("O", teaching_hours=NOMINAL * 1.5)])[0]
        under = rh.needs_attention([FakeResult("U", teaching_hours=NOMINAL * 0.5)])[0]
        assert over["deviation_pct"] > 0
        assert under["deviation_pct"] < 0


class TestDepartmentSummary:
    def test_headline_totals(self):
        staff = [
            FakeResult("A", fte=1.0, teaching_hours=1000),
            FakeResult("B", fte=0.5, teaching_hours=500),
        ]
        summary = rh.department_summary(staff)
        assert summary["headcount"] == 2
        assert summary["total_fte"] == pytest.approx(1.5)
        assert summary["total_hours"] == pytest.approx(1500)
        assert summary["average_hours"] == pytest.approx(750)
        assert summary["nominal_total"] == pytest.approx(1.5 * NOMINAL)

    def test_empty_roster_does_not_divide_by_zero(self):
        summary = rh.department_summary([])
        assert summary["headcount"] == 0
        assert summary["average_hours"] == 0


class TestCategoryStatistics:
    def test_groups_by_contract_category(self):
        staff = [
            FakeResult("A", category="ART", teaching_hours=400),
            FakeResult("B", category="ART", teaching_hours=600),
            FakeResult("C", category="T and S", teaching_hours=800),
        ]
        stats = rh.category_statistics(staff)
        assert stats["ART"]["count"] == 2
        assert stats["T and S"]["count"] == 1
        assert stats["ART"]["averages"]["teaching"] == pytest.approx(500)

    def test_actual_split_percentages_sum_to_one_hundred(self):
        staff = [FakeResult("A", category="ART", teaching_hours=500,
                            research_hours=300, admin_hours=200)]
        split = rh.category_statistics(staff)["ART"]["actual_split_pct"]
        assert sum(split.values()) == pytest.approx(100.0)

    def test_normative_target_attached_when_mapped(self):
        stats = rh.category_statistics([FakeResult("A", category="ART", teaching_hours=100)])
        assert stats["ART"]["normative_split_pct"] is not None
        assert sum(stats["ART"]["normative_split_pct"].values()) == pytest.approx(100.0, abs=0.5)

    def test_unmapped_category_has_no_target(self):
        stats = rh.category_statistics([FakeResult("A", category="", teaching_hours=100)])
        assert stats["Unknown"]["normative_split_pct"] is None


class TestSharedByBothReports:
    """Guards the E2 property: one implementation, not two."""

    def test_individual_report_uses_the_shared_comparison(self):
        import new_individual_reports as nir
        assert nir._compute_category_deviations is rh.category_deviations

    def test_department_report_imports_the_shared_helpers(self):
        import output_generator
        assert output_generator.reporting_helpers is rh

    def test_no_duplicate_threshold_constants_remain(self):
        """The per-report threshold constants must be gone, not just unused."""
        import new_individual_reports as nir
        assert not hasattr(nir, "_DEVIATION_OK")
        assert not hasattr(nir, "_DEVIATION_MODERATE")
