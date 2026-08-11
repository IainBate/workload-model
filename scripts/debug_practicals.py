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

    # Create a fake staff_dict for supervision allocation
    staff_dict = {}
    for t in normalized_teachers:
        staff_dict[t] = type('StaffData', (), {
            'fte': 1.0,
            'roles': [],
            'phd_supervisions': 0,
            'phd_co_supervisions': 0,
            'phd_assessor_count': 0,
            'student_load': None,
            'project_count_ug': 0,
            'project_count_msc': 0,
            'active': True
        })()

    supervision = allocate_supervision(staff_dict)

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
