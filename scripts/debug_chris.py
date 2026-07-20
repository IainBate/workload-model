#!/usr/bin/env python3
"""Debug script to trace Chris Crispin-Bailey data loading."""
import sys
sys.path.insert(0, '.')

from pathlib import Path
DATA_DIR = Path('../data')

# Load name lookup
import json
with open(DATA_DIR / 'staff_name_lookup.json', 'r', encoding='utf-8-sig') as f:
    mappings = json.load(f).get('mappings', {})

def _build_reverse_lookup(mappings):
    """Build a reverse lookup: alias -> canonical_name."""
    reverse = {}
    for canonical, aliases in mappings.items():
        for alias in aliases:
            reverse[alias.strip().lower()] = canonical
    return reverse

reverse_lookup = _build_reverse_lookup(mappings)

print("=== Name Lookup Tests ===")
test_names = ["Chris CB", "Chris Crispin-Bailey", "Christopher Crispin-Bailey"]
for name in test_names:
    key = name.lower()
    if key in reverse_lookup:
        print(f"'{name}' -> '{reverse_lookup[key]}' (from aliases)")
    else:
        # Check if any alias matches
        for alias, canonical in reverse_lookup.items():
            if 'crispin' in alias.lower() and 'bailey' in alias.lower():
                print(f"  Found Chris-related: '{alias}' -> '{canonical}'")

print("\n=== Pastoral Load CSV ===")
import csv
with open(DATA_DIR / 'pastoral_load.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        supervisor = row.get('Supervisor', '').strip()
        total = row.get('UG & PGT Supervisees', '').strip()
        if 'crispin' in supervisor.lower() or 'bailey' in supervisor.lower():
            print(f"'{supervisor}': {total}")

print("\n=== Project Load CSV ===")
with open(DATA_DIR / 'project_load.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        name = row.get('Staff Name', '').strip()
        project_raw = row.get('Project Load', '').strip()
        if 'crispin' in name.lower() or 'bailey' in name.lower():
            print(f"'{name}': raw={project_raw}")

print("\n=== Staff Data Loading ===")
# Now load all data to see what Chris gets
from data_loader import load_all_data, normalize_name

unknown_callback = None  # Don't prompt for unknown names
year_data = load_all_data(data_dir=str(DATA_DIR), unknown_callback=unknown_callback)

if 'Christopher Crispin-Bailey' in year_data.staff:
    chris = year_data.staff['Christopher Crispin-Bailey']
    print(f"Found Christopher Crispin-Bailey:")
    print(f"  pastoral_students: {chris.pastoral_students}")
    print(f"  project_load: {chris.project_load}")
else:
    print("Christopher Crispin-Bailey NOT in staff data!")
    print(f"Staff names: {list(year_data.staff.keys())}")

print("\n=== WTW Modules with Chris CB ===")
for m in year_data.modules:
    if 'Chris' in str(m.teachers) or 'crispin' in str(m.teachers).lower():
        print(f"{m.name} ({m.codes[0]}): teachers={m.teachers}, lead={m.lead_name}")
