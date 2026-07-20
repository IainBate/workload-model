#!/usr/bin/env python3
"""Debug script to trace project load lookup for Chris."""
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

from data_loader import normalize_name

# Simulate what happens when processing "Chris CB"
raw_name = "Chris CB"
canonical = normalize_name(raw_name, reverse_lookup, unknown_callback=None)
print(f"raw_name: '{raw_name}'")
print(f"canonical: '{canonical}'")

# Load project load data and trace lookup
import csv
project_load_data = {}
path = DATA_DIR / 'project_load.csv'
with open(path, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        person = row.get("Person", "").strip()
        if not person or person == "Total FTE":
            continue
        project_load_data[person] = {
            "project_load_raw": float(row.get("Project Load", 0) or 0),
        }

print(f"\n=== Project load data keys ===")
for key in project_load_data:
    print(f"  '{key}'")

print(f"\n=== Lookup trace for raw_name='{raw_name}', canonical='{canonical}' ===")
proj_data = None

# First loop
print("\nFirst loop (checking against raw_name):")
for key, val in project_load_data.items():
    matches_raw_upper = (key.upper() == raw_name.upper())
    matches_raw_lower = (key.lower() == raw_name.lower())
    print(f"  '{key}': upper match={matches_raw_upper}, lower match={matches_raw_lower}")
    if key.upper() == raw_name.upper() or key.lower() == raw_name.lower():
        proj_data = val
        print(f"    MATCH! (raw)")
        break

# Check canonical match in first loop
if not proj_data:
    for key, val in project_load_data.items():
        matches_canonical = (key.lower() == canonical.lower())
        if matches_canonical:
            proj_data = val
            print(f"\n  First loop also has canonical match: '{key}' == '{canonical}' -> MATCH!")
            break

if not proj_data:
    # Second loop
    print("\nSecond loop (normalizing keys against canonical):")
    for key, val in project_load_data.items():
        norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
        matches_norm = (norm_key == canonical)
        print(f"  '{key}' -> '{norm_key}': match={matches_norm}")
        if norm_key == canonical:
            proj_data = val
            print(f"    MATCH! (normalized)")
            break

print(f"\n=== Result ===")
if proj_data:
    print(f"Found project load data: {proj_data}")
else:
    print("No project load data found!")
