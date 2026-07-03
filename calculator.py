\"\"\"
Main calculation engine for determining teaching workload.
Uses parameters from config.py and data from data_loader.py.
\"\"\"

from typing import List
from .config import (
    BASELOADS,
    ASSESSMENT_MULTIPLIERS,
    ASSESSMENT_ADMIN_FIXED_FEE,
    TEACHING_MULTIPLIERS,
    REPETITION_MULTIPLIER,
    SUPERVISION_MULTIPLIERS,
    ONLINE_PROGRAMS,
    DEFAULT_VALUE
)
from .data_loader import ModuleData

def calculate_module_workload(module: ModuleData, known_lecturers: set = None) -> dict:
    \"\"\"
    Calculates the workload hours for a single module.
    Note: Because multiple people may be assigned to a module,
    this returns the total \"points\" of work available on that module's
    teaching components, which is then split by the number of teachers.
    \"\"\"

    # Base Components (shared/fixed)
    total_base = sum(BASELOADS.values())

    # Teaching Calculations
    # Identify if there are any \"new\" lecturers on this module.
    has_new_lecturer = False
    if known_lecturers is not None:
        has_new_lecturer = any(t not in known_lecturers for t in module.teachers)

    teaching_hours = 0.0
    # If a new lecturer is present, we use the higher multiplier to ensure
    # they receive more \"time\" as per the requirement.
    base_teaching_units = 10 # Placeholder until specific sessions/quantities are added
    multiplier = TEACHING_MULTIPLIERS[\"lecture_new_to_new_lecturer\"] if has_new_lecturer else TEACHING_MULTIPLIERS[\"lecture_standard\"]
    teaching_hours = base_teaching_units * multiplier

    # Assessment Calculations
    # Every module has one assessment with the module leader setting it.
    # Since we don't know if it is auto or manual yet, we use a standard calculation
    # for the "setting" part and assume all other aspects are shared.
    assessment_hours = 0.0
    # Note: 'auto_paper_standard'/'manual_paper_standard' include the setting component.
    # We choose a default unless specific status is known.
    assessment_hours = ASSESSMENT_MULTIPLIERS[\"auto_paper_standard\"]

    # Supervision Calculations
    # Each teacher has 10 project students and 20 pastoral students.
    # Total supervision hours are calculated for the module's pool.
    supervision_hours = 0.0
    num_teachers = len(module.teachers)
    if num_teachers > 0:
        # Each teacher has a set amount of students, so we multiply by num_teachers
        # to get the total 'points' for the module pool.
        pastoral_count = 20 * num_teachers
        project_count = 10 * num_teachers

        # Determine if it is an MS or UG project based on stage (heuristic)
        if module.stage >= 10:
            proj_mult = SUPERVISION_MULTIPLIRES[\"ms_project\"]
        else:
            proj_mult = SUPERVISION_MULTIPLIERS[\"ug_project\"]

        supervision_hours = (pastoral_count * SUPERVISION_MULTIPLIERS[\"pastoral\"]) + \
                             (project_count * proj_mult)

    online_extra = 0.0
    # Handle special online cases
    if module.has_h_m_variants:
        # Example placeholder for multi-variant handling
        pass

    total_hours = total_base + teaching_hours + assessment_hours + supervision_hours + online_extra

    return {
        \"module_name\": module.name,
        \"total_calculation_points\": total_hours,
        \"num_teachers\": num_teachers,
        \"per_teacher_share\": total_hours / max(num_teachers, 1),
        \"has_new_lecturer_present\": has_new_lecturer
    }

def process_all_modules(modules: List[ModuleData]):
    \"\"\"Processes all modules and prints/returns their workload analysis.\"\"\"
    results = []
    for m in modules:
        res = calculate_module_workload(m)
        results.append(res)
    return results

if __name__ == \"__main__\":
    from data_loader import load_modules
    data = load_modules(\"WTW.csv\")
    results = process_all_modules(data)
    for r in results:
        print(f\"Module: {r['module_name']} | Total: {r['total_calculation_points']:.2f} | Share: {r['per_teacher_share']:.2f}\")
