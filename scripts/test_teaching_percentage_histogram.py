"""
Tests for the teaching-%-of-remaining-time department chart (output_generator.py).

_prepare_teaching_percentage_chart_data() is pure data-shaping split out of
generate_teaching_percentage_histogram() specifically so it can be unit
tested without touching matplotlib. The rendering function itself is covered
by test_format_baseline.py's "all expected artifacts produced" smoke test.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import WorkloadResult  # noqa: E402
from output_generator import (  # noqa: E402
    _prepare_teaching_percentage_chart_data,
    _prepare_teaching_percentage_by_grade_chart_data,
    _TEACHING_PCT_CATEGORY_COLORS,
    _TEACHING_PCT_OVERLOADED_COLOR,
    _TEACHING_PCT_Y_AXIS_FLOOR,
    _TEACHING_PCT_GRADE_ORDER,
)


def _result(name, category="ART", pct=50.0, include=True, grade=""):
    return WorkloadResult(
        name=name, fte=1.0, total_hours=1000.0, teaching_hours=100.0,
        research_hours=500.0, admin_hours=200.0, category=category,
        assumptions=(), missing_data=(),
        teaching_pct_of_remaining=pct, include_in_teaching_pct_chart=include,
        grade=grade,
    )


class TestPrepareTeachingPercentageChartData:
    def test_included_staff_coloured_by_category(self):
        results = [_result("Art Person", category="ART", pct=40.0),
                   _result("TS Person", category="T and S", pct=60.0)]

        data = _prepare_teaching_percentage_chart_data(results)

        assert data["names"] == ["Art Person", "TS Person"]
        assert data["plotted_values"] == [40.0, 60.0]
        assert data["colors"] == [_TEACHING_PCT_CATEGORY_COLORS["ART"],
                                   _TEACHING_PCT_CATEGORY_COLORS["T and S"]]
        assert data["overloaded"] == []
        assert data["excluded"] == []
        assert data["undefined"] == []

    def test_excluded_staff_omitted_but_listed(self):
        excluded_person = _result("Excluded Person", include=False)
        results = [_result("Included Person"), excluded_person]

        data = _prepare_teaching_percentage_chart_data(results)

        assert "Excluded Person" not in data["names"]
        assert data["excluded"] == [excluded_person]

    def test_undefined_percentage_omitted_but_listed(self):
        undefined_person = _result("Undefined Person", pct=None)
        results = [_result("Included Person"), undefined_person]

        data = _prepare_teaching_percentage_chart_data(results)

        assert "Undefined Person" not in data["names"]
        assert data["undefined"] == [undefined_person]

    def test_negative_percentage_pinned_to_top_in_third_colour(self):
        """A negative percentage (remaining_hours < 0) isn't a meaningful
        fraction - it's pinned to the y-axis ceiling in the overloaded colour
        rather than plotted at its (misleadingly small-looking) true value."""
        overloaded_person = _result("Overloaded Person", category="ART", pct=-6.9)
        results = [_result("Normal Person", pct=40.0), overloaded_person]

        data = _prepare_teaching_percentage_chart_data(results)

        idx = data["names"].index("Overloaded Person")
        assert data["plotted_values"][idx] == data["y_max"]
        assert data["colors"][idx] == _TEACHING_PCT_OVERLOADED_COLOR
        assert data["overloaded"] == [overloaded_person]
        # The real (negative) value is preserved on the result for the footnote.
        assert data["overloaded"][0].teaching_pct_of_remaining == -6.9

    def test_zero_percent_is_normal_not_overloaded(self):
        zero_person = _result("Zero Person", category="ART", pct=0.0)

        data = _prepare_teaching_percentage_chart_data([zero_person])

        assert data["overloaded"] == []
        assert data["colors"] == [_TEACHING_PCT_CATEGORY_COLORS["ART"]]
        assert data["plotted_values"] == [0.0]

    def test_y_axis_floor_when_all_values_well_under_100(self):
        """Should not waste space with a wide fixed range when the real data
        sits comfortably under 100% - but 100% stays visible as a reference."""
        results = [_result("A", pct=10.0), _result("B", pct=25.0)]

        data = _prepare_teaching_percentage_chart_data(results)

        assert data["y_max"] == _TEACHING_PCT_Y_AXIS_FLOOR

    def test_y_axis_grows_for_a_genuine_high_performer(self):
        results = [_result("High Performer", pct=150.0)]

        data = _prepare_teaching_percentage_chart_data(results)

        assert data["y_max"] == pytest.approx(150.0 * 1.1)

    def test_y_axis_unaffected_by_overloaded_staff(self):
        """The axis scale is driven by the real (non-negative) data only -
        an overloaded person's pinned bar must not inflate or shrink it."""
        results = [_result("Normal", pct=30.0), _result("Overloaded", pct=-500.0)]

        data = _prepare_teaching_percentage_chart_data(results)

        assert data["y_max"] == _TEACHING_PCT_Y_AXIS_FLOOR

    def test_average_computed_over_normal_staff_only(self):
        results = [_result("A", pct=20.0), _result("B", pct=40.0)]

        data = _prepare_teaching_percentage_chart_data(results)

        assert data["average_pct"] == pytest.approx(30.0)

    def test_average_excludes_overloaded_excluded_and_undefined_staff(self):
        results = [
            _result("Normal", pct=20.0),
            _result("Overloaded", pct=-500.0),
            _result("Excluded", pct=90.0, include=False),
            _result("Undefined", pct=None),
        ]

        data = _prepare_teaching_percentage_chart_data(results)

        assert data["average_pct"] == pytest.approx(20.0)

    def test_average_is_none_when_no_normal_staff(self):
        results = [_result("Overloaded", pct=-500.0)]

        data = _prepare_teaching_percentage_chart_data(results)

        assert data["average_pct"] is None


class TestPrepareTeachingPercentageByGradeChartData:
    def test_groups_ordered_by_seniority(self):
        results = [
            _result("A Lecturer", grade="Lecturer", pct=10.0),
            _result("A Prof", grade="Prof", pct=20.0),
            _result("A Reader", grade="Reader", pct=30.0),
            _result("A SL", grade="SL", pct=40.0),
        ]

        data = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert data["names"] == ["A Prof", "A Reader", "A SL", "A Lecturer"]
        assert [g for g, _, _ in data["grade_groups"]] == ["Prof", "Reader", "SL", "Lecturer"]

    def test_ranked_highest_first_within_a_grade(self):
        results = [
            _result("Low", grade="SL", pct=20.0),
            _result("High", grade="SL", pct=80.0),
            _result("Mid", grade="SL", pct=50.0),
        ]

        data = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert data["names"] == ["High", "Mid", "Low"]

    def test_grade_groups_record_start_index_and_count(self):
        results = [
            _result("P1", grade="Prof", pct=10.0),
            _result("P2", grade="Prof", pct=20.0),
            _result("S1", grade="SL", pct=30.0),
        ]

        data = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert data["grade_groups"] == [("Prof", 0, 2), ("SL", 2, 1)]

    def test_missing_grade_omitted_from_bars_but_listed(self):
        no_grade_person = _result("No Grade", grade="", pct=50.0)
        results = [_result("Graded", grade="SL", pct=30.0), no_grade_person]

        data = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert "No Grade" not in data["names"]
        assert data["no_grade"] == [no_grade_person]

    def test_unrecognized_grade_omitted_from_bars_but_listed(self):
        weird_person = _result("Weird", grade="Emeritus", pct=50.0)
        results = [_result("Graded", grade="SL", pct=30.0), weird_person]

        data = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert "Weird" not in data["names"]
        assert data["unrecognized_grade"] == [weird_person]

    def test_overloaded_ranks_first_but_pinned_to_top(self):
        """Overloaded staff rank first (leftmost) within their grade -
        arguably the most heavily loaded people in the group - even though
        their bar is pinned to y_max rather than showing their true height."""
        overloaded = _result("Overloaded", grade="SL", pct=-500.0)
        normal = _result("Normal", grade="SL", pct=30.0)
        results = [normal, overloaded]

        data = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert data["names"] == ["Overloaded", "Normal"]
        idx = data["names"].index("Overloaded")
        assert data["plotted_values"][idx] == data["y_max"]
        assert data["overloaded"] == [overloaded]

    def test_multiple_overloaded_ranked_most_severe_first(self):
        mild = _result("Mildly Overloaded", grade="SL", pct=-10.0)
        severe = _result("Severely Overloaded", grade="SL", pct=-500.0)
        normal = _result("Normal", grade="SL", pct=30.0)
        results = [normal, mild, severe]

        data = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert data["names"] == ["Severely Overloaded", "Mildly Overloaded", "Normal"]

    def test_axis_stats_match_flat_chart_for_same_population(self):
        results = [_result("A", grade="Prof", pct=20.0), _result("B", grade="SL", pct=60.0)]

        flat = _prepare_teaching_percentage_chart_data(results)
        by_grade = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert by_grade["y_max"] == flat["y_max"]
        assert by_grade["average_pct"] == flat["average_pct"]

    def test_empty_grade_group_produces_no_entry(self):
        results = [_result("Only SL", grade="SL", pct=30.0)]

        data = _prepare_teaching_percentage_by_grade_chart_data(results)

        assert [g for g, _, _ in data["grade_groups"]] == ["SL"]

    def test_all_known_grades_are_in_order_constant(self):
        assert _TEACHING_PCT_GRADE_ORDER == ["Prof", "Reader", "SL", "Lecturer"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
