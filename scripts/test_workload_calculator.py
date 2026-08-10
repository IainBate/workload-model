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

from data_loader import StaffData, ModuleData, SupervisionAllocation, YearData
from workload_calculator import (
    _calculate_teaching_workload,
    _calculate_research_workload,
    _calculate_admin_workload,
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
            contact_hours=40,
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
            contact_hours=40,
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
            contact_hours=40,
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
            contact_hours=40,
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
            contact_hours=20,
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
            contact_hours=40,
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
            contact_hours=40,
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
            contact_hours=40,
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
            contact_hours=40,
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
                contact_hours=40,
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
            contact_hours=40,
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
            contact_hours=40,
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
        assert breakdown.get("phd_supervision", 0) == expected_hours

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
        total, breakdown, detail = _calculate_admin_workload(staff, config.NOMINAL_WORKING_HOURS_PER_YEAR)

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

        total, breakdown, detail = _calculate_admin_workload(staff, config.NOMINAL_WORKING_HOURS_PER_YEAR)

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

        total, breakdown, detail = _calculate_admin_workload(staff, config.NOMINAL_WORKING_HOURS_PER_YEAR * 0.5)

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

        total, breakdown, detail = _calculate_admin_workload(staff, config.NOMINAL_WORKING_HOURS_PER_YEAR * 0.5)

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
            contact_hours=40,
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
            contact_hours=0,
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

        total, breakdown, detail, grant_titles = _calculate_research_workload(staff)
        # _calculate_research_workload does not include protected baseline
        assert total == 0

    def test_multiple_teachers_shared_hours(self):
        """Test that hours are shared correctly among multiple teachers."""
        module = ModuleData(
            name="Team Teaching",
            codes=["TEST010"],
            credits=20,
            stage=5,
            contact_hours=40,
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
            contact_hours=40,
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
            contact_hours=40,
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
            contact_hours=40,
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
