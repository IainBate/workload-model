"""
Main entry point for the Workload Model calculator.
Orchestrates data loading, calculation, and output generation.

Usage:
    python main.py                  # Run with default (latest) WTW file
    python main.py --output-dir out  # Custom output directory
    python main.py --dry-run         # Show data summary without full calculation
"""

import argparse
import os
import sys

# Get project root (parent of scripts folder)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)

# Add project root to path for imports
sys.path.insert(0, SCRIPTS_DIR)

from data_loader import (
    load_all_data, normalize_name, _load_name_lookup, _build_reverse_lookup,
    _prompt_category_match, sync_adjustment_names, WTW_XLSX_FILENAME, YEAR_SHEET_PATTERN,
)
from workload_calculator import calculate_workload
from validation import validate_all_results, run_validation_pipeline
from output_generator import OUTPUT_DIR, generate_all_outputs
from new_individual_reports import generate_new_style_individual_reports
from calculation_baseline import export_baseline

# Try to import Google Sheets integration (optional)
try:
    from google_sheets import write_workload_to_google_sheets
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False

# Try to import publishing strategy modules (optional)
try:
    from email_data import load_staff_emails, get_all_staff_emails
    EMAIL_DATA_AVAILABLE = True
except ImportError:
    EMAIL_DATA_AVAILABLE = False

try:
    from google_forms import create_feedback_form, generate_prefilled_urls
    GOOGLE_FORMS_AVAILABLE = True
except ImportError:
    GOOGLE_FORMS_AVAILABLE = False

try:
    from email_sender import send_emails_via_smtp, verify_smtp_config
    EMAIL_SENDER_AVAILABLE = True
except ImportError:
    EMAIL_SENDER_AVAILABLE = False

try:
    from feedback_dashboard import generate_feedback_summary
    FEEDBACK_DASHBOARD_AVAILABLE = True
except ImportError:
    FEEDBACK_DASHBOARD_AVAILABLE = False


def prompt_name_match(user_name: str, canonical_name=None) -> bool:
    """Interactive prompt for unknown staff names."""
    if canonical_name:
        response = input(f"  Does '{user_name}' refer to '{canonical_name}'? (y/n): ").strip().lower()
        return response == "y"
    else:
        response = input(f"  Unknown name: '{user_name}'. Use as-is? (y/n): ").strip().lower()
        return response == "y"


def detect_wtw_year_sheets(base_dir: str = "."):
    """Detect the year-named sheets (e.g. "2026-7") in the WTW workbook."""
    path = os.path.join(base_dir, WTW_XLSX_FILENAME)
    if not os.path.exists(path):
        return []
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    return sorted(s for s in wb.sheetnames if YEAR_SHEET_PATTERN.match(s))


def print_data_summary(year_data, results=None):
    """Print a summary of loaded data and/or calculation results."""
    print(f"\n{'='*60}")
    print(f"Workload Model Report - Year {year_data.year_label}")
    print(f"{'='*60}")

    print(f"\nModules loaded: {len(year_data.modules)}")
    for m in year_data.modules:
        student_info = f"{m.student_count} students" if m.student_count > 0 else "no student data"
        print(f"  - {m.name} ({m.codes[0]}) [{m.credits}cr, Stage {m.stage}] - {student_info}")

    # Convert staff tuple to dict for iteration
    staff_dict = {s.canonical_name: s for s in year_data.staff}
    print(f"\nStaff in roster: {len(year_data.staff)}")
    for name, staff in sorted(staff_dict.items()):
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
    parser.add_argument("--output-dir", type=str, default=".", help="Output directory")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory (default: data/)")
    parser.add_argument("--dry-run", action="store_true", help="Show data summary only")
    parser.add_argument("--validate-only", action="store_true", help="Run calculation and validation only, no output generation")
    parser.add_argument("--export-baseline", action="store_true", help="Export the structured calculation baseline (baseline/expected_results.json) and exit")
    parser.add_argument("--interactive", action="store_true", help="Prompt for unknown names")
    parser.add_argument("--google-sheets", action="store_true", help="Upload results to Google Sheets after calculation")

    # Publishing strategy arguments
    parser.add_argument("--generate-forms", action="store_true", help="Create Google Forms for staff feedback")
    parser.add_argument("--form-title", type=str, default=None, help="Title for the feedback form (default: 'Workload Review {year}')")
    parser.add_argument("--send-emails", action="store_true", help="Send emails with form links to staff")
    parser.add_argument("--smtp-config", type=str, default=None, help="Path to SMTP configuration YAML file")
    parser.add_argument("--feedback-csv", type=str, default=None, help="Path to exported feedback CSV (for dashboard)")
    args = parser.parse_args()

    # Get project root (parent of scripts folder)
    SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)

    base_dir = os.path.join(PROJECT_ROOT, "data") if args.data_dir is None else args.data_dir

    # Detect WTW workbook year sheets
    wtw_year_sheets = detect_wtw_year_sheets(base_dir)
    if not wtw_year_sheets:
        print(f"ERROR: No year-named sheet found in {WTW_XLSX_FILENAME!r}. "
              f"Expected a sheet named like '2026-7'.")
        sys.exit(1)

    print(f"Found WTW year sheets: {', '.join(wtw_year_sheets)}")
    print(f"Using: {wtw_year_sheets[-1]}")

    # Load all data (data_dir is passed, defaults to DATA_DIR inside load_all_data)
    print("\nLoading data...")
    if not args.interactive:
        # In non-interactive mode, pass None so unknown names/categories are
        # kept as-is / left unresolved rather than blocking on input
        year_data = load_all_data(data_dir=base_dir, unknown_callback=None, category_callback=None)
    else:
        year_data = load_all_data(data_dir=base_dir, unknown_callback=prompt_name_match, category_callback=_prompt_category_match)

    # Keep workload_adjustments.csv in sync: append a blank row for any active
    # staff member missing from it, so a human always has a ready-to-fill row.
    # Strictly additive - runs unconditionally, including under --dry-run.
    newly_added = sync_adjustment_names(year_data)
    if newly_added:
        print(f"\nAdded {len(newly_added)} new staff to workload_adjustments.csv: {', '.join(newly_added)}")

    # Print summary
    print_data_summary(year_data)

    if args.dry_run:
        print("\n(Dry run - no calculation performed)")
        return

    # Calculate workload
    print("\nCalculating workload...")
    results = calculate_workload(year_data)

    # Validate calculations before output
    print("\nValidating calculations...")
    if not run_validation_pipeline(results):
        print("\nValidation failed. Please check the errors above.")
        sys.exit(1)
    print("  All validations passed.")

    if args.export_baseline:
        path = export_baseline(results, year_data.year_label)
        print(f"\nCalculation baseline written to {path}")
        print(f"  {len(results)} staff recorded")
        return

    if args.validate_only:
        print("\n(Validate-only run - no output generation performed)")
        return

    # Print results
    print_data_summary(year_data, results)

    # Generate outputs
    print("\nGenerating outputs...")
    if args.output_dir == ".":
        output_dir = OUTPUT_DIR
    else:
        # For relative paths (not starting with /), join with PROJECT_ROOT
        # and resolve to absolute path without the ../ simplification issue
        if os.path.isabs(args.output_dir):
            output_dir = args.output_dir
        else:
            # Relative path - join and use realpath to get actual directory
            joined = os.path.join(PROJECT_ROOT, args.output_dir)
            output_dir = os.path.abspath(joined)
    generate_all_outputs(results, year_data, output_dir)
    generate_new_style_individual_reports(results, year_data, output_dir)

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

    # Publishing strategy: Create Google Forms for feedback
    if args.generate_forms:
        _handle_form_generation(args, results, year_data)

    # Publishing strategy: Send emails with form links
    if args.send_emails:
        _handle_email_send(args, results, year_data, output_dir)

    # Publishing strategy: Generate feedback dashboard
    if args.feedback_csv:
        _handle_feedback_dashboard(args, results, output_dir)

    print("\nDone.")


def _handle_form_generation(args, results, year_data):
    """Handle Google Form generation and URL creation."""
    if not GOOGLE_FORMS_AVAILABLE:
        print("\nGoogle Forms integration is not available.")
        print("Install with: pip install google-api-python-client google-auth")
        return

    print("\n" + "="*60)
    print("Google Forms Integration")
    print("="*60)

    # Load emails for pre-filling
    if EMAIL_DATA_AVAILABLE:
        emails, missing_names = get_all_staff_emails(year_data)
        print(f"\nLoaded email addresses for {len(emails)} staff members")
        if missing_names:
            print(f"  No confirmed address for {len(missing_names)}: {', '.join(missing_names)}")

    # Create or use existing form
    form_title = args.form_title or f"Workload Review {year_data.year_label}"
    print(f"\nCreating feedback form: {form_title}")

    # Note: Without OAuth, we provide instructions for manual form creation
    print("\nNOTE: Google Forms API requires OAuth credentials.")
    print("To proceed manually:")
    print(f"  1. Go to https://docs.google.com/forms/u/0/")
    print("  2. Create a new blank form")
    print(f"  3. Title: {form_title}")
    print("  4. Add questions for feedback collection")
    print("  5. Get your form ID from the URL (forms.gle/{FORM_ID})")

    # Generate prefilled URLs using manual approach
    print("\nTo generate pre-filled URLs after creating the form:")
    print(f"  python -c \"from google_forms import generate_prefilled_urls; ...\"")


def _handle_email_send(args, results, year_data):
    """Handle SMTP email sending."""
    if not EMAIL_SENDER_AVAILABLE:
        print("\nEmail sender is not available.")
        return

    print("\n" + "="*60)
    print("Email Distribution")
    print("="*60)

    # Load emails
    if EMAIL_DATA_AVAILABLE:
        emails = get_all_staff_emails(year_data)
        print(f"\nLoaded email addresses for {len(emails)} staff members")
    else:
        print("\nEmail data module not available.")
        return

    # Load SMTP config
    smtp_config_path = args.smtp_config
    if smtp_config_path and os.path.exists(smtp_config_path):
        import yaml
        with open(smtp_config_path, 'r') as f:
            smtp_config = yaml.safe_load(f)
    else:
        print("\nSMTP configuration not provided or file not found.")
        print("Please provide --smtp-config path to YAML config file")
        return

    # Verify SMTP config
    if not verify_smtp_config(smtp_config):
        print("\nSMTP configuration is incomplete.")
        return

    # Generate form URLs (placeholder - would use actual form ID)
    print("\nGenerating pre-filled form URLs...")
    if GOOGLE_FORMS_AVAILABLE and EMAIL_DATA_AVAILABLE:
        # In practice, you'd provide a form_id from a created form
        print("  Note: Form ID not provided. Use --form-id to generate URLs.")
        print("  Without form IDs, emails will be sent without personalized links.")
        form_urls = {r.name: "[FORM_URL_HERE]" for r in results}
    else:
        form_urls = {r.name: "[FORM_URL_HERE]" for r in results}

    # Send emails with attachments from output directory
    print(f"\nSending emails to {len(results)} staff members...")
    statuses = send_emails_via_smtp(results, form_urls, smtp_config, output_dir=output_dir)

    success_count = sum(1 for v in statuses.values() if v)
    fail_count = len(statuses) - success_count
    print(f"\nEmail send complete: {success_count} succeeded, {fail_count} failed")


def _handle_feedback_dashboard(args, results, output_dir):
    """Generate feedback summary dashboard."""
    if not FEEDBACK_DASHBOARD_AVAILABLE:
        print("\nFeedback dashboard is not available.")
        return

    print("\n" + "="*60)
    print("Feedback Dashboard")
    print("="*60)

    # Generate the dashboard
    html_path = generate_feedback_summary(
        results=results,
        feedback_csv_path=args.feedback_csv,
        output_dir=output_dir,
        year_label=getattr(results[0], 'year_label', '2026-7') if results else '2026-7',
        deadline=None  # Can be added via --deadline if needed
    )

    print(f"\nFeedback dashboard generated: {html_path}")


if __name__ == "__main__":
    main()
