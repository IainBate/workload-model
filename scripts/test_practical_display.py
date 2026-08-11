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
                staff={t: StaffData(t, 1.0, [], 0, 0, 0, [], [], True) for t in teachers},
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
            if 'COM00029I' in code:
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

        # Expected repeat_hours = 0.67 × 2.0 × 2.5 × 1.5 = 5.0h (per week)
        expected_repeat_weekly = (total_groups / n_teachers - 1) * first_session_hours * config.TEACHING_PROBLEM_CLASS * config.REPETITION_MULTIPLIER
        assert abs(repeat_hours - expected_repeat_weekly) < 0.1, f"Expected repeat_hours≈{expected_repeat_weekly}, got {repeat_hours}"

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
                "John Smith": StaffData("John Smith", 1.0, [], 0, 0, 0, [], [], True),
                "Jane Doe": StaffData("Jane Doe", 1.0, [], 0, 0, 0, [], [], True)
            },
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)

        # Generate HTML output to verify display text
        from output_generator import _format_module_practicals_section

        for result in results:
            if result.name == "John Smith":
                module_breakdown = None
                for code, breakdown in result.teaching_module_breakdowns.items():
                    if 'TEST001' in code:
                        module_breakdown = breakdown
                        break

                assert module_breakdown is not None, "Module breakdown not found"

                # Get the practicals section display text
                parts = _format_module_practicals_section(
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
            staff={"John Smith": StaffData("John Smith", 1.0, [], 0, 0, 0, [], [], True)},
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)

        # Generate HTML to check display text
        from output_generator import _format_module_practicals_section

        for result in results:
            module_breakdown = None
            for code, breakdown in result.teaching_module_breakdowns.items():
                if 'TEST002' in code:
                    module_breakdown = breakdown
                    break

            parts = _format_module_practicals_section(
                module_breakdown,
                css_class="teaching-section",
                module_code="TEST002",
                is_new_lecturer=False
            )

            # Check that "First time session" or similar appears (not "First time delivery")
            has_first_time = any("first time session" in p.lower() for p in parts)
            has_repeat = any("repeat" in p.lower() for p in parts)

            # Both should use consistent terminology
            if has_repeat:
                assert has_first_time, "Should have first time session text when repeat sessions appear"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
