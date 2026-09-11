#!/usr/bin/env python3
"""
Entry point for the Google Sheets sync-check.

Usage: python sync_sheets.py

Fetches every source in data/google_sheets_sources.json, compares each
against its local data/ file, and asks before writing any change. Never run
automatically by main.py - this is a separate, on-demand step. See
docs/superpowers/specs/2026-09-11-google-sheets-sync-design.md for the
design.
"""

from sheet_sync import main

if __name__ == "__main__":
    main()
