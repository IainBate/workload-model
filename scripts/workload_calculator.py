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
from config import DEFAULT_LECURE_HOURS_PER_WEEK
from data_loader import (
    YearData,
    ModuleData,
    StaffData,
    WorkloadResult,
    AdjustmentRecord,
    SupervisionAllocation,
    allocate_supervision,
    normalize_name,
    _load_module_mapping,
)

# Per-module teaching breakdown keys that are numeric and get summed across a
# staff member's modules to produce the aggregated (category-level) teaching_breakdown.
# Shared between _aggregate_teaching_breakdown() (the roll-up) and
# _apply_teaching_module_adjustments() (which computes a module's pre-adjustment
# calculated total using this same list) so the two can never drift apart -
# if a key is added to one but not the other, a module-scoped adjustment would
# either double-count or silently vanish from the rolled-up category total.
# "manual_adjustment" is included so a module-scoped adjustment (written into a
# module's breakdown dict by _apply_teaching_module_adjustments()) automatically
# rolls into the aggregated teaching_breakdown total.
_TEACHING_MODULE_SUM_KEYS = ["teaching", "practicals", "assessment_setting", "marking",
                             "admin", "supervision", "hw_lab", "drop_in", "manual_adjustment"]


def _get_prev_year_module_names(module: ModuleData) -> List[str]:
    """Get all possible module names from previous year that could map to this module.

    This handles H/M variant merging where a single current-year module might
    combine two variants from the previous year (e.g., AURO-H + AURO-M -> AURO).

    Returns:
        List of possible previous year module names to check, in order of preference.
    """
    names_to_check = []

    # Add all codes first
    if module.codes:
        names_to_check.extend(list(module.codes))

    # Add current module name
    if module.name:
        names_to_check.append(module.name)

    # Check module mapping for previous year variant names
    module_mapping = _load_module_mapping()
    merged_modules = module_mapping.get("merged_modules", {})

    # If this is a combined module, also check the H/M variants from previous year
    if module.name:
        for old_name, mapping in merged_modules.items():
            if mapping.get("2026-7") == module.name:
                names_to_check.append(old_name)

    return names_to_check
from validation import (
    validate_year_data,
    run_validation_pipeline_input,
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
        'lecture_hours': 0.0,  # Total lecture hours for the module
        'individual_lecture_hours': {},  # After multiplier applied
        'individual_lecture_contact_hours': {},  # Base contact hours (before multiplier)
        'lecture_multipliers': {},
        'lecturer_types': [],
        'total_lecture_hours': 0.0,  # Total lecture hours before splitting among teachers
        'teacher_count': 0,  # Number of teachers
    }

    contact_weeks = TEACHING_WEEKS_PER_SEMESTER

    # Calculate weeks of teaching (typical semester is ~22 weeks)
    practicals_count = module.practicals

    # Default lecture hours per week (standard modules without specified contact time)
    # This represents the standard weekly lecture contact time for staff
    default_lecture_hours_per_week = DEFAULT_LECURE_HOURS_PER_WEEK

    # Calculate lecture hours using the default (2h/week × 11 weeks = 22h typical)
    lecture_hours = default_lecture_hours_per_week * contact_weeks

    # Calculate practical duration for reporting purposes
    if practicals_count > 0 and module.practical_contact_hours > 0:
        total_practical_duration = module.practical_contact_hours * practicals_count
    else:
        total_practical_duration = 0.0

    result['lecture_hours'] = lecture_hours
    result['total_lecture_hours'] = lecture_hours  # Total before splitting among teachers
    result['teacher_count'] = len(teachers) if teachers else 0

    # Determine which teachers from last year taught THIS specific module
    # Check ALL possible names (codes, current name, AND previous year H/M variants)
    known_teachers_this_module = None
    for lookup_name in _get_prev_year_module_names(module):
        known_teachers_this_module = known_lecturers_per_module.get(lookup_name)
        if known_teachers_this_module is not None:
            break

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

    # Mapping from internal lecturer_type strings to YAML config keys
    LECTURER_TYPE_TO_CONFIG_KEY = {
        'video': 'lecture_new_video',
        'new_lecturer_new_content': 'lecture_new_content_and_lecturer',
        'new_lecturer': 'lecture_new_content_or_lecturer',
        'existing_lecturer_new_content': 'lecture_new_content_or_lecturer',
        'standard': 'lecture_standard',
    }

    for t in teachers:
        is_new_lecturer = t not in known_lecturers_for_module
        is_video_format = getattr(module, 'teaching_format', '') == "video" or "video" in module_name_lower

        if is_video_format:
            config_key = LECTURER_TYPE_TO_CONFIG_KEY.get('video')
            multiplier = config.TEACHING_MULTIPLIERS.get(config_key, 10.0)
            result['lecturer_types'].append((t, 'video'))
        elif is_new_lecturer and is_new_content_module:
            # New lecturer + new content gets 7.5x
            config_key = LECTURER_TYPE_TO_CONFIG_KEY.get('new_lecturer_new_content')
            multiplier = config.TEACHING_MULTIPLIERS.get(config_key, 7.5)
            result['lecturer_types'].append((t, 'new_lecturer_new_content'))
        elif is_new_lecturer:
            # New lecturer (not new content) gets 5x
            config_key = LECTURER_TYPE_TO_CONFIG_KEY.get('new_lecturer')
            multiplier = config.TEACHING_MULTIPLIERS.get(config_key, 5.0)
            result['lecturer_types'].append((t, 'new_lecturer'))
        else:
            if is_new_content_module:
                # Existing lecturer on new content gets 5x (content dev only)
                config_key = LECTURER_TYPE_TO_CONFIG_KEY.get('existing_lecturer_new_content')
                multiplier = config.TEACHING_MULTIPLIERS.get(config_key, 5.0)
                result['lecturer_types'].append((t, 'existing_lecturer_new_content'))
            else:
                # Standard existing lecturer gets 2.5x
                config_key = LECTURER_TYPE_TO_CONFIG_KEY.get('standard')
                multiplier = config.TEACHING_MULTIPLIERS.get(config_key, 2.5)
                result['lecturer_types'].append((t, 'standard'))

        # Calculate per-teacher lecture hours (split equally among teachers) with multiplier applied
        per_teacher_lecture_hours = lecture_hours / len(teachers) if teachers else 0.0
        per_teacher_with_multiplier = per_teacher_lecture_hours * multiplier

        result['individual_lecture_hours'][t] = per_teacher_with_multiplier
        # Store the base contact hours (before multiplier) for display purposes
        result['individual_lecture_contact_hours'][t] = per_teacher_lecture_hours
        result['lecture_multipliers'][t] = multiplier

    return result


def _calculate_practical_hours_and_breakdown(
    module: ModuleData,
    teachers: List[str],
    lecturer_types: Optional[List[Tuple[str, str]]] = None
) -> dict:
    """Calculate practical session hours with repetition multipliers.

    Practical sessions use two rates:
    - First session rate: Standard problem class rate (TEACHING_PROBLEM_CLASS)
    - Repeat session rate: REPETITION_MULTIPLIER applied to first-session rate

    Each teacher's multiplier is applied based on their lecturer type (new lecturer gets 5x).

    Args:
        module: ModuleData with practicals count and contact hours
        teachers: List of teacher names (canonical)
        lecturer_types: Optional list of (teacher, lecturer_type) tuples from lecture calculation.
                       If provided, each teacher's multiplier is used for their practical hours.

    Returns a dict with structured breakdown suitable for output display.
    """
    # Mapping from internal lecturer_type strings to YAML config keys
    LECTURER_TYPE_TO_CONFIG_KEY = {
        'video': 'lecture_new_video',
        'new_lecturer_new_content': 'lecture_new_content_and_lecturer',
        'new_lecturer': 'lecture_new_content_or_lecturer',
        'existing_lecturer_new_content': 'lecture_new_content_or_lecturer',
        'standard': 'lecture_standard',
    }

    result = {
        'total_practical_hours': 0.0,
        'individual_practical_hours': {},
        'practicals_breakdown': None,  # Structured breakdown dict or None
        'practical_details': [],  # List of detail strings for HTML display
    }

    # Build multiplier lookup from lecturer_types using the mapping
    teacher_multiplier = {}
    if lecturer_types:
        for t, ltype in lecturer_types:
            config_key = LECTURER_TYPE_TO_CONFIG_KEY.get(ltype)
            mult = config.TEACHING_MULTIPLIERS.get(config_key, config.TEACHING_PROBLEM_CLASS)
            teacher_multiplier[t] = mult

    contact_weeks = TEACHING_WEEKS_PER_SEMESTER
    practicals_count = module.practicals

    if practicals_count > 0:
        # Get parallel groups configuration (if available)
        parallel_groups = getattr(module, 'parallel_groups', None)

        # Convert integer practical_groups to list of group objects for compatibility
        # First check if parallel_groups is an int (already set), otherwise check practical_groups
        if isinstance(parallel_groups, int):
            n_parallel_groups = parallel_groups
        elif hasattr(module, 'practical_groups') and isinstance(module.practical_groups, int) and module.practical_groups > 1:
            n_parallel_groups = module.practical_groups
        else:
            n_parallel_groups = None

        # Note: n_parallel_groups (from "Number of Practical Groups" in CS Module
        # Assessment Numbers.csv) is independent of practicals_count (from "Number of
        # Practicals" - sessions/week). A module can have 1 session/week that is
        # repeated across several parallel groups (e.g. SYS3: 1 session/week, 6 groups),
        # so groups > practicals_count is expected, not a data error - do not discard it.

        if n_parallel_groups is not None:
            parallel_groups = []
            for i in range(n_parallel_groups):
                # Each group runs once per week (sessions=1), with the specified duration
                parallel_groups.append(type('ParallelGroup', (), {
                    'sessions': 1,  # Each group meets once per week
                    'hours_per_week': getattr(module, 'practical_contact_hours', config.TEACHING_PROBLEM_CLASS)
                })())

        n_teachers = len(teachers) if teachers else 1

        if parallel_groups and len(parallel_groups) > 1:
            # Multiple parallel groups - each group has its own session count
            # In parallel groups, each teacher teaches one group (or shares one group),
            # so we calculate for ONE representative group only.
            group = parallel_groups[0]
            group_sessions = getattr(group, 'sessions', practicals_count)

            if group_sessions > 0:
                weekly_hrs = getattr(group, 'hours_per_week', config.TEACHING_PROBLEM_CLASS)
                first_session_rate = config.TEACHING_PROBLEM_CLASS
                repeat_rate = config.REPETITION_MULTIPLIER

                # Calculate hours for one teacher teaching one group (base hours without their multiplier)
                # For parallel groups: repeats are sessions beyond what each teacher does as first session
                # Each teacher gets n_parallel_groups/n_teachers worth of practicals on average
                # First session is the base share; additional is repeat

                # Calculate per-teacher first session and repeat shares separately
                groups_per_teacher = n_parallel_groups / n_teachers if n_teachers > 0 else 0
                repeat_sessions = max(0, groups_per_teacher - 1)

                # Base hours without any rates applied
                # Each teacher gets exactly 1 "first session" at their rate (first delivery of content)
                first_session_base = 1.0 * weekly_hrs * contact_weeks
                repeat_base = repeat_sessions * weekly_hrs * contact_weeks

                for t in teachers:
                    multiplier = teacher_multiplier.get(t, 1.0)
                    if t not in result['individual_practical_hours']:
                        result['individual_practical_hours'][t] = 0.0

                    # First session: apply lecturer's full multiplier to base hours
                    first_session_with_mult = first_session_base * multiplier

                    # Repeat sessions: only apply REPETITION_MULTIPLIER (not the lecturer's rate)
                    repeat_with_rate = repeat_base * repeat_rate

                    # Total for this teacher
                    total_for_teacher = first_session_with_mult + repeat_with_rate
                    result['individual_practical_hours'][t] += total_for_teacher

                # Store structured breakdown (per teacher, per group) - shows base rates without multipliers
                # The 'total' field is the module's total at standard rates (no teacher multipliers)
                # First session base at standard rate = first_session_base * first_session_rate
                # Repeat base at repetition rate = repeat_base * repeat_rate
                module_total_at_standard_rates = (first_session_base * first_session_rate) + (repeat_base * repeat_rate)

                result['practicals_breakdown'] = {
                    "first_session_hours": round(weekly_hrs, 2),
                    "repeat_hours": round(repeat_sessions * weekly_hrs, 2),  # Base repeat hours without rates
                    "week_count": contact_weeks,
                    "total_groups": n_parallel_groups,
                    "first_session_rate": first_session_rate,
                    "repeat_rate": repeat_rate,
                    "total": round(module_total_at_standard_rates, 2),
                    "n_teachers": n_teachers,
                    # Store per-teacher values for display
                    "groups_per_teacher": groups_per_teacher,
                    "repeat_sessions_per_teacher": repeat_sessions
                }

                # Display shows per-group calculation with lecturer type info

                # Build rate text based on teacher multipliers (check if all same or mixed)
                unique_multipliers = set(teacher_multiplier.get(t, 1.0) for t in teachers)
                if len(unique_multipliers) == 1:
                    mult_val = list(unique_multipliers)[0]
                    mult_text = f"{mult_val}x" if mult_val != 1.0 else "standard"
                    rate_display = f"- {mult_text} lecturer rate applied (first session: {first_session_rate}x, repeats: {repeat_rate}x)"
                else:
                    # Mixed multipliers - list them
                    mult_details = ", ".join(f"{t}: {teacher_multiplier.get(t, 1.0)}x" for t in teachers)
                    rate_display = f"- Per-teacher rates applied: {mult_details}"

                result['practical_details'].append(
                    f"First time delivery: {group_sessions} sessions/week @ {weekly_hrs}h each; "
                    f"{rate_display}"
                )
        else:
            # No parallel groups - each teacher gets practical hours based on their multiplier
            std_first_session_weekly = getattr(module, 'practical_contact_hours', config.TEACHING_PROBLEM_CLASS)
            repeat_rate = config.REPETITION_MULTIPLIER

            if practicals_count > 1:
                # Calculate per-teacher first session and repeat shares directly
                # First session rate: each teacher's multiplier (standard or new lecturer rate)
                # Repeat sessions: apply REPETITION_MULTIPLIER only (not the lecturer's rate)

                # Each teacher gets at least 1 "first session" unit, plus their share of repeats
                # Total practicals per week = n_teachers + repeat_sessions_total
                # Per teacher: first_session = 1, repeat = (practicals_count - n_teachers) / n_teachers

                groups_per_teacher = practicals_count / n_teachers if n_teachers > 0 else 0
                repeat_sessions = max(0, groups_per_teacher - 1)

                # Base hours without any rates applied (just sessions * hours * weeks)
                # First session base: 1 session/unit per teacher
                first_session_base = std_first_session_weekly * contact_weeks
                # Repeat base: additional sessions beyond the first per week
                repeat_base = repeat_sessions * std_first_session_weekly * contact_weeks

                for t in teachers:
                    multiplier = teacher_multiplier.get(t, 1.0)
                    if t not in result['individual_practical_hours']:
                        result['individual_practical_hours'][t] = 0.0

                    # First session: apply lecturer's full multiplier to base hours
                    first_session_with_mult = first_session_base * multiplier

                    # Repeat sessions: only apply REPETITION_MULTIPLIER (not the lecturer's rate)
                    repeat_with_rate = repeat_base * repeat_rate

                    # Total for this teacher
                    total_for_teacher = first_session_with_mult + repeat_with_rate
                    result['individual_practical_hours'][t] += total_for_teacher

                # Store structured breakdown - shows per-teacher values with rates applied
                # The 'total' field is the module's total at standard rates (no teacher multipliers)
                # First session: n_teachers × 1 × rate × weeks, Repeat: repeat_sessions_total × rate × weeks
                first_session_base_total = n_teachers * first_session_base
                repeat_base_total = repeat_sessions * n_teachers * std_first_session_weekly * contact_weeks
                total_at_standard_rates = (
                    first_session_base_total * config.TEACHING_PROBLEM_CLASS / n_teachers +
                    repeat_base_total * repeat_rate / n_teachers
                )

                result['practicals_breakdown'] = {
                    "first_session_hours": round(std_first_session_weekly, 2),
                    "repeat_hours": round(repeat_sessions * std_first_session_weekly, 2),
                    "week_count": contact_weeks,
                    "total_groups": practicals_count,
                    "first_session_rate": config.TEACHING_PROBLEM_CLASS,
                    "repeat_rate": repeat_rate,
                    "total": round(total_at_standard_rates, 2),
                    "n_teachers": n_teachers,
                    "groups_per_teacher": groups_per_teacher,
                    "repeat_sessions_per_teacher": repeat_sessions
                }

                # Build display text based on teacher multipliers
                unique_multipliers = set(teacher_multiplier.get(t, 1.0) for t in teachers)
                if len(unique_multipliers) == 1:
                    mult_val = list(unique_multipliers)[0]
                    rate_display = f"- {mult_val}x lecturer rate applied (first session: {config.TEACHING_PROBLEM_CLASS}x, repeats: {repeat_rate}x)"
                else:
                    # Mixed multipliers
                    mult_details = ", ".join(f"{t}: {teacher_multiplier.get(t, 1.0)}x" for t in teachers)
                    rate_display = f"- Per-teacher rates applied: {mult_details}"

                result['practical_details'].append(
                    f"First time delivery: {practicals_count} sessions/week @ {std_first_session_weekly}h each; "
                    f"{rate_display}"
                )
            else:
                # Single session - no repetition
                total_practical_hours = std_first_session_weekly * contact_weeks

                result['practicals_breakdown'] = {
                    "first_session_hours": round(std_first_session_weekly, 2),
                    "repeat_hours": 0,
                    "week_count": contact_weeks,
                    "first_session_rate": config.TEACHING_PROBLEM_CLASS,
                    "repeat_rate": repeat_rate,
                    "total": round(total_practical_hours, 2),
                    "n_teachers": n_teachers,
                }

                # Distribute to individual teachers based on their multiplier
                for t in teachers:
                    if t not in result['individual_practical_hours']:
                        result['individual_practical_hours'][t] = 0.0
                    multiplier = teacher_multiplier.get(t, 1.0)
                    base_share = total_practical_hours / n_teachers
                    result['individual_practical_hours'][t] += base_share * multiplier
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

    # Check ALL possible names (codes, current name, AND previous year H/M variants)
    known_teachers_this_module = None
    for lookup_name in _get_prev_year_module_names(module):
        known_teachers_this_module = known_lecturers_per_module.get(lookup_name)
        if known_teachers_this_module is not None:
            break

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


def _classify_marking_levels(module: ModuleData) -> List[dict]:
    """Split a module's students into UG ("H") and MSc ("M") marking cohorts.

    Some modules are taught as a single shared class to two cohorts, recorded
    as two module codes on one WTW row (e.g. AURO: COM00052H + COM00186M).
    The "H"/"M" code suffix - not module.stage - is the reliable signal for
    level here: these shared modules are all recorded at stage 3 in WTW
    (matching CLAUDE.md's "1-3 UG, 4+ MSc" convention), so module.stage alone
    can't tell a UG-only stage-3 module apart from a shared UG/MSc one, or a
    MSc-only module that happens to keep its WTW stage at 3.

    Returns a list of {'label', 'student_count', 'is_msc'} - one entry per
    level. A single-level module gets one entry with label=None.
    """
    by_code = getattr(module, 'student_count_by_code', {}) or {}
    h_count = sum(c for code, c in by_code.items() if code.endswith('H'))
    m_count = sum(c for code, c in by_code.items() if code.endswith('M'))

    if h_count > 0 and m_count > 0:
        return [
            {'label': 'H level', 'student_count': h_count, 'is_msc': False},
            {'label': 'M level', 'student_count': m_count, 'is_msc': True},
        ]

    student_count = module.student_count
    if student_count == 0:
        return []

    if m_count > 0 and h_count == 0:
        is_msc = True
    elif h_count > 0 and m_count == 0:
        is_msc = False
    else:
        # No H/M-coded students at all (e.g. stage 1-2 modules) - fall back
        # to the module's own stage.
        is_msc = config.is_msc_level(getattr(module, 'stage', 1))

    return [{'label': None, 'student_count': student_count, 'is_msc': is_msc}]


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

    levels = _classify_marking_levels(module)
    if not levels:
        return result

    # Determine marking type and rates
    is_automated = getattr(module, 'marking_type', 'manual') == 'automated'
    resit_fraction = 0.2  # 20% resits, applied to both automated and manual marking
    result['admin_flat'] = config.MARKING_AUTO_ADMIN if is_automated else config.MARKING_MANUAL_ADMIN

    level_breakdowns = []
    total_marking_hours = 0.0
    for level in levels:
        if is_automated:
            rate_per_script = config.MARKING_AUTO_MSC if level['is_msc'] else config.MARKING_AUTO_UG
        else:
            rate_per_script = config.MARKING_MANUAL_MSC if level['is_msc'] else config.MARKING_MANUAL_UG

        student_count = level['student_count']
        main_hrs = rate_per_script * student_count
        resit_student_count = student_count * resit_fraction
        resit_hrs = rate_per_script * resit_student_count
        level_total = main_hrs + resit_hrs
        total_marking_hours += level_total

        level_breakdowns.append({
            'label': level['label'],
            'rate_per_script': rate_per_script,
            'main_student_count': student_count,
            'main_hours': main_hrs,
            'resit_student_count': resit_student_count,
            'resit_hours': resit_hrs,
            'total_hours': level_total,
        })

    # Split equally among teachers
    per_teacher_hours = total_marking_hours / len(teachers) if teachers else 0.0

    for t in teachers:
        result['individual_hours'][t] = per_teacher_hours
        result['total_hours'] += per_teacher_hours

    result['details'] = f"{'Automated' if is_automated else 'Manual'}: {per_teacher_hours:.1f}h total (initial + resit)"

    # Structured breakdown for display (module-level totals, before splitting among teachers)
    result['marking_structured'] = {
        'is_automated': is_automated,
        'levels': level_breakdowns,
        'total_hours': total_marking_hours,
        'n_teachers': len(teachers),
        'hours_per_teacher': per_teacher_hours,
    }

    return result


# --- Teaching Workload ---


def _build_lecture_details(lecture_result: dict, teachers: List[str]) -> list:
    """Build lecture detail strings for display from lecture calculation results.

    Args:
        lecture_result: Dict from _calculate_lecture_hours_and_multipliers
        teachers: List of teacher names

    Returns:
        List of formatted detail strings for each lecturer type
    """
    teaching_details = []
    for lecturer_type in lecture_result['lecturer_types']:
        teacher_name, ltype = lecturer_type
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
    return teaching_details


def _build_module_detail_parts(teacher: str, lecture_result: dict, practical_result: dict,
                                hw_lab_details: list, drop_in_details: list,
                                assessment_details: list, marking_result: dict) -> list:
    """Build the detail parts list for a single teacher's module breakdown.

    Args:
        teacher: Teacher name
        lecture_result: Dict from _calculate_lecture_hours_and_multipliers
        practical_result: Dict from _calculate_practical_hours_and_breakdown
        hw_lab_details: List of HW lab detail strings
        drop_in_details: List of drop-in detail strings
        assessment_details: List of assessment detail strings
        marking_result: Dict from _calculate_assessment_marking_hours

    Returns:
        List of formatted detail strings for this teacher's module activities
    """
    module_detail_parts = []

    # Add lecture details (from helper result)
    if 'lecturer_types' in lecture_result:
        for lecturer_type in lecture_result['lecturer_types']:
            t, ltype = lecturer_type
            if t == teacher:
                base_share = lecture_result['lecture_hours'] / len(lecture_result.get('teachers', [])) if lecture_result.get('teachers') else 0
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

    return module_detail_parts


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

    # Check if this is a new content module (for HW lab multiplier selection)
    is_new_content_module = getattr(module, 'new_content', False)

    # --- Use helper functions for structured calculations ---

    # 1. Calculate lecture hours and multipliers per teacher
    lecture_result = _calculate_lecture_hours_and_multipliers(
        module, teachers, known_lecturers_global, known_lecturers_per_module
    )

    lecture_hours_with_mult = lecture_result['individual_lecture_hours']

    # Build lecture details for display (one-time, not per-teacher)
    teaching_details = _build_lecture_details(lecture_result, teachers)

    # 2. Calculate practical hours with structured breakdown
    # Pass lecturer_types so each teacher's multiplier is used for practical hours
    practical_result = _calculate_practical_hours_and_breakdown(
        module, teachers, lecture_result.get('lecturer_types', [])
    )

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
            teacher_supervision_hours.get(teacher, 0.0) +
            teacher_hw_lab +
            teacher_drop_in
        )

        # Build detail text for display using helper results
        module_detail_parts = _build_module_detail_parts(
            teacher, lecture_result, practical_result,
            hw_lab_details, drop_in_details, assessment_details, marking_result
        )

        # Build structured practicals breakdown from helper result
        teacher_practicals_structured = {}
        if 'practicals_breakdown' in practical_result:
            teacher_practicals_structured = practical_result['practicals_breakdown'].copy()

            # Per-teacher display values. The renderer previously derived these by
            # dividing this teacher's practical hours by the module base to recover
            # the rate that had been applied; compute them here instead so the
            # output layer only formats.
            if teacher_practicals_structured:
                _ps = teacher_practicals_structured
                _n_teachers = _ps.get('n_teachers', 1) or 1
                _week_count = _ps.get('week_count', contact_weeks)
                _first_session_hours = _ps.get('first_session_hours', 0)
                _base_per_teacher = _ps.get('total', 0) / _n_teachers
                _applied_rate = (
                    teacher_practical_hrs / _base_per_teacher if _base_per_teacher > 0
                    else _ps.get('first_session_rate', config.TEACHING_PROBLEM_CLASS)
                )
                _repeat_per_teacher = _ps.get('repeat_sessions_per_teacher', 0)
                # Parallel-group modules show one "first session" plus repeats;
                # single-session modules show only the combined calculation line.
                _fs_sessions = 1 if _repeat_per_teacher > 0 else max(1, _ps.get('groups_per_teacher', 1))
                _ps['applied_rate'] = _applied_rate
                _ps['first_session_sessions'] = _fs_sessions
                _ps['first_session_total'] = (
                    _fs_sessions * _first_session_hours * _applied_rate * _week_count
                )
                _ps['repeat_total'] = (
                    _repeat_per_teacher * _first_session_hours
                    * _ps.get('repeat_rate', config.REPETITION_MULTIPLIER) * _week_count
                )
                _ps['sessions_per_teacher'] = (
                    _ps.get('total', 0) / _n_teachers / (_first_session_hours * _week_count)
                    if _first_session_hours and _week_count else 1
                )

        # Build structured marking breakdown from helper result
        teacher_marking_structured = marking_result.get('marking_structured', {}).copy()

        # Structured delivery (lecture) breakdown. These are values the renderer
        # previously reverse-engineered by dividing displayed totals (teacher
        # count, applied multiplier, per-teacher base). Emitting them here keeps
        # the output layer to pure formatting.
        teacher_lecture_count = lecture_result.get('teacher_count', 0) or 1
        teacher_lecture_base = lecture_result.get('total_lecture_hours', 0.0) / teacher_lecture_count
        teacher_delivery_structured = {
            "teacher_count": teacher_lecture_count,
            "total_lecture_hours": lecture_result.get('total_lecture_hours', 0.0),
            "base_per_teacher": round(teacher_lecture_base, 4),
            "multiplier": lecture_result['lecture_multipliers'].get(teacher, 0.0),
            "lecturer_type": dict(lecture_result.get('lecturer_types', [])).get(teacher, 'standard'),
            "lectures_per_week": DEFAULT_LECURE_HOURS_PER_WEEK / 2.0,
            "week_count": contact_weeks,
        }

        result[teacher] = {
            "hours": total_teacher_hours,
            "teaching_breakdown": {
                "teaching": teacher_lecture_hours_with_mult,
                "practicals": teacher_practical_hrs,
                "assessment_setting": teacher_assessment_hours,
                "marking": marking_hours_per_teacher,
                "supervision": teacher_supervision_hours.get(teacher, 0.0),
                "hw_lab": teacher_hw_lab,
                "drop_in": teacher_drop_in,
                "online_content_dev": 0.0,  # Not calculated per-module in current implementation
                # Store the base contact hours (before multiplier) for display purposes
                "lecture_contact_hours": lecture_result['individual_lecture_contact_hours'].get(teacher, 0.0),
                # Store total lecture hours (before splitting among teachers) for display
                "total_lecture_hours": lecture_result.get('total_lecture_hours', 0.0),
            },
            "practicals_breakdown": teacher_practicals_structured,
            "marking_breakdown": teacher_marking_structured,
            "delivery_breakdown": teacher_delivery_structured,
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
        Tuple of (total_hours, structured_breakdown_dict, detail_string, grant_titles_dict) where:
            - total_hours: Sum of all research activities (excluding protected baseline)
            - structured_breakdown_dict: Nested dict with grants and phd_students as separate entries
                Example structure:
                {
                    "grants": {"grant_ABC": 164.2, "grant_XYZ": 82.1},
                    "phd_students": {
                        "supervision": {"count": 3, "rate": 80.0, "total": 240.0},
                        "co_supervision": {"count": 3, "rate": 48.0, "total": 144.0},
                        "assessor": {"count": 4, "rate": 8.0, "total": 32.0}
                    }
                }
            - detail_string: Human-readable summary
            - grant_titles_dict: Mapping of project IDs to display titles
    """
    total = 0.0
    details = []
    structured_breakdown = {
        "grants": {},
        "phd_students": {}
    }
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
        phd_breakdown["supervision"] = {
            "count": sole_count,
            "rate": config.SUPERVISION_MULTIPLIERS["pgr_primary_supervisor_per_fte"],
            "total": round(sole_hours, 2)
        }
        phd_details.append(f"{sole_count}x full-time PhD student × {config.SUPERVISION_MULTIPLIERS['pgr_primary_supervisor_per_fte']}h/FTE")

    # Co-supervisors - part-time PhD students (60% of primary)
    if staff_member.phd_co_supervisions > 0:
        co_count = staff_member.phd_co_supervisions
        co_hours = co_count * config.SUPERVISION_MULTIPLIERS["pgr_co_supervisor_per_fte"]
        phd_hours += co_hours
        phd_breakdown["co_supervision"] = {
            "count": co_count,
            "rate": config.SUPERVISION_MULTIPLIERS["pgr_co_supervisor_per_fte"],
            "total": round(co_hours, 2)
        }
        phd_details.append(f"{co_count}x part-time PhD student × {config.SUPERVISION_MULTIPLIERS['pgr_co_supervisor_per_fte']}h/FTE")

    # TAP assessor work (assessor for PhD students)
    if staff_member.phd_assessor_count > 0:
        assessor_count = staff_member.phd_assessor_count
        assessor_hours = assessor_count * config.SUPERVISION_MULTIPLIERS["pgr_assessor"]
        phd_hours += assessor_hours
        phd_breakdown["assessor"] = {
            "count": assessor_count,
            "rate": config.SUPERVISION_MULTIPLIERS["pgr_assessor"],
            "total": round(assessor_hours, 2)
        }
        phd_details.append(f"{assessor_count}x assessor ({config.SUPERVISION_MULTIPLIERS['pgr_assessor']}h each)")

    if phd_hours > 0:
        total += phd_hours
        structured_breakdown["phd_students"].update(phd_breakdown)
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
            structured_breakdown["grants"][f"grant_{project_id}"] = grant_hours
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

    return total, structured_breakdown, "; ".join(details) if details else "No research activities recorded", grant_titles, assumptions


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


def _apply_adjustments(staff_member: StaffData, calculated: Dict[str, float],
                        missing_data: List[str]) -> tuple:
    """Apply workload_adjustments.csv entries on top of calculated category totals.

    Args:
        staff_member: StaffData carrying the parsed adjustments (and any warnings
            from malformed/incomplete adjustment rows) for this person.
        calculated: {"teaching": teaching_hours, "research": research_total, "admin": admin_hours}
            - the calculated totals before any manual adjustment.
        missing_data: The in-progress missing_data list for this staff member -
            conflicts, negative-result rejections, and file-level parse warnings
            are appended to it directly (no guessed data - see CLAUDE.md).

    Returns:
        (adjusted_values, adjustments_breakdown) where:
            - adjusted_values: dict with the same keys as `calculated`, replaced by the
              adjusted total for any category that had an adjustment applied.
            - adjustments_breakdown: {category: {"mode", "calculated_total",
              "adjusted_total", "delta", "entries": (...)}} for categories that
              actually got an adjustment applied (conflicts/rejections are NOT
              included here - they show up only via missing_data).

    Conflict (multiple absolutes, or absolute+delta mixed for one category) or a
    result that would go negative -> apply nothing for that category, flag via
    missing_data. Otherwise the adjustment becomes the new authoritative total for
    that category, consumed by every downstream total (this function's caller
    reassigns teaching_hours/research_total/admin_hours from the returned dict
    before total_hours is summed, so nominal-hours comparison, department "Needs
    Attention", and normative-split logic all automatically reflect adjustments).
    """
    for warning in staff_member.adjustment_warnings:
        missing_data.append(f"Adjustment file: {warning}")

    adjusted_values = dict(calculated)
    adjustments_breakdown: Dict[str, Dict] = {}

    by_category: Dict[str, List[AdjustmentRecord]] = {}
    for adj in staff_member.adjustments:
        if adj.category == "teaching" and adj.module:
            continue  # handled by _apply_teaching_module_adjustments()
        by_category.setdefault(adj.category, []).append(adj)

    for category, calculated_value in calculated.items():
        entries = by_category.get(category, [])
        if not entries:
            continue

        absolutes = [e for e in entries if e.mode == "absolute"]
        deltas = [e for e in entries if e.mode == "delta"]

        if len(absolutes) > 1 or (absolutes and deltas):
            missing_data.append(
                f"{category.title()} adjustment conflict: {len(absolutes)} absolute "
                f"override(s) and {len(deltas)} delta(s) in workload_adjustments.csv - "
                f"no adjustment applied; calculated value ({calculated_value:.1f}h) used.")
            continue

        if absolutes:
            mode, adjusted_value, display_entries = "absolute", absolutes[0].value, absolutes
        else:
            mode = "delta"
            adjusted_value = calculated_value + sum(e.value for e in deltas)
            display_entries = deltas

        if adjusted_value < 0:
            missing_data.append(
                f"{category.title()} adjustment would result in negative hours "
                f"({adjusted_value:.1f}h) - no adjustment applied; calculated value "
                f"({calculated_value:.1f}h) used instead.")
            continue

        adjusted_values[category] = adjusted_value
        adjustments_breakdown[category] = {
            "mode": mode,
            "calculated_total": round(calculated_value, 2),
            "adjusted_total": round(adjusted_value, 2),
            "delta": round(adjusted_value - calculated_value, 2),
            "entries": tuple(
                {"mode": e.mode, "amount": e.value, "rationale": e.rationale, "source_row": e.source_row}
                for e in display_entries
            ),
        }

    return adjusted_values, adjustments_breakdown


def _apply_teaching_module_adjustments(staff_member: StaffData, teaching_module_breakdowns: Dict[str, Dict],
                                        missing_data: List[str]) -> float:
    """Apply module-scoped Teaching entries from workload_adjustments.csv (Teaching Module filled).

    Args:
        staff_member: StaffData carrying the parsed adjustments for this person.
        teaching_module_breakdowns: this person's raw per-module teaching breakdown dicts
            (the same dict object that a shallow copy later becomes
            WorkloadResult.teaching_module_breakdowns from) - mutated IN PLACE so the caller
            automatically sees the result with no further wiring.
        missing_data: the in-progress missing_data list for this staff member - unresolved
            module names, conflicts, and negative-result rejections are appended to it directly
            (no guessed data - see CLAUDE.md).

    Returns:
        The total delta (adjusted - calculated) across all successfully-applied module-scoped
        adjustments, to be added to the person's overall teaching_hours (0.0 if none applied).

    Module-name resolution is a case-insensitive EXACT match against this person's
    teaching_module_breakdowns keys (the section-heading names shown in their report) - no
    fuzzy/substring matching, per the project's "no guessed data" rule. Conflict/negative-result
    handling mirrors _apply_adjustments()'s category-level logic exactly, but scoped to
    (category, module) instead of category alone - SYS2 and SYS3 adjustments for the same person
    are completely independent of each other and of any category-wide (blank-module) adjustment.
    """
    teaching_module_entries = [
        adj for adj in staff_member.adjustments
        if adj.category == "teaching" and adj.module
    ]
    if not teaching_module_entries:
        return 0.0

    name_map = {name.casefold(): name for name in teaching_module_breakdowns}

    groups: Dict[str, List[AdjustmentRecord]] = {}
    for adj in teaching_module_entries:
        canonical = name_map.get(adj.module.strip().casefold())
        if canonical is None:
            taught = sorted(teaching_module_breakdowns)
            taught_desc = f"they teach: {', '.join(taught)}" if taught else "they teach no modules this year"
            missing_data.append(
                f"row {adj.source_row}: Teaching adjustment for module '{adj.module}' not applied - "
                f"no exact match in {staff_member.canonical_name}'s modules ({taught_desc}).")
            continue
        groups.setdefault(canonical, []).append(adj)

    total_delta = 0.0
    for canonical, entries in groups.items():
        module_breakdown = teaching_module_breakdowns[canonical]
        module_calculated = sum(
            v for k, v in module_breakdown.items()
            if k in _TEACHING_MODULE_SUM_KEYS and isinstance(v, (int, float))
        )

        absolutes = [e for e in entries if e.mode == "absolute"]
        deltas = [e for e in entries if e.mode == "delta"]

        if len(absolutes) > 1 or (absolutes and deltas):
            missing_data.append(
                f"Teaching adjustment conflict for module '{canonical}': {len(absolutes)} absolute "
                f"override(s) and {len(deltas)} delta(s) in workload_adjustments.csv - "
                f"no adjustment applied; calculated value ({module_calculated:.1f}h) used.")
            continue

        if absolutes:
            mode, adjusted_value, display_entries = "absolute", absolutes[0].value, absolutes
        else:
            mode = "delta"
            adjusted_value = module_calculated + sum(e.value for e in deltas)
            display_entries = deltas

        if adjusted_value < 0:
            missing_data.append(
                f"Teaching adjustment for module '{canonical}' would result in negative hours "
                f"({adjusted_value:.1f}h) - no adjustment applied; calculated value "
                f"({module_calculated:.1f}h) used instead.")
            continue

        delta = round(adjusted_value - module_calculated, 2)
        module_breakdown["manual_adjustment"] = delta
        module_breakdown["adjustment_breakdown"] = {
            "mode": mode,
            "calculated_total": round(module_calculated, 2),
            "adjusted_total": round(adjusted_value, 2),
            "delta": delta,
            "entries": tuple(
                {"mode": e.mode, "amount": e.value, "rationale": e.rationale, "source_row": e.source_row}
                for e in display_entries
            ),
        }
        total_delta += delta

    return total_delta


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
        validation_result = run_validation_pipeline_input(year_data)
        if validation_result["has_warnings"]:
            # Surface input warnings on the console. They are additionally
            # attached to the affected staff below (see estimated_student_modules)
            # so they appear in the reports rather than being silently dropped.
            for issue in validation_result["issues"]:
                print(f"  Data warning: {issue.message}")

    # Modules whose student numbers are a fabricated default rather than real
    # data. Anyone teaching one has estimated marking hours, so this is recorded
    # against them as missing data and shown in their report.
    estimated_student_modules = {
        m.name for m in year_data.modules
        if m.student_count == config.DEFAULT_STUDENT_COUNT
    }

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
                # Store structured practicals breakdown per module if available (separate from teaching_breakdown)
                if "practicals_breakdown" in breakdown and breakdown["practicals_breakdown"]:
                    staff_teaching[teacher]["teaching_module_breakdowns"][module.name].update({
                        "practicals_structured": breakdown["practicals_breakdown"]
                    })
                # Store structured marking breakdown per module if available (separate from teaching_breakdown)
                if "marking_breakdown" in breakdown and breakdown["marking_breakdown"]:
                    staff_teaching[teacher]["teaching_module_breakdowns"][module.name].update({
                        "marking_structured": breakdown["marking_breakdown"]
                    })
                # Store structured delivery/lecture breakdown per module if available
                if "delivery_breakdown" in breakdown and breakdown["delivery_breakdown"]:
                    staff_teaching[teacher]["teaching_module_breakdowns"][module.name].update({
                        "delivery_structured": breakdown["delivery_breakdown"]
                    })
                # Store module code as structured data (Phase 3: avoid regex parsing)
                if module.codes:
                    staff_teaching[teacher]["teaching_module_breakdowns"][module.name].update({
                        "module_codes": tuple(sorted(set(module.codes)))
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

        # Teaching hours come solely from module involvement and supervision.
        # There is deliberately no baseline/minimum teaching allowance: staff not
        # associated with any module get 0 teaching hours. They still receive the
        # departmental engagement baseline and personal development allowance,
        # which are counted under admin, not teaching.
        teaching_hours = staff_teaching.get(canonical_name, {}).get("hours", 0.0)

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

        # Project setting allowance - removed from teaching hours calculation
        # Per the workload model, project setting is not included in teaching total

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

        # Add protected baseline as a top-level entry, with grants and phd_students nested
        # This creates the hierarchical structure: protected_research_baseline at top level,
        # then grants dict and phd_students dict as separate entries
        structured_research_breakdown = {
            "protected_research_baseline": protected_research,
            **research_breakdown  # Unpack grants and phd_students from _calculate_research_workload
        }

        # Total research = protected baseline + additional work from grants/supervision
        research_total = protected_research + research_hours

        # Administration
        admin_hours, admin_breakdown, admin_detail = _calculate_admin_workload(staff, nominal_hours)

        # Apply module-scoped Teaching adjustments (Teaching Module column filled in
        # workload_adjustments.csv) first, mutating this person's raw per-module breakdown
        # dicts in place - the same dict object teaching_module_breakdowns is built from
        # below, so the mutation is automatically visible everywhere downstream. Must run
        # before _apply_adjustments() below, which now skips these entries (they're handled
        # here instead) and only applies category-wide (blank Teaching Module) adjustments.
        module_adjustment_total = _apply_teaching_module_adjustments(
            staff,
            staff_teaching.get(canonical_name, {}).get("teaching_module_breakdowns", {}),
            missing_data,
        )
        teaching_hours += module_adjustment_total

        # Apply manual workload adjustments (data/workload_adjustments.csv), if any,
        # on top of the calculated category totals. This is the ONLY place adjustments
        # are applied - reassigning here means every downstream consumer (nominal-hours
        # comparison, department "Needs Attention", normative split) automatically
        # reflects the adjusted values with no changes needed elsewhere.
        adjusted_totals, adjustments_breakdown = _apply_adjustments(
            staff,
            {"teaching": teaching_hours, "research": research_total, "admin": admin_hours},
            missing_data,
        )
        teaching_hours = adjusted_totals["teaching"]
        research_total = adjusted_totals["research"]
        admin_hours = adjusted_totals["admin"]

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

        def _aggregate_teaching_breakdown(staff_data):
            """Aggregate teaching breakdowns from all modules for a staff member.

            Sums per-module teaching components and combines with supervision components
            that are already at staff level.
            """
            aggregated = {}

            # Keys that should be summed across modules (only numeric values, not nested dicts)
            sum_keys = _TEACHING_MODULE_SUM_KEYS

            module_breakdowns = staff_data.get("teaching_module_breakdowns", {})
            for module_name, module_breakdown in module_breakdowns.items():
                for key in sum_keys:
                    if key in module_breakdown:
                        value = module_breakdown[key]
                        # Only sum if the value is numeric (not a nested dict like practicals_breakdown)
                        if isinstance(value, (int, float)):
                            aggregated[key] = aggregated.get(key, 0.0) + value
                        # If it's a dict, skip it - those are structured breakdowns for display

            # Include supervision components (already at staff level, not summed)
            if "pastoral_supervision" in staff_data.get("teaching_breakdown", {}):
                aggregated["pastoral_supervision"] = staff_data["teaching_breakdown"]["pastoral_supervision"]
            if "project_supervision" in staff_data.get("teaching_breakdown", {}):
                aggregated["project_supervision"] = staff_data["teaching_breakdown"]["project_supervision"]
            if "project_setting" in staff_data.get("teaching_breakdown", {}):
                aggregated["project_setting"] = staff_data["teaching_breakdown"]["project_setting"]

            return aggregated

        # Build structured teaching breakdown from per-module data
        teaching_breakdown = {}
        teaching_module_breakdowns = {}
        if canonical_name in staff_teaching:
            staff_data = staff_teaching[canonical_name]
            # Per-module teaching_breakdown for accurate display
            if "teaching_module_breakdowns" in staff_data and staff_data["teaching_module_breakdowns"]:
                teaching_module_breakdowns = dict(staff_data["teaching_module_breakdowns"])
            # Aggregated teaching_breakdown (sum of all modules)
            if "teaching_module_breakdowns" in staff_data and staff_data["teaching_module_breakdowns"]:
                # Use new aggregation function to sum per-module breakdowns
                teaching_breakdown = _aggregate_teaching_breakdown(staff_data)
            elif len(staff_data.get("details", [])) > 0:
                # Fallback: parse from details string for backward compatibility
                if "teaching_breakdown" in staff_data and staff_data["teaching_breakdown"]:
                    teaching_breakdown = _sum_breakdown_dict(staff_data["teaching_breakdown"])

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

        # Flag estimated marking hours for anyone teaching a module with no real
        # student numbers, so the report says so rather than presenting the
        # default count as fact.
        taught_estimated = sorted(
            estimated_student_modules
            & set(staff_teaching.get(canonical_name, {}).get("teaching_module_breakdowns", {}))
        )
        for module_name in taught_estimated:
            missing_data.append(
                f"{module_name}: no student numbers in CS Module Numbers.csv - "
                f"marking hours estimated from a default of {config.DEFAULT_STUDENT_COUNT} students"
            )

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

        # Reconcile manual adjustments into the finalized breakdown dicts: add a single
        # scalar "manual_adjustment" key (the delta actually applied) into each adjusted
        # category's breakdown. This keeps the calculated sub-items (Delivery, Practicals,
        # Marking, grants, PhD supervision, departmental roles, ...) untouched and visible,
        # while keeping sum(breakdown.values()) == the category total in both delta and
        # absolute-override modes (delta = adjusted_total - calculated_total by
        # construction either way).
        if "teaching" in adjustments_breakdown:
            teaching_breakdown["manual_adjustment"] = adjustments_breakdown["teaching"]["delta"]
        if "research" in adjustments_breakdown:
            structured_research_breakdown["manual_adjustment"] = adjustments_breakdown["research"]["delta"]
        if "admin" in adjustments_breakdown:
            admin_breakdown["manual_adjustment"] = adjustments_breakdown["admin"]["delta"]

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
            research_breakdown=structured_research_breakdown,
            admin_breakdown=admin_breakdown,
            nominal_hours=nominal_hours,
            grant_titles=grant_titles,
            module_details=tuple(module_details),  # Convert to tuple for frozen dataclass
            supervision_details=tuple(unique_supervision),  # Convert to tuple for frozen dataclass
            pastoral_breakdown=pastoral_breakdown,  # Structured pastoral supervision breakdown
            project_breakdown=project_breakdown,  # Structured project supervision breakdown
            adjustments_breakdown=adjustments_breakdown,  # Manual workload_adjustments.csv overrides applied
        )
        results.append(result)

    return results
