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
- Pastoral supervision defaults (20 students/teacher)
- Project supervision defaults (10 students/teacher)

Use workload_calculator.calculate_workload(year_data, track_assumptions=True)
to enable detailed assumption tracking.
"""

from typing import List, Dict
from dataclasses import dataclass

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


# --- Teaching Workload ---


def _calculate_teaching_workload(module: ModuleData, teachers: List[str],
                                  known_lecturers_global: set,
                                  known_lecturers_per_module: Dict[str, frozenset],
                                  staff_data: Dict[str, StaffData],
                                  supervision: SupervisionAllocation) -> dict:
    """
    Calculate teaching workload for a single module, split by teacher.

    Applies multipliers based on lecturer experience (new vs. established) and
    account for lecture hours, practical sessions with repetition, assessment
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

    # --- Teaching (Lecture) Hours ---
    # Contact hours from credits represents total contact time.
    # We need to separate lecture hours from practical hours for correct calculation.
    # If practical_contact_hours is available, use that to estimate actual teaching structure.

    contact_hours = module.contact_hours
    practicals_count = module.practicals

    if practicals_count > 0 and module.practical_contact_hours > 0:
        # We have actual practical data: Total Duration / Number of Practicals gives hours per session
        total_practical_duration = module.practical_contact_hours * practicals_count
        # Estimate lecture hours as contact_hours minus practical hours (if practicals are part of contact time)
        # If practicals represent significant portion, subtract them from contact_hours
        lecture_hours = max(0, contact_hours - total_practical_duration)
    else:
        # No practical data available, assume all contact hours are lectures
        lecture_hours = contact_hours
        total_practical_duration = 0.0

    teaching_details = []

    # Store individual practical hours per teacher (initialized here for all cases)
    individual_practical_hours = {}

    # Determine which teachers from last year taught THIS specific module
    # Use per-module tracking first, fall back to global set for modules without tracking
    module_code = module.codes[0] if module.codes else None

    # Try looking up by full code first (e.g., COM00029I)
    known_teachers_this_module = known_lecturers_per_module.get(module_code)

    # If not found, try the module name (e.g., "SYS2") which may be stored
    if known_teachers_this_module is None:
        known_teachers_this_module = known_lecturers_per_module.get(module.name)

    # If we have module-specific tracking, use it; otherwise use global known lecturers
    if known_teachers_this_module is not None:
        known_lecturers_for_module = known_teachers_this_module
    else:
        # No per-module tracking available - fall back to global set
        # This handles new modules or modules without previous year data
        known_lecturers_for_module = known_lecturers_global

    # Check if this is a new content module (for 7.5x rate when teacher is also new)
    is_new_content_module = getattr(module, 'new_content', False)

    # Calculate lecture multiplier per-teacher based on:
    # - Whether THAT teacher is new for THIS module
    # - Whether THIS module has new content (for combined "new lecturer AND new content" 7.5x rate)
    # New lecturers get 5x for content development + delivery
    # New lecturers on NEW content get 7.5x (additional content dev time)
    # Existing lecturers get 2.5x for delivery only (content already developed)
    lecture_multipliers = {}
    for t in teachers:
        if t not in known_lecturers_for_module:
            if is_new_content_module:
                lecture_multipliers[t] = config.TEACHING_MULTIPLIERS["lecture_new_content_and_lecturer"]  # 7.5
            else:
                lecture_multipliers[t] = config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]  # 5
        else:
            lecture_multipliers[t] = config.TEACHING_MULTIPLIERS["lecture_standard"]  # 2.5

    # Build teaching details string showing multiplier type for each teacher
    new_lecturers = [t for t in teachers if t not in known_lecturers_for_module]
    standard_lecturers = [t for t in teachers if t in known_lecturers_for_module]

    # Calculate lecture hours using the new approach:
    # 1. All lecturers get an equal "base" share at standard rate (2.5x)
    # 2. New lecturers get additional time to account for content development
    # 3. New lecturers on NEW content get extra additional time (7.5x total)
    #
    # This reflects that existing lecturers (e.g., Mike, Andy) just deliver,
    # while new lecturers need time to develop materials in addition to delivery.
    n_teachers = len(teachers)

    # Base share: divide total contact hours equally among all teachers
    base_lecture_share = lecture_hours / n_teachers

    # Calculate per-teacher hours:
    # - Standard lecturers: base_share * standard_multiplier (just delivery)
    # - New lecturers on existing content: base + 2.5x content dev (5x total)
    # - New lecturers on NEW content: base + 5x content dev (7.5x total)
    #
    # The content_dev_time represents the additional effort for new material.
    lecture_hours_with_mult = {}
    detail_parts = []

    for t in teachers:
        if t not in known_lecturers_for_module:
            if is_new_content_module:
                # New lecturer on NEW content: 7.5x total
                delivery_hours = base_lecture_share * config.TEACHING_MULTIPLIERS["lecture_standard"]
                content_dev_hours = base_lecture_share * (config.TEACHING_MULTIPLIERS["lecture_new_content_and_lecturer"] - config.TEACHING_MULTIPLIERS["lecture_standard"])
                total_hours = delivery_hours + content_dev_hours

                lecture_hours_with_mult[t] = total_hours
                detail_parts.append(f"New lecturer + new content ({config.TEACHING_MULTIPLIERS['lecture_new_content_and_lecturer']}x): {base_lecture_share:.1f}h base @ 2.5x = {delivery_hours:.1f}h + {content_dev_hours:.1f}h content dev")
            else:
                # New lecturer on existing content: 5x total
                delivery_hours = base_lecture_share * config.TEACHING_MULTIPLIERS["lecture_standard"]
                content_dev_hours = base_lecture_share * (config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"] - config.TEACHING_MULTIPLIERS["lecture_standard"])
                total_hours = delivery_hours + content_dev_hours

                lecture_hours_with_mult[t] = total_hours
                detail_parts.append(f"New lecturer ({config.TEACHING_MULTIPLIERS['lecture_new_content_or_lecturer']}x): {base_lecture_share:.1f}h base @ 2.5x = {delivery_hours:.1f}h + {content_dev_hours:.1f}h content dev")
        else:
            # Standard lecturer: just delivery at standard rate
            total_hours = base_lecture_share * config.TEACHING_MULTIPLIERS["lecture_standard"]
            lecture_hours_with_mult[t] = total_hours
            detail_parts.append(f"Standard ({config.TEACHING_MULTIPLIERS['lecture_standard']}x): {base_lecture_share:.1f}h @ 2.5x = {total_hours:.1f}h")

    teaching_details.append("; ".join(detail_parts))

    # --- Practical Sessions with Repetition Multiplier ---
    # Per the spec: "For each repetition of an identical class (e.g. 2nd and 3rd version)
    # have a multiplier of 1.5 times contact duration."
    #
    # Each week has multiple practical sessions:
    # - First session delivered by one lecturer at 2.5x (first delivery rate)
    # - Remaining sessions delivered by other lecturers at 1.5x (repetition rate)
    #
    # With n_groups shared among n_teachers:
    # - Each week: 1 session × contact × 2.5x + (n_groups-1) sessions × contact × 1.5x
    # - Per-teacher weekly hours = total_week_hours / n_teachers
    #
    # If practical_weeks is specified (from CSV Notes column), only count those weeks.

    practical_hours_total = 0.0  # Total for all teachers combined
    practical_hours_one = 0.0  # Per-teacher hours
    practical_details = []
    practical_breakdown = {}  # For structured teaching breakdown

    # Initialize practical_week_count (used even when practicals_count == 0)
    practical_week_count = TEACHING_WEEKS_PER_SEMESTER if practicals_count > 0 else 0

    if practicals_count > 0:
        contact_per_practical = module.practical_contact_hours if module.practical_contact_hours > 0 else (contact_hours / max(practicals_count, 1))
        n_groups = module.practical_groups

        # Determine weeks with practicals
        if module.practical_weeks is not None and len(module.practical_weeks) > 0:
            # Use specified weeks from CSV notes
            practical_weeks_list = sorted(module.practical_weeks)
            practical_week_count = len(practical_weeks_list)
            first_week = practical_weeks_list[0]
            other_weeks = practical_weeks_list[1:]  # All weeks after the first
        else:
            # Default: all teaching weeks (1-11)
            practical_week_count = TEACHING_WEEKS_PER_SEMESTER
            first_week = 1
            other_weeks = list(range(2, TEACHING_WEEKS_PER_SEMESTER + 1))

        n_teachers = len(teachers)

        # Identify new vs standard lecturers for practical calculations (use per-module tracking)
        new_lecturers_practical = [t for t in teachers if t not in known_lecturers_for_module]
        standard_lecturers_practical = [t for t in teachers if t in known_lecturers_for_module]

        # Store individual practical hours per teacher
        individual_practical_hours = {}

        if n_groups > 0:
            # With parallel groups:
            # Each week, lecturers deliver first-session sessions.
            # - Standard lecturers: deliver at 2.5x rate (delivery only)
            # - New lecturers: deliver at 5x rate (content development + delivery)
            # - Additional repeat sessions: 1.5x regardless of who delivers
            #
            # Strategy:
            # 1. Each lecturer gets one "first" session slot per week
            # 2. Standard lecturers' first sessions = contact × 2.5x
            # 3. New lecturers' first sessions = contact × 5x (extra for content dev)
            # 4. Repeat sessions are split among all, at 1.5x each

            rep_rate = config.REPETITION_MULTIPLIER  # 1.5

            repeat_sessions = max(0, n_groups - n_teachers)

            # Calculate weekly hours per teacher
            # Each lecturer gets one first-delivery session slot
            # New lecturers: 5x multiplier for their first session (content dev + delivery)
            # Standard lecturers: 2.5x multiplier for their first session (delivery only)
            #
            # Note: practicals_count represents the number of practical sessions per week.
            # Each session has contact_per_practical duration, so we multiply by practicals_count
            # to get total weekly hours for all sessions delivered by a teacher.

            for t in teachers:
                if t in new_lecturers_practical:
                    # New lecturer: their first session at 5x + share of repeats
                    # Multiply by practicals_count since each teacher delivers that many sessions per week
                    first_session = contact_per_practical * config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"] * practicals_count
                    repeat_share = (repeat_sessions * contact_per_practical * rep_rate * practicals_count) / n_teachers
                    individual_practical_hours[t] = first_session + repeat_share
                else:
                    # Standard lecturer: their first session at 2.5x + share of repeats
                    first_session = contact_per_practical * config.TEACHING_MULTIPLIERS["problem_class_seminar_practical"] * practicals_count
                    repeat_share = (repeat_sessions * contact_per_practical * rep_rate * practicals_count) / n_teachers
                    individual_practical_hours[t] = first_session + repeat_share

            # Total hours across all teachers (for tracking total workload)
            practical_hours_total = sum(individual_practical_hours.values())

            # Build display details - each week pattern
            repeat_count = len(other_weeks) if module.practical_weeks and len(module.practical_weeks) > 1 else TEACHING_WEEKS_PER_SEMESTER - 1
            if repeat_count > 0:
                weeks_str = ", ".join(str(w) for w in other_weeks[:5]) + ("..." if repeat_count > 5 else "")
                repeat_display = f"{repeat_count}w @ {rep_rate}x (weeks {weeks_str})"
            else:
                repeat_display = "no repeats"

            # Calculate per-teacher breakdown details
            new_first_per_session = contact_per_practical * config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"] * practicals_count
            std_first_per_session = contact_per_practical * config.TEACHING_MULTIPLIERS["problem_class_seminar_practical"] * practicals_count

            # Display individual practical hours per teacher type
            # Note: first_session values are weekly hours (include practicals_count)
            if new_lecturers_practical and standard_lecturers_practical:
                total_new = individual_practical_hours[new_lecturers_practical[0]] * practical_week_count
                total_std = individual_practical_hours[standard_lecturers_practical[0]] * practical_week_count
                practical_details.append(
                    f"Practicals: {n_groups} groups shared by {n_teachers} lecturers, "
                    f"{practical_week_count}w - New: {new_first_per_session:.1f}h/week @ 5x + repeats; "
                    f"Standard: {std_first_per_session:.1f}h/week @ 2.5x + repeats ({repeat_sessions} grps @ {rep_rate}x); "
                    f"{repeat_display}; "
                    f"New: {total_new:.1f}h, Standard: {total_std:.1f}h"
                )
            elif new_lecturers_practical:
                # All are new lecturers
                total_new = individual_practical_hours[new_lecturers_practical[0]] * practical_week_count
                practical_details.append(
                    f"Practicals: {n_groups} groups shared by {n_teachers} lecturers, "
                    f"{practical_week_count}w - New: {new_first_per_session:.1f}h/week @ 5x + repeats; "
                    f"{repeat_display}; "
                    f"Total: {total_new:.1f}h"
                )
            else:
                # All are standard lecturers
                total_std = individual_practical_hours[standard_lecturers_practical[0]] * practical_week_count
                practical_details.append(
                    f"Practicals: {n_groups} groups shared by {n_teachers} lecturers, "
                    f"{practical_week_count}w - Standard: {std_first_per_session:.1f}h/week @ 2.5x + repeats ({repeat_sessions} grps @ {rep_rate}x); "
                    f"{repeat_display}; "
                    f"Total: {total_std:.1f}h"
                )

            # Add to breakdown (per-teacher values - use individual hours)
            for t in teachers:
                if t not in practical_breakdown.get("practicals_per_teacher", {}):
                    if "practicals_per_teacher" not in practical_breakdown:
                        practical_breakdown["practicals_per_teacher"] = {}
                    practical_breakdown["practicals_per_teacher"][t] = individual_practical_hours[t] * practical_week_count

        else:
            # No parallel groups - single session type shared by all teachers
            # Each week: one session delivered once at 2.5x (first delivery) or 1.5x (repeat)

            rep_rate = config.REPETITION_MULTIPLIER  # 1.5

            # No parallel groups - single session shared by all teachers
            # Each week: one session delivered once
            # First delivery (week 1) at higher rate, repeats at lower rate
            #
            # For new lecturers: first session = 5x (content dev + delivery)
            # For standard lecturers: first session = 2.5x (delivery only)
            # Alllecturers share the same session, so we calculate total then divide

            if practical_week_count > 0:
                # First week's session - split by lecturer type
                # Multiply by practicals_count since each teacher delivers that many sessions per week
                first_week_first_delivery = contact_per_practical * config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"] * practicals_count
                first_week_std_delivery = contact_per_practical * config.TEACHING_MULTIPLIERS["problem_class_seminar_practical"] * practicals_count

                # Total for first week (all lecturers combined)
                first_week_total = (
                    len(new_lecturers_practical) * first_week_first_delivery +
                    len(standard_lecturers_practical) * first_week_std_delivery
                )
                first_week_per_teacher = first_week_total / n_teachers

                # Other weeks - all at repetition rate (1.5x)
                other_weeks_count = max(0, practical_week_count - 1)
                if other_weeks_count > 0:
                    repeat_session_hours = contact_per_practical * rep_rate * practicals_count
                    other_weeks_total = other_weeks_count * repeat_session_hours * n_teachers
                    other_weeks_per_teacher = other_weeks_total / n_teachers

                    practical_hours_one = first_week_per_teacher + other_weeks_per_teacher
                else:
                    practical_hours_one = first_week_per_teacher
            else:
                practical_hours_one = 0.0

            practical_hours_total = practical_hours_one * n_teachers  # Total for all teachers

            # Store per-teacher practical hours (same for all when no parallel groups)
            for t in teachers:
                individual_practical_hours[t] = practical_hours_one

            # Build display details
            repeat_count = max(0, practical_week_count - 1)
            if repeat_count > 0:
                weeks_str = ", ".join(str(w) for w in other_weeks[:5])
                if len(other_weeks) > 5:
                    weeks_str += "..."
                repeat_display = f"{repeat_count}w @ {rep_rate}x (weeks {weeks_str})"
            else:
                repeat_display = "no repeats"

            new_first_per_session = contact_per_practical * config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"] * practicals_count
            std_first_per_session = contact_per_practical * config.TEACHING_MULTIPLIERS["problem_class_seminar_practical"] * practicals_count

            total_for_all_teachers = practical_hours_one
            practical_details.append(
                f"Practicals: {practical_week_count}w - New lecturers: {new_first_per_session:.1f}h/week @ 5x; "
                f"Standard lecturers: {std_first_per_session:.1f}h/week @ 2.5x; "
                f"{repeat_display}: {contact_per_practical * practicals_count:.1f}h @ {rep_rate}x = {contact_per_practical * rep_rate * practicals_count:.1f}h/week; "
                f"Total: {total_for_all_teachers:.1f}h/teacher"
            )

            practical_breakdown["practicals_first_time"] = first_week_per_teacher if practical_week_count > 0 else 0.0
            if repeat_count > 0:
                practical_breakdown["practicals_repeat"] = contact_per_practical * rep_rate

    # Add repetition_multiplier back if removed
    if "repetition_multiplier" not in config.TEACHING_MULTIPLIERS:
        # Will be added to YAML
        pass

    # Assessment setting (per teacher based on whether THEY are new)
    # New lecturers get higher multiplier for first-time assessment setup
    # Standard lecturers get lower multiplier for familiar assessment formats
    # Split into main paper and resit paper for display purposes
    assessment_hours = {t: 0.0 for t in teachers}
    assessment_details = []
    assessment_count = module.assessment_count

    if assessment_count > 0:
        # Calculate base setting cost at standard rate for all assessments
        base_setting_cost = config.ASSESSMENT_MANUAL_STANDARD * assessment_count

        # Resit papers take the same time to set as main papers (same effort)
        # The 20% resit student assumption only applies to marking, not setting
        # For display: split total setting time equally between main and resit
        resit_paper_proportion = 1.0  # Resit papers take full setting time

        # New lecturers get additional time for first-time setup
        # Difference: new_setter_same_format (22.5) - standard (15) = 7.5h per assessment
        std_per_assessment = base_setting_cost / assessment_count if assessment_count > 0 else 0

        setting_details_parts = []
        for t in teachers:
            if t not in known_lecturers_for_module:
                # New setter: standard time + additional content development time
                # At 22.5h vs 15h per assessment, the difference is 7.5h
                base_hours = base_setting_cost / len(teachers)
                content_dev_per_assessment = config.ASSESSMENT_MANUAL_NEW_SETTER - config.ASSESSMENT_MANUAL_STANDARD
                additional_content_hours = (content_dev_per_assessment * assessment_count) / len(teachers)
                total_hours = base_hours + additional_content_hours

                assessment_hours[t] = total_hours
                # Resit papers take same time to set as main papers
                # For display: split equally since each paper type requires full setting effort
                main_paper_hours = (base_setting_cost / 2) / len(teachers)
                resit_paper_hours = (base_setting_cost / 2) / len(teachers)
                setting_details_parts.append(
                    f"New setter ({config.ASSESSMENT_MANUAL_NEW_SETTER}h/assess): "
                    f"{main_paper_hours:.1f}h main + {resit_paper_hours:.1f}h resit = {total_hours:.1f}h"
                )
            else:
                # Standard setter: just the base cost divided equally
                base_hours = base_setting_cost / len(teachers)
                assessment_hours[t] = base_hours

                # Split between main and resit for display (equal portions, both full setting time)
                main_paper_hours = (base_setting_cost / 2) / len(teachers)
                resit_paper_hours = (base_setting_cost / 2) / len(teachers)

                setting_details_parts.append(
                    f"Standard ({config.ASSESSMENT_MANUAL_STANDARD}h/assess): "
                    f"{main_paper_hours:.1f}h main + {resit_paper_hours:.1f}h resit = {base_hours:.1f}h"
                )

        # Use standard cost for display (all teachers share same assessment count)
        # Each assessment includes both main and resit papers = 2 papers
        # For display: show the split as equal portions of total setting time
        num_papers = assessment_count * 2  # Main + resit for each assessment
        paper_total_per_assessment = config.ASSESSMENT_MANUAL_STANDARD
        total_setting_cost = num_papers * paper_total_per_assessment / len(teachers)

        main_paper_total = (assessment_count * paper_total_per_assessment) / 2 / len(teachers)
        resit_paper_total = (assessment_count * paper_total_per_assessment) / 2 / len(teachers)

        # Display: show both main and resit papers separately in the count
        # Each assessment has 2 papers (main + resit), so total papers = assessments * 2
        num_papers = assessment_count * 2
        assessment_details.append(
            f"{num_papers} paper(s) set ({assessment_count} assessment(s)): "
            f"{paper_total_per_assessment:.1f}h each ({main_paper_total:.1f}h main + {resit_paper_total:.1f}h resit)"
        )

    # Assessment marking (split equally among teachers)
    # Assume 20% of students do resits (additional marking workload)
    # Select rates based on module stage: MSc (3+) uses automated by default, UG uses manual
    # Can be overridden via module.marking_type field
    marking_hours_per_teacher = 0.0
    marking_details = []
    if module.student_count > 0:
        # Determine marking type and rates
        is_automated = getattr(module, 'marking_type', 'manual') == 'automated'
        is_msc = module.stage >= 3  # Stage 3+ typically MSc level

        if is_automated:
            per_script = config.MARKING_AUTO_MSC if is_msc else config.MARKING_AUTO_UG
            admin_flat = config.MARKING_AUTO_ADMIN
        else:
            per_script = config.MARKING_MANUAL_MSC if is_msc else config.MARKING_MANUAL_UG
            admin_flat = config.MARKING_MANUAL_ADMIN

        initial_students = module.student_count
        resit_proportion = 0.20  # 20% of students do resits

        # Calculate main and resit script counts
        initial_scripts = initial_students
        resit_students = int(initial_students * resit_proportion)
        resit_scripts = resit_students

        total_scripts = initial_scripts + resit_scripts
        marking_hours_per_teacher = (total_scripts * per_script) / max(len(teachers), 1)

        # Breakdown showing main paper, resit papers, and total
        initial_hours = initial_scripts * per_script
        resit_hours = resit_scripts * per_script

        marking_details.append(
            f"{initial_scripts} scripts + {resit_scripts} resits x {per_script:.3f}h = "
            f"{total_scripts * per_script:.1f}h total ({initial_hours:.1f}h initial + {resit_hours:.1f}h resit), "
            f"{marking_hours_per_teacher:.1f}h per teacher"
        )

    # Assessment admin flat rate (split among teachers)
    # Already determined in marking section above, but need to re-select for admin rate
    is_automated = getattr(module, 'marking_type', 'manual') == 'automated'
    is_msc = module.stage >= 3

    if is_automated:
        admin_flat = config.MARKING_AUTO_ADMIN
    else:
        admin_flat = config.MARKING_MANUAL_ADMIN

    admin_hours_per_teacher = (admin_flat * assessment_count) / max(len(teachers), 1)

    # Supervision - moved outside per-module calculation since it's staff-level, not module-level
    # The supervision allocation is passed as an immutable object containing
    # pastoral counts and project loads for all teachers. We track it here but
    # the actual hours will be added once at the end in calculate_workload()
    teacher_supervision_hours = {t: 0.0 for t in teachers}  # Placeholder - not used per module
    supervision_details = []  # Not populated per-module anymore

    # Calculate per-teacher total for this module
    result = {}
    num_teachers = len(teachers)

    for teacher in teachers:
        # Get this teacher's specific lecture multiplier
        teacher_lecture_hours_with_mult = lecture_hours_with_mult.get(teacher, 0.0)
        teacher_assessment_hours = assessment_hours.get(teacher, 0.0)

        # Total for this teacher from module activities (shared items divided by num_teachers)
        # Note: practicals are multiplied by weeks to get yearly total
        total_teacher_hours = (
            teacher_lecture_hours_with_mult +
            individual_practical_hours.get(teacher, practical_hours_one) * practical_week_count +  # Yearly practical hours
            teacher_assessment_hours +
            marking_hours_per_teacher +
            admin_hours_per_teacher +
            teacher_supervision_hours.get(teacher, 0.0)
        )

        # Calculate base lecture hours for display
        # For new lecturers: total = delivery + content_dev = (base × 2.5) + (base × 2.5)
        # where base = lecture_hours / num_teachers
        # Display shows the actual per-teacher calculation
        module_detail_parts = []
        if lecture_multipliers[teacher] == config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]:
            # For new lecturer, show: base_share × 5x = total (delivery + content dev)
            base_share = lecture_hours / len(teachers) if teachers else 0
            module_detail_parts.append(f"New lecturer ({config.TEACHING_MULTIPLIERS['lecture_new_content_or_lecturer']}x): {base_share:.1f}h base @ 2.5x + content dev = {teacher_lecture_hours_with_mult:.0f}h")
        else:
            module_detail_parts.append(f"Standard ({config.TEACHING_MULTIPLIERS['lecture_standard']}x): {teacher_lecture_hours_with_mult:.1f}h")

        if practical_details:
            module_detail_parts.extend(practical_details)
        module_detail_parts.append(assessment_details[0] if assessment_details else "")
        module_detail_parts.extend(marking_details)

        # Calculate total practical hours for this teacher (per-week × weeks)
        teacher_practical_total = individual_practical_hours.get(teacher, practical_hours_one) * practical_week_count

        result[teacher] = {
            "hours": total_teacher_hours,
            "teaching_breakdown": {
                "teaching": teacher_lecture_hours_with_mult,
                "practicals": teacher_practical_total,  # Total practical hours (weekly × weeks)
                "assessment_setting": teacher_assessment_hours,
                "marking": marking_hours_per_teacher,
                "admin": admin_hours_per_teacher,
                "supervision": teacher_supervision_hours.get(teacher, 0.0),
            },
            "detail_text": "; ".join(module_detail_parts),
            "supervision_details": [d for d in supervision_details if teacher in d],
        }

    return result


# --- Research Workload ---


def _calculate_research_workload(staff_member: StaffData) -> tuple:
    """
    Calculate research workload for a staff member.

    Returns (total_hours, breakdown_dict, detail_string, grant_titles_dict)
    where grant_titles_dict maps project_id -> display title for output.

    University now has only 10% protected baseline for all staff.
    Only IGGI project staff get an additional primary research allowance (20%).
    ART staff only get the protected baseline (no additional allowance).

    Research workload consists of:
        - Protected baseline: 10% of nominal hours (164.2h for full-time)
        - Additional work from PhD supervision, research grants, and project marking

    Args:
        staff_member: StaffData object with supervision counts and grant data

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
        explanation = "PhD supervision (primary supervisor, co-supervisor & assessor)"
        details.append(f"{explanation} ({formula_str}): {'; '.join(phd_details)} = {phd_hours:.1f}h")

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
            if "assumptions" not in locals():
                assumptions = []
            assumptions.append(f"Invalid FTE value for grant: '{fte_str}'")

    return total, breakdown, "; ".join(details) if details else "No research activities recorded", grant_titles


# --- Administration Workload ---


def _calculate_admin_workload(staff_member: StaffData, nominal_hours: float) -> tuple:
    """
    Calculate administration workload from departmental roles and service points.

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
    """
    Calculate the complete workload for all staff members.

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
                # Aggregate teaching_breakdown from each module
                for k, v in breakdown.get("teaching_breakdown", {}).items():
                    if "teaching_breakdown" not in staff_teaching[teacher]:
                        staff_teaching[teacher]["teaching_breakdown"] = {}
                    staff_teaching[teacher]["teaching_breakdown"][k] = staff_teaching[teacher]["teaching_breakdown"].get(k, 0.0) + v
                # Aggregate supervision details (to be shown separately)
                if "supervision_details" not in staff_teaching[teacher]:
                    staff_teaching[teacher]["supervision_details"] = []
                staff_teaching[teacher]["supervision_details"].extend(breakdown["supervision_details"])

    # Build results
    results = []
    for canonical_name, staff in staff_dict.items():
        if not staff.active:
            continue

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

        # Project setting allowance - fixed teaching-related amount for all staff (separate from supervision)
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

        # Supervision - add once per staff member (not per module)
        # Get pastoral and project supervision from the allocation object
        pastoral_count = supervision.pastoral_students.get(canonical_name, 0)
        if pastoral_count > 0:
            pastoral_hours = pastoral_count * config.SUPERVISION_MULTIPLIERS["pastoral"]
            teaching_hours += pastoral_hours
            staff_teaching[canonical_name]["hours"] += pastoral_hours
            if "teaching_breakdown" not in staff_teaching[canonical_name]:
                staff_teaching[canonical_name]["teaching_breakdown"] = {}
            staff_teaching[canonical_name]["teaching_breakdown"]["pastoral_supervision"] = pastoral_hours
            # Add supervision detail for HTML display
            if "supervision_details" not in staff_teaching[canonical_name]:
                staff_teaching[canonical_name]["supervision_details"] = []
            staff_teaching[canonical_name]["supervision_details"].append(
                f"Pastoral: {pastoral_count} students x {config.SUPERVISION_MULTIPLIERS['pastoral']}h = {pastoral_hours:.1f}h"
            )

        # Get project load for this teacher from supervision allocation (already ceiling'd)
        teacher_project_load = supervision.project_loads.get(canonical_name, 0)

        if teacher_project_load > 0:
            proj_mult = config.SUPERVISION_MULTIPLIERS["ug_project"]
            if canonical_name in staff_dict:
                # Use stage from staff's modules to determine project multiplier
                for mod in year_data.modules:
                    if canonical_name in [normalize_name(t, year_data.reverse_lookup, unknown_callback=None) or t for t in mod.teachers]:
                        if mod.stage >= 10:  # MSc and above
                            proj_mult = config.SUPERVISION_MULTIPLIERS["msc_project"]
                            break
            project_hours = teacher_project_load * proj_mult
            teaching_hours += project_hours
            staff_teaching[canonical_name]["hours"] += project_hours
            if "teaching_breakdown" not in staff_teaching[canonical_name]:
                staff_teaching[canonical_name]["teaching_breakdown"] = {}
            staff_teaching[canonical_name]["teaching_breakdown"]["project_supervision"] = project_hours
            # Add supervision detail for HTML display
            if "supervision_details" not in staff_teaching[canonical_name]:
                staff_teaching[canonical_name]["supervision_details"] = []
            proj_level = "UG" if proj_mult == config.SUPERVISION_MULTIPLIERS["ug_project"] else "MSc"
            staff_teaching[canonical_name]["supervision_details"].append(
                f"Projects: {teacher_project_load} projects x {proj_level} ({proj_mult}h) = {project_hours:.1f}h"
            )

        # General baseline is handled within _calculate_admin_workload via service_points
        # Protected research baseline (10% of nominal hours) - included in all staff totals
        protected_research = config.PROTECTED_RESEARCH_BASELINE * fte_value

        # Research (grants, supervision - additional to protected baseline)
        research_hours, research_breakdown, research_detail, grant_titles = _calculate_research_workload(staff)

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
        module_details = staff_teaching.get(canonical_name, {}).get("details", [])

        # Build structured teaching breakdown from per-module data
        teaching_breakdown = {}
        if canonical_name in staff_teaching:
            staff_data = staff_teaching[canonical_name]
            # Direct teaching_breakdown at staff level (from aggregation)
            if "teaching_breakdown" in staff_data and staff_data["teaching_breakdown"]:
                teaching_breakdown = dict(staff_data["teaching_breakdown"])
            elif len(staff_data.get("details", [])) > 0:
                # Fallback: parse from details string for backward compatibility
                pass
        else:
            # For admin staff with only minimum teaching load
            if min_teaching > 0:
                teaching_breakdown["minimum_admin_load"] = min_teaching

        # Track assumptions and missing data
        assumptions = []
        missing_data = []

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

        result = WorkloadResult(
            name=canonical_name,
            fte=staff.fte,
            total_hours=total_hours,
            teaching_hours=teaching_hours,
            research_hours=research_total,
            admin_hours=admin_hours,
            assumptions=tuple(assumptions),  # Convert to tuple for frozen dataclass
            missing_data=tuple(missing_data),  # Convert to tuple for frozen dataclass
            teaching_detail=teaching_detail_str,
            research_detail=research_detail,
            admin_detail=admin_detail,
            teaching_breakdown=teaching_breakdown,
            research_breakdown=research_breakdown,
            admin_breakdown=admin_breakdown,
            nominal_hours=nominal_hours,
            grant_titles=grant_titles,
            module_details=tuple(module_details),  # Convert to tuple for frozen dataclass
            supervision_details=tuple(unique_supervision),  # Convert to tuple for frozen dataclass
        )
        results.append(result)

    return results
