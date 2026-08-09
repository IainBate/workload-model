#!/usr/bin/env python3
"""
Generate baseline outputs for the Workload Model.

This script runs the full calculation pipeline and saves all output artifacts
to a 'baseline/' directory. These files are then used by check_against_baseline.py
to verify that future changes don't alter output content.

Usage:
    python generate_baseline.py [--data-dir <dir>]
"""

import os
import sys
import shutil
from pathlib import Path

# Get project root (parent of scripts folder)
SCRIPTS_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPTS_DIR.parent

# Add project root to path for imports
sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import load_all_data, normalize_name
from workload_calculator import calculate_workload
from output_generator import OUTPUT_DIR, generate_all_outputs


def get_project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent


def generate_baseline(data_dir: str = None):
    """
    Generate baseline outputs from the current codebase.

    Args:
        data_dir: Optional custom data directory. If None, uses 'data/' subdir.
    """
    # Set up paths
    project_root = get_project_root()

    # Baseline directory - should be checked into version control
    baseline_dir = project_root / "baseline"

    print(f"Baseline directory: {baseline_dir}")

    # Create baseline directory if it doesn't exist
    baseline_dir.mkdir(exist_ok=True)

    # Data directory
    if data_dir is None:
        data_dir = project_root / "data"
    else:
        data_dir = Path(data_dir)
        if not data_dir.is_absolute():
            data_dir = project_root / data_dir

    print(f"Data directory: {data_dir}")

    # Load all data
    print("\nLoading data...")
    year_data = load_all_data(data_dir=str(data_dir), unknown_callback=None)
    print(f"  Modules loaded: {len(year_data.modules)}")
    print(f"  Staff in roster: {len(year_data.staff)}")

    # Calculate workload
    print("\nCalculating workload...")
    results = calculate_workload(year_data)
    print(f"  Results generated for {len(results)} staff members")

    # Generate all outputs to baseline directory
    print("\nGenerating outputs...")

    # Override OUTPUT_DIR to point to baseline
    original_output_dir = OUTPUT_DIR

    # Generate to baseline directory
    generate_all_outputs(results, year_data, output_dir=str(baseline_dir))

    print(f"\nBaseline outputs saved to: {baseline_dir}")
    print("Files generated:")
    for f in sorted(baseline_dir.iterdir()):
        if f.is_file():
            size = f.stat().st_size
            print(f"  - {f.name} ({size:,} bytes)")

    # Also save a copy of the input data summary for reference
    summary_file = baseline_dir / "input_summary.txt"
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(f"Workload Model Baseline Generation Summary\n")
        f.write(f"{'=' * 50}\n\n")
        f.write(f"Year: {year_data.year_label}\n")
        f.write(f"Modules: {len(year_data.modules)}\n")
        f.write(f"Staff: {len(year_data.staff)}\n")

        # List modules
        f.write(f"\nModules:\n")
        for m in year_data.modules:
            teachers_str = ', '.join(m.teachers[:3])  # First 3 only
            if len(m.teachers) > 3:
                teachers_str += "..."
            f.write(f"  - {m.name} ({m.codes[0]}) [{m.credits}cr, Stage {m.stage}] - {teachers_str}\n")

        # List staff
        f.write(f"\nStaff:\n")
        for s in sorted(year_data.staff, key=lambda x: x.canonical_name):
            roles_str = ', '.join(s.roles[:2]) if s.roles else "none"
            f.write(f"  - {s.canonical_name} [FTE: {s.fte}, Roles: {roles_str}]\n")

    print(f"\nInput summary saved to: {summary_file}")
    print("\nBaseline generation complete!")
    print("\nNext steps:")
    print("1. Run check_against_baseline.py once to verify harness works (should show 0 differences)")
    print("2. Commit the baseline/ directory to version control")
    print("3. Proceed with refactoring work, re-running check_against_baseline.py after each change")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate baseline outputs for workload model")
    parser.add_argument("--data-dir", type=str, default=None, help="Custom data directory path")
    args = parser.parse_args()

    generate_baseline(data_dir=args.data_dir)
