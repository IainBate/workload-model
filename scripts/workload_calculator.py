"""
Core workload calculation engine.
Applies the Workload Model parameters to module and staff data.

Calculates workload per staff member across three categories:
- Teaching: contact hours * multipliers, assessment setting/marking, supervision
- Research: PhD supervision, grant work, project marking
- Administration: departmental roles as % of nominal hours
"""

from typing import List, Dict

import config
from data_loader import YearData, ModuleData, StaffData, WorkloadResult, SupervisionAllocation, allocate_supervision, normalize_name


# --- Constants ---

TEACHING_WEEKS_PER_SEMESTER = 11  # Actual teaching weeks per semester (UK academic calendar)


# --- Teaching Workload ---

def _calculate_teaching_workload(module: ModuleData, teachers: List[str],
                                  known_lecturers: set,
                                  staff_data: Dict[str, StaffData],
                                  supervision: SupervisionAllocation) -> dict:
    """
    Calculate teaching workload for a single module, split by teacher.

    Returns a dict: {teacher_name: {hours, details}}

    The supervision allocation is passed as an immutable SupervisionAllocation
    object. Teachers receive their supervision hours exactly once per calculation run.
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

    # Calculate lecture multiplier per-teacher based on whether THAT teacher is new
    lecture_multipliers = {}
    for t in teachers:
        if t not in known_lecturers:
            lecture_multipliers[t] = config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]  # 5
        else:
            lecture_multipliers[t] = config.TEACHING_MULTIPLIERS["lecture_standard"]  # 2.5

    # Build teaching details string showing multiplier type for each teacher
    new_lecturers = [t for t in teachers if t not in known_lecturers]
    standard_lecturers = [t for t in teachers if t in known_lecturers]

    # Calculate base lecture hours (before multiplier) and total with multipliers
    lecture_base = lecture_hours  # Base lecture hours from contact time minus practicals

    detail_parts = []
    if new_lecturers:
        # New lecturer gets: contact hours x multiplier (e.g., 18h x 5x = 90h)
        new_hours_with_mult = lecture_base * config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]
        detail_parts.append(f"New lecturer ({config.TEACHING_MULTIPLIERS['lecture_new_content_or_lecturer']}x): {lecture_base:.1f}h x {config.TEACHING_MULTIPLIERS['lecture_new_content_or_lecturer']} = {new_hours_with_mult:.0f}h")
    if standard_lecturers:
        # Standard lecturer gets: contact hours x multiplier (e.g., 18h x 2.5x = 45h)
        std_hours_with_mult = lecture_base * config.TEACHING_MULTIPLIERS["lecture_standard"]
        detail_parts.append(f"Standard ({config.TEACHING_MULTIPLIERS['lecture_standard']}x): {lecture_base:.1f}h x {config.TEACHING_MULTIPLIERS['lecture_standard']} = {std_hours_with_mult:.0f}h")

    teaching_details.append("; ".join(detail_parts))

    # Calculate per-teacher lecture hours with their specific multiplier
    # Lectures are shared among teachers, so divide by number of teachers first
    lecture_hours_with_mult = {t: (lecture_hours / len(teachers)) * lecture_multipliers[t] for t in teachers}

    # --- Practical Sessions with Repetition Multiplier ---
    # Per the spec: "For each repetition of an identical class (e.g. 2nd and 3rd version)
    # have a multiplier of 1.5 times contact duration."
    #
    # Each week has a NEW class pattern:
    # - First delivery: new content at 5x contact time
    # - Subsequent deliveries: repetition at 1.5x contact time per session
    #
    # If practical_weeks is specified (from CSV Notes column), only count those weeks.
    # Example: "Practicals only in weeks 7, 8, 9" means:
    #   - Week 7: first delivery at 5x
    #   - Weeks 8, 9: repeats at 1.5x each

    practical_hours_total = 0.0  # Total for all teachers combined
    practical_hours_one = 0.0  # Per-teacher hours
    practical_details = []
    practical_breakdown = {}  # For structured teaching breakdown

    if practicals_count > 0:
        contact_per_practical = module.practical_contact_hours if module.practical_contact_hours > 0 else (contact_hours / max(practicals_count, 1))
        n_groups = module.practical_groups

        # Determine weeks with practicals
        if module.practical_weeks is not None and len(module.practical_weeks) > 0:
            # Use specified weeks from CSV notes
            practical_week_count = len(module.practical_weeks)
            first_week = min(module.practical_weeks)
            other_weeks = [w for w in module.practical_weeks if w != first_week]
        else:
            # Default: all teaching weeks (1-11)
            practical_week_count = TEACHING_WEEKS_PER_SEMESTER
            first_week = 1
            other_weeks = list(range(2, TEACHING_WEEKS_PER_SEMESTER + 1))

        if n_groups > 0:
            # With parallel groups:
            # Groups are shared among teachers. If 3 lecturers share 5 groups,
            # each lecturer gets 5/3 = 1.67 groups per week.
            #
            # For each lecturer:
            # - First delivery (first week) at their personal first-delivery multiplier
            #   (2.5x standard, or higher if they're new to the content)
            # - Subsequent deliveries (other weeks) at repetition rate (1.5x)

            n_teachers = len(teachers)
            groups_per_teacher = n_groups / n_teachers

            rep_rate = config.REPETITION_MULTIPLIER  # 1.5

            # Calculate per-teacher hours (not summed across teachers)
            teacher_first_mult = None
            weekly_first_one = 0.0
            weekly_repeat_one = 0.0

            iteration = 0
            for t in teachers:
                iteration += 1
                if t not in known_lecturers:
                    first_time_mult = config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]  # 5
                else:
                    first_time_mult = config.TEACHING_MULTIPLIERS["problem_class_seminar_practical"]  # 2.5

                if teacher_first_mult is None:
                    teacher_first_mult = first_time_mult

                contribution = groups_per_teacher * contact_per_practical * first_time_mult
                contrib = groups_per_teacher * contact_per_practical * first_time_mult
                weekly_first_one += contrib
                repeat_contribution = len(other_weeks) * groups_per_teacher * contact_per_practical * rep_rate
                weekly_repeat_one += repeat_contribution

            # Each teacher gets their own share (we sum then divide by n_teachers since loop accumulated)
            practical_hours_one = (weekly_first_one + weekly_repeat_one) / n_teachers
            practical_hours_total = practical_hours_one * n_teachers  # Total for all teachers

            # Build display details - show groups per teacher and their multiplier
            first_time_groups = groups_per_teacher * contact_per_practical * teacher_first_mult
            repeat_groups_total = len(other_weeks) * groups_per_teacher * contact_per_practical * rep_rate

            first_time_display = f"{groups_per_teacher:.1f} grps @ {teacher_first_mult}x (week {first_week})"
            repeat_count = len(other_weeks)
            if repeat_count > 0:
                weeks_str = ", ".join(str(w) for w in other_weeks)
                repeat_display = f"weeks {weeks_str} @ {rep_rate}x"
            else:
                repeat_display = "no repeats"

            practical_details.append(
                f"Practicals: {n_groups} groups shared by {n_teachers} lecturers, "
                f"{practical_week_count}w - week {first_week}: {groups_per_teacher:.1f} grps x {contact_per_practical:.1f}h x {teacher_first_mult}x = {first_time_groups:.1f}h; "
                f"{repeat_display}: {len(other_weeks)}w x {groups_per_teacher:.1f} grps x {contact_per_practical:.1f}h x {rep_rate}x = {repeat_groups_total:.1f}h; "
                f"Total: {first_time_groups + repeat_groups_total:.1f}h / {n_teachers} teachers = {practical_hours_one:.1f}h/teacher"
            )

            # Add to breakdown (per-teacher values)
            practical_breakdown["practicals_first_time"] = weekly_first_one / n_teachers if n_teachers > 0 else 0
            if weekly_repeat_one > 0:
                practical_breakdown["practicals_repeat"] = weekly_repeat_one / n_teachers if n_teachers > 0 else 0
        else:
            # No parallel groups - single session type shared by all teachers
            # Per spec: "For each repetition of an identical class have a multiplier of 1.5 times contact duration."
            # - First delivery (first week): first-delivery rate for each teacher based on their status
            # - Subsequent deliveries (other weeks): repetition rate (1.5x)

            rep_rate = config.REPETITION_MULTIPLIER  # 1.5

            n_teachers = len(teachers)

            # Calculate per-teacher hours (not summed across teachers)
            teacher_first_mult = None
            weekly_first_one = 0.0
            weekly_repeat_one = 0.0

            for t in teachers:
                if t not in known_lecturers:
                    first_time_mult = config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]  # 5
                else:
                    first_time_mult = config.TEACHING_MULTIPLIERS["problem_class_seminar_practical"]  # 2.5

                if teacher_first_mult is None:
                    teacher_first_mult = first_time_mult

                weekly_first_one += contact_per_practical * first_time_mult
                weekly_repeat_one += len(other_weeks) * contact_per_practical * rep_rate

            # Each teacher gets their own share (we sum then divide by n_teachers since loop accumulated)
            practical_hours_one = (weekly_first_one + weekly_repeat_one) / n_teachers
            practical_hours_total = practical_hours_one * n_teachers  # Total for all teachers

            # Calculate breakdown for display
            first_time_total = contact_per_practical * teacher_first_mult
            repeat_weeks_total = len(other_weeks) * contact_per_practical * rep_rate

            if other_weeks:
                weeks_str = ", ".join(str(w) for w in other_weeks)
                repeat_display = f"weeks {weeks_str} @ {rep_rate}x"
            else:
                repeat_display = "no repeats"

            practical_details.append(
                f"Practicals: {practical_week_count}w - week {first_week}: 1 grp x {contact_per_practical:.1f}h x {teacher_first_mult}x = {first_time_total:.1f}h; "
                f"{repeat_display}: {len(other_weeks)}w x 1 grp x {contact_per_practical:.1f}h x {rep_rate}x = {repeat_weeks_total:.1f}h; "
                f"Total: {first_time_total + repeat_weeks_total:.1f}h / {n_teachers} teachers = {practical_hours_one:.1f}h/teacher"
            )

            practical_breakdown["practicals_first_time"] = weekly_first_one / n_teachers if n_teachers > 0 else 0
            if weekly_repeat_one > 0:
                practical_breakdown["practicals_repeat"] = weekly_repeat_one / n_teachers if n_teachers > 0 else 0

    # Add repetition_multiplier back if removed
    if "repetition_multiplier" not in config.TEACHING_MULTIPLIERS:
        # Will be added to YAML
        pass

    # Assessment setting (per teacher based on whether THEY are new)
    assessment_hours = {t: 0.0 for t in teachers}
    assessment_details = []
    assessment_count = module.assessment_count

    if assessment_count > 0:
        setting_details_parts = []
        for t in teachers:
            if t not in known_lecturers:
                setting_cost = config.ASSESSMENT_MANUAL_NEW_SETTER * assessment_count
                assessment_hours[t] = setting_cost / len(teachers)
            else:
                setting_cost = config.ASSESSMENT_MANUAL_STANDARD * assessment_count
                assessment_hours[t] = setting_cost / len(teachers)

        # Use standard cost for display (all teachers share same assessment count)
        assessment_details.append(f"{assessment_count} assessment(s) set at {config.ASSESSMENT_MANUAL_STANDARD}h each")

    # Assessment marking (split equally among teachers)
    marking_hours_per_teacher = 0.0
    marking_details = []
    if module.student_count > 0:
        per_script = config.MARKING_MANUAL_MSC
        total_scripts = module.student_count
        marking_hours_per_teacher = (total_scripts * per_script) / max(len(teachers), 1)
        marking_details.append(
            f"{total_scripts} scripts x {per_script}h = {total_scripts * per_script:.1f}h total, "
            f"{marking_hours_per_teacher:.1f}h per teacher"
        )

    # Assessment admin flat rate (split among teachers)
    admin_flat = config.MARKING_MANUAL_ADMIN
    admin_hours_per_teacher = (admin_flat * assessment_count) / max(len(teachers), 1)

    # Supervision - calculate per-teacher based on their individual project load
    # The supervision allocation is passed as an immutable object containing
    # pastoral counts and project loads for all teachers
    supervision_details = []
    teacher_supervision_hours = {}  # {teacher: hours}

    proj_mult = config.SUPERVISION_MULTIPLIERS["ug_project"] if module.stage < 10 else config.SUPERVISION_MULTIPLIERS["msc_project"]

    for teacher in teachers:
        # Teacher names are already normalized to canonical form by the caller
        # Use them directly as keys into supervision allocation

        supervision_hours = 0.0
        teacher_details = []

        # Get pastoral student count from supervision allocation
        pastoral_count = supervision.pastoral_students.get(teacher, 0)

        if pastoral_count > 0:
            pastoral_hours = pastoral_count * config.SUPERVISION_MULTIPLIERS["pastoral"]
            supervision_hours += pastoral_hours
            teacher_details.append(f"Pastoral: {pastoral_count:.1f} students x {config.SUPERVISION_MULTIPLIERS['pastoral']}h = {pastoral_hours:.0f}h")

        # Get project load for this teacher from supervision allocation (already ceiling'd)
        teacher_project_load = supervision.project_loads.get(teacher, 0)

        if teacher_project_load > 0:
            teacher_project_hours = teacher_project_load * proj_mult
            supervision_hours += teacher_project_hours
            teacher_details.append(f"Projects: {teacher_project_load:.1f} projects x {proj_mult}h = {teacher_project_hours:.1f}h")

        teacher_supervision_hours[teacher] = supervision_hours

        if teacher_details:
            supervision_details.append(f"{teacher}: {'; '.join(teacher_details)}")

    # Calculate per-teacher total for this module
    result = {}
    num_teachers = len(teachers)

    for teacher in teachers:
        # Get this teacher's specific lecture multiplier
        teacher_lecture_hours_with_mult = lecture_hours_with_mult.get(teacher, 0.0)
        teacher_assessment_hours = assessment_hours.get(teacher, 0.0)

        # Total for this teacher from module activities (shared items divided by num_teachers)
        total_teacher_hours = (
            teacher_lecture_hours_with_mult +
            practical_hours_one +  # Already per-teacher
            teacher_assessment_hours +
            marking_hours_per_teacher +
            admin_hours_per_teacher +
            teacher_supervision_hours.get(teacher, 0.0)
        )

        # Calculate base lecture hours for display
        teacher_lecture_base = lecture_hours / lecture_multipliers[teacher] if lecture_multipliers[teacher] > 0 else lecture_hours
        module_detail_parts = []
        if lecture_multipliers[teacher] == config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]:
            module_detail_parts.append(f"New lecturer (5x): {teacher_lecture_base:.1f}h x 5 = {teacher_lecture_hours_with_mult:.0f}h")
        else:
            module_detail_parts.append(f"Standard (2.5x): {teacher_lecture_base:.1f}h x 2.5 = {teacher_lecture_hours_with_mult:.0f}h")

        if practical_details:
            module_detail_parts.extend(practical_details)
        module_detail_parts.append(assessment_details[0] if assessment_details else "")
        module_detail_parts.extend(marking_details)

        result[teacher] = {
            "hours": total_teacher_hours,
            "teaching_breakdown": {
                "teaching": teacher_lecture_hours_with_mult,
                "practicals": practical_hours_one,
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

    ART staff only get the protected baseline (10% of nominal hours = 164.2h).
    Non-ART staff (with research grants) also get the primary research allowance.
    """
    total = 0.0
    details = []
    breakdown = {}
    grant_titles = {}  # project_id -> title mapping for output display

    # ART staff only get the protected baseline, not the additional primary research allowance
    is_art_staff = (staff_member.category or "").upper() == "ART"

    if not is_art_staff and staff_member.research_projects:
        # Non-ART staff with research grants get primary research allowance
        primary_allowance = config.RESEARCH_ALLOWANCES.get("primary_research_allowance_art", 328.4)
        total += primary_allowance
        breakdown["primary_research_allowance"] = primary_allowance
        details.append(f"Primary research allowance: {primary_allowance:.1f}h")

    # PhD supervision work (supervisor, co-supervisor and assessor are part of research workload)
    phd_hours = 0.0
    phd_details = []
    phd_breakdown = {}

    # Sole supervisors (primary supervisor role)
    if staff_member.phd_supervisions > 0:
        sole_count = staff_member.phd_supervisions
        sole_hours = sole_count * config.SUPERVISION_MULTIPLIERS["pgr_primary_supervisor_per_fte"]
        phd_hours += sole_hours
        phd_breakdown["primary_supervisor"] = sole_hours
        phd_details.append(f"{sole_count}x primary supervisor ({config.SUPERVISION_MULTIPLIERS['pgr_primary_supervisor_per_fte']}h each)")

    # Co-supervisors
    if staff_member.phd_co_supervisions > 0:
        co_count = staff_member.phd_co_supervisions
        co_hours = co_count * config.SUPERVISION_MULTIPLIERS["pgr_co_supervisor_per_fte"]
        phd_hours += co_hours
        phd_breakdown["co_supervisor"] = co_hours
        phd_details.append(f"{co_count}x co-supervisor ({config.SUPERVISION_MULTIPLIERS['pgr_co_supervisor_per_fte']}h each)")

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
        details.append(f"PhD supervision: {'; '.join(phd_details)} = {phd_hours:.1f}h")

    # Research grant time (from % FTE for CS.csv)
    grant_titles = {}  # project_id -> title mapping for output display
    for proj in staff_member.research_projects:
        fte_str = proj.get("fte", "0%")
        try:
            fte = int(fte_str.replace("%", "")) / 100.0
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
            pass

    return total, breakdown, "; ".join(details) if details else "No research activities recorded", grant_titles


# --- Administration Workload ---

def _calculate_admin_workload(staff_member: StaffData, nominal_hours: float) -> tuple:
    """
    Calculate administration workload from departmental roles and service points.

    Returns (total_hours, breakdown_dict, detail_string)
    """
    total = 0.0
    details = []
    breakdown = {}

    for role in staff_member.roles:
        percentage = config.ROLES_PERCENTAGE.get(role, 0.0)
        hours = nominal_hours * percentage
        total += hours
        breakdown[role] = hours
        details.append(f"{role}: {percentage*100:.0f}% of {nominal_hours:.0f}h = {hours:.1f}h")

    # Add service points (university-level committee work) for administrative staff
    # Service points are typically 175h for HoD and other senior admin roles
    if staff_member.roles:  # Only add service points if they have any departmental roles
        service_hours = config.SERVICE_POINTS_DEFAULT
        total += service_hours
        breakdown["service_points"] = service_hours
        details.append(f"Service points (committee work): {service_hours:.0f}h")

    return total, breakdown, "; ".join(details) if details else "No administrative roles"


# --- Main Calculation ---

def calculate_workload(year_data: YearData) -> List[WorkloadResult]:
    """Calculate the complete workload for all staff members. Returns a list of WorkloadResult, one per staff member."""
    # Allocate supervision once for all teachers (pure function)
    supervision = allocate_supervision(year_data.staff)

    # Initialize per-staff teaching totals
    staff_teaching = {name: {"hours": 0.0, "details": []} for name in year_data.staff}

    # Process each module
    for module in year_data.modules:
        # Normalize teacher names
        normalized_teachers = []
        for t in module.teachers:
            name = normalize_name(t.strip(), year_data.name_lookup, unknown_callback=None)
            if name:
                normalized_teachers.append(name)
            else:
                normalized_teachers.append(t.strip())

        if not normalized_teachers:
            # Module has no teachers - flag as incomplete
            continue

        # Calculate teaching workload (supervision passed as immutable allocation)
        module_teaching = _calculate_teaching_workload(
            module, normalized_teachers, year_data.known_lecturers, year_data.staff,
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
    for canonical_name, staff in year_data.staff.items():
        if not staff.active:
            continue

        # Nominal hours scaled by FTE for part-time staff
        nominal_hours = config.NOMINAL_WORKING_HOURS_PER_YEAR * staff.fte

        # Teaching - default to minimum teaching hours for administrative staff
        teaching_hours = staff_teaching.get(canonical_name, {}).get("hours", 0.0)
        min_teaching = 0.0

        # Add minimum teaching load for HoD and other admin staff who don't teach modules
        # Original model shows ~30h teaching for HoD (reduced from full teaching load)
        has_module_teaching = canonical_name in staff_teaching and len(staff_teaching[canonical_name].get("details", [])) > 0

        if not has_module_teaching:
            # Administrative staff need a minimum teaching component
            # HoD typically has reduced teaching - use default of 30h
            if "Head of Department" in staff.roles or len(staff.roles) > 1:
                min_teaching = config.BASELOADS.get("min_admin_teaching", 30.0)
                if min_teaching > 0:
                    teaching_hours = min_teaching
                    # Add detail for minimum admin teaching
                    staff_teaching[canonical_name]["hours"] = min_teaching
                    staff_teaching[canonical_name]["details"].append(
                        f"Minimum administrative teaching load: {min_teaching:.0f}h"
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

        # General baseline (outside teaching/research/admin)
        # Engagement and personal dev are per staff member, not shared
        engagement_baseline = config.BASELOADS.get("engagement", 100)
        personal_dev = config.BASELOADS["personal_development"] * staff.fte

        # Protected research baseline (10% of nominal hours)
        protected_research = config.PROTECTED_RESEARCH_BASELINE * staff.fte

        # Research (additional to protected baseline - grants, supervision)
        research_hours, research_breakdown, research_detail, grant_titles = _calculate_research_workload(staff)

        # Total research includes protected baseline + additional work
        research_total = protected_research + research_hours

        # Add protected research baseline to breakdown for transparency in reports
        research_breakdown["protected_research_baseline"] = protected_research

        # Administration
        admin_hours, admin_breakdown, admin_detail = _calculate_admin_workload(staff, nominal_hours)

        # Total: teaching + research (protected + additional) + admin + general baseline
        total_hours = teaching_hours + research_total + admin_hours + engagement_baseline + personal_dev

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
            staff.fte = 1.0
            nominal_hours = config.NOMINAL_WORKING_HOURS_PER_YEAR

        if not staff.roles:
            missing_data.append("No administrative roles assigned")

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
