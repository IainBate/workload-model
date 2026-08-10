"""
Core workload calculation engine.
Applies the Workload Model parameters to module and staff data.

Calculates workload per staff member across three categories:
- Teaching: contact hours * multipliers, assessment setting/marking, supervision
- Research: PhD supervision, grant work, project marking
- Administration: departmental roles as % of nominal hours

Assumptions Tracking
--------------------
The calculator tracks assumptions made during calculation:
- Default student counts when actual count is unknown (default: 100)
- Default contact hours per credit (default: 1.0)
- Assessment marking type (defaults to manual if not specified)

Note: Pastoral and project supervision use explicit values from CSV data.
No defaults are applied - a value of 0 means no supervision.

Use workload_calculator.calculate_workload(year_data, track_assumptions=True)
to enable detailed assumption tracking.
"""

from typing import List, Dict
from dataclasses import dataclass
import math

import config
from data_loader import YearData, ModuleData, StaffData, WorkloadResult, SupervisionAllocation, allocate_supervision, normalize_name
from validation import (
    validate_year_data,
    run_validation_pipeline,
    ValidationResult,
    ValidationLevel
)


# --- Assumptions Data Structure ---

@dataclass(frozen=True)
class Assumption:
    """
    Records an assumption made during workload calculation.

    Args:
        category: Type of assumption (student_count, marking_type, supervision, etc.)
        description: Human-readable description of what was assumed
        staff_name: Optional staff member affected by this assumption
        module_code: Optional module affected by this assumption
        default_value: The value that was used as fallback
        actual_value: The actual value found (if different from default)
    """
    category: str
    description: str
    staff_name: str = None
    module_code: str = None
    default_value: float = None
    actual_value: float = None


# --- Constants ---

from config import TEACHING_WEEKS_PER_SEMESTER


# --- Helper Functions for Teaching Workload Calculation ---

def _calculate_lecture_hours_and_multipliers(module: ModuleData,
                                              teachers: List[str],
                                              known_lecturers_global: set,
                                              known_lecturers_per_module: Dict[str, frozenset]) -> dict:
    """Calculate lecture hours and determine multipliers per teacher.

    Returns a dict with:
        - lecture_hours: Total lecture hours for the module
        - individual_lecture_hours: Dict mapping teachers to their lecture hours
        - lecture_multipliers: Dict mapping teachers to their multiplier
        - lecturer_types: List of (teacher, type) tuples for reporting
    """
    result = {
        'lecture_hours': 0.0,
        'individual_lecture_hours': {},
        'lecture_multipliers': {},
        'lecturer_types': [],
    }

    contact_weeks = TEACHING_WEEKS_PER_SEMESTER

    # Calculate weeks of teaching (typical semester is ~22 weeks)
    contact_hours = module.contact_hours
    practicals_count = module.practicals

    if practicals_count > 0 and module.practical_contact_hours > 0:
        total_practical_duration = module.practical_contact_hours * practicals_count
        lecture_hours = max(0, contact_hours - total_practical_duration)
    else:
        lecture_hours = contact_hours
        total_practical_duration = 0.0

    result['lecture_hours'] = lecture_hours

    # Determine which teachers from last year taught THIS specific module
    module_code = module.codes[0] if module.codes else None
    known_teachers_this_module = known_lecturers_per_module.get(module_code)

    if known_teachers_this_module is None:
        known_teachers_this_module = known_lecturers_per_module.get(module.name)

    if known_teachers_this_module is not None:
        known_lecturers_for_module = known_teachers_this_module
    else:
        known_lecturers_for_module = known_lecturers_global

    # Check if this is a new content module (for 7.5x rate when teacher is also new)
    is_new_content_module = getattr(module, 'new_content', False)

    # Detect online modules by name pattern for special rates
    module_name_lower = module.name.lower()
    is_online_module = "online" in module_name_lower

    # Detect video teaching format (by name pattern or module attribute)
    module_name_lower = module.name.lower()
    is_video_module = getattr(module, 'teaching_format', '') == "video" or "video" in module_name_lower

    # Calculate lecture multiplier per-teacher based on experience and content status
    new_lecturers = []
    existing_with_new_content = []
    standard_lecturers = []

    for t in teachers:
        is_new_lecturer = t not in known_lecturers_for_module
        is_video_format = getattr(module, 'teaching_format', '') == "video" or "video" in module_name_lower

        if is_video_format:
            multiplier = config.TEACHING_MULTIPLIERS.get('video', 10.0)
            lecturer_type = "Video"
            result['lecturer_types'].append((t, "video"))
        elif is_new_lecturer and is_new_content_module:
            # New lecturer + new content gets 7.5x
            multiplier = config.TEACHING_MULTIPLIERS.get('new_lecturer_new_content', 7.5)
            lecturer_type = "New lecturer + new content"
            result['lecturer_types'].append((t, "new_lecturer_new_content"))
        elif is_new_lecturer:
            # New lecturer (not new content) gets 5x
            multiplier = config.TEACHING_MULTIPLIERS.get('new_lecturer', 5.0)
            lecturer_type = "New lecturer"
            result['lecturer_types'].append((t, "new_lecturer"))
        else:
            if is_new_content_module:
                # Existing lecturer on new content gets 5x (content dev only)
                multiplier = config.TEACHING_MULTIPLIERS.get('existing_lecturer_new_content', 5.0)
                lecturer_type = "Existing + new content"
                result['lecturer_types'].append((t, "existing_lecturer_new_content"))
            else:
                # Standard existing lecturer gets 2.5x
                multiplier = config.TEACHING_MULTIPLIERS.get('standard', 2.5)
                lecturer_type = "Standard"
                result['lecturer_types'].append((t, "standard"))

        # Calculate per-teacher lecture hours (split equally among teachers) with multiplier applied
        per_teacher_lecture_hours = lecture_hours / len(teachers) if teachers else 0.0
        per_teacher_with_multiplier = per_teacher_lecture_hours * multiplier

        result['individual_lecture_hours'][t] = per_teacher_with_multiplier
        result['lecture_multipliers'][t] = multiplier

    return result


def _calculate_practical_hours_and_breakdown(module: ModuleData, teachers: List[str]) -> dict:
    """Calculate practical session hours with repetition multipliers.

    Returns a dict with structured breakdown suitable for output display.
    """
    result = {
        'total_practical_hours': 0.0,
        'individual_practical_hours': {},
        'practicals_breakdown': None,  # Structured breakdown dict or None
        'practical_details': [],  # List of detail strings for HTML display
    }

    contact_weeks = TEACHING_WEEKS_PER_SEMESTER
    practicals_count = module.practicals

    if practicals_count > 0:
        # Get parallel groups configuration (if available)
        parallel_groups = getattr(module, 'parallel_groups', None)

        n_teachers = len(teachers) if teachers else 1

        if parallel_groups and len(parallel_groups) > 1:
            # Multiple parallel groups - each group has its own session count
            first_session_rate = config.TEACHING_PROBLEM_CLASS

            for i, group in enumerate(parallel_groups):
                group_sessions = getattr(group, 'sessions', practicals_count)

                if group_sessions > 0:
                    weekly_hrs = getattr(group, 'hours_per_week', config.TEACHING_PROBLEM_CLASS)

                    # Calculate total hours including weeks
                    first_session_total = weekly_hrs * contact_weeks  # First session per week for one teacher
                    repeat_sessions = max(0, group_sessions - 1)
                    repeat_rate = config.REPETITION_MULTIPLIER
                    repeat_session_total = repeat_sessions * weekly_hrs * repeat_rate * contact_weeks

                    # Total for this group across all teachers (first session + repeats)
                    total_group_hours = first_session_total + repeat_session_total

                    # Distribute to individual teachers (all get same rate in parallel groups)
                    per_teacher_group_hours = total_group_hours / n_teachers

                    for t in teachers:
                        if t not in result['individual_practical_hours']:
                            result['individual_practical_hours'][t] = 0.0
                        result['individual_practical_hours'][t] += per_teacher_group_hours

                    # Store structured breakdown
                    result['practicals_breakdown'] = {
                        "first_session_hours": round(weekly_hrs, 2),
                        "repeat_hours": round(repeat_session_total / contact_weeks if contact_weeks > 0 else 0, 2),
                        "week_count": group_sessions,
                        "first_session_rate": first_session_rate,
                        "repeat_rate": repeat_rate,
                        "total": round(per_teacher_group_hours, 2)
                    }

                    result['practical_details'].append(
                        f"First time delivery: {group_sessions} sessions/week @ {weekly_hrs}h each; "
                        f"- Standard lecturers: {first_session_rate}x first session (standard), {repeat_rate}x repeats"
                    )
        else:
            # No parallel groups - all teachers get same rate
            std_first_session_weekly = getattr(module, 'practical_hours_per_week', config.TEACHING_PROBLEM_CLASS)
            repeat_rate = config.REPETITION_MULTIPLIER

            # Calculate total practical hours for the semester (including weeks and repetition multiplier)
            if practicals_count > 1:
                first_session_total = std_first_session_weekly * contact_weeks
                repeat_sessions = max(0, practicals_count - 1)
                repeat_session_total = repeat_sessions * std_first_session_weekly * repeat_rate * contact_weeks
                total_practical_hours = first_session_total + repeat_session_total

                # Store structured breakdown
                result['practicals_breakdown'] = {
                    "first_session_hours": round(std_first_session_weekly, 2),
                    "repeat_hours": round(repeat_sessions * std_first_session_weekly, 2),
                    "week_count": practicals_count,
                    "first_session_rate": std_first_session_weekly,
                    "repeat_rate": repeat_rate,
                    "total": round(total_practical_hours, 2),
                }

                result['practical_details'].append(
                    f"First time delivery: {practicals_count} sessions/week @ {std_first_session_weekly}h each; "
                    f"- Standard lecturers: {std_first_session_weekly}x first session (standard), {repeat_rate}x repeats"
                )
            else:
                # Single session - no repetition
                total_practical_hours = std_first_session_weekly * contact_weeks

                result['practicals_breakdown'] = {
                    "first_session_hours": round(std_first_session_weekly, 2),
                    "repeat_hours": 0,
                    "week_count": practicals_count,
                    "first_session_rate": std_first_session_weekly,
                    "repeat_rate": repeat_rate,
                    "total": round(total_practical_hours, 2),
                }

            # Distribute to individual teachers (all get same rate)
            per_teacher_practical_hours = total_practical_hours / n_teachers
            for t in teachers:
                if t not in result['individual_practical_hours']:
                    result['individual_practical_hours'][t] = 0.0
                result['individual_practical_hours'][t] += per_teacher_practical_hours
    else:
        # No practicals - empty structured breakdown
        result['practicals_breakdown'] = {}

    # Calculate total practical hours across all teachers
    if result['individual_practical_hours']:
        result['total_practical_hours'] = sum(result['individual_practical_hours'].values())

    return result


def _calculate_assessment_setting_hours(module: ModuleData, teachers: List[str],
                                         known_lecturers_global: set,
                                         known_lecturers_per_module: Dict[str, frozenset]) -> dict:
    """Calculate assessment setting hours per teacher.

    Returns a dict with:
        - total_hours: Total assessment setting time
        - individual_hours: Dict mapping teachers to their hours
        - details: List of detail strings for HTML display
    """
    result = {
        'total_hours': 0.0,
        'individual_hours': {},
        'details': [],
    }

    assessment_count = module.assessment_count

    if assessment_count == 0:
        return result

    # Determine if this module uses automated marking (affects setting rates)
    is_automated = getattr(module, 'marking_type', 'manual') == 'automated'

    # Get the appropriate rates based on marking type and teacher role
    if is_automated:
        base_setting_cost = config.ASSESSMENT_AUTO_STANDARD * assessment_count
        new_setter_rate = config.ASSESSMENT_AUTO_NEW_SETTER
        standard_rate = config.ASSESSMENT_AUTO_STANDARD
        checking_rate = config.ASSESSMENT_AUTO_CHECKING
        new_assessment_rate = config.ASSESSMENT_AUTO_NEW_ASSESSMENT
    else:
        base_setting_cost = config.ASSESSMENT_MANUAL_STANDARD * assessment_count
        new_setter_rate = config.ASSESSMENT_MANUAL_NEW_SETTER
        standard_rate = config.ASSESSMENT_MANUAL_STANDARD
        checking_rate = config.ASSESSMENT_MANUAL_CHECKING
        new_assessment_rate = config.ASSESSMENT_MANUAL_NEW_ASSESSMENT

    module_code = module.codes[0] if module.codes else None
    known_teachers_this_module = known_lecturers_per_module.get(module_code)

    if known_teachers_this_module is None:
        known_teachers_this_module = known_lecturers_per_module.get(module.name)

    if known_teachers_this_module is not None:
        known_lecturers_for_module = known_teachers_this_module
    else:
        known_lecturers_for_module = known_lecturers_global

    setting_details_parts = []

    for t in teachers:
        is_checking_only = getattr(module, 'checking_only', False)
        is_new_assessment_module = getattr(module, 'new_assessment', False)

        if is_checking_only:
            base_hours = (checking_rate * assessment_count) / len(teachers)
            result['individual_hours'][t] = base_hours
            result['total_hours'] += base_hours

            main_paper_hours = (checking_rate * assessment_count / 2) / len(teachers)
            resit_paper_hours = (checking_rate * assessment_count / 2) / len(teachers)

            rate_type = checking_rate
        elif t not in known_lecturers_for_module:
            # New setter: standard time + additional content development time
            if is_new_assessment_module:
                base_hours = (new_assessment_rate * assessment_count) / len(teachers)
                total_hours = base_hours  # All new assessment time is content dev
            else:
                base_hours = base_setting_cost / len(teachers)
                content_dev_per_assessment = new_setter_rate - standard_rate
                additional_content_hours = (content_dev_per_assessment * assessment_count) / len(teachers)
                total_hours = base_hours + additional_content_hours

            result['individual_hours'][t] = total_hours
            result['total_hours'] += total_hours

            if is_new_assessment_module:
                main_paper_hours = (new_assessment_rate * assessment_count / 2) / len(teachers)
                resit_paper_hours = (new_assessment_rate * assessment_count / 2) / len(teachers)
                rate_type = new_assessment_rate
            else:
                main_paper_hours = (base_setting_cost / 2) / len(teachers)
                resit_paper_hours = (base_setting_cost / 2) / len(teachers)
                rate_type = standard_rate
        else:
            # Standard setter: just the base cost divided equally
            if is_new_assessment_module:
                base_hours = (new_assessment_rate * assessment_count) / len(teachers)
            else:
                base_hours = base_setting_cost / len(teachers)

            result['individual_hours'][t] = base_hours
            result['total_hours'] += base_hours

            if is_new_assessment_module:
                main_paper_hours = (new_assessment_rate * assessment_count / 2) / len(teachers)
                resit_paper_hours = (new_assessment_rate * assessment_count / 2) / len(teachers)
                rate_type = new_assessment_rate
            else:
                main_paper_hours = (base_setting_cost / 2) / len(teachers)
                resit_paper_hours = (base_setting_cost / 2) / len(teachers)
                rate_type = standard_rate

        # Build detail string
        if is_automated:
            setting_details_parts.append(
                f"{'New setter' if t not in known_lecturers_for_module else 'Standard'} "
                f"({rate_type}h/assess, auto): "
                f"{main_paper_hours:.1f}h main + {resit_paper_hours:.1f}h resit = {result['individual_hours'][t]:.1f}h"
            )
        else:
            setting_details_parts.append(
                f"{'New setter' if t not in known_lecturers_for_module else 'Standard'} "
                f"({rate_type}h/assess, manual): "
                f"{main_paper_hours:.1f}h main + {resit_paper_hours:.1f}h resit = {result['individual_hours'][t]:.1f}h"
            )

    result['details'] = setting_details_parts
    return result


def _calculate_assessment_marking_hours(module: ModuleData, teachers: List[str]) -> dict:
    """Calculate assessment marking hours per teacher.

    Returns a dict with:
        - total_hours: Total marking time
        - individual_hours: Dict mapping teachers to their hours
        - details: Detail string for HTML display
        - admin_flat: The admin flat rate used
    """
    result = {
        'total_hours': 0.0,
        'individual_hours': {},
        'details': '',
        'admin_flat': config.MARKING_MANUAL_ADMIN,  # Default
    }

    student_count = module.student_count

    if student_count == 0:
        return result

    # Determine marking type and rates
    is_automated = getattr(module, 'marking_type', 'manual') == 'automated'

    if is_automated:
        result['admin_flat'] = config.MARKING_AUTO_ADMIN
        first_mark_hrs = config.MARKING_AUTO_MSC * student_count if config.is_msc_level(getattr(module, 'stage', 1)) else config.MARKING_AUTO_UG * student_count
        resit_hrs = first_mark_hrs * 0.2  # 20% resits for automated
    else:
        result['admin_flat'] = config.MARKING_MANUAL_ADMIN
        stage = getattr(module, 'stage', 1)
        if config.is_msc_level(stage):
            first_mark_hrs = config.MARKING_MANUAL_MSC * student_count
        else:
            first_mark_hrs = config.MARKING_MANUAL_UG * student_count
        resit_hrs = first_mark_hrs * 0.2  # 20% resits for manual

    total_marking_hours = first_mark_hrs + resit_hrs

    # Split equally among teachers
    per_teacher_hours = total_marking_hours / len(teachers) if teachers else 0.0

    for t in teachers:
        result['individual_hours'][t] = per_teacher_hours
        result['total_hours'] += per_teacher_hours

    result['details'] = f"{'Automated' if is_automated else 'Manual'}: {per_teacher_hours:.1f}h total (initial + resit)"

    return result


# --- Teaching Workload ---


def _calculate_teaching_workload(module: ModuleData, teachers: List[str],
                                  known_lecturers_global: set,
                                  known_lecturers_per_module: Dict[str, frozenset],
                                  staff_data: Dict[str, StaffData],
                                  supervision: SupervisionAllocation) -> dict:
    """Calculate teaching workload for a single module, split by teacher.

    Applies multipliers based on lecturer experience (new vs. established) and
    accounts for lecture hours, practical sessions with repetition, assessment
    setting and marking, and supervision activities.

    Args:
        module: ModuleData object with contact hours, assessments, and practicals
        teachers: List of teacher names (canonical)
        known_lecturers_global: Set of lecturers from previous year (for new lecturer detection)
        known_lecturers_per_module: Dict mapping module codes to sets of previous lecturers
        staff_data: Dict mapping staff names to StaffData objects
        supervision: SupervisionAllocation with pastoral counts and project loads

    Returns:
        Dict mapping teacher names to their teaching breakdown, including:
            - hours: Total teaching workload for this module
            - detail_text: Human-readable summary of activities
            - teaching_breakdown: Structured hour allocations by category
            - supervision_details: List of supervision activity strings
    """
    if not teachers:
        return {}

    # Calculate weeks of teaching (typical semester is ~22 weeks)
    contact_weeks = TEACHING_WEEKS_PER_SEMESTER

    # --- Use helper functions for structured calculations ---

    # 1. Calculate lecture hours and multipliers per teacher
    lecture_result = _calculate_lecture_hours_and_multipliers(
        module, teachers, known_lecturers_global, known_lecturers_per_module
    )

    lecture_hours_with_mult = lecture_result['individual_lecture_hours']
    teaching_details = []
    for lecturer_type in lecture_result['lecturer_types']:
        teacher_name, ltype = lecturer_type
        # Build detail string for each teacher based on their type
        base_share = lecture_result['lecture_hours'] / len(teachers) if teachers else 0
        multiplier = lecture_result['lecture_multipliers'][teacher_name]

        if ltype == 'video':
            teaching_details.append(
                f"{teacher_name}: Video ({multiplier}x): {base_share:.1f}h base @ 2.5x"
            )
        elif ltype == 'new_lecturer_new_content':
            content_dev = base_share * (multiplier - 2.5)
            teaching_details.append(
                f"{teacher_name}: New lecturer + new content ({multiplier}x): {base_share:.1f}h base @ 2.5x + {content_dev:.1f}h content dev"
            )
        elif ltype == 'new_lecturer':
            content_dev = base_share * (multiplier - 2.5)
            teaching_details.append(
                f"{teacher_name}: New lecturer ({multiplier}x): {base_share:.1f}h base @ 2.5x + {content_dev:.1f}h content dev"
            )
        elif ltype == 'existing_lecturer_new_content':
            content_dev = base_share * (multiplier - 2.5)
            teaching_details.append(
                f"{teacher_name}: Existing lecturer + new content ({multiplier}x): {base_share:.1f}h base @ 2.5x + {content_dev:.1f}h content dev"
            )
        else:  # standard
            estimated_lectures = round(lecture_result['lecture_hours'] / 2) if lecture_result['lecture_hours'] > 0 else 0
            lectures_per_teacher = math.ceil(estimated_lectures / len(teachers)) if teachers else 0
            teaching_details.append(
                f"{teacher_name}: Standard ({multiplier}x): {estimated_lectures} two-hour lectures split between {len(teachers)} staff"
            )

    # 2. Calculate practical hours with structured breakdown
    practical_result = _calculate_practical_hours_and_breakdown(module, teachers)

    # Store individual practical hours per teacher for later use
    individual_practical_hours = practical_result['individual_practical_hours']
    practical_week_count = TEACHING_WEEKS_PER_SEMESTER if module.practicals > 0 else 0

    # Build practical details for display
    practical_details = []
    if practical_result['practical_details']:
        practical_details.extend(practical_result['practical_details'])

    # 3. Calculate assessment setting hours per teacher
    assessment_result = _calculate_assessment_setting_hours(
        module, teachers, known_lecturers_global, known_lecturers_per_module
    )

    # 4. Calculate assessment marking hours per teacher
    marking_result = _calculate_assessment_marking_hours(module, teachers)

    # --- Use helper function results directly (no re-calculation) ---

    # Extract values from helper results for use in total calculation
    practical_week_count = TEACHING_WEEKS_PER_SEMESTER if module.practicals > 0 else 0
    individual_practical_hours = practical_result.get('individual_practical_hours', {})

    assessment_hours = assessment_result.get('individual_hours', {})
    assessment_details = assessment_result.get('details', [])

    marking_hours_per_teacher = marking_result.get('total_hours', 0.0) / max(len(teachers), 1)
    admin_hours_per_teacher = (marking_result.get('admin_flat', config.MARKING_MANUAL_ADMIN) * module.assessment_count) / max(len(teachers), 1)

    # --- HW Lab and Drop-in Sessions (from module data, not helpers) ---
    hw_lab_hours = getattr(module, 'hw_lab_hours', 0.0)
    drop_in_count = getattr(module, 'drop_in_sessions', 0)

    individual_hw_lab_hours = {}
    individual_drop_in_hours = {}
    hw_lab_details = []
    drop_in_details = []

    if hw_lab_hours > 0:
        hw_multiplier = config.TEACHING_NEW_HW_LAB if is_new_content_module else config.TEACHING_MULTIPLIERS['hw_lab']
        per_teacher_hw = hw_lab_hours / len(teachers)
        for t in teachers:
            individual_hw_lab_hours[t] = per_teacher_hw
        hw_lab_details.append(f"HW lab: {hw_lab_hours:.1f}h total ({per_teacher_hw:.1f}h/teacher) @ {hw_multiplier}x")

    if drop_in_count > 0:
        per_teacher_drop_in = (drop_in_count * config.TEACHING_DROP_IN) / len(teachers)
        for t in teachers:
            individual_drop_in_hours[t] = per_teacher_drop_in
        drop_in_details.append(f"Drop-in: {drop_in_count} sessions x {config.TEACHING_DROP_IN}h = {drop_in_count * config.TEACHING_DROP_IN:.1f}h total ({per_teacher_drop_in:.1f}h/teacher)")

    # Supervision - moved outside per-module calculation since it's staff-level, not module-level
    teacher_supervision_hours = {t: 0.0 for t in teachers}
    supervision_details = []

    # Calculate per-teacher total for this module
    result = {}
    num_teachers = len(teachers)

    for teacher in teachers:
        # Get values from helper results
        teacher_lecture_hours_with_mult = lecture_hours_with_mult.get(teacher, 0.0)
        teacher_assessment_hours = assessment_hours.get(teacher, 0.0)
        teacher_hw_lab = individual_hw_lab_hours.get(teacher, 0.0)
        teacher_drop_in = individual_drop_in_hours.get(teacher, 0.0)

        # Get practical hours for this teacher (from helper result - already includes weeks)
        teacher_practical_hrs = individual_practical_hours.get(teacher, 0.0)

        # Total for this teacher from module activities
        total_teacher_hours = (
            teacher_lecture_hours_with_mult +
            teacher_practical_hrs +
            teacher_assessment_hours +
            marking_hours_per_teacher +
            admin_hours_per_teacher +
            teacher_supervision_hours.get(teacher, 0.0) +
            teacher_hw_lab +
            teacher_drop_in
        )

        # Build detail text for display using helper results
        module_detail_parts = []

        # Add lecture details (from helper result)
        if 'lecturer_types' in lecture_result:
            for lecturer_type in lecture_result['lecturer_types']:
                t, ltype = lecturer_type
                if t == teacher:
                    base_share = lecture_result['lecture_hours'] / len(teachers) if teachers else 0
                    multiplier = lecture_result['lecture_multipliers'].get(t, 2.5)
                    if ltype == 'video':
                        module_detail_parts.append(f"{t}: Video ({multiplier}x): {base_share:.1f}h base @ 2.5x")
                    elif ltype == 'new_lecturer_new_content':
                        content_dev = base_share * (multiplier - 2.5)
                        module_detail_parts.append(f"{t}: New lecturer + new content ({multiplier}x): {base_share:.1f}h base @ 2.5x + {content_dev:.1f}h content dev")
                    elif ltype == 'new_lecturer':
                        content_dev = base_share * (multiplier - 2.5)
                        module_detail_parts.append(f"{t}: New lecturer ({multiplier}x): {base_share:.1f}h base @ 2.5x + {content_dev:.1f}h content dev")
                    elif ltype == 'existing_lecturer_new_content':
                        content_dev = base_share * (multiplier - 2.5)
                        module_detail_parts.append(f"{t}: Existing lecturer + new content ({multiplier}x): {base_share:.1f}h base @ 2.5x + {content_dev:.1f}h content dev")
                    else:
                        module_detail_parts.append(f"{t}: Standard ({multiplier}x): {base_share:.1f}h/teacher @ 2.5x")

        # Add practical details (from helper result)
        if 'practical_details' in practical_result and practical_result['practical_details']:
            module_detail_parts.extend(practical_result['practical_details'])

        # Add HW lab details
        if hw_lab_details:
            module_detail_parts.extend(hw_lab_details)

        # Add drop-in details
        if drop_in_details:
            module_detail_parts.extend(drop_in_details)

        # Add assessment details (from helper result)
        if assessment_details:
            module_detail_parts.extend(assessment_details)

        # Add marking details (from helper result)
        if 'marking_details' in marking_result and marking_result['marking_details']:
            module_detail_parts.extend(marking_result['marking_details'])

        # Build structured practicals breakdown from helper result
        teacher_practicals_structured = {}
        if 'practicals_breakdown' in practical_result:
            teacher_practicals_structured = practical_result['practicals_breakdown'].copy()
            # Scale by weeks for the total
            if practical_week_count > 0 and 'total' in teacher_practicals_structured:
                teacher_practicals_structured['total'] = round(teacher_practicals_structured.get('total', 0) * practical_week_count, 2)

        result[teacher] = {
            "hours": total_teacher_hours,
            "teaching_breakdown": {
                "teaching": teacher_lecture_hours_with_mult,
                "practicals": teacher_practical_hrs,
                "assessment_setting": teacher_assessment_hours,
                "marking": marking_hours_per_teacher,
                "admin": admin_hours_per_teacher,
                "supervision": teacher_supervision_hours.get(teacher, 0.0),
                "hw_lab": teacher_hw_lab,
                "drop_in": teacher_drop_in,
                "online_content_dev": 0.0,  # Not calculated per-module in current implementation
            },
            "practicals_breakdown": teacher_practicals_structured,
            "detail_text": "; ".join(module_detail_parts),
            "supervision_details": [],
        }

    return result


# --- Research Workload ---


def _calculate_research_workload(staff_member: StaffData, assumptions: List[str] = None) -> tuple:
    """Calculate research workload for a staff member.

    University has a 10% protected baseline for all staff. Research grants,
    PhD supervision, and project marking contribute additional research time.

    Args:
        staff_member: StaffData object with supervision counts and grant data
        assumptions: Optional list to append assumption strings to (for invalid FTE values)

    Returns:
        Tuple of (total_hours, breakdown_dict, detail_string, grant_titles_dict) where:
            - total_hours: Sum of all research activities
            - breakdown_dict: Category-wise hour allocations
            - detail_string: Human-readable summary
            - grant_titles_dict: Mapping of project IDs to display titles
    """
    total = 0.0
    details = []
    breakdown = {}
    grant_titles = {}  # project_id -> title mapping for output display


    # Note: IGGI project staff are identified by their grant in % FTE for CS.csv
    # There is no separate "primary research allowance" - all research work comes from grants

    # PhD supervision work (supervisor, co-supervisor and assessor are part of research workload)
    phd_hours = 0.0
    phd_details = []
    phd_breakdown = {}

    # Sole supervisors (primary supervisor role) - full-time PhD students
    if staff_member.phd_supervisions > 0:
        sole_count = staff_member.phd_supervisions
        sole_hours = sole_count * config.SUPERVISION_MULTIPLIERS["pgr_primary_supervisor_per_fte"]
        phd_hours += sole_hours
        phd_breakdown["primary_supervisor"] = sole_hours
        phd_details.append(f"{sole_count}x full-time PhD student × {config.SUPERVISION_MULTIPLIERS['pgr_primary_supervisor_per_fte']}h/FTE")

    # Co-supervisors - part-time PhD students (60% of primary)
    if staff_member.phd_co_supervisions > 0:
        co_count = staff_member.phd_co_supervisions
        co_hours = co_count * config.SUPERVISION_MULTIPLIERS["pgr_co_supervisor_per_fte"]
        phd_hours += co_hours
        phd_breakdown["co_supervisor"] = co_hours
        phd_details.append(f"{co_count}x part-time PhD student × {config.SUPERVISION_MULTIPLIERS['pgr_co_supervisor_per_fte']}h/FTE")

    # TAP assessor work (assessor for PhD students)
    if staff_member.phd_assessor_count > 0:
        assessor_count = staff_member.phd_assessor_count
        assessor_hours = assessor_count * config.SUPERVISION_MULTIPLIERS["pgr_assessor"]
        phd_hours += assessor_hours
        phd_breakdown["assessor"] = assessor_hours
        phd_details.append(f"{assessor_count}x assessor ({config.SUPERVISION_MULTIPLIERS['pgr_assessor']}h each)")

    if phd_hours > 0:
        total += phd_hours
        # Add detailed breakdown items first (primary, co-supervisor, assessor)
        breakdown.update(phd_breakdown)
        # Then add the combined total for reference
        breakdown["phd_supervision"] = phd_hours
        # Build formula string showing N × 80 + M × 48 structure
        formula_parts = []
        if staff_member.phd_supervisions > 0:
            formula_parts.append(f"{staff_member.phd_supervisions} × {config.SUPERVISION_MULTIPLIERS['pgr_primary_supervisor_per_fte']}")
        if staff_member.phd_co_supervisions > 0:
            formula_parts.append(f"{staff_member.phd_co_supervisions} × {config.SUPERVISION_MULTIPLIERS['pgr_co_supervisor_per_fte']}")
        if staff_member.phd_assessor_count > 0:
            formula_parts.append(f"{assessor_count} × {config.SUPERVISION_MULTIPLIERS['pgr_assessor']}")
        formula_str = " + ".join(formula_parts) if formula_parts else ""
        # Add explanation of what's included in PhD supervision
        # Note: Individual items (primary_supervisor, co_supervisor, assessor) are already
        # shown in the breakdown table; this line is just for reference
        details.append(f"PhD supervision: {'; '.join(phd_details)} = {phd_hours:.1f}h")

    # Research grant time (from % FTE for CS.csv)
    grant_titles = {}  # project_id -> title mapping for output display
    for proj in staff_member.research_projects:
        fte_str = proj.get("fte", "0%")
        try:
            fte = float(fte_str.replace("%", "")) / 100.0
            grant_hours = fte * config.NOMINAL_WORKING_HOURS_PER_YEAR
            total += grant_hours
            project_id = proj['project_id']
            breakdown[f"grant_{project_id}"] = grant_hours
            # Use title if available and meaningful, otherwise use project ID
            title = proj.get('title', '').strip()
            display_name = title if title and len(title) > 3 else project_id
            grant_titles[project_id] = display_name
            details.append(f"Grant {display_name}: {fte_str} of {config.NOMINAL_WORKING_HOURS_PER_YEAR}h = {grant_hours:.1f}h")
        except ValueError:
            # Record the invalid FTE value but don't fail silently
            if assumptions is None:
                assumptions = []
            assumptions.append(f"Invalid FTE value for grant: '{fte_str}'")

    # Ensure assumptions is always a list (convert None to empty list)
    if assumptions is None:
        assumptions = []

    return total, breakdown, "; ".join(details) if details else "No research activities recorded", grant_titles, assumptions


# --- Administration Workload ---


def _calculate_admin_workload(staff_member: StaffData, nominal_hours: float) -> tuple:
    """Calculate administration workload from departmental roles and service points.

    Args:
        staff_member: StaffData object with role assignments
        nominal_hours: Annual working hours (scaled by FTE)

    Returns:
        Tuple of (total_hours, breakdown_dict, detail_string) where:
            - total_hours: Sum of all administrative activities
            - breakdown_dict: Role-wise hour allocations
            - detail_string: Human-readable summary
    """
    total = 0.0
    details = []
    breakdown = {}

    # Track which roles have been counted to avoid double-counting
    counted_roles = set()

    for role in staff_member.roles:
        percentage = config.ROLES_PERCENTAGE.get(role, 0.0)
        hours = nominal_hours * percentage
        total += hours
        breakdown[role] = hours
        details.append(f"{role}: {percentage*100:.0f}% of {nominal_hours:.0f}h = {hours:.1f}h")
        counted_roles.add(role)

    # Add service points - general baseline activities for all staff
    # This includes engagement (email/meetings) and personal development
    # Based on BASELOADS: engagement=100h + personal_development=75h = 175h total
    # Scale by FTE to handle part-time staff correctly
    fte_value = nominal_hours / config.NOMINAL_WORKING_HOURS_PER_YEAR if nominal_hours > 0 else 1.0
    engagement_hours = config.BASELOADS.get('engagement', 100.0) * fte_value
    personal_dev_hours = config.BASELOADS.get('personal_development', 75.0) * fte_value
    service_hours = engagement_hours + personal_dev_hours

    total += service_hours
    breakdown["engagement"] = engagement_hours
    breakdown["personal_development"] = personal_dev_hours
    details.append(f"Engagement (email/meetings): {engagement_hours:.1f}h")
    details.append(f"Personal development: {personal_dev_hours:.1f}h (FTE: {fte_value:.2f})")

    return total, breakdown, "; ".join(details) if details else "No administrative roles"


# --- Main Calculation ---

def calculate_workload(year_data: YearData, validate_input: bool = True) -> List[WorkloadResult]:
    """Calculate the complete workload for all staff members.

    This is the main entry point for the workload calculation engine. It processes
    all modules and staff, applying teaching multipliers, research allowances,
    and administrative role percentages to compute total workload hours.

    Args:
        year_data: YearData object containing module data, staff data, known lecturers,
            and metadata for the academic year
        validate_input: If True, run input validation before calculation (default True)

    Returns:
        List of WorkloadResult objects, one per active staff member.
        Each result contains:
            - name: Staff member's canonical name
            - fte: Full-time equivalent (1.0 for full-time)
            - total_hours: Total workload (teaching + research + admin)
            - teaching_hours: Teaching-related activities
            - research_hours: Research time (protected baseline + additional)
            - admin_hours: Administrative role hours
            - teaching/research/admin_details: Human-readable breakdown strings
            - teaching/research/admin_breakdown: Structured hour allocations by category

    The workload formula is:
        Total = Teaching + Research (Protected + Additional) + Admin

    Raises:
        ValueError: If validate_input=True and validation fails with errors
    """
    # Run input validation if requested
    if validate_input:
        validation_result = run_validation_pipeline(year_data)
        if validation_result["has_warnings"]:
            # Store warnings in assumptions for reporting
            pass  # Warnings are captured in results, not raised as errors

    # Convert tuples to dicts for internal use (YearData is immutable at the container level)
    staff_dict = {s.canonical_name: s for s in year_data.staff}

    # Allocate supervision once for all teachers (pure function)
    supervision = allocate_supervision(staff_dict)

    # Initialize per-staff teaching totals
    staff_teaching = {name: {"hours": 0.0, "details": []} for name in staff_dict}

    # Process each module
    for module in year_data.modules:
        # Normalize teacher names (use reverse_lookup instead of name_lookup)
        normalized_teachers = []
        for t in module.teachers:
            name = normalize_name(t.strip(), year_data.reverse_lookup, unknown_callback=None)
            if name:
                normalized_teachers.append(name)
            else:
                normalized_teachers.append(t.strip())

        # Include the module lead as a teacher only if they're also listed as one of the teachers
        # The lead column (column 6 in WTW CSV) is separate from the teacher columns (7-8)
        # Only add lead to teachers list if they're teaching the module
        if module.lead_name:
            lead_name = normalize_name(module.lead_name.strip(), year_data.reverse_lookup, unknown_callback=None)
            # Only add if lead is also in the teachers list (i.e., they're actually teaching)
            if lead_name and lead_name in normalized_teachers:
                # Lead is already in the list, no need to add again
                pass

        if not normalized_teachers:
            # Module has no teachers - flag as incomplete
            continue

        # Calculate teaching workload (supervision passed as immutable allocation)
        module_teaching = _calculate_teaching_workload(
            module, normalized_teachers, year_data.known_lecturers,
            year_data.known_lecturers_per_module, staff_dict,
            supervision=supervision
        )

        for teacher, breakdown in module_teaching.items():
            if teacher in staff_teaching:
                staff_teaching[teacher]["hours"] += breakdown["hours"]
                staff_teaching[teacher]["details"].append(
                    f"{module.name} ({module.credits}cr): {breakdown['detail_text']}"
                )
                # Store per-module teaching_breakdown for accurate display
                if "teaching_module_breakdowns" not in staff_teaching[teacher]:
                    staff_teaching[teacher]["teaching_module_breakdowns"] = {}
                if module.name not in staff_teaching[teacher]["teaching_module_breakdowns"]:
                    staff_teaching[teacher]["teaching_module_breakdowns"][module.name] = {}
                # Copy the teaching_breakdown for this specific module
                staff_teaching[teacher]["teaching_module_breakdowns"][module.name].update(
                    breakdown.get("teaching_breakdown", {})
                )
                # Store structured practicals breakdown per module if available
                if "practicals_breakdown" in breakdown and breakdown["practicals_breakdown"]:
                    staff_teaching[teacher]["teaching_module_breakdowns"][module.name].update({
                        "practicals": breakdown["practicals_breakdown"]
                    })
                # Aggregate supervision details (to be shown separately)
                if "supervision_details" not in staff_teaching[teacher]:
                    staff_teaching[teacher]["supervision_details"] = []
                staff_teaching[teacher]["supervision_details"].extend(breakdown["supervision_details"])

    # Build results
    results = []
    for canonical_name, staff in staff_dict.items():
        if not staff.active:
            continue

        # Initialize assumptions and missing data early (they're used throughout the loop)
        assumptions = []
        missing_data = []

        # Nominal hours scaled by FTE for part-time staff (StaffData is now frozen)
        fte_value = staff.fte if staff.fte > 0 else 1.0
        nominal_hours = config.NOMINAL_WORKING_HOURS_PER_YEAR * fte_value

        # Teaching - default to minimum teaching hours for administrative staff
        teaching_hours = staff_teaching.get(canonical_name, {}).get("hours", 0.0)
        min_teaching = 0.0

        # Add minimum teaching load for HoD and other admin staff who don't teach modules
        # Original model shows ~30h teaching for HoD (reduced from full teaching load)
        has_module_teaching = canonical_name in staff_teaching and len(staff_teaching[canonical_name].get("details", [])) > 0

        if not has_module_teaching:
            # Administrative staff need a minimum teaching component
            # HoD typically has reduced teaching - use default from config (from workload_parameters.yaml)
            if "Head of Department" in staff.roles or len(staff.roles) > 1:
                min_teaching = config.MIN_ADMIN_TEACHING_HOURS
                if min_teaching > 0:
                    teaching_hours = min_teaching
                    # Add detail for minimum admin teaching - show source reference
                    staff_teaching[canonical_name]["hours"] = min_teaching
                    staff_teaching[canonical_name]["details"].append(
                        f"Minimum administrative teaching load (from workload_parameters.yaml): {min_teaching:.0f}h"
                    )
                    # Also set up the teaching_breakdown for this entry
                    if "teaching_breakdown" not in staff_teaching[canonical_name]:
                        staff_teaching[canonical_name]["teaching_breakdown"] = {}
                    staff_teaching[canonical_name]["teaching_breakdown"]["minimum_admin_load"] = min_teaching

        # Supervision - add once per staff member (not per module)
        # Get pastoral and project supervision from the allocation object
        pastoral_count = supervision.pastoral_students.get(canonical_name, 0)

        pastoral_hours = pastoral_count * config.SUPERVISION_MULTIPLIERS["pastoral"]
        teaching_hours += pastoral_hours
        staff_teaching[canonical_name]["hours"] += pastoral_hours
        if "teaching_breakdown" not in staff_teaching[canonical_name]:
            staff_teaching[canonical_name]["teaching_breakdown"] = {}

        # Store structured pastoral breakdown (similar to practicals pattern from Phase 3a)
        staff_teaching[canonical_name]["teaching_breakdown"]["pastoral_supervision"] = pastoral_hours
        if "pastoral_breakdown" not in staff_teaching[canonical_name]["teaching_breakdown"]:
            staff_teaching[canonical_name]["teaching_breakdown"]["pastoral_breakdown"] = {}
        staff_teaching[canonical_name]["teaching_breakdown"]["pastoral_breakdown"].update({
            "student_count": pastoral_count,
            "rate": config.SUPERVISION_MULTIPLIERS["pastoral"],
            "total": round(pastoral_hours, 2)
        })

        # Add supervision detail for HTML display
        if "supervision_details" not in staff_teaching[canonical_name]:
            staff_teaching[canonical_name]["supervision_details"] = []
        if pastoral_count > 0:
            staff_teaching[canonical_name]["supervision_details"].append(
                f"Pastoral: {pastoral_count} students x {config.SUPERVISION_MULTIPLIERS['pastoral']}h = {pastoral_hours:.1f}h"
            )

        # Get project load for this teacher from supervision allocation (already ceiling'd)
        teacher_project_load = supervision.project_loads.get(canonical_name, 0)

        # Project setting allowance - only for staff who actually supervise projects
        if teacher_project_load > 0:
            project_setting_hours = config.PROJECT_SETTING_ALLOWANCE
            teaching_hours += project_setting_hours
            if canonical_name not in staff_teaching:
                staff_teaching[canonical_name] = {"hours": 0.0, "details": [], "teaching_breakdown": {}}
            else:
                # Ensure teaching_breakdown exists
                if "teaching_breakdown" not in staff_teaching[canonical_name]:
                    staff_teaching[canonical_name]["teaching_breakdown"] = {}
                # Add project setting to details for display
                staff_teaching[canonical_name]["details"].append(
                    f"Project setting (fixed): {project_setting_hours}h"
                )
            staff_teaching[canonical_name]["hours"] += project_setting_hours
            staff_teaching[canonical_name]["teaching_breakdown"]["project_setting"] = project_setting_hours

        if teacher_project_load > 0:
            proj_mult = config.SUPERVISION_MULTIPLIERS["ug_project"]
            if canonical_name in staff_dict:
                # Use stage from staff's modules to determine project multiplier
                for mod in year_data.modules:
                    if canonical_name in [normalize_name(t, year_data.reverse_lookup, unknown_callback=None) or t for t in mod.teachers]:
                        if config.is_msc_level(mod.stage):  # MSc level (stage >= 4)
                            proj_mult = config.SUPERVISION_MULTIPLIERS["msc_project"]
                            break
            project_hours = teacher_project_load * proj_mult
            teaching_hours += project_hours
            staff_teaching[canonical_name]["hours"] += project_hours
            if "teaching_breakdown" not in staff_teaching[canonical_name]:
                staff_teaching[canonical_name]["teaching_breakdown"] = {}
            staff_teaching[canonical_name]["teaching_breakdown"]["project_supervision"] = project_hours

            # Store structured project breakdown (similar to practicals pattern from Phase 3a)
            if "project_breakdown" not in staff_teaching[canonical_name]["teaching_breakdown"]:
                staff_teaching[canonical_name]["teaching_breakdown"]["project_breakdown"] = {}
            proj_level = "UG" if proj_mult == config.SUPERVISION_MULTIPLIERS["ug_project"] else "MSc"
            staff_teaching[canonical_name]["teaching_breakdown"]["project_breakdown"].update({
                "project_count": teacher_project_load,
                "level": proj_level,
                "rate": proj_mult,
                "total": round(project_hours, 2)
            })

            # Add supervision detail for HTML display
            if "supervision_details" not in staff_teaching[canonical_name]:
                staff_teaching[canonical_name]["supervision_details"] = []
            staff_teaching[canonical_name]["supervision_details"].append(
                f"Projects: {teacher_project_load} projects x {proj_level} ({proj_mult}h) = {project_hours:.1f}h"
            )

        # General baseline is handled within _calculate_admin_workload via service_points
        # Protected research baseline (10% of nominal hours) - included in all staff totals
        protected_research = config.PROTECTED_RESEARCH_BASELINE * fte_value

        # Research (grants, supervision - additional to protected baseline)
        # Pass assumptions list to capture any issues found during calculation
        research_hours, research_breakdown, research_detail, grant_titles, grant_assumptions = _calculate_research_workload(staff, assumptions)

        # Add assumptions from research grants calculation to the main assumptions list
        if grant_assumptions:
            assumptions.extend(grant_assumptions)

        # Add protected baseline to breakdown
        research_breakdown['protected_research_baseline'] = protected_research

        # Total research = protected baseline + additional work from grants/supervision
        research_total = protected_research + research_hours

        # Administration
        admin_hours, admin_breakdown, admin_detail = _calculate_admin_workload(staff, nominal_hours)

        # Admin hours already include service_points (engagement + personal_dev)
        # So we don't add them separately to avoid double-counting
        # Total: teaching + research (protected + additional) + admin
        total_hours = teaching_hours + research_total + admin_hours

        # Build detail strings
        teaching_detail_str = "; ".join(staff_teaching.get(canonical_name, {}).get("details", [])) if canonical_name in staff_teaching else "No teaching activities"

        # Process supervision details (deduplicated for both teaching_detail and result)
        supervision_details_list = staff_teaching.get(canonical_name, {}).get("supervision_details", [])
        unique_supervision = []
        if supervision_details_list:
            # Deduplicate while preserving order
            seen = set()
            for item in supervision_details_list:
                if item not in seen:
                    seen.add(item)
                    unique_supervision.append(item)
            teaching_detail_str += "; " + "; ".join(unique_supervision)

        if staff.saint_modules:
            teaching_detail_str += f"; Also teaches: {', '.join(staff.saint_modules)} (SAINTS - not included in workload)"

        # Get module details list for reporting
        module_details = list(staff_teaching.get(canonical_name, {}).get("details", []))
        # Add unique supervision details (Pastoral, Projects) to the module_details list
        # so they appear as separate rows in the HTML table
        if unique_supervision:
            module_details.extend(unique_supervision)

        def _sum_breakdown_dict(breakdown_dict):
            """Sum per-module breakdown values to totals."""
            result = {}
            for k, v in breakdown_dict.items():
                if isinstance(v, dict):
                    # Check if this is a structured breakdown (like pastoral_breakdown or project_breakdown)
                    # These have 'total' as the main numeric field and should not be summed
                    if 'total' in v:
                        result[k] = v  # Keep structured breakdown as-is
                    else:
                        # Dict of per-module breakdowns - sum them
                        result[k] = sum(v.values())
                elif isinstance(v, list):
                    result[k] = sum(v)
                else:
                    # Scalar value (e.g., pastoral_supervision, project_setting)
                    result[k] = v
            return result

        # Build structured teaching breakdown from per-module data
        teaching_breakdown = {}
        teaching_module_breakdowns = {}
        if canonical_name in staff_teaching:
            staff_data = staff_teaching[canonical_name]
            # Per-module teaching_breakdown for accurate display
            if "teaching_module_breakdowns" in staff_data and staff_data["teaching_module_breakdowns"]:
                teaching_module_breakdowns = dict(staff_data["teaching_module_breakdowns"])
            # Aggregated teaching_breakdown (sum of all modules)
            if "teaching_breakdown" in staff_data and staff_data["teaching_breakdown"]:
                teaching_breakdown = _sum_breakdown_dict(staff_data["teaching_breakdown"])
            elif len(staff_data.get("details", [])) > 0:
                # Fallback: parse from details string for backward compatibility
                pass
        else:
            # For admin staff with only minimum teaching load
            if min_teaching > 0:
                teaching_breakdown["minimum_admin_load"] = min_teaching

        # Extract structured supervision breakdowns (pastoral and project)
        pastoral_breakdown = {}
        project_breakdown = {}
        if canonical_name in staff_teaching:
            staff_data = staff_teaching[canonical_name]
            if "teaching_breakdown" in staff_data:
                teaching_data = staff_data["teaching_breakdown"]
                # Extract structured pastoral breakdown
                if "pastoral_breakdown" in teaching_data:
                    pastoral_breakdown = dict(teaching_data["pastoral_breakdown"])
                # Extract structured project breakdown
                if "project_breakdown" in teaching_data:
                    project_breakdown = dict(teaching_data["project_breakdown"])

        # Track missing data (assumptions are tracked earlier in the function)
        if not staff.fte or staff.fte == 0:
            missing_data.append("FTE not found (defaulting to 1.0)")
            fte_for_calculation = 1.0
            nominal_hours = config.NOMINAL_WORKING_HOURS_PER_YEAR
        else:
            fte_for_calculation = staff.fte
            # Nominal hours scaled by FTE for part-time staff
            nominal_hours = config.NOMINAL_WORKING_HOURS_PER_YEAR * fte_for_calculation

        if not staff.roles:
            missing_data.append("No administrative roles assigned")

        # Add assumptions from validation
        validation_info = getattr(year_data, 'validation_info', {})
        if validation_info.get('has_warnings'):
            assumptions.append("Data contains warnings - values may be outside typical ranges")

        # Track default student count assumption (if module had 0 students)
        for detail in staff_teaching.get(canonical_name, {}).get("details", []):
            if "student" in detail.lower() or "scripts" in detail.lower():
                if "0 scripts" in detail:
                    assumptions.append(Assumption(
                        category="student_count",
                        description="Module had 0 students - marking not calculated",
                        module_code=detail.split(":")[0].strip() if ":" in detail else None
                    ).description)

        result = WorkloadResult(
            name=canonical_name,
            fte=staff.fte,
            total_hours=total_hours,
            teaching_hours=teaching_hours,
            research_hours=research_total,
            admin_hours=admin_hours,
            category=staff.category,
            assumptions=tuple(assumptions),  # Convert to tuple for frozen dataclass
            missing_data=tuple(missing_data),  # Convert to tuple for frozen dataclass
            teaching_detail=teaching_detail_str,
            research_detail=research_detail,
            admin_detail=admin_detail,
            teaching_breakdown=teaching_breakdown,
            teaching_module_breakdowns=teaching_module_breakdowns,
            research_breakdown=research_breakdown,
            admin_breakdown=admin_breakdown,
            nominal_hours=nominal_hours,
            grant_titles=grant_titles,
            module_details=tuple(module_details),  # Convert to tuple for frozen dataclass
            supervision_details=tuple(unique_supervision),  # Convert to tuple for frozen dataclass
            pastoral_breakdown=pastoral_breakdown,  # Structured pastoral supervision breakdown
            project_breakdown=project_breakdown,  # Structured project supervision breakdown
        )
        results.append(result)

    return results
