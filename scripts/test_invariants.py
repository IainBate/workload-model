"""
Property-based invariant tests (plan item B9).

Where the baseline tests pin down *specific* values for the real dataset, these
assert properties that must hold for *any* input. Hypothesis generates the
inputs and shrinks any counterexample to a minimal reproduction.

These target the decomposed calculator helpers
(`_calculate_lecture_hours_and_multipliers`, `_calculate_practical_hours_and_breakdown`)
plus the full `calculate_workload` pipeline.
"""

import sys
from pathlib import Path

import pytest
from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import config  # noqa: E402
from data_loader import (  # noqa: E402
    ModuleData,
    StaffData,
    SupervisionAllocation,
    YearData,
)
from workload_calculator import (  # noqa: E402
    _calculate_lecture_hours_and_multipliers,
    _calculate_practical_hours_and_breakdown,
    calculate_workload,
)

# Keep generated cases small: these exercise arithmetic, not scale.
TEACHER_NAMES = ["A", "B", "C", "D"]

teachers_strategy = st.lists(
    st.sampled_from(TEACHER_NAMES), min_size=1, max_size=4, unique=True
)


def _module(**kwargs) -> ModuleData:
    """ModuleData with sensible defaults, overridable per test."""
    defaults = dict(
        name="M",
        codes=("TEST001",),
        credits=20,
        stage=2,
        practicals=0,
        practical_contact_hours=0.0,
        practical_groups=0,
        practical_weeks=(),
        assessment_count=1,
        student_count=10,
        teachers=("A",),
        lead_name=None,
    )
    defaults.update(kwargs)
    return ModuleData(**defaults)


class TestPracticalInvariants:
    """Properties of the practical-hours helper."""

    @given(
        teachers=teachers_strategy,
        groups=st.integers(min_value=0, max_value=8),
        hours=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
        practicals=st.integers(min_value=0, max_value=4),
    )
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_practical_hours_never_negative(self, teachers, groups, hours, practicals):
        """No teacher can ever be allocated negative practical hours."""
        module = _module(
            practicals=practicals,
            practical_contact_hours=hours,
            practical_groups=groups,
            teachers=tuple(teachers),
        )
        result = _calculate_practical_hours_and_breakdown(module, teachers)
        for name, value in result["individual_practical_hours"].items():
            assert value >= 0, f"{name} got negative practical hours: {value}"

    @given(
        teachers=teachers_strategy,
        groups=st.integers(min_value=2, max_value=8),
        hours=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_total_equals_sum_of_individual(self, teachers, groups, hours):
        """'Group distribution neutrality': the reported total is exactly the
        sum of the per-teacher allocations, however groups divide across staff."""
        module = _module(
            practicals=1,
            practical_contact_hours=hours,
            practical_groups=groups,
            teachers=tuple(teachers),
        )
        result = _calculate_practical_hours_and_breakdown(module, teachers)
        individual_sum = sum(result["individual_practical_hours"].values())
        assert result["total_practical_hours"] == pytest.approx(individual_sum, rel=1e-9)

    @given(
        teachers=teachers_strategy,
        groups=st.integers(min_value=2, max_value=8),
        hours=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_repeat_hours_are_base_hours_without_rates(self, teachers, groups, hours):
        """repeat_hours must stay rate-free base hours.

        The renderer applies REPETITION_MULTIPLIER itself; if the calculator ever
        starts pre-applying it, reports would silently inflate. This pins the
        contract that a previous stale unit test got wrong.
        """
        module = _module(
            practicals=1,
            practical_contact_hours=hours,
            practical_groups=groups,
            teachers=tuple(teachers),
        )
        breakdown = _calculate_practical_hours_and_breakdown(module, teachers)["practicals_breakdown"]
        if not breakdown or "repeat_sessions_per_teacher" not in breakdown:
            return
        expected = breakdown["repeat_sessions_per_teacher"] * breakdown["first_session_hours"]
        assert breakdown["repeat_hours"] == pytest.approx(expected, abs=0.01)

    @given(
        n_teachers=st.integers(min_value=1, max_value=4),
        groups=st.integers(min_value=1, max_value=8),
        hours=st.floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_more_teachers_never_increases_individual_load(self, n_teachers, groups, hours):
        """Adding staff to a module must not increase any one person's share."""
        assume(n_teachers < 4)
        small = TEACHER_NAMES[:n_teachers]
        large = TEACHER_NAMES[: n_teachers + 1]

        def per_teacher(team):
            module = _module(
                practicals=1,
                practical_contact_hours=hours,
                practical_groups=groups,
                teachers=tuple(team),
            )
            res = _calculate_practical_hours_and_breakdown(module, team)
            vals = list(res["individual_practical_hours"].values())
            return max(vals) if vals else 0.0

        assert per_teacher(large) <= per_teacher(small) + 1e-6


class TestLectureInvariants:
    """Properties of the lecture-hours helper."""

    @given(teachers=teachers_strategy)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_contact_hours_split_across_teachers(self, teachers):
        """Base contact hours divide evenly and sum back to the module total."""
        module = _module(teachers=tuple(teachers))
        result = _calculate_lecture_hours_and_multipliers(module, teachers, set(teachers), {})
        contact = result["individual_lecture_contact_hours"]
        assert sum(contact.values()) == pytest.approx(result["total_lecture_hours"], rel=1e-9)

    @given(teachers=teachers_strategy)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_new_lecturer_never_cheaper_than_standard(self, teachers):
        """A lecturer new to a module never attracts a lower rate than a known one."""
        module = _module(teachers=tuple(teachers))
        known = _calculate_lecture_hours_and_multipliers(module, teachers, set(teachers), {})
        unknown = _calculate_lecture_hours_and_multipliers(module, teachers, set(), {})
        for t in teachers:
            assert unknown["lecture_multipliers"][t] >= known["lecture_multipliers"][t]

    @given(teachers=teachers_strategy)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_multipliers_are_configured_values(self, teachers):
        """Every applied multiplier is one of the configured rates - never ad hoc."""
        allowed = set(config.TEACHING_MULTIPLIERS.values())
        module = _module(teachers=tuple(teachers))
        for known_set in (set(teachers), set()):
            result = _calculate_lecture_hours_and_multipliers(module, teachers, known_set, {})
            for t, mult in result["lecture_multipliers"].items():
                assert mult in allowed, f"{mult} is not a configured multiplier"


class TestPipelineInvariants:
    """Properties of the full calculate_workload pipeline."""

    @staticmethod
    def _run(fte: float, student_count: int, teachers):
        module = _module(student_count=student_count, teachers=tuple(teachers))
        year = YearData.create(
            year_label="2026-7",
            modules=[module],
            student_counts={},
            assessment_counts={},
            staff={
                t: StaffData(
                    canonical_name=t, fte=fte, aliases=[], roles=[],
                    research_projects=[], saint_modules=[], active=True,
                )
                for t in teachers
            },
            known_lecturers=set(teachers),
            known_lecturers_per_module={},
        )
        return calculate_workload(year, validate_input=False)

    @given(
        fte=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
        students=st.integers(min_value=0, max_value=300),
        teachers=teachers_strategy,
    )
    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_total_equals_sum_of_categories(self, fte, students, teachers):
        """The headline invariant: total = teaching + research + admin, always."""
        for r in self._run(fte, students, teachers):
            expected = r.teaching_hours + r.research_hours + r.admin_hours
            assert r.total_hours == pytest.approx(expected, abs=0.05), (
                f"{r.name}: {r.total_hours} != {expected}"
            )

    @given(
        fte=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
        students=st.integers(min_value=0, max_value=300),
        teachers=teachers_strategy,
    )
    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_no_category_is_negative(self, fte, students, teachers):
        """No category can go negative for any input."""
        for r in self._run(fte, students, teachers):
            for field in ("total_hours", "teaching_hours", "research_hours", "admin_hours"):
                assert getattr(r, field) >= 0, f"{r.name}.{field} negative"

    @given(
        low=st.floats(min_value=0.1, max_value=0.5, allow_nan=False, allow_infinity=False),
        high=st.floats(min_value=0.6, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_higher_fte_gives_higher_nominal_hours(self, low, high):
        """Nominal hours scale monotonically with FTE, all else equal."""
        low_result = self._run(low, 50, ["A"])[0]
        high_result = self._run(high, 50, ["A"])[0]
        assert high_result.nominal_hours > low_result.nominal_hours

    @given(students=st.integers(min_value=0, max_value=400))
    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_marking_hours_monotonic_in_student_count(self, students):
        """More students never means less marking."""
        fewer = self._run(1.0, students, ["A"])[0]
        more = self._run(1.0, students + 25, ["A"])[0]
        assert more.teaching_breakdown.get("marking", 0) >= fewer.teaching_breakdown.get("marking", 0) - 1e-6
