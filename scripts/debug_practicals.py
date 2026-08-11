#!/usr/bin/env python3
"""Debug practical hours calculation."""
import sys
sys.path.insert(0, '.')

# Suppress interactive prompts by setting environment variable before import
import os
os.environ['WORKLOAD_MODEL_INTERACTIVE'] = '0'

from data_loader import load_all_data
from workload_calculator import calculate_workload

year_data = load_all_data(data_dir='../data')
results = calculate_workload(year_data, validate_input=True)

for r in results:
    if 'Crispin-Bailey' in r.name or 'Pomfret' in r.name:
        print(f'{r.name}: FTE={r.fte}')
        for mod_name, mb in sorted(r.teaching_module_breakdowns.items()):
            practicals = mb.get('practicals', 'NOT FOUND')
            ps_structured = mb.get('practicals_structured', {})
            ps_total = ps_structured.get('total', 'NOT FOUND') if isinstance(ps_structured, dict) else 'NOT FOUND'
            print(f'  {mod_name}: practicals={practicals}, structured_total={ps_total}')
        print()
