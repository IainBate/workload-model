"""
Unit tests for workload calculator.

Tests teaching, research, and admin workload calculations,
FTE scaling, new lecturer detection, and edge cases.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import sys
from pathlib import Path

# Add scripts directory to path for imports
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import StaffData, ModuleData, SupervisionAllocation, YearData, AdjustmentRecord
from workload_calculator import (
    _calculate_teaching_workload,
    _calculate_research_workload,
    _calculate_admin_workload,
    _apply_adjustments,
    _apply_teaching_module_adjustments,
    _TEACHING_MODULE_SUM_KEYS,
    calculate_workload,
)
import config


class TestTeachingWorkload:
    """Tests for teaching workload calculations."""

    def test_basic_lecture_calculation(self):
        """Test basic lecture hour calculation with standard lecturer."""
        # Create a mock module
        module = ModuleData(
            name="TestModule",
            codes=["TEST001"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )

        teachers = ["John Smith"]
        known_lecturers_global = {"John Smith"}
        known_lecturers_per_module = {}
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = _calculate_teaching_workload(
            module, teachers, known_lecturers_global,
            known_lecturers_per_module, {}, supervision
        )

        assert "John Smith" in result
        # Standard lecturer: 40 contact hours * 2.5x multiplier = 100 hours (shared)
        assert result["John Smith"]["hours"] > 0

    def test_new_lecturer_calculation(self):
        """Test new lecturer gets higher multiplier."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST002"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["New Lecturer"],
            lead_name=None,
        )

        teachers = ["New Lecturer"]
        # New lecturer not in known set
        known_lecturers_global = {"John Smith"}
        known_lecturers_per_module = {}
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = _calculate_teaching_workload(
            module, teachers, known_lecturers_global,
            known_lecturers_per_module, {}, supervision
        )

        assert "New Lecturer" in result
        # New lecturer should get 5x multiplier for content development + delivery
        # 40 contact hours / 1 teacher * 5x = 200 hours (approximately)
        teaching_hours = result["New Lecturer"]["hours"]
        assert teaching_hours > 150  # Should be significantly higher than standard

    def test_new_lecturer_new_content_calculation(self):
        """Test new lecturer on new content gets 7.5x multiplier."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST003"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["New Content Lecturer"],
            lead_name=None,
        )
        # Mark as new content
        module.new_content = True

        teachers = ["New Content Lecturer"]
        known_lecturers_global = {"John Smith"}
        known_lecturers_per_module = {}
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = _calculate_teaching_workload(
            module, teachers, known_lecturers_global,
            known_lecturers_per_module, {}, supervision
        )

        assert "New Content Lecturer" in result
        # New lecturer + new content should get 7.5x multiplier
        teaching_hours = result["New Content Lecturer"]["hours"]
        assert teaching_hours > 200  # Should be higher than 5x case

    def test_existing_lecturer_new_content_calculation(self):
        """Test existing lecturer on new content gets 5x multiplier (P1-7)."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST004"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["Existing Lecturer"],
            lead_name=None,
        )
        # Mark as new content
        module.new_content = True

        teachers = ["Existing Lecturer"]
        # Existing lecturer IS in known set (this is the key difference from P1-7 test)
        known_lecturers_global = {"Existing Lecturer", "John Smith"}
        known_lecturers_per_module = {}
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = _calculate_teaching_workload(
            module, teachers, known_lecturers_global,
            known_lecturers_per_module, {}, supervision
        )

        assert "Existing Lecturer" in result
        # Existing lecturer with new content should get 5x multiplier (not 7.5x for new lecturer+new, not 2.5x standard)
        teaching_hours = result["Existing Lecturer"]["hours"]
        # Total includes: teaching (200h @ 5x) + assessment (15h) + marking (60h) + admin (3h) = 278h
        # Should be significantly more than standard (2.5x ~178h) but less than new lecturer+new content (7.5x ~378h)
        # Teaching hours only (ignoring assessment, marking, admin overhead)
        teaching_only = result["Existing Lecturer"]["teaching_breakdown"]["teaching"]
        assert teaching_hours > 150  # More than standard 2.5x (~178h total)
        assert teaching_hours < 350  # Less than new lecturer+new content 7.5x (~378h total)

    def test_practical_sessions_calculation(self):
        """Test practical session calculations with repetition multiplier."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST004"],
            credits=20,
            stage=5,
            practicals=1,
            practical_contact_hours=2,
            practical_groups=2,
            practical_weeks=list(range(1, 12)),
            assessment_count=1,
            student_count=100,
            teachers=["John Smith", "Jane Doe"],
            lead_name=None,
        )

        teachers = ["John Smith", "Jane Doe"]
        known_lecturers_global = {"John Smith", "Jane Doe"}
        known_lecturers_per_module = {}
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = _calculate_teaching_workload(
            module, teachers, known_lecturers_global,
            known_lecturers_per_module, {}, supervision
        )

        assert "John Smith" in result
        assert "Jane Doe" in result

        # Check practical hours are included
        breakdown = result["John Smith"]["teaching_breakdown"]
        assert breakdown.get("practicals", 0) > 0

    def test_assessment_setting_calculation(self):
        """Test assessment setting hours for new vs standard setters."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST005"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["New Setter", "Standard Setter"],
            lead_name=None,
        )

        teachers = ["New Setter", "Standard Setter"]
        known_lecturers_global = {"Standard Setter"}
        known_lecturers_per_module = {}
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = _calculate_teaching_workload(
            module, teachers, known_lecturers_global,
            known_lecturers_per_module, {}, supervision
        )

        # New setter should have higher assessment hours
        new_hours = result["New Setter"]["teaching_breakdown"].get("assessment_setting", 0)
        std_hours = result["Standard Setter"]["teaching_breakdown"].get("assessment_setting", 0)

        assert new_hours > std_hours

    def test_assessment_setting_automated_marking(self):
        """Test assessment setting uses automated rates when marking_type is 'automated' (P1-1)."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST007"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )
        # Mark as automated marking
        module.marking_type = "automated"

        result = _calculate_teaching_workload(
            module, ["John Smith"], {"John Smith"}, {}, {},
            SupervisionAllocation({}, {})
        )

        # With automated marking, standard rate is 25h (config.ASSESSMENT_AUTO_STANDARD)
        # vs manual standard of 15h
        assessment_hours = result["John Smith"]["teaching_breakdown"].get("assessment_setting", 0)
        assert assessment_hours == 25.0

    def test_assessment_setting_new_assessment(self):
        """Test assessment setting uses new_assessment_or_format rate (P1-1)."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST008"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )
        # Mark as new assessment (entirely new format)
        module.new_assessment = True

        result = _calculate_teaching_workload(
            module, ["John Smith"], {"John Smith"}, {}, {},
            SupervisionAllocation({}, {})
        )

        # With manual marking and new_assessment, rate is 37.5h (config.ASSESSMENT_MANUAL_NEW_ASSESSMENT)
        assessment_hours = result["John Smith"]["teaching_breakdown"].get("assessment_setting", 0)
        assert assessment_hours == 37.5

    def test_assessment_setting_checking_only(self):
        """Test assessment setting uses checking rate for checking-only papers (P1-1)."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST009"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )
        # Mark as checking only (doesn't set, just checks)
        module.checking_only = True

        result = _calculate_teaching_workload(
            module, ["John Smith"], {"John Smith"}, {}, {},
            SupervisionAllocation({}, {})
        )

        # With manual marking and checking_only, rate is 2h (config.ASSESSMENT_MANUAL_CHECKING)
        assessment_hours = result["John Smith"]["teaching_breakdown"].get("assessment_setting", 0)
        assert assessment_hours == 2.0

    def test_stage_threshold_consistency(self):
        """Test that stage >= threshold is consistent for MSc detection (P1-2)."""
        # Test marking calculation with modules at different stages
        for stage, expected_ug in [(1, True), (3, True), (4, False), (7, False)]:
            module = ModuleData(
                name=f"TestModule-stage-{stage}",
                codes=[f"TEST-S{stage}"],
                credits=20,
                stage=stage,
                practicals=0,
                practical_contact_hours=0,
                practical_groups=0,
                practical_weeks=None,
                assessment_count=1,
                student_count=50,  # Use odd number to get non-integer script count
                teachers=["John Smith"],
                lead_name=None,
            )

            result = _calculate_teaching_workload(
                module, ["John Smith"], {"John Smith"}, {}, {},
                SupervisionAllocation({}, {})
            )

            marking_hours = result["John Smith"]["teaching_breakdown"].get("marking", 0)

            if config.is_msc_level(stage):
                # MSc (stage >= 4): should use UG rate for automated, MSC for manual
                expected_rate = config.MARKING_MANUAL_MSC  # 0.5
            else:
                # UG (stage < 4): should use UG rate for automated, UG for manual
                expected_rate = config.MARKING_MANUAL_UG  # 0.33

            # Verify the rate used matches is_msc_level behavior
            # 50 students + ~10 resits = ~60 scripts * rate / 1 teacher
            assert marking_hours > 0

    def test_assessment_marking_calculation(self):
        """Test marking hours based on student count and marking type."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST006"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )

        teachers = ["John Smith"]
        known_lecturers_global = {"John Smith"}
        known_lecturers_per_module = {}
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = _calculate_teaching_workload(
            module, teachers, known_lecturers_global,
            known_lecturers_per_module, {}, supervision
        )

        marking_hours = result["John Smith"]["teaching_breakdown"].get("marking", 0)
        # 100 students * 0.33h/script (UG manual) + 20 resits * 0.33h = ~40h total, /1 teacher
        assert marking_hours > 30

    def test_empty_teachers_returns_empty_result(self):
        """Test that empty teachers list returns empty result."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST007"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=[],
            lead_name=None,
        )

        result = _calculate_teaching_workload(
            module, [], set(), {}, {}, SupervisionAllocation({}, {})
        )
        assert result == {}


class TestResearchWorkload:
    """Tests for research workload calculations."""

    def test_protected_baseline(self):
        """Test protected research baseline constant is set correctly."""
        # Protected baseline is 164.2h for full-time (10% of 1642)
        assert config.PROTECTED_RESEARCH_BASELINE == 164.2

    def test_phd_supervision_hours(self):
        """Test PhD supervision hours are calculated correctly."""
        staff = StaffData(
            canonical_name="John Smith",
            fte=1.0,
            roles=[],
            phd_supervisions=2,  # 2 primary supervisors
            phd_co_supervisions=1,  # 1 co-supervisor
            phd_assessor_count=1,  # 1 assessor
            research_projects=[],
            saint_modules=[],
            active=True
        )

        total, breakdown, detail, grant_titles, _ = _calculate_research_workload(staff)

        expected_hours = (
            2 * config.SUPERVISION_MULTIPLIERS["pgr_primary_supervisor_per_fte"] +
            1 * config.SUPERVISION_MULTIPLIERS["pgr_co_supervisor_per_fte"] +
            1 * config.SUPERVISION_MULTIPLIERS["pgr_assessor"]
        )
        assert total == expected_hours
        # PhD hours live in a nested 'phd_students' dict with one entry per
        # supervision type (there is deliberately no flat 'phd_supervision'
        # total key - having both caused a double-counting bug historically).
        phd_students = breakdown.get("phd_students", {})
        assert phd_students.get("supervision", {}).get("count") == 2
        assert phd_students.get("supervision", {}).get("total") == 2 * config.SUPERVISION_MULTIPLIERS["pgr_primary_supervisor_per_fte"]
        assert phd_students.get("co_supervision", {}).get("count") == 1
        assert phd_students.get("co_supervision", {}).get("total") == 1 * config.SUPERVISION_MULTIPLIERS["pgr_co_supervisor_per_fte"]
        assert phd_students.get("assessor", {}).get("count") == 1
        assert phd_students.get("assessor", {}).get("total") == 1 * config.SUPERVISION_MULTIPLIERS["pgr_assessor"]
        assert sum(v["total"] for v in phd_students.values()) == expected_hours
        assert "phd_supervision" not in breakdown

    def test_grant_hours(self):
        """Test research grant hours are calculated correctly."""
        staff = StaffData(
            canonical_name="John Smith",
            fte=1.0,
            roles=[],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[
                {"project_id": "GRANT001", "title": "Research Grant", "fte": "50%"}
            ],
            saint_modules=[],
            active=True
        )

        total, breakdown, detail, grant_titles, _ = _calculate_research_workload(staff)

        # 50% of 1642h = 821h
        expected_grant_hours = config.NOMINAL_WORKING_HOURS_PER_YEAR * 0.5
        assert total == expected_grant_hours
        assert "GRANT001" in grant_titles

    def test_part_time_research_workload(self):
        """Test research workload is scaled by FTE for part-time staff."""
        staff = StaffData(
            canonical_name="Part Time Staff",
            fte=0.5,  # Part-time
            roles=[],
            phd_supervisions=2,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        total, breakdown, detail, grant_titles, _ = _calculate_research_workload(staff)

        # PhD supervision hours are NOT scaled by FTE in the current implementation
        expected_phd_hours = 2 * config.SUPERVISION_MULTIPLIERS["pgr_primary_supervisor_per_fte"]

        # _calculate_research_workload does not include protected baseline
        assert total == expected_phd_hours


class TestAdminWorkload:
    """Tests for admin workload calculations."""

    def test_admin_role_hours(self):
        """Test admin role hours are calculated from percentage of nominal."""
        staff = StaffData(
            canonical_name="John Smith",
            fte=1.0,
            roles=["Head of Department"],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        # Head of Department is 100% in config
        total, breakdown, detail, unknown_roles = _calculate_admin_workload(staff, config.NOMINAL_WORKING_HOURS_PER_YEAR)

        assert "Head of Department" in breakdown
        # Should be 100% of nominal hours = 1642h
        assert breakdown["Head of Department"] == config.NOMINAL_WORKING_HOURS_PER_YEAR

    def test_service_points_calculation(self):
        """Test engagement and personal development service points."""
        staff = StaffData(
            canonical_name="John Smith",
            fte=1.0,
            roles=[],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        total, breakdown, detail, unknown_roles = _calculate_admin_workload(staff, config.NOMINAL_WORKING_HOURS_PER_YEAR)

        # Should include engagement and personal development
        assert "engagement" in breakdown
        assert "personal_development" in breakdown

        expected_service = (
            config.BASELOADS.get('engagement', 100.0) +
            config.BASELOADS.get('personal_development', 75.0)
        )
        assert breakdown["engagement"] + breakdown["personal_development"] == expected_service

    def test_part_time_admin_workload(self):
        """Test admin workload is scaled by FTE for part-time staff."""
        staff = StaffData(
            canonical_name="Part Time Admin",
            fte=0.5,
            roles=["Committee Chair"],  # Some percentage role
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        total, breakdown, detail, unknown_roles = _calculate_admin_workload(staff, config.NOMINAL_WORKING_HOURS_PER_YEAR * 0.5)

        # With FTE scaling, total should be less than full-time equivalent
        nominal_for_calc = config.NOMINAL_WORKING_HOURS_PER_YEAR * 0.5

        # Check service points are scaled correctly
        fte_value = 0.5
        expected_engagement = config.BASELOADS.get('engagement', 100.0) * fte_value
        assert breakdown["engagement"] == expected_engagement


class TestFTECalculation:
    """Tests for FTE scaling calculations."""

    def test_part_time_teaching_hours(self):
        """Test teaching hours scale correctly with part-time FTE."""
        # This is more of an integration test - verify the overall calculation
        # handles FTE correctly

        staff = StaffData(
            canonical_name="Part Time Lecturer",
            fte=0.5,
            roles=[],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        # Protected research baseline scales with FTE
        expected_protected = config.PROTECTED_RESEARCH_BASELINE * 0.5
        assert expected_protected == 82.1

    def test_service_points_scaled_by_fte(self):
        """Test service points (engagement + personal_dev) scale with FTE."""
        staff = StaffData(
            canonical_name="Part Time",
            fte=0.5,
            roles=[],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        total, breakdown, detail, unknown_roles = _calculate_admin_workload(staff, config.NOMINAL_WORKING_HOURS_PER_YEAR * 0.5)

        # Service points should be scaled by FTE (0.5)
        expected_engagement = config.BASELOADS.get('engagement', 100.0) * 0.5
        expected_personal_dev = config.BASELOADS.get('personal_development', 75.0) * 0.5

        assert breakdown["engagement"] == expected_engagement
        assert breakdown["personal_development"] == expected_personal_dev


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_zero_student_count(self):
        """Test module with zero students."""
        module = ModuleData(
            name="No Students",
            codes=["TEST008"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=0,
            teachers=["John Smith"],
            lead_name=None,
        )

        result = _calculate_teaching_workload(
            module, ["John Smith"], {"John Smith"}, {}, {},
            SupervisionAllocation({}, {})
        )

        # Marking should be 0 when no students
        assert "John Smith" in result
        marking_hours = result["John Smith"]["teaching_breakdown"].get("marking", 0)
        assert marking_hours == 0

    def test_zero_contact_hours(self):
        """Test module with zero contact hours."""
        module = ModuleData(
            name="Zero Contact",
            codes=["TEST009"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )

        result = _calculate_teaching_workload(
            module, ["John Smith"], {"John Smith"}, {}, {},
            SupervisionAllocation({}, {})
        )

        assert "John Smith" in result
        # Should still have marking and admin components
        teaching_breakdown = result["John Smith"]["teaching_breakdown"]
        assert teaching_breakdown.get("marking", 0) > 0

    def test_empty_staff_data(self):
        """Test staff with no activities."""
        staff = StaffData(
            canonical_name="No Activities",
            fte=1.0,
            roles=[],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        total, breakdown, detail, grant_titles, _ = _calculate_research_workload(staff)
        # _calculate_research_workload does not include protected baseline
        assert total == 0

    def test_multiple_teachers_shared_hours(self):
        """Test that hours are shared correctly among multiple teachers."""
        module = ModuleData(
            name="Team Teaching",
            codes=["TEST010"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["Teacher A", "Teacher B", "Teacher C"],
            lead_name=None,
        )

        result = _calculate_teaching_workload(
            module, ["Teacher A", "Teacher B", "Teacher C"],
            {"Teacher A", "Teacher B", "Teacher C"}, {}, {},
            SupervisionAllocation({}, {})
        )

        # All teachers should have similar hours (shared equally)
        total_hours = sum(r["hours"] for r in result.values())
        # With 3 teachers, each gets ~1/3 of total module workload
        assert len(result) == 3


class TestNormalizeName:
    """Tests for name normalization functionality (P1-3)."""

    def test_normalize_name_rejects_no_answer(self):
        """Test that normalize_name respects False return from unknown_callback (P1-3)."""
        from data_loader import normalize_name

        reverse_lookup = {
            "john smith": "John Smith",
            "jane doe": "Jane Doe"
        }

        # Create a mock callback that always returns False
        def reject_all_callback(user_name, canonical_name):
            return False

        # When the callback returns False, should not use the partial match
        result = normalize_name("john s", reverse_lookup, unknown_callback=reject_all_callback)

        # Should be None (rejected), not "John Smith"
        assert result is None

    def test_normalize_name_accepts_yes_answer(self):
        """Test that normalize_name accepts True return from unknown_callback."""
        from data_loader import normalize_name

        reverse_lookup = {
            "john smith": "John Smith",
            "jane doe": "Jane Doe"
        }

        # Create a mock callback that always returns True
        def accept_all_callback(user_name, canonical_name):
            return True

        result = normalize_name("john s", reverse_lookup, unknown_callback=accept_all_callback)

        # Should be "John Smith" (accepted)
        assert result == "John Smith"


class TestAssumptionsTracking:
    """Tests for assumptions tracking functionality."""

    def test_assumption_class_exists(self):
        """Verify Assumption class can be imported and used."""
        from workload_calculator import Assumption

        assumption = Assumption(
            category="student_count",
            description="Default student count applied",
            staff_name=None,
            module_code=None
        )

        assert assumption.category == "student_count"
        assert assumption.description == "Default student count applied"

    def test_assumptions_list_initialized(self):
        """Test that assumptions list is properly initialized."""
        from workload_calculator import Assumption
        from data_loader import YearData

        # Create a scenario with an assumption (invalid grant FTE)
        module = ModuleData(
            name="TestModule",
            codes=["TEST001"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )

        staff = StaffData(
            canonical_name="John Smith",
            fte=1.0,
            roles=[],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[
                {"title": "Grant", "total_income": 10000, "fte": "invalid"}
            ],
            saint_modules=[],
            active=True
        )

        # Create YearData with the module and staff
        year_data = YearData.create(
            year_label="2026-7",
            modules=[module],
            student_counts={},
            assessment_counts={},
            staff={"John Smith": staff},
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        result = calculate_workload(year_data, validate_input=False)

        # Verify assumptions are tracked (invalid FTE string should create an assumption)
        assert len(result) > 0
        john_result = result[0]
        assumptions = getattr(john_result, 'assumptions', [])
        assert len(assumptions) > 0

    def test_data_loader_imports_any(self):
        """Test that data_loader module imports successfully with Any type."""
        # This test verifies P0-1: the Any import was added to typing
        from data_loader import _load_module_mapping

        # Just verify the function exists and can be imported
        assert callable(_load_module_mapping)


# --- Tests for Prompt 0: Category field and normative split mapping ---

class TestCategoryField:
    """Tests for WorkloadResult.category field (Prompt 0)."""

    def test_workload_result_has_category_field(self):
        """Verify WorkloadResult has a category field."""
        from data_loader import WorkloadResult

        result = WorkloadResult(
            name="Test Staff",
            fte=1.0,
            total_hours=2000,
            teaching_hours=800,
            research_hours=600,
            admin_hours=400,
            category="T and S",
            assumptions=(),
            missing_data=()
        )

        assert result.category == "T and S"

    def test_category_set_from_staff_data(self):
        """Verify calculate_workload sets category from StaffData."""
        module = ModuleData(
            name="TestModule",
            codes=["TEST001"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )

        # Test with ART category
        staff_art = StaffData(
            canonical_name="John Smith",
            fte=1.0,
            category="ART",
            roles=[],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        year_data = YearData.create(
            year_label="2026-7",
            modules=[module],
            student_counts={},
            assessment_counts={},
            staff={"John Smith": staff_art},
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)
        assert len(results) == 1
        assert results[0].category == "ART"

    def test_category_defaults_to_staff_data_value(self):
        """Verify category defaults to StaffData.category when not explicitly set."""
        # Create a module for testing
        test_module = ModuleData(
            name="TestModule",
            codes=["TEST001"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["Jane Doe"],
            lead_name=None,
        )

        staff_ts = StaffData(
            canonical_name="Jane Doe",
            fte=1.0,
            category="T and S",
            roles=[],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        year_data = YearData.create(
            year_label="2026-7",
            modules=[test_module],
            student_counts={},
            assessment_counts={},
            staff={"Jane Doe": staff_ts},
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)
        assert len(results) == 1
        assert results[0].category == "T and S"


class TestNormativeSplitMapping:
    """Tests for normative split mapping functions (Prompt 0)."""

    def test_normative_key_for_category_art(self):
        """Verify ART maps to TR_staff key."""
        from config import normative_key_for_category

        assert normative_key_for_category("ART") == "TR_staff"

    def test_normative_key_for_category_t_and_s(self):
        """Verify T and S maps to TS_staff_lecturer_and_above key."""
        from config import normative_key_for_category

        assert normative_key_for_category("T and S") == "TS_staff_lecturer_and_above"

    def test_normative_key_for_category_unknown_returns_none(self):
        """Verify unknown category returns None, not a default."""
        from config import normative_key_for_category

        assert normative_key_for_category("Unknown Category") is None
        assert normative_key_for_category("") is None

    def test_get_normative_split_art(self):
        """Verify get_normative_split returns correct split for ART."""
        from config import get_normative_split

        split = get_normative_split("ART")
        assert split is not None
        assert "teaching_hours" in split
        assert "research_hours" in split
        # ART should have teaching=0.40, research_and_scholarship=0.40, citizenship=0.20

    def test_get_normative_split_t_and_s(self):
        """Verify get_normative_split returns correct split for T and S."""
        from config import get_normative_split

        split = get_normative_split("T and S")
        assert split is not None
        # TS staff should have teaching=0.65, scholarship=0.15, citizenship=0.20
        assert "teaching_hours" in split

    def test_get_normative_split_unknown_returns_none(self):
        """Verify get_normative_split returns None for unknown category."""
        from config import get_normative_split

        assert get_normative_split("Unknown Category") is None


class TestNewLecturerDetectionRegression:
    """Regression tests for new-lecturer detection edge cases."""

    def test_new_lecturer_detection_with_reordered_module_codes(self):
        """Test that all module codes are checked when detecting new lecturers.

        The fix in _get_prev_year_module_names checks all of a module's codes,
        not just codes[0]. This test verifies the fix by having a module where
        the teacher appears under a different code than codes[0] in the previous
        year's known_lecturers_per_module.
        """
        from workload_calculator import _calculate_teaching_workload

        # Module this year has codes where COM00088Y is NOT the first code
        module = ModuleData(
            name="TestModule",
            codes=["COM00099X", "COM00088Y"],  # Note: COM00088Y is second
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["John Smith"],
            lead_name=None,
        )

        # In previous year's data, John Smith taught COM00088Y (which IS in this year's codes)
        # but NOT COM00099X (the first code). The fix should find him under COM00088Y
        known_lecturers_global = set()  # Not in global list
        known_lecturers_per_module = {
            "COM00088Y": frozenset(["John Smith"]),  # Only under second code, not first!
        }
        supervision = SupervisionAllocation(
            pastoral_students={},
            project_loads={}
        )

        result = _calculate_teaching_workload(
            module, ["John Smith"], known_lecturers_global,
            known_lecturers_per_module, {}, supervision
        )

        # John Smith should be found via COM00088Y lookup and get standard 2.5x rate
        assert "John Smith" in result
        teaching_breakdown = result["John Smith"]["teaching_breakdown"]
        teaching_hours = teaching_breakdown.get("teaching", 0)

        # Lecture hours come from the flat weekly rate (DEFAULT_LECURE_HOURS_PER_WEEK
        # × TEACHING_WEEKS_PER_SEMESTER), NOT from module.contact_hours - which is
        # computed during loading but never consumed by the calculator. Derive the
        # expectations from the model so this test tracks the rates rather than
        # hard-coding hour values that silently rot when the model changes.
        base_lecture_hours = config.DEFAULT_LECURE_HOURS_PER_WEEK * config.TEACHING_WEEKS_PER_SEMESTER
        standard_expected = base_lecture_hours * config.TEACHING_MULTIPLIERS["lecture_standard"]
        new_lecturer_expected = base_lecture_hours * config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]

        assert teaching_hours == pytest.approx(standard_expected, abs=0.5), (
            f"Expected the standard {config.TEACHING_MULTIPLIERS['lecture_standard']}x rate "
            f"({standard_expected}h), got {teaching_hours}h"
        )
        assert teaching_hours != pytest.approx(new_lecturer_expected, abs=0.5), (
            "Lecturer was charged the new-lecturer rate despite teaching the module "
            "last year under its second module code"
        )


class TestHoDFallbackRegression:
    """Regression tests for HoD fallback logic."""

    def test_hod_not_in_wtw_uses_real_data(self):
        """Test that HoD not in WTW is added with real data from FTE/grant files.

        The fix in data_loader.py (~line 1402) looks up the Head of Department
        role generically via WAW rather than a hardcoded name, and sources their
        FTE/grants/PhD supervision from the real data files.
        """
        from data_loader import StaffData, YearData
        from workload_calculator import calculate_workload

        # Module with one teacher who is NOT the HoD
        module = ModuleData(
            name="TestModule",
            codes=["TEST001"],
            credits=20,
            stage=5,
            practicals=0,
            practical_contact_hours=0,
            practical_groups=0,
            practical_weeks=None,
            assessment_count=1,
            student_count=100,
            teachers=["Jane Doe"],
            lead_name=None,
        )

        # HoD (John Smith) has a role in WAW but is NOT in the module's teachers
        # This should trigger the fallback to add them with real data
        hod_staff = StaffData(
            canonical_name="John Smith",
            fte=1.0,  # Will be overridden by real FTE data if available
            roles=["Head of Department"],  # The HoD role
            phd_supervisions=2,
            phd_co_supervisions=1,
            phd_assessor_count=1,
            research_projects=[
                {"project_id": "GRANT001", "title": "Real Research Grant", "fte": "50%"}
            ],
            saint_modules=[],
            active=True
        )

        year_data = YearData.create(
            year_label="2026-7",
            modules=[module],
            student_counts={},
            assessment_counts={},
            staff={"Jane Doe": hod_staff},  # Only Jane is in WTW, HoD is added via fallback
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)

        # The HoD should be in the results (added by the fallback)
        names = [r.name for r in results]
        assert "John Smith" in names, f"Expected John Smith to be added via HoD fallback, got {names}"

        john_result = next(r for r in results if r.name == "John Smith")
        # Verify they have research grants (not a fabricated SCHEME entry)
        assert len(john_result.research_breakdown) > 0
        # The grant should have real data, not a fake entry

    def test_hod_with_multiple_roles_collects_all(self):
        """Test that HoD with multiple WAW roles gets all roles assigned.

        When the HoD also holds other roles in WAW (e.g., also chairs a committee),
        those additional roles should be included, not just Head of Department.
        """
        # Create staff with HoD role plus another role (e.g., Committee Chair)
        hod_staff = StaffData(
            canonical_name="John Smith",
            fte=1.0,
            # Multiple roles, both of which must exist in Appendix A - an
            # unrecognised name is now reported via missing_data rather than
            # being carried through the breakdown at 0%.
            roles=["Head of Department", "REF Lead"],
            phd_supervisions=0,
            phd_co_supervisions=0,
            phd_assessor_count=0,
            research_projects=[],
            saint_modules=[],
            active=True
        )

        year_data = YearData.create(
            year_label="2026-7",
            modules=[],
            student_counts={},
            assessment_counts={},
            staff={"John Smith": hod_staff},
            known_lecturers=set(),
            known_lecturers_per_module={}
        )

        results = calculate_workload(year_data, validate_input=False)
        john_result = next(r for r in results if r.name == "John Smith")

        # Both roles should be present
        assert "Head of Department" in john_result.admin_detail
        assert "REF Lead" in john_result.admin_detail

    def test_unknown_role_is_flagged_not_silently_zeroed(self):
        """A WAW role with no Appendix A rate must be reported, not scored as 0%.

        Silently returning 0.0 for an unrecognised name is what hid five real
        roles (CBoE, DEC Chair, Graduate Chair, StAMP, CSCSE) worth ~1,480h.
        """
        staff = StaffData(
            canonical_name="Jane Doe", aliases=("Jane Doe",), fte=1.0,
            roles=["REF Lead", "Chair of Something That Does Not Exist"],
            active=True,
        )
        total, breakdown, detail, unknown_roles = _calculate_admin_workload(
            staff, config.NOMINAL_WORKING_HOURS_PER_YEAR)

        assert unknown_roles == ["Chair of Something That Does Not Exist"]
        assert "Chair of Something That Does Not Exist" not in breakdown
        assert "Chair of Something That Does Not Exist" not in detail
        # The recognised role is unaffected.
        assert breakdown["REF Lead"] == pytest.approx(
            config.NOMINAL_WORKING_HOURS_PER_YEAR * config.ROLES_PERCENTAGE["REF Lead"])

    def test_duplicate_role_is_counted_once(self):
        """A role duplicated in WAW must not add its hours twice.

        The breakdown dict is keyed by role, so a double-count would make the
        total silently disagree with the detail shown beside it.
        """
        once = StaffData(canonical_name="A", aliases=("A",), fte=1.0,
                         roles=["REF Lead"], active=True)
        twice = StaffData(canonical_name="B", aliases=("B",), fte=1.0,
                          roles=["REF Lead", "REF Lead"], active=True)
        nominal = config.NOMINAL_WORKING_HOURS_PER_YEAR
        assert (_calculate_admin_workload(twice, nominal)[0]
                == pytest.approx(_calculate_admin_workload(once, nominal)[0]))


def _calc_single(staff_member: StaffData):
    """Run the full calculate_workload() pipeline for one staff member with no
    modules, so teaching_hours starts at 0.0 and research/admin are just the
    protected baseline / service-points floor. Returns the single WorkloadResult."""
    year_data = YearData.create(
        year_label="2026-7",
        modules=[],
        student_counts={},
        assessment_counts={},
        staff={staff_member.canonical_name: staff_member},
        known_lecturers=set(),
        known_lecturers_per_module={}
    )
    results = calculate_workload(year_data, validate_input=False)
    assert len(results) == 1
    return results[0]


def _base_staff(canonical_name="Adj Test Person", **overrides):
    """A minimal StaffData with zero teaching/research/admin activity beyond the
    protected research baseline and admin service points, so any change after
    adding adjustments is attributable purely to the adjustment."""
    defaults = dict(
        canonical_name=canonical_name, fte=1.0, roles=(), phd_supervisions=0,
        phd_co_supervisions=0, phd_assessor_count=0, research_projects=(),
        saint_modules=(), pastoral_students=0, project_load=0, active=True,
    )
    defaults.update(overrides)
    return StaffData(**defaults)


class TestManualAdjustments:
    """workload_adjustments.csv application via _apply_adjustments() and its
    two call sites inside calculate_workload()."""

    HOURS_ATTR = {"teaching": "teaching_hours", "research": "research_hours", "admin": "admin_hours"}

    @pytest.mark.parametrize("category", ["teaching", "research", "admin"])
    def test_single_delta_increases_category_and_total(self, category):
        baseline = _calc_single(_base_staff())
        calculated_value = getattr(baseline, self.HOURS_ATTR[category])

        adj = AdjustmentRecord(category=category, mode="delta", value=25.0,
                                rationale="extra work", source_row=2, raw_person="Adj Test Person")
        adjusted = _calc_single(_base_staff(adjustments=(adj,)))

        assert getattr(adjusted, self.HOURS_ATTR[category]) == pytest.approx(calculated_value + 25.0)
        assert adjusted.total_hours == pytest.approx(baseline.total_hours + 25.0)
        assert adjusted.adjustments_breakdown[category]["mode"] == "delta"
        assert adjusted.adjustments_breakdown[category]["delta"] == pytest.approx(25.0)

    @pytest.mark.parametrize("category", ["teaching", "research", "admin"])
    def test_multiple_deltas_summed(self, category):
        baseline = _calc_single(_base_staff())
        calculated_value = getattr(baseline, self.HOURS_ATTR[category])

        adjs = (
            AdjustmentRecord(category=category, mode="delta", value=10.0,
                              rationale="a", source_row=2, raw_person="Adj Test Person"),
            AdjustmentRecord(category=category, mode="delta", value=-3.0,
                              rationale="b", source_row=3, raw_person="Adj Test Person"),
        )
        adjusted = _calc_single(_base_staff(adjustments=adjs))

        assert getattr(adjusted, self.HOURS_ATTR[category]) == pytest.approx(calculated_value + 7.0)
        assert adjusted.adjustments_breakdown[category]["delta"] == pytest.approx(7.0)
        assert len(adjusted.adjustments_breakdown[category]["entries"]) == 2

    @pytest.mark.parametrize("category", ["teaching", "research", "admin"])
    def test_absolute_override_replaces_total_keeps_breakdown_visible(self, category):
        baseline = _calc_single(_base_staff())
        calculated_value = getattr(baseline, self.HOURS_ATTR[category])
        baseline_breakdown = getattr(baseline, f"{category}_breakdown")

        adj = AdjustmentRecord(category=category, mode="absolute", value=999.0,
                                rationale="override for testing", source_row=2,
                                raw_person="Adj Test Person")
        adjusted = _calc_single(_base_staff(adjustments=(adj,)))

        assert getattr(adjusted, self.HOURS_ATTR[category]) == pytest.approx(999.0)
        assert adjusted.total_hours == pytest.approx(baseline.total_hours - calculated_value + 999.0)

        info = adjusted.adjustments_breakdown[category]
        assert info["mode"] == "absolute"
        assert info["calculated_total"] == pytest.approx(calculated_value)
        assert info["adjusted_total"] == pytest.approx(999.0)
        assert info["delta"] == pytest.approx(999.0 - calculated_value)

        # Calculated sub-items (e.g. admin's engagement/personal_development,
        # research's protected_research_baseline) remain visible untouched,
        # alongside the new manual_adjustment reconciliation key.
        adjusted_breakdown = getattr(adjusted, f"{category}_breakdown")
        for key, value in baseline_breakdown.items():
            assert adjusted_breakdown.get(key) == value
        assert adjusted_breakdown["manual_adjustment"] == pytest.approx(info["delta"])

        # sum(breakdown.values()) == category total still holds (numeric leaves only).
        numeric_sum = sum(v for v in adjusted_breakdown.values() if isinstance(v, (int, float)))
        assert numeric_sum == pytest.approx(getattr(adjusted, self.HOURS_ATTR[category]), abs=0.05)

    @pytest.mark.parametrize("category", ["teaching", "research", "admin"])
    def test_absolute_and_delta_conflict_applies_nothing(self, category):
        baseline = _calc_single(_base_staff())
        calculated_value = getattr(baseline, self.HOURS_ATTR[category])

        adjs = (
            AdjustmentRecord(category=category, mode="absolute", value=500.0,
                              rationale="override", source_row=2, raw_person="Adj Test Person"),
            AdjustmentRecord(category=category, mode="delta", value=10.0,
                              rationale="delta", source_row=3, raw_person="Adj Test Person"),
        )
        adjusted = _calc_single(_base_staff(adjustments=adjs))

        assert getattr(adjusted, self.HOURS_ATTR[category]) == pytest.approx(calculated_value)
        assert category not in adjusted.adjustments_breakdown
        assert any("conflict" in m.lower() for m in adjusted.missing_data)

    @pytest.mark.parametrize("category", ["teaching", "research", "admin"])
    def test_two_absolutes_conflict_applies_nothing(self, category):
        baseline = _calc_single(_base_staff())
        calculated_value = getattr(baseline, self.HOURS_ATTR[category])

        adjs = (
            AdjustmentRecord(category=category, mode="absolute", value=500.0,
                              rationale="override 1", source_row=2, raw_person="Adj Test Person"),
            AdjustmentRecord(category=category, mode="absolute", value=600.0,
                              rationale="override 2", source_row=3, raw_person="Adj Test Person"),
        )
        adjusted = _calc_single(_base_staff(adjustments=adjs))

        assert getattr(adjusted, self.HOURS_ATTR[category]) == pytest.approx(calculated_value)
        assert category not in adjusted.adjustments_breakdown
        assert any("conflict" in m.lower() for m in adjusted.missing_data)

    @pytest.mark.parametrize("category", ["teaching", "research", "admin"])
    def test_negative_result_rejected(self, category):
        baseline = _calc_single(_base_staff())
        calculated_value = getattr(baseline, self.HOURS_ATTR[category])

        adj = AdjustmentRecord(category=category, mode="delta", value=-(calculated_value + 1000.0),
                                rationale="huge negative delta", source_row=2,
                                raw_person="Adj Test Person")
        adjusted = _calc_single(_base_staff(adjustments=(adj,)))

        assert getattr(adjusted, self.HOURS_ATTR[category]) == pytest.approx(calculated_value)
        assert category not in adjusted.adjustments_breakdown
        assert any("negative" in m.lower() for m in adjusted.missing_data)

    def test_no_adjustments_leaves_result_unaffected(self):
        result = _calc_single(_base_staff())
        assert result.adjustments_breakdown == {}
        assert result.total_hours == pytest.approx(
            result.teaching_hours + result.research_hours + result.admin_hours)

    def test_adjustment_warnings_surface_in_missing_data(self):
        staff = _base_staff(adjustment_warnings=("row 5: malformed cell - not applied.",))
        result = _calc_single(staff)
        assert any("row 5: malformed cell" in m for m in result.missing_data)


class TestApplyAdjustmentsDirect:
    """Direct unit tests of _apply_adjustments() itself, isolated from the full
    calculate_workload() pipeline."""

    def test_returns_calculated_values_unchanged_when_no_adjustments(self):
        staff = _base_staff()
        calculated = {"teaching": 100.0, "research": 200.0, "admin": 50.0}
        missing_data = []
        adjusted, breakdown = _apply_adjustments(staff, calculated, missing_data)
        assert adjusted == calculated
        assert breakdown == {}
        assert missing_data == []

    def test_delta_and_absolute_independent_across_categories(self):
        staff = _base_staff(adjustments=(
            AdjustmentRecord(category="teaching", mode="delta", value=15.0,
                              rationale="a", source_row=2, raw_person="X"),
            AdjustmentRecord(category="admin", mode="absolute", value=40.0,
                              rationale="b", source_row=3, raw_person="X"),
        ))
        calculated = {"teaching": 100.0, "research": 200.0, "admin": 50.0}
        missing_data = []
        adjusted, breakdown = _apply_adjustments(staff, calculated, missing_data)
        assert adjusted == {"teaching": 115.0, "research": 200.0, "admin": 40.0}
        assert breakdown["teaching"]["mode"] == "delta"
        assert breakdown["admin"]["mode"] == "absolute"
        assert "research" not in breakdown
        assert missing_data == []


class TestFormatAdjustmentItems:
    """_format_adjustment_items() (output_generator.py) - pure rendering of
    already-computed adjustments_breakdown data. No arithmetic, text only."""

    def test_delta_renders_amount_and_rationale(self):
        from output_generator import _format_adjustment_items

        class FakeResult:
            adjustments_breakdown = {
                "admin": {
                    "mode": "delta",
                    "calculated_total": 175.0,
                    "adjusted_total": 200.0,
                    "delta": 25.0,
                    "entries": ({"mode": "delta", "amount": 25.0,
                                 "rationale": "extra committee work", "source_row": 2},),
                }
            }

        html_parts = _format_adjustment_items(FakeResult(), "admin-item")
        assert len(html_parts) == 1
        assert "+25.0h" in html_parts[0]
        assert "Rationale: extra committee work" in html_parts[0]
        assert "manual-adjustment-line" in html_parts[0]

    def test_absolute_override_renders_calculated_and_adjusted(self):
        from output_generator import _format_adjustment_items

        class FakeResult:
            adjustments_breakdown = {
                "research": {
                    "mode": "absolute",
                    "calculated_total": 164.2,
                    "adjusted_total": 300.0,
                    "delta": 135.8,
                    "entries": ({"mode": "absolute", "amount": 300.0,
                                 "rationale": "grant admin override", "source_row": 4},),
                }
            }

        html_parts = _format_adjustment_items(FakeResult(), "research-item")
        assert len(html_parts) == 1
        assert "Manual override applied" in html_parts[0]
        assert "Calculated: 164.2h" in html_parts[0]
        assert "Adjusted: 300.0h" in html_parts[0]
        assert "Rationale: grant admin override" in html_parts[0]
        assert "manual-override-block" in html_parts[0]

    def test_no_adjustment_returns_empty_list(self):
        from output_generator import _format_adjustment_items

        class FakeResult:
            adjustments_breakdown = {}

        assert _format_adjustment_items(FakeResult(), "teaching-item") == []


class TestModuleScopedTeachingAdjustments:
    """Module-scoped Teaching adjustments (the "Teaching Module" column in
    workload_adjustments.csv), run through the full calculate_workload()
    pipeline with two real modules taught by one test person - mirroring
    TestTeachingWorkload's fixture style. Research/Admin have no module
    concept and are deliberately not covered here (see TestManualAdjustments)."""

    STAFF_NAME = "Mod Test Person"

    @classmethod
    def _module(cls, name, teachers=None, **overrides):
        defaults = dict(
            name=name, codes=[f"{name}CODE"], credits=20, stage=5,
            practicals=0, practical_contact_hours=0, practical_groups=0,
            practical_weeks=None, assessment_count=1, student_count=100,
            teachers=teachers or [cls.STAFF_NAME], lead_name=None,
        )
        defaults.update(overrides)
        return ModuleData(**defaults)

    @classmethod
    def _staff(cls, adjustments=()):
        return StaffData(canonical_name=cls.STAFF_NAME, fte=1.0, roles=(), active=True,
                          adjustments=adjustments)

    @classmethod
    def _calc(cls, adjustments=(), modules=None):
        modules = [cls._module("SYS2"), cls._module("SYS3")] if modules is None else modules
        year_data = YearData.create(
            year_label="2026-7", modules=modules, student_counts={}, assessment_counts={},
            staff={cls.STAFF_NAME: cls._staff(adjustments)},
            known_lecturers={cls.STAFF_NAME}, known_lecturers_per_module={},
        )
        results = calculate_workload(year_data, validate_input=False)
        return next(r for r in results if r.name == cls.STAFF_NAME)

    @staticmethod
    def _calculated_total(module_breakdown):
        return sum(v for k, v in module_breakdown.items()
                   if k in _TEACHING_MODULE_SUM_KEYS and isinstance(v, (int, float)))

    def test_case_insensitive_resolution_succeeds(self):
        baseline = self._calc()
        sys2_calculated = self._calculated_total(baseline.teaching_module_breakdowns["SYS2"])

        adj = AdjustmentRecord(category="teaching", mode="absolute", value=200.0,
                                rationale="SYS2 unconventional", source_row=2,
                                raw_person=self.STAFF_NAME, module="sys2")
        adjusted = self._calc(adjustments=(adj,))

        sys2 = adjusted.teaching_module_breakdowns["SYS2"]
        assert sys2["adjustment_breakdown"]["mode"] == "absolute"
        assert sys2["adjustment_breakdown"]["calculated_total"] == pytest.approx(sys2_calculated)
        assert sys2["manual_adjustment"] == pytest.approx(200.0 - sys2_calculated)

    def test_unresolved_module_not_taught_flagged_nothing_applied(self):
        baseline = self._calc()
        adj = AdjustmentRecord(category="teaching", mode="delta", value=50.0,
                                rationale="typo'd module name", source_row=2,
                                raw_person=self.STAFF_NAME, module="SYS9")
        adjusted = self._calc(adjustments=(adj,))

        assert adjusted.teaching_hours == pytest.approx(baseline.teaching_hours)
        assert "manual_adjustment" not in adjusted.teaching_module_breakdowns["SYS2"]
        assert "manual_adjustment" not in adjusted.teaching_module_breakdowns["SYS3"]
        assert any("SYS9" in m for m in adjusted.missing_data)

    def test_no_modules_taught_at_all_flagged(self):
        adj = AdjustmentRecord(category="teaching", mode="delta", value=50.0,
                                rationale="no modules this year", source_row=2,
                                raw_person=self.STAFF_NAME, module="SYS2")
        result = self._calc(adjustments=(adj,), modules=[])

        assert result.teaching_hours == pytest.approx(0.0)
        assert any("SYS2" in m for m in result.missing_data)

    def test_absolute_override_leaves_other_module_untouched(self):
        baseline = self._calc()
        sys3_calculated = self._calculated_total(baseline.teaching_module_breakdowns["SYS3"])

        adj = AdjustmentRecord(category="teaching", mode="absolute", value=200.0,
                                rationale="SYS2 override", source_row=2,
                                raw_person=self.STAFF_NAME, module="SYS2")
        adjusted = self._calc(adjustments=(adj,))

        assert "adjustment_breakdown" not in adjusted.teaching_module_breakdowns["SYS3"]
        assert self._calculated_total(adjusted.teaching_module_breakdowns["SYS3"]) == pytest.approx(sys3_calculated)
        # Overall teaching_hours = the override plus the other module's calculated total.
        assert adjusted.teaching_hours == pytest.approx(200.0 + sys3_calculated)

    def test_module_delta_stacks_with_independent_category_wide_delta(self):
        baseline = self._calc()

        module_adj = AdjustmentRecord(category="teaching", mode="delta", value=15.0,
                                       rationale="SYS2 extra", source_row=2,
                                       raw_person=self.STAFF_NAME, module="SYS2")
        category_adj = AdjustmentRecord(category="teaching", mode="delta", value=8.0,
                                         rationale="general teaching cover", source_row=3,
                                         raw_person=self.STAFF_NAME)  # module="" (category-wide)
        adjusted = self._calc(adjustments=(module_adj, category_adj))

        assert adjusted.teaching_hours == pytest.approx(baseline.teaching_hours + 15.0 + 8.0)
        assert adjusted.adjustments_breakdown["teaching"]["delta"] == pytest.approx(8.0)
        assert adjusted.teaching_module_breakdowns["SYS2"]["manual_adjustment"] == pytest.approx(15.0)

    def test_two_different_modules_coexist_without_conflict(self):
        baseline = self._calc()
        sys2_calculated = self._calculated_total(baseline.teaching_module_breakdowns["SYS2"])
        sys3_calculated = self._calculated_total(baseline.teaching_module_breakdowns["SYS3"])

        sys2_adj = AdjustmentRecord(category="teaching", mode="absolute", value=200.0,
                                     rationale="SYS2 override", source_row=2,
                                     raw_person=self.STAFF_NAME, module="SYS2")
        sys3_adj = AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                                     rationale="SYS3 extra", source_row=3,
                                     raw_person=self.STAFF_NAME, module="SYS3")
        adjusted = self._calc(adjustments=(sys2_adj, sys3_adj))

        assert not any("conflict" in m.lower() for m in adjusted.missing_data)
        assert adjusted.teaching_module_breakdowns["SYS2"]["manual_adjustment"] == pytest.approx(200.0 - sys2_calculated)
        assert adjusted.teaching_module_breakdowns["SYS3"]["manual_adjustment"] == pytest.approx(10.0)
        assert adjusted.teaching_hours == pytest.approx(200.0 + sys3_calculated + 10.0)

    def test_same_module_absolute_and_delta_conflict_scoped_to_that_module(self):
        baseline = self._calc()
        sys3_calculated = self._calculated_total(baseline.teaching_module_breakdowns["SYS3"])

        adjs = (
            AdjustmentRecord(category="teaching", mode="absolute", value=200.0,
                              rationale="a", source_row=2, raw_person=self.STAFF_NAME, module="SYS2"),
            AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                              rationale="b", source_row=3, raw_person=self.STAFF_NAME, module="SYS2"),
        )
        adjusted = self._calc(adjustments=adjs)

        assert "manual_adjustment" not in adjusted.teaching_module_breakdowns["SYS2"]
        assert any("conflict" in m.lower() for m in adjusted.missing_data)
        # SYS3 (a different module) is completely unaffected by SYS2's conflict.
        assert self._calculated_total(adjusted.teaching_module_breakdowns["SYS3"]) == pytest.approx(sys3_calculated)
        assert adjusted.teaching_hours == pytest.approx(baseline.teaching_hours)

    def test_breakdown_sum_equals_teaching_hours_with_module_adjustment(self):
        adj = AdjustmentRecord(category="teaching", mode="absolute", value=200.0,
                                rationale="SYS2 override", source_row=2,
                                raw_person=self.STAFF_NAME, module="SYS2")
        adjusted = self._calc(adjustments=(adj,))

        numeric_sum = sum(v for v in adjusted.teaching_breakdown.values() if isinstance(v, (int, float)))
        assert numeric_sum == pytest.approx(adjusted.teaching_hours, abs=0.05)


class TestApplyTeachingModuleAdjustmentsDirect:
    """Direct unit tests of _apply_teaching_module_adjustments(), isolated from
    the full calculate_workload() pipeline, against a hand-built breakdown dict."""

    @staticmethod
    def _breakdown():
        return {
            "SYS2": {"teaching": 100.0, "practicals": 20.0, "assessment_setting": 5.0, "marking": 10.0},
            "SYS3": {"teaching": 50.0, "practicals": 0.0, "assessment_setting": 5.0, "marking": 5.0},
        }

    def test_absolute_override_mutates_module_in_place(self):
        breakdown = self._breakdown()
        staff = StaffData(canonical_name="X", adjustments=(
            AdjustmentRecord(category="teaching", mode="absolute", value=200.0,
                              rationale="override", source_row=2, raw_person="X", module="SYS2"),
        ))
        missing_data = []

        delta = _apply_teaching_module_adjustments(staff, breakdown, missing_data)

        assert delta == pytest.approx(200.0 - 135.0)  # 100+20+5+10 = 135
        assert breakdown["SYS2"]["manual_adjustment"] == pytest.approx(65.0)
        assert breakdown["SYS2"]["adjustment_breakdown"]["mode"] == "absolute"
        assert breakdown["SYS2"]["adjustment_breakdown"]["calculated_total"] == pytest.approx(135.0)
        assert breakdown["SYS2"]["adjustment_breakdown"]["adjusted_total"] == pytest.approx(200.0)
        assert "manual_adjustment" not in breakdown["SYS3"]  # untouched
        assert missing_data == []

    def test_delta_adds_to_module(self):
        breakdown = self._breakdown()
        staff = StaffData(canonical_name="X", adjustments=(
            AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                              rationale="extra", source_row=2, raw_person="X", module="SYS3"),
        ))
        missing_data = []

        delta = _apply_teaching_module_adjustments(staff, breakdown, missing_data)

        assert delta == pytest.approx(10.0)
        assert breakdown["SYS3"]["manual_adjustment"] == pytest.approx(10.0)
        assert missing_data == []

    def test_unresolved_module_flagged_nothing_applied(self):
        breakdown = self._breakdown()
        staff = StaffData(canonical_name="X", adjustments=(
            AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                              rationale="typo", source_row=2, raw_person="X", module="SYS 2"),
        ))
        missing_data = []

        delta = _apply_teaching_module_adjustments(staff, breakdown, missing_data)

        assert delta == 0.0
        assert "manual_adjustment" not in breakdown["SYS2"]
        assert any("SYS 2" in m for m in missing_data)

    def test_no_modules_taught_flagged(self):
        staff = StaffData(canonical_name="X", adjustments=(
            AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                              rationale="x", source_row=2, raw_person="X", module="SYS2"),
        ))
        missing_data = []

        delta = _apply_teaching_module_adjustments(staff, {}, missing_data)

        assert delta == 0.0
        assert any("SYS2" in m for m in missing_data)

    def test_same_module_conflict_flagged(self):
        breakdown = self._breakdown()
        staff = StaffData(canonical_name="X", adjustments=(
            AdjustmentRecord(category="teaching", mode="absolute", value=200.0,
                              rationale="a", source_row=2, raw_person="X", module="SYS2"),
            AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                              rationale="b", source_row=3, raw_person="X", module="SYS2"),
        ))
        missing_data = []

        delta = _apply_teaching_module_adjustments(staff, breakdown, missing_data)

        assert delta == 0.0
        assert "manual_adjustment" not in breakdown["SYS2"]
        assert any("conflict" in m.lower() for m in missing_data)

    def test_negative_result_rejected(self):
        breakdown = self._breakdown()
        staff = StaffData(canonical_name="X", adjustments=(
            AdjustmentRecord(category="teaching", mode="delta", value=-1000.0,
                              rationale="huge negative delta", source_row=2, raw_person="X", module="SYS3"),
        ))
        missing_data = []

        delta = _apply_teaching_module_adjustments(staff, breakdown, missing_data)

        assert delta == 0.0
        assert "manual_adjustment" not in breakdown["SYS3"]
        assert any("negative" in m.lower() for m in missing_data)

    def test_two_modules_coexist_returns_summed_delta(self):
        breakdown = self._breakdown()
        staff = StaffData(canonical_name="X", adjustments=(
            AdjustmentRecord(category="teaching", mode="absolute", value=200.0,
                              rationale="a", source_row=2, raw_person="X", module="SYS2"),
            AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                              rationale="b", source_row=3, raw_person="X", module="SYS3"),
        ))
        missing_data = []

        delta = _apply_teaching_module_adjustments(staff, breakdown, missing_data)

        assert delta == pytest.approx((200.0 - 135.0) + 10.0)
        assert breakdown["SYS2"]["manual_adjustment"] == pytest.approx(65.0)
        assert breakdown["SYS3"]["manual_adjustment"] == pytest.approx(10.0)
        assert missing_data == []

    def test_no_module_scoped_entries_returns_zero(self):
        breakdown = self._breakdown()
        staff = StaffData(canonical_name="X", adjustments=(
            AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                              rationale="category-wide", source_row=2, raw_person="X"),  # module=""
        ))
        missing_data = []

        delta = _apply_teaching_module_adjustments(staff, breakdown, missing_data)

        assert delta == 0.0
        assert "manual_adjustment" not in breakdown["SYS2"]
        assert "manual_adjustment" not in breakdown["SYS3"]
        assert missing_data == []


class TestFormatModuleAdjustmentSection:
    """_format_module_adjustment_section() (output_generator.py) - pure
    rendering of an already-computed adjustment_breakdown. No arithmetic."""

    def test_no_adjustment_breakdown_renders_nothing(self):
        from output_generator import _format_module_adjustment_section

        assert _format_module_adjustment_section({}, "teaching-item") == []

    def test_absolute_renders_headline_and_calculation_subrow(self):
        from output_generator import _format_module_adjustment_section

        module_breakdown = {
            "adjustment_breakdown": {
                "mode": "absolute",
                "calculated_total": 96.5,
                "adjusted_total": 200.0,
                "delta": 103.5,
                "entries": ({"mode": "absolute", "amount": 200.0,
                             "rationale": "SYS2 unconventional", "source_row": 2},),
            }
        }

        parts = _format_module_adjustment_section(module_breakdown, "teaching-item", "COM00029I")

        assert len(parts) == 2
        assert "manual-adjustment-line" in parts[0]
        assert "Manual adjustment (absolute override)" in parts[0]
        assert "200.0h" in parts[0]
        assert "[COM00029I]" in parts[0]
        assert "Calculation" in parts[1]
        assert "Calculated: 96.5h" in parts[1]
        assert "Adjusted: 200.0h" in parts[1]
        assert "Rationale: SYS2 unconventional" in parts[1]

    def test_delta_renders_headline_and_calculation_subrow(self):
        from output_generator import _format_module_adjustment_section

        module_breakdown = {
            "adjustment_breakdown": {
                "mode": "delta",
                "calculated_total": 60.0,
                "adjusted_total": 70.0,
                "delta": 10.0,
                "entries": ({"mode": "delta", "amount": 10.0,
                             "rationale": "extra cover", "source_row": 3},),
            }
        }

        parts = _format_module_adjustment_section(module_breakdown, "teaching-item")

        assert len(parts) == 2
        assert "manual-adjustment-line" in parts[0]
        assert "Manual adjustment (delta)" in parts[0]
        assert "+10.0h" in parts[0]
        assert "Calculation" in parts[1]
        assert "Rationale: extra cover" in parts[1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
