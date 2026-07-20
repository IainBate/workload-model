#!/usr/bin/env python3
import json
from pathlib import Path

DATA_DIR = Path('data')
path = DATA_DIR / 'staff_name_lookup.json'

with open(path, 'r', encoding='utf-8-sig') as f:
    mappings = json.load(f).get('mappings', {})

def _build_reverse_lookup(mappings):
    """Build a reverse lookup: alias -> canonical_name."""
    reverse = {}
    for canonical, aliases in mappings.items():
        for alias in aliases:
            reverse[alias.strip().lower()] = canonical
    return reverse

reverse_lookup = _build_reverse_lookup(mappings)

print(f"reverse_lookup['chris cb'] = {reverse_lookup.get('chris cb', 'NOT FOUND')}")

def normalize_name(name: str, reverse_lookup):
    """Normalize a staff name to its canonical form."""
    if not name:
        return None
    stripped = name.strip()

    name = name.strip()
    key = name.lower()

    if key in reverse_lookup:
        return reverse_lookup[key]

    # Try partial match (e.g., "Iain B" should match "Iain Bate")
    for alias, canonical in reverse_lookup.items():
        if key == alias.lower():
            return canonical
        if (len(key) <= 3 and key == alias.lower()[:len(key)]) or \
           (' ' in key and key == alias.lower()[:len(key)]):
            return canonical

    # Non-interactive mode: return the raw name (will be flagged later)
    if stripped.strip().lower() in {'as below', 'n/a', 'none'}:
        return None
    return stripped if stripped else None

raw_name = "Chris CB"
canonical = normalize_name(raw_name, reverse_lookup)

print(f"\nTesting normalization:")
print(f"  raw_name='{raw_name}'")
print(f"  canonical='{canonical}'")

# Now test pastoral lookup
import csv
DATA_DIR = Path('data')
path = DATA_DIR / 'pastoral_load.csv'
data = {}
with open(path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        supervisor = row.get('Supervisor', '').strip().upper()
        total = row.get('UG & PGT Supervisees', '0').strip()
        data[supervisor] = int(total) if total else 0

pastoral_students = 0
for key, val in data.items():
    print(f"Checking: key='{key}', key.lower()='{key.lower()}'")
    print(f"  raw_name.lower()='{raw_name.lower()}'")
    print(f"  canonical.lower()='{canonical.lower()}'")
    if key.lower() == raw_name.lower() or key.lower() == canonical.lower():
        print(f"  MATCH! val={val}")
        pastoral_students = val
        break

print(f"\nFinal pastoral_students: {pastoral_students}")
