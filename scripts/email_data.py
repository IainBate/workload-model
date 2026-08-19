"""
Staff email address loading for the workload model.

This module provides functionality to load staff email addresses from CSV files.
Emails are used for distributing workload reports and feedback forms.

No changes are made to existing data files - this module only reads optional files.
"""

import csv
from pathlib import Path
from typing import Dict, Optional

# Get project root directory (parent of scripts folder)
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"


def load_staff_emails(data_dir: str = None) -> Dict[str, str]:
    """Load staff email addresses from optional CSV files.

    Looks for emails in the following locations (in priority order):
    1. data/Staff Emails.csv - dedicated email file
    2. data/Staff Categories and FTE.csv with Email column

    Args:
        data_dir: Directory containing data files. Defaults to 'data' folder.

    Returns:
        Dict mapping canonical_name to email address. Empty dict if no emails found.

    File Format (Staff Emails.csv):
        Name,Email
        John Doe,john.doe@york.ac.uk

    File Format (extended Staff Categories and FTE.csv):
        Name,Category,FTE,Notes,Email
        John Doe,T and S,1.0,,john.doe@york.ac.uk
    """
    data_dir_path = Path(data_dir) if data_dir else DATA_DIR

    # Try dedicated email file first
    email_file = data_dir_path / "Staff Emails.csv"
    if email_file.exists():
        return _load_emails_from_dedicated_file(email_file)

    # Fall back to extended Staff Categories and FTE.csv
    categories_file = data_dir_path / "Staff Categories and FTE.csv"
    if categories_file.exists():
        return _load_emails_from_categories_file(categories_file)

    return {}


def _load_emails_from_dedicated_file(filepath: Path) -> Dict[str, str]:
    """Load emails from dedicated Staff Emails.csv file."""
    emails = {}
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Name") or "").strip()
            email = (row.get("Email") or "").strip()
            if name and email:
                emails[name] = email
    return emails


def _load_emails_from_categories_file(filepath: Path) -> Dict[str, str]:
    """Load emails from extended Staff Categories and FTE.csv file."""
    emails = {}
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Name") or "").strip()
            email = (row.get("Email") or "").strip()
            if name and email:
                emails[name] = email
    return emails


def generate_default_email(canonical_name: str, domain: str = "york.ac.uk") -> str:
    """Generate a default email address from a staff member's canonical name.

    Args:
        canonical_name: Staff member's full name (e.g., "John Smith")
        domain: Email domain (default: york.ac.uk)

    Returns:
        Generated email address (e.g., "john.smith@york.ac.uk")

    Note: This is a best-effort guess - actual emails may need manual verification.
    """
    if not canonical_name:
        return ""

    # Split name into parts
    parts = canonical_name.strip().split()
    if len(parts) < 2:
        # Single name - just use it with domain
        return f"{parts[0].lower()}@{domain}"

    # First name + last name format
    first_name = parts[0].lower()
    last_name = parts[-1].lower()

    # Remove common prefixes/suffixes from last name
    last_name = last_name.replace("jr.", "").replace("sr.", "").replace("ii", "").replace("iii", "")

    email = f"{first_name}.{last_name}@{domain}"
    return email


def verify_email_format(email: str) -> bool:
    """Verify that an email address has a valid format.

    Args:
        email: Email address to validate

    Returns:
        True if email appears valid, False otherwise
    """
    import re

    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def get_all_staff_emails(year_data) -> Dict[str, str]:
    """Get confirmed emails for staff in year_data.

    Matches canonical names against data/Staff Emails.csv (or the Email column
    of Staff Categories and FTE.csv). Deliberately does NOT fabricate an
    address for anyone missing from those sources - see generate_default_email()
    below for why "firstname.lastname@york.ac.uk" is a guess, not a fact: a
    workload report contains a colleague's personal data, so a guessed address
    that happens to belong to someone else - or simply bounces - is a real
    failure mode, not a formatting nicety. This mirrors the "no guessed data"
    rule the rest of the pipeline follows (CLAUDE.md) - missing addresses are
    reported via missing_names, not silently invented.

    Args:
        year_data: YearData object from load_all_data()

    Returns:
        (emails, missing_names): emails maps canonical_name to a confirmed
        address; missing_names lists staff with no entry in either source.
    """
    available_emails = load_staff_emails()

    emails = {}
    missing_names = []
    for staff in year_data.staff:
        name = staff.canonical_name
        if name in available_emails:
            emails[name] = available_emails[name]
        else:
            missing_names.append(name)

    return emails, missing_names
