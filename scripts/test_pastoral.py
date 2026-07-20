#!/usr/bin/env python3
import csv
from pathlib import Path

DATA_DIR = Path('data')
path = DATA_DIR / 'pastoral_load.csv'
print(f'File exists: {path.exists()}')

data = {}
with open(path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        supervisor = row.get('Supervisor', '').strip().upper()
        total = row.get('UG & PGT Supervisees', '0').strip()
        data[supervisor] = int(total) if total else 0

print(f'CHRISTOPHER CRISPIN-BAILEY in keys: {"CHRISTOPHER CRISPIN-BAILEY" in data}')
if "CHRISTOPHER CRISPIN-BAILEY" in data:
    print(f'Value: {data["CHRISTOPHER CRISPIN-BAILEY"]}')

# Test comparison
raw_name = "Chris CB"
canonical = "Christopher Crispin-Bailey"

print(f"\nTesting comparisons:")
for key, val in data.items():
    if 'crispin' in key.lower() or 'bailey' in key.lower():
        print(f"key='{key}', key.lower()='{key.lower()}'")
        print(f"  raw_name='{raw_name}', raw_name.lower()='{raw_name.lower()}'")
        print(f"  canonical='{canonical}', canonical.lower()='{canonical.lower()}'")
        print(f"  key.lower() == raw_name.lower(): {key.lower() == raw_name.lower()}")
        print(f"  key.lower() == canonical.lower(): {key.lower() == canonical.lower()}")
