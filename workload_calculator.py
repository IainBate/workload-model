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
from data_loader import YearData, ModuleData, StaffData, WorkloadResult, normalize_name


# --- Teaching Workload ---

def _calculate_teaching_workload(module: ModuleData, teachers: List[str],
                                  known_lecturers: set) -> dict:
    """
    Calculate teaching workload for a single module, split by teacher.

    Returns a dict: {teacher_name: {hours, details}}
    """
    if not teachers:
        return {}

    # Base fixed components (shared equally)
    engagement_share = config.BASELOADS.get("engagement", 100) / max(len(teachers), 1)
    project_setting_share = config.BASELOADS.get("project_setting", 6) / max(len(teachers), 1)

    # Teaching hours
    contact_hours = module.contact_hours
    teaching_hours = 0.0
    teaching_details = []

    # Determine multiplier: check if any teacher is new
    has_new_lecturer = any(t not in known_lecturers for t in teachers)

    if has_new_lecturer:
        mult = config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]  # 5
        teaching_details.append(f"New lecturer multiplier (5x) applied to {contact_hours:.0f} contact hours")
    else:
        mult = config.TEACHING_MULTIPLIERS["lecture_standard"]  # 2.5
        teaching_details.append(f"Standard multiplier (2.5x) applied to {contact_hours:.0f} contact hours")

    teaching_hours = contact_hours * mult

    # Assessment setting
    assessment_hours = 0.0
    assessment_details = []
    assessment_count = module.assessment_count

    # All assessments are assumed manual (no automated marking detail available)
    if has_new_lecturer:
        setting_cost = config.ASSESSMENT_MANUAL_NEW_SETTER * assessment_count
    else:
        setting_cost = config.ASSESSMENT_MANUAL_STANDARD * assessment_count

    assessment_hours = setting_cost
    assessment_details.append(f"{assessment_count} assessment(s) set at {config.ASSESSMENT_MANUAL_STANDARD}h each")

    # Assessment marking (split equally among teachers)
    marking_hours = 0.0
    marking_details = []
    if module.student_count > 0:
        per_script = config.MARKING_MANUAL_MSC
        total_scripts = module.student_count
        per_teacher = (total_scripts * per_script) / max(len(teachers), 1)
        marking_hours = per_teacher
        marking_details.append(
            f"{total_scripts} scripts x {per_script}h = {total_scripts * per_script:.1f}h total, "
            f"{per_teacher:.1f}h per teacher"
        )

    # Assessment admin flat rate
    admin_flat = config.MARKING_MANUAL_ADMIN
    admin_hours = admin_flat * assessment_count

    # Supervision
    supervision_hours = 0.0
    supervision_details = []

    # Pastoral supervision (from pastoral_load.csv or default)
    pastoral_count = 0
    for teacher in teachers:
        # Would look up from pastoral_load_data
        pastoral_count += 20  # Default

    if pastoral_count > 0:
        pastoral_hours = pastoral_count * config.SUPERVISION_MULTIPLIERS["pastoral"]
        supervision_hours += pastoral_hours
        supervision_details.append(f"Pastoral: {pastoral_count} students x {config.SUPERVISION_MULTIPLIERS['pastoral']}h = {pastoral_hours:.1f}h")

    # Project supervision
    project_count = 0
    for teacher in teachers:
        project_count += 10  # Default

    if project_count > 0:
        proj_mult = config.SUPERVISION_MULTIPLIERS["ug_project"] if module.stage < 10 else config.SUPERVISION_MULTIPLIERS["msc_project"]
        project_hours = project_count * proj_mult
        supervision_hours += project_hours
        supervision_details.append(
            f"Projects: {project_count} students x {proj_mult}h = {project_hours:.1f}h"
        )

    # Total for the module (shared among teachers)
    total_module_hours = (engagement_share + project_setting_share + teaching_hours +
                          assessment_hours + marking_hours + admin_hours + supervision_hours)

    per_teacher = total_module_hours / max(len(teachers), 1)

    result = {}
    for teacher in teachers:
        result[teacher] = {
            "hours": per_teacher,
            "details": {
                "engagement": engagement_share,
                "project_setting": project_setting_share,
                "teaching": teaching_hours,
                "assessment_setting": assessment_hours,
                "marking": marking_hours,
                "admin": admin_hours,
                "supervision": supervision_hours,
            },
            "detail_text": f"{teaching_details[0]}; {assessment_details[0]}; {'; '.join(marking_details)}; {'; '.join(supervision_details)}",
        }

    return result


# --- Research Workload ---

def _calculate_research_workload(staff_member: StaffData) -> tuple:
    """
    Calculate research workload for a staff member.

    Returns (hours, detail_string)
    """
    total = 0.0
    details = []

    # PhD supervision (primary supervisor)
    if staff_member.phd_supervisions > 0:
        # Use adjusted project load if available
        pgr_count = staff_member.phd_supervisions
        phd_hours = pgr_count * config.SUPERVISION_MULTIPLIERS["pgr_primary_supervisor_per_fte"]
        total += phd_hours
        details.append(f"PhD primary supervisor: {pgr_count} x {config.SUPERVISION_MULTIPLIERS['pgr_primary_supervisor_per_fte']}h = {phd_hours:.1f}h")

    # Research grant time (from % FTE for CS.csv)
    for proj in staff_member.research_projects:
        fte_str = proj.get("fte", "0%")
        try:
            fte = int(fte_str.replace("%", "")) / 100.0
            grant_hours = fte * config.NOMINAL_WORKING_HOURS_PER_YEAR
            total += grant_hours
            details.append(f"Grant {proj['project_id']}: {fte_str} of {config.NOMINAL_WORKING_HOURS_PER_YEAR}h = {grant_hours:.1f}h ({proj['title'][:50]})")
        except ValueError:
            pass

    return total, "; ".join(details) if details else "No research activities recorded"


# --- Administration Workload ---

def _calculate_admin_workload(staff_member: StaffData, nominal_hours: float) -> tuple:
    """
    Calculate administration workload from departmental roles.

    Returns (hours, detail_string)
    """
    total = 0.0
    details = []

    for role in staff_member.roles:
        percentage = config.ROLES_PERCENTAGE.get(role, 0.0)
        hours = nominal_hours * percentage
        total += hours
        details.append(f"{role}: {percentage*100:.0f}% of {nominal_hours:.0f}h = {hours:.1f}h")

    return total, "; ".join(details) if details else "No administrative roles"


# --- Main Calculation ---

def calculate_workload(year_data: YearData) -> List[WorkloadResult]:
    """
    Calculate the complete workload for all staff members.

    Returns a list of WorkloadResult, one per staff member.
    """
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

        # Calculate teaching workload
        teaching_breakdown = _calculate_teaching_workload(
            module, normalized_teachers, year_data.known_lecturers
        )

        for teacher, breakdown in teaching_breakdown.items():
            if teacher in staff_teaching:
                staff_teaching[teacher]["hours"] += breakdown["hours"]
                staff_teaching[teacher]["details"].append(
                    f"{module.name} ({module.credits}cr): {breakdown['detail_text']}"
                )

    # Build results
    results = []
    for canonical_name, staff in year_data.staff.items():
        if not staff.active:
            continue

        # Nominal hours scaled by FTE for part-time staff
        nominal_hours = config.NOMINAL_WORKING_HOURS_PER_YEAR * staff.fte

        # Teaching
        teaching_hours = staff_teaching.get(canonical_name, {}).get("hours", 0.0)

        # Baselines: scale personal development by FTE for part-time staff
        personal_dev = config.BASELOADS["personal_development"] * staff.fte

        # Research
        research_hours, research_detail = _calculate_research_workload(staff)

        # Administration
        admin_hours, admin_detail = _calculate_admin_workload(staff, nominal_hours)

        # Total: teaching + research + admin + personal development baseline
        total_hours = teaching_hours + research_hours + admin_hours + personal_dev

        # Build detail strings
        teaching_detail_str = "; ".join(staff_teaching.get(canonical_name, {}).get("details", [])) if canonical_name in staff_teaching else "No teaching activities"
        if staff.saint_modules:
            teaching_detail_str += f"; Also teaches: {', '.join(staff.saint_modules)} (SAINTS - not included in workload)"

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
            research_hours=research_hours,
            admin_hours=admin_hours,
            teaching_detail=teaching_detail_str,
            research_detail=research_detail,
            admin_detail=admin_detail,
            assumptions=assumptions,
            missing_data=missing_data,
            nominal_hours=nominal_hours,
        )
        results.append(result)

    return results
