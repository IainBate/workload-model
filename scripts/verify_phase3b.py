#!/usr/bin/env python3
"""Verify Phase 3b: structured supervision breakdowns."""

from data_loader import load_all_data, WorkloadResult
from workload_calculator import calculate_workload

# Load data and run calculation (non-interactive mode)
year_data = load_all_data(data_dir='../data', unknown_callback=None, category_callback=None)
results = calculate_workload(year_data)

print("=== Phase 3b Verification: Structured Supervision Breakdown ===\n")

adrian_found = False
for r in results:
    if 'Adrian' in r.name:
        adrian_found = True
        print(f'Staff: {r.name}')
        print(f'Total Hours: {r.total_hours}')
        print(f'\nteaching_breakdown keys: {list(r.teaching_breakdown.keys())}')
        print(f'pastoral_breakdown: {r.pastoral_breakdown}')
        print(f'project_breakdown: {r.project_breakdown}')

        # Verify structured data
        if r.pastoral_breakdown:
            print(f'\nPastoral breakdown check:')
            print(f'  - student_count: {r.pastoral_breakdown.get("student_count")}')
            print(f'  - rate: {r.pastoral_breakdown.get("rate")}')
            print(f'  - total: {r.pastoral_breakdown.get("total")}')

        if r.project_breakdown:
            print(f'\nProject breakdown check:')
            print(f'  - project_count: {r.project_breakdown.get("project_count")}')
            print(f'  - level: {r.project_breakdown.get("level")}')
            print(f'  - rate: {r.project_breakdown.get("rate")}')
            print(f'  - total: {r.project_breakdown.get("total")}')

        # Verify that structured data matches the calculated totals
        if r.pastoral_breakdown:
            expected_pastoral = r.pastoral_breakdown.get('student_count', 0) * r.pastoral_breakdown.get('rate', 0)
            actual_pastoral = r.pastoral_breakdown.get('total', 0)
            assert abs(expected_pastoral - actual_pastoral) < 0.1, f"Pastoral mismatch: {expected_pastoral} vs {actual_pastoral}"
            print(f'\n[PASS] Pastoral supervision calculation verified')

        if r.project_breakdown:
            expected_project = r.project_breakdown.get('project_count', 0) * r.project_breakdown.get('rate', 0)
            actual_project = r.project_breakdown.get('total', 0)
            assert abs(expected_project - actual_project) < 0.1, f"Project mismatch: {expected_project} vs {actual_project}"
            print(f'[PASS] Project supervision calculation verified')

        break

if not adrian_found:
    print("WARNING: Adrian Bors not found in results")

# Check a few more staff members for variety
print("\n=== Checking other staff with structured breakdowns ===\n")
for r in results[:10]:
    if r.pastoral_breakdown or r.project_breakdown:
        name = r.name
        pastoral = r.pastoral_breakdown.get('total', 0) if r.pastoral_breakdown else 0
        project = r.project_breakdown.get('total', 0) if r.project_breakdown else 0
        print(f'{name}: Pastoral={pastoral:.1f}h, Project={project:.1f}h')

print("\n=== Phase 3b verification complete ===")
