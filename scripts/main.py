"""
Main entry point for the Workload Model calculator.
Orchestrates data loading, calculation, and output generation.

Usage:
    python main.py                  # Run with default (latest) WTW file
    python main.py --year 2026-7    # Run with specific year
    python main.py --output-dir out  # Custom output directory
    python main.py --dry-run         # Show data summary without full calculation
"""

import argparse
import os
import sys
import glob

# Get project root (parent of scripts folder)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)

# Add project root to path for imports
sys.path.insert(0, SCRIPTS_DIR)

from data_loader import load_all_data, normalize_name, _load_name_lookup, _build_reverse_lookup
from workload_calculator import calculate_workload
from output_generator import OUTPUT_DIR, generate_all_outputs

# Try to import Google Sheets integration (optional)
try:
    from google_sheets import write_workload_to_google_sheets
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False


def prompt_google_sheets_upload() -> bool:
    """Ask user if they want to upload results to Google Sheets."""
    try:
        response = input("\nUpload results to Google Sheets? (y/n): ").strip().lower()
        return response == "y"
    except EOFError:
        return False


def prompt_name_match(user_name: str, canonical_name=None) -> bool:
    """Interactive prompt for unknown staff names."""
    if canonical_name:
        response = input(f"  Does '{user_name}' refer to '{canonical_name}'? (y/n): ").strip().lower()
        return response == "y"
    else:
        response = input(f"  Unknown name: '{user_name}'. Use as-is? (y/n): ").strip().lower()
        return response == "y"


def detect_wtw_files(base_dir: str = "."):
    """Detect available WTW files."""
    files = sorted(glob.glob(os.path.join(base_dir, "WTW *.csv")))
    return files


def print_data_summary(year_data, results=None):
    """Print a summary of loaded data and/or calculation results."""
    print(f"\n{'='*60}")
    print(f"Workload Model Report - Year {year_data.year_label}")
    print(f"{'='*60}")

    print(f"\nModules loaded: {len(year_data.modules)}")
    for m in year_data.modules:
        student_info = f"{m.student_count} students" if m.student_count > 0 else "no student data"
        print(f"  - {m.name} ({m.codes[0]}) [{m.credits}cr, Stage {m.stage}] - {student_info}")

    print(f"\nStaff in roster: {len(year_data.staff)}")
    for name, staff in sorted(year_data.staff.items()):
        fte_str = f"FTE {staff.fte}" if staff.fte else "FTE unknown"
        cat_str = f" ({staff.category})" if staff.category else ""
        print(f"  - {name} [{fte_str}{cat_str}]")

    if results:
        print(f"\n{'='*60}")
        print(f"Workload Results")
        print(f"{'='*60}")
        print(f"\n{'Name':<25} {'FTE':>4} {'Total':>8} {'Teach':>8} {'Research':>8} {'Admin':>8}")
        print(f"{'-'*65}")
        for r in sorted(results, key=lambda x: x.total_hours, reverse=True):
            print(f"{r.name:<25} {r.fte:>4.2f} {r.total_hours:>8.1f} {r.teaching_hours:>8.1f} {r.research_hours:>8.1f} {r.admin_hours:>8.1f}")

        # Summary statistics
        total_teaching = sum(r.teaching_hours for r in results)
        total_research = sum(r.research_hours for r in results)
        total_admin = sum(r.admin_hours for r in results)
        total_all = sum(r.total_hours for r in results)
        print(f"\n{'-'*65}")
        print(f"{'TOTAL':<25} {'':>4} {total_all:>8.1f} {total_teaching:>8.1f} {total_research:>8.1f} {total_admin:>8.1f}")

        # Average FTE
        avg_fte = sum(r.fte for r in results) / len(results) if results else 0
        print(f"\nAverage FTE: {avg_fte:.2f}")
        print(f"Full-time equivalent staff: {avg_fte:.1f}")

        # Flag issues
        flagged = [r for r in results if r.missing_data or r.assumptions]
        if flagged:
            print(f"\n{'='*60}")
            print(f"Staff with flagged items:")
            print(f"{'='*60}")
            for r in flagged:
                if r.missing_data:
                    print(f"  {r.name}: MISSING - {', '.join(r.missing_data)}")
                if r.assumptions:
                    print(f"  {r.name}: ASSUMPTION - {', '.join(r.assumptions)}")


def main():
    parser = argparse.ArgumentParser(description="Workload Model Calculator")
    parser.add_argument("--year", type=str, default=None, help="Academic year (e.g., 2026-7)")
    parser.add_argument("--output-dir", type=str, default=".", help="Output directory")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory (default: data/)")
    parser.add_argument("--dry-run", action="store_true", help="Show data summary only")
    parser.add_argument("--interactive", action="store_true", help="Prompt for unknown names")
    parser.add_argument("--google-sheets", action="store_true", help="Upload results to Google Sheets after calculation")
    args = parser.parse_args()

    # Get project root (parent of scripts folder)
    SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)

    base_dir = os.path.join(PROJECT_ROOT, "data") if args.data_dir is None else args.data_dir

    # Detect WTW files
    wtw_files = detect_wtw_files(base_dir)
    if not wtw_files:
        print("ERROR: No WTW CSV files found. Expected files matching 'WTW *.csv'.")
        sys.exit(1)

    print(f"Found WTW files: {', '.join(os.path.basename(f) for f in wtw_files)}")
    print(f"Using: {os.path.basename(wtw_files[-1])}")

    # Load all data (data_dir is passed, defaults to DATA_DIR inside load_all_data)
    print("\nLoading data...")
    unknown_callback = prompt_name_match if args.interactive else None
    if not args.interactive:
        # In non-interactive mode, pass None so unknown names are kept as-is
        year_data = load_all_data(data_dir=base_dir, unknown_callback=None)
    else:
        year_data = load_all_data(data_dir=base_dir, unknown_callback=prompt_name_match)

    # Print summary
    print_data_summary(year_data)

    if args.dry_run:
        print("\n(Dry run - no calculation performed)")
        return

    # Calculate workload
    print("\nCalculating workload...")
    results = calculate_workload(year_data)

    # Print results
    print_data_summary(year_data, results)

    # Generate outputs
    print("\nGenerating outputs...")
    output_dir = OUTPUT_DIR if args.output_dir == "." else os.path.join(PROJECT_ROOT, args.output_dir)
    generate_all_outputs(results, year_data, output_dir)

    print(f"\nOutput files in {output_dir}:")
    for f in os.listdir(output_dir):
        if any(ext in f for ext in ['.csv', '.xlsx', '.png', '.html']):
            size = os.path.getsize(os.path.join(output_dir, f))
            print(f"  - {f} ({size:,} bytes)")

    # Upload to Google Sheets if requested
    if args.google_sheets:
        if not GOOGLE_SHEETS_AVAILABLE:
            print("\nGoogle Sheets integration is not available.")
            print("Install with: pip install gspread")
        else:
            write_workload_to_google_sheets(results, year_data)

    print("\nDone.")


if __name__ == "__main__":
    main()
