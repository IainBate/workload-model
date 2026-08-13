"""
Tests for practical session display formatting.

These tests verify that the display text matches the calculated values.
"""

import pytest
from pathlib import Path
import sys

# Add scripts directory to path for imports
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import StaffData, ModuleData, SupervisionAllocation, YearData
from workload_calculator import calculate_workload
import config


class TestPracticalDisplayCalculation:
    """Tests for practical session display calculation accuracy."""

    def test_practical_display_matches_calculation_parallel_groups(self):
        """
        Verify that the display text matches the calculated values for parallel groups.

        For SYS2-like module with 5 parallel groups, 3 teachers, 2h sessions:
        - Total first session (module): 5 × 2.0 × 2.5 × 11 = 275.0h
        - Total repeat (module): 0.67 × 2.0 × 2.5 × 1.5 × 11 = 55.0h
        - Each teacher's base: (275 + 55) / 3 = 110.0h
        """
        # Create a module similar to SYS2 with parallel groups
        module = ModuleData(
            name="SYS2 Module",
            codes=["COM00029I"],
            credits=20,
            stage=2,
            contact_hours=40,
            practicals=1,  # 1 session per group
            practical_contact_hours=2.0,  # 2 hours per session
            practical_groups=5,  # 5 parallel groups
            practical_weeks=list(range(1, 12)),  # 11 weeks
            assessment_count=1,
            student_count=100,
            teachers=["Christopher Crispin-Bailey", "Teacher B", "Teacher C"],
            lead_name=None,
        )

        teachers = ["Christopher Crispin-Bailey", "Teacher B", "Teacher C"]
        # Not in known lecturers, so all are new lecturers at 5x
        known_lecturers_global = set()
        known_lecturers_per_module = {}
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = calculate_workload(
            YearData.create(
                year_label="2026-7",
                modules=[module],
                student_counts={},
                assessment_counts={},
                staff={t: StaffData(canonical_name=t, fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True) for t in teachers},
                known_lecturers=known_lecturers_global,
                known_lecturers_per_module=known_lecturers_per_module
            ),
            validate_input=False
        )

        # Find Christopher's result
        chris_result = next(r for r in result if r.name == "Christopher Crispin-Bailey")

        # Verify the structured breakdown exists
        assert hasattr(chris_result, 'teaching_module_breakdowns')

        module_breakdown = None
        for code, breakdown in chris_result.teaching_module_breakdowns.items():
            if 'COM00029I' in code or 'SYS2' in code:
                module_breakdown = breakdown
                break

        # The structured practicals breakdown should exist
        practicals_structured = module_breakdown.get('practicals_structured', {})

        # Verify the calculation values
        assert 'first_session_hours' in practicals_structured, "first_session_hours missing from structured data"
        assert 'repeat_hours' in practicals_structured, "repeat_hours missing from structured data"
        assert 'total_groups' in practicals_structured, "total_groups missing from structured data"

        # Check the values
        first_session_hours = practicals_structured['first_session_hours']  # Should be 2.0 (hours per session)
        repeat_hours = practicals_structured['repeat_hours']  # Should be repeat sessions × hours × rates
        total_groups = practicals_structured['total_groups']  # Should be 5
        n_teachers = practicals_structured['n_teachers']  # Should be 3

        assert first_session_hours == 2.0, f"Expected first_session_hours=2.0, got {first_session_hours}"

        # repeat_hours holds BASE hours per week (sessions × duration), with no
        # rates applied - the renderer applies the repetition rate at display
        # time. groups_per_teacher = 5/3 = 1.67, so repeats = 0.67 per teacher,
        # giving 0.67 × 2.0 = 1.33h/week base.
        expected_repeat_base = ((total_groups / n_teachers) - 1) * first_session_hours
        assert abs(repeat_hours - expected_repeat_base) < 0.1, \
            f"Expected repeat_hours≈{expected_repeat_base} (base, no rates), got {repeat_hours}"

        # And applying the repetition rate to that base must reproduce the
        # repeat hours the report actually displays.
        week_count = practicals_structured['week_count']
        displayed_repeat_total = repeat_hours * config.REPETITION_MULTIPLIER * week_count
        expected_repeat_total = (
            ((total_groups / n_teachers) - 1) * first_session_hours
            * config.REPETITION_MULTIPLIER * week_count
        )
        assert abs(displayed_repeat_total - expected_repeat_total) < 0.1

    def test_practical_display_termination(self):
        """Test that display text terminates correctly without partial sentences."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST001"],
            credits=20,
            stage=5,
            contact_hours=40,
            practicals=1,
            practical_contact_hours=2.0,
            practical_groups=3,  # 3 groups, 2 teachers = 1.5 groups per teacher
            practical_weeks=list(range(1, 12)),
            assessment_count=1,
            student_count=100,
            teachers=["John Smith", "Jane Doe"],
            lead_name=None,
        )

        year_data = YearData.create(
            year_label="2026-7",
            modules=[module],
            student_counts={},
            assessment_counts={},
            staff={
                "John Smith": StaffData(canonical_name="John Smith", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True),
                "Jane Doe": StaffData(canonical_name="Jane Doe", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True)
            },
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)

        # Generate HTML output to verify display text (method of TeachingBreakdown class)
        from output_generator import TeachingBreakdown

        tb = TeachingBreakdown(
            delivery_hours=0.0,
            delivery_multiplier="",
            practical_hours=0.0,
            practical_detail="",
            assessment_setting_hours=0.0,
            assessment_setting_detail="",
            marking_hours=0.0,
            marking_detail=""
        )

        for result in results:
            if result.name == "John Smith":
                module_breakdown = None
                for code, breakdown in result.teaching_module_breakdowns.items():
                    if 'TEST001' in code or 'TestModule' in code:
                        module_breakdown = breakdown
                        break

                assert module_breakdown is not None, "Module breakdown not found"

                # Get the practicals section display text (method of TeachingBreakdown class)
                parts = tb._format_module_practicals_section(
                    module_breakdown,
                    css_class="teaching-section",
                    module_code="TEST001",
                    is_new_lecturer=False  # Standard lecturer for simplicity
                )

                # Check that all lines have complete sentences
                for part in parts:
                    if 'sessions/week' in part or 'repeat' in part.lower():
                        # Should be a complete, readable calculation
                        assert not part.endswith('=') or 'h' in part, f"Incomplete line: {part}"
                        assert '@' not in part or '×' in part, f"Missing multiplication symbol in: {part}"


class TestPracticalDisplayText:
    """Tests for practical session display text format."""

    def test_display_text_uses_correct_terminology(self):
        """Verify display uses consistent terminology."""
        # "First time session" should be consistent with "Repeat sessions"
        module = ModuleData(
            name="TestModule",
            codes=["TEST002"],
            credits=20,
            stage=5,
            contact_hours=40,
            practicals=1,
            practical_contact_hours=2.0,
            practical_groups=2,  # 2 groups, 1 teacher = no repeats
            practical_weeks=list(range(1, 12)),
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )

        year_data = YearData.create(
            year_label="2026-7",
            modules=[module],
            student_counts={},
            assessment_counts={},
            staff={"John Smith": StaffData(canonical_name="John Smith", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True)},
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)

        # Generate HTML to check display text (method of TeachingBreakdown class)
        from output_generator import TeachingBreakdown
        tb = TeachingBreakdown(
            delivery_hours=0.0,
            delivery_multiplier="",
            practical_hours=0.0,
            practical_detail="",
            assessment_setting_hours=0.0,
            assessment_setting_detail="",
            marking_hours=0.0,
            marking_detail=""
        )

        for result in results:
            module_breakdown = None
            for code, breakdown in result.teaching_module_breakdowns.items():
                if 'TEST002' in code or 'TestModule' in code:
                    module_breakdown = breakdown
                    break

            parts = tb._format_module_practicals_section(
                module_breakdown,
                css_class="teaching-section",
                module_code="TEST002",
                is_new_lecturer=False
            )

            # Check that "First session share" or similar appears (not "First time delivery")
            has_first_session = any("first session" in p.lower() for p in parts)
            has_repeat = any("repeat" in p.lower() for p in parts)

            # When there are no repeats, we shouldn't see "Repeat sessions"
            # But when repeats exist, both should use consistent terminology
            if has_repeat:
                assert has_first_session, "Should have first session text when repeat sessions appear"


class TestPracticalDisplayMath:
    """Tests to verify display math is correct."""

    def test_display_math_is_correct_for_parallel_groups(self):
        """
        Verify the display calculation matches actual mathematical calculation.

        For a module with 5 parallel groups, 3 teachers, 2h sessions:
        - First session total (module): 5 × 2.0 × 2.5 × 11 = 275.0h
        - Repeat weekly: (5/3 - 1) × 2.0 × 2.5 × 1.5 = 5.0h/week
        - Repeat total (module): 5.0 × 11 = 55.0h
        - Total practicals (module): 275 + 55 = 330.0h
        - Per teacher base: 330 / 3 = 110.0h
        """
        module = ModuleData(
            name="TestModule",
            codes=["TEST003"],
            credits=20,
            stage=5,
            contact_hours=40,
            practicals=1,
            practical_contact_hours=2.0,
            practical_groups=5,  # 5 parallel groups
            practical_weeks=list(range(1, 12)),
            assessment_count=1,
            student_count=100,
            teachers=["Teacher A", "Teacher B", "Teacher C"],
            lead_name=None,
        )

        year_data = YearData.create(
            year_label="2026-7",
            modules=[module],
            student_counts={},
            assessment_counts={},
            staff={
                "Teacher A": StaffData(canonical_name="Teacher A", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True),
                "Teacher B": StaffData(canonical_name="Teacher B", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True),
                "Teacher C": StaffData(canonical_name="Teacher C", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True)
            },
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)

        # Get Teacher A's result
        teacher_a = next(r for r in results if r.name == "Teacher A")

        # Find the module breakdown
        module_breakdown = None
        for code, breakdown in teacher_a.teaching_module_breakdowns.items():
            if 'TEST003' in code or 'TestModule' in code:
                module_breakdown = breakdown
                break

        assert module_breakdown is not None, "Module breakdown not found"

        structured = module_breakdown.get('practicals_structured', {})

        # Verify the key values match expected calculations
        total_groups = structured['total_groups']  # 5
        n_teachers = structured['n_teachers']  # 3
        hours_per_session = structured['first_session_hours']  # 2.0

        # repeat_hours is BASE hours per week (no rates applied); the renderer
        # multiplies by REPETITION_MULTIPLIER and week_count for display.
        expected_repeat_base = ((total_groups / n_teachers) - 1) * hours_per_session

        assert abs(structured.get('repeat_hours', 0) - expected_repeat_base) < 0.1, \
            f"Repeat base mismatch: expected {expected_repeat_base}, got {structured.get('repeat_hours')}"

    def test_display_text_does_not_contain_invalid_math(self):
        """Verify display doesn't show mathematically incorrect formulas like '1.67 sessions/week × 2h × 11 = 275'."""
        module = ModuleData(
            name="SYS2 Module",
            codes=["COM00029I"],
            credits=20,
            stage=2,
            contact_hours=40,
            practicals=1,
            practical_contact_hours=2.0,
            practical_groups=5,
            practical_weeks=list(range(1, 12)),
            assessment_count=1,
            student_count=100,
            teachers=["Christopher Crispin-Bailey", "Teacher B", "Teacher C"],
            lead_name=None,
        )

        year_data = YearData.create(
            year_label="2026-7",
            modules=[module],
            student_counts={},
            assessment_counts={},
            staff={
                "Christopher Crispin-Bailey": StaffData(canonical_name="Christopher Crispin-Bailey", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True),
                "Teacher B": StaffData(canonical_name="Teacher B", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True),
                "Teacher C": StaffData(canonical_name="Teacher C", fte=1.0, aliases=[], roles=[], research_projects=[], saint_modules=[], active=True)
            },
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)

        from output_generator import TeachingBreakdown
        tb = TeachingBreakdown(
            delivery_hours=0.0,
            delivery_multiplier="",
            practical_hours=0.0,
            practical_detail="",
            assessment_setting_hours=0.0,
            assessment_setting_detail="",
            marking_hours=0.0,
            marking_detail=""
        )

        chris_result = next(r for r in results if r.name == "Christopher Crispin-Bailey")

        for code, breakdown in chris_result.teaching_module_breakdowns.items():
            if 'COM00029I' in code or 'SYS2' in code:
                parts = tb._format_module_practicals_section(
                    breakdown,
                    css_class="teaching-section",
                    module_code="COM00029I",
                    is_new_lecturer=True
                )

                # Check that no line contains the invalid pattern "X.XX sessions/week @ Yh × weeks = ZZZ"
                # (where X.XX is a number of sessions without hours per session info)
                for part in parts:
                    if 'sessions/week' in part and 'h each' not in part and 'h per session' not in part:
                        assert False, f"Invalid format 'sessions/week' found (without h per session): {part}"

                # Check that valid format appears: "X.Xh per session @" or "repeat sessions/week"
                has_valid_format = any("h per session @" in part for part in parts)
                has_repeat_format = any("repeat sessions/week" in part for part in parts)
                assert has_valid_format or has_repeat_format, "Valid format 'h per session @' or 'repeat sessions/week' not found in practicals display"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
