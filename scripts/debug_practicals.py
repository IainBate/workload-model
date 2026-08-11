#!/usr/bin/env python3
"""Debug practical hours calculation."""
import sys
sys.path.insert(0, '.')

# Patch input() to always return "y" for interactive prompts
def mock_input(prompt=""):
    return "y"
if isinstance(__builtins__, dict):
    __builtins__['input'] = mock_input
else:
    import builtins
    builtins.input = mock_input

from data_loader import load_all_data, normalize_name, allocate_supervision
from workload_calculator import calculate_workload, _calculate_teaching_workload

year_data = load_all_data(data_dir='../data')

# Find SYS2 module
sys2_module = None
for m in year_data.modules:
    if 'SYS2' in m.name or 'COM00029I' in m.codes:
        sys2_module = m
        break

if sys2_module:
    print(f"Found SYS2: {sys2_module.name}")
    print(f"Teachers: {sys2_module.teachers}")

    # Calculate module teaching directly
    normalized_teachers = []
    for t in sys2_module.teachers:
        norm = normalize_name(t.strip(), year_data.reverse_lookup, unknown_callback=None)
        if norm:
            normalized_teachers.append(norm)
        else:
            normalized_teachers.append(t.strip())

    print(f"Normalized teachers: {normalized_teachers}")

    from dataclasses import dataclass

    # Create a fake staff_dict for supervision allocation
    @dataclass
    class FakeStaffData:
        fte: float = 1.0
        roles: list = None
        phd_supervisions: int = 0
        phd_co_supervisions: int = 0
        phd_assessor_count: int = 0
        pastoral_students: int = 20
        project_load: float = 10.0
        active: bool = True

    staff_dict = {}
    for t in normalized_teachers:
        staff_dict[t] = FakeStaffData()

    supervision = allocate_supervision(staff_dict)

    # Add debug to _calculate_practical_hours_and_breakdown
    import workload_calculator as wc

    original_func = wc._calculate_practical_hours_and_breakdown
    def debug_practical_calc(module, teachers, lecturer_types):
        result = original_func(module, teachers, lecturer_types)
        print(f"\n=== DEBUG: {module.name} ===")
        print(f"  Teachers: {teachers}")
        print(f"  lecturers_types: {lecturer_types}")

        # Calculate expected values
        from workload_calculator import TEACHING_WEEKS_PER_SEMESTER, config
        practicals_count = module.practicals
        std_first_session_weekly = getattr(module, 'practical_contact_hours', config.TEACHING_PROBLEM_CLASS)
        contact_weeks = TEACHING_WEEKS_PER_SEMESTER

        first_session_rate = config.TEACHING_PROBLEM_CLASS
        repeat_rate = config.REPETITION_MULTIPLIER

        if practicals_count > 1:
            first_session_total = practicals_count * std_first_session_weekly * first_session_rate * contact_weeks
            repeat_sessions = max(0, practicals_count - 1)
            repeat_session_total = repeat_sessions * std_first_session_weekly * first_session_rate * repeat_rate * contact_weeks
            total_practical_hours = first_session_total + repeat_session_total

            print(f"  Calculated total: {total_practical_hours}")
            print(f"  n_teachers: {len(teachers)}")
            print(f"  base_share per teacher (before multiplier): {total_practical_hours / len(teachers)}")

            for t, ltype in lecturer_types:
                mult = config.TEACHING_MULTIPLIERS.get(ltype, 1.0)
                expected = (total_practical_hours / len(teachers)) * mult
                print(f"    Expected for {t} ({ltype}, {mult}x): {expected}")

        print(f"  practicals_breakdown: {result.get('practicals_breakdown', {})}")
        print(f"  individual_practical_hours: {result.get('individual_practical_hours', {})}")
        return result
    wc._calculate_practical_hours_and_breakdown = debug_practical_calc

    module_teaching = _calculate_teaching_workload(
        sys2_module,
        normalized_teachers,
        year_data.known_lecturers,
        year_data.known_lecturers_per_module,
        {},
        supervision=supervision
    )

    print("\nPer-teacher breakdown from _calculate_teaching_workload:")
    for teacher, breakdown in module_teaching.items():
        practicals = breakdown.get('teaching_breakdown', {}).get('practicals', 'NOT FOUND')
        print(f"  {teacher}: practicals={practicals}")
