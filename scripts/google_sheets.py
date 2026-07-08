"""
Google Sheets integration for the workload model calculator.

This module provides functionality to:
1. Export data in formats compatible with Google Sheets
2. Provide instructions for manual import

NO API SETUP REQUIRED - This uses simple CSV export that you can
manually import into Google Sheets.

Usage:
    # Generate all outputs including CSV
    python main.py

    # Then manually import the CSV into Google Sheets:
    # 1. Open https://sheets.google.com
    # 2. Create new spreadsheet or open template
    # 3. File > Import > Upload > Select "Staff workload model.csv"
    # 4. Choose "Replace data" or "Insert rows"
"""

import os
from typing import List, Any, Optional

import gspread
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound

from data_loader import WorkloadResult, YearData


# Template spreadsheet ID (the source template that will be copied)
TEMPLATE_SPREADSHEET_ID = '1fqHmhhRvj1HIRcl_qqOglcGjLgT2aFNPl9ELholADGI'


def generate_google_sheets_data(results: List[WorkloadResult]) -> tuple:
    """
    Generate data in the format needed for Google Sheets.

    Returns:
        Tuple of (headers, rows) where headers is a list and rows is a 2D list
    """
    # Header row
    headers = [
        "Name", "FTE", "Total Hours",
        "Teaching Hours", "Research Hours", "Admin Hours",
        "Teaching Detail", "Research Detail", "Admin Detail",
        "Assumptions", "Missing Data"
    ]

    # Data rows
    rows = []
    for r in results:
        row = [
            r.name,
            float(r.fte),
            round(r.total_hours, 1),
            round(r.teaching_hours, 1),
            round(r.research_hours, 1),
            round(r.admin_hours, 1),
            r.teaching_detail.replace('\n', ' ').replace(',', ';'),
            r.research_detail.replace('\n', ' ').replace(',', ';'),
            r.admin_detail.replace('\n', ' ').replace(',', ';'),
            "; ".join(r.assumptions) if r.assumptions else "None",
            "; ".join(r.missing_data) if r.missing_data else "None",
        ]
        rows.append(row)

    return headers, rows


def write_workload_to_google_sheets(results: List[WorkloadResult], year_data: YearData,
                                     spreadsheet_id: str = None) -> Optional[str]:
    """
    Write workload data to a Google Sheet.

    Since no API credentials are required, this function provides
    instructions for manual import instead of automatic upload.

    Args:
        results: List of WorkloadResult objects
        year_data: YearData object for metadata
        spreadsheet_id: Optional existing spreadsheet ID (ignored in manual mode)

    Returns:
        Spreadsheet URL on success, None if user cancels
    """
    # Generate data
    headers, rows = generate_google_sheets_data(results)
    all_rows = [headers] + rows

    print("\n" + "="*60)
    print("Google Sheets Import Instructions")
    print("="*60)

    print("""
Since no API setup is required, here are two easy options:

OPTION 1: Manual CSV Import (RECOMMENDED - No API needed)
---------------------------------------------------------
1. The CSV file has already been generated: Staff workload model.csv
2. Go to https://sheets.google.com
3. Click your template sheet OR create a new one
4. In the menu: File > Import > Upload...
5. Select "Staff workload model.csv" from this folder
6. Choose "Replace data" or "Insert rows"
7. Done! The data will appear in your spreadsheet

OPTION 2: Direct Google Sheets API (Advanced)
----------------------------------------------
If you want automatic updates, you need to set up Google Cloud:
1. Go to https://console.cloud.google.com/
2. Create a project (free - no billing required for low usage)
3. Enable "Google Sheets API"
4. Create OAuth client ID for Desktop app
5. Download JSON and save as 'client_secret.json'

For University of York users:
- Contact IT about using the university's Google Cloud project
- They may have pre-configured credentials available

To try automatic upload anyway, run:
  python main.py --google-sheets --with-credentials

""")

    # Ask if user wants to continue with manual import (skip in non-interactive mode)
    import sys
    import webbrowser

    print("""
To manually import into Google Sheets:
1. Go to https://sheets.google.com
2. Create new or open existing spreadsheet
3. File > Import > Upload > Select "Staff workload model.csv"
4. Choose "Replace data" or "Insert rows"

Or use your University of York Google Workspace account:
- If your institution has pre-configured access, run with:
  python main.py --google-sheets
""")
    print("\nOpening template spreadsheet in browser...")
    try:
        webbrowser.open(f"https://docs.google.com/spreadsheets/d/{TEMPLATE_SPREADSHEET_ID}/copy")
    except Exception as e:
        print(f"Could not open browser: {e}")

    return None


def format_spreadsheet(spreadsheet_id: str, gc: gspread.Client = None) -> dict:
    """
    Format a Google Sheet (requires API credentials).

    Args:
        spreadsheet_id: The ID of the target spreadsheet
        gc: gspread Client

    Returns:
        Success status
    """
    print("\nFormatting requires API credentials.")
    print("Use manual import instead - see write_workload_to_google_sheets() for instructions.")
    return {"success": False}
