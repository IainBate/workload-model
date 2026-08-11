#!/usr/bin/env python3
"""Debug practical hours calculation."""
import sys
sys.path.insert(0, '.')

# Patch input() to always return "y" for interactive prompts
original_input = __builtins__.input if isinstance(__builtins__, dict) else getattr(__builtins__, 'input', None)
def mock_input(prompt=""):
    return "y"
if isinstance(__builtins__, dict):
    __builtins__['input'] = mock_input
else:
    import builtins
    builtins.input = mock_input

from data_loader import load_all_data
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
    module_teaching = _calculate_teaching_workload(
        sys2_module,
        [normalize_name(t.strip(), year_data.reverse_lookup, unknown_callback=None) or t.strip() for t in sys2_module.teachers],
        year_data.known_lecturers,
        year_data.known_lecturers_per_module,
        {}
    )

    print("\nPer-teacher breakdown from _calculate_teaching_workload:")
    for teacher, breakdown in module_teaching.items():
        practicals = breakdown.get('teaching_breakdown', {}).get('practicals', 'NOT FOUND')
        print(f"  {teacher}: practicals={practicals}")

# Now run full calculation
results = calculate_workload(year_data, validate_input=True)

print("\nPer-teacher module breakdown after full calculation:")
for r in results:
    if 'Crispin-Bailey' in r.name or 'Pomfret' in r.name:
        print(f'{r.name}:')
        for mod_name, mb in sorted(r.teaching_module_breakdowns.items()):
            practicals = mb.get('practicals', 'NOT FOUND')
            print(f"  {mod_name}: practicals={practicals}")
