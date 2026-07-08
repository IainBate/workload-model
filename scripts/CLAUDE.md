# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
This project provides an automated system for calculating academic staff workloads based on a specified model. It processes module data from CSV files and applies a set of predefined multipliers to determine "calculation points" (workload units) that are shared among the teaching team for each module.

## Directory Structure

```
Workload Model/
├── scripts/           # Python source code
│   ├── main.py        # Entry point
│   ├── config.py      # Configuration constants
│   ├── data_loader.py # CSV ingestion and data processing
│   ├── workload_calculator.py # Core calculation logic
│   ├── output_generator.py    # Report generation (CSV, XLSX, PNG, HTML)
│   └── google_sheets.py       # Google Sheets integration (optional)
├── data/              # Input data files
│   ├── WTW 2026-7.csv    # Current year module data
│   ├── WTW 2025-6.csv    # Previous year module data
│   ├── CS Module Numbers.csv
│   ├── CS Module Assessment Numbers.csv
│   ├── pastoral_load.csv
│   ├── project_load.csv
│   ├── PhD Supervision Data.csv
│   ├── % FTE for CS.csv
│   ├── WAW.csv
│   ├── Part time.csv
│   ├── staff_name_lookup.json
│   └── module_mapping.json
├── params/            # Configuration parameters
│   └── workload_parameters.yaml
├── output/            # Generated outputs (auto-created)
│   ├── Staff workload model.csv
│   ├── Staff workload model.xlsx
│   ├── workload_summary_boxplot.png
│   ├── workload_detailed_boxplot.png
│   └── workload_report.html
└── docs/              # Documentation
```

## Core Logic & Rules
- **Workload Calculation:** The engine calculates work as: `Base + Teaching + Assessment + Supervision + Online Extras`.
- **New Lecturer Rule:** If a lecturer is identified as "new" (not present in the previous year's dataset), they are assigned higher multipliers to account for initial content development.
- **Assessment Assumptions:** Currently assumes automated marking unless specified otherwise.
- **Supervision Defaults:** Based on current project parameters, each teacher accounts for 20 pastoral and 10 project students (scaled by the multiplier).

## Development & Execution

### Running the Calculator
```bash
cd scripts/
python main.py                    # Full run: load → calculate → generate outputs
python main.py --data-dir ../custom_data    # Use custom data directory
python main.py --output-dir ../my_output    # Custom output directory
python main.py --dry-run          # Data summary only, no calculation
python main.py --interactive      # Prompt for unknown staff names
```

### Dependencies
```bash
pip install -r requirements.txt  # python-docx, matplotlib, pandas, pyyaml, gspread (optional)
```

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | Configuration constants loaded from YAML |
| `data_loader.py` | CSV ingestion, staff name normalization, module mapping |
| `workload_calculator.py` | Core workload calculation logic |
| `output_generator.py` | CSV/XLSX/HTML report and chart generation |
| `params/workload_parameters.yaml` | Human-readable workload parameters |

## Output Files

- **Staff workload model.csv** - Per-staff workload details
- **Staff workload model.xlsx** - Excel file with charts and formatting
- **workload_summary_boxplot.png** - Stacked bar chart summary
- **workload_detailed_boxplot.png** - Detailed component breakdown
- **workload_report.html** - HTML report with embedded charts

## Guidelines for Development

- **Type Hinting:** Maintain type hints in all function signatures (e.g., `List[ModuleData]`).
- **Configuration over Hardcoding:** New multipliers should be added to `params/workload_parameters.yaml`.
- **Modularity:** Keep data parsing in `data_loader.py`, calculations in `workload_calculator.py`.
- **Staff name updates:** Add new variants to `staff_name_lookup.json`.
- **Module mapping updates:** Update `module_mapping.json` when modules change.
- **No guessed data:** Flag genuinely missing data rather than silently defaulting.

## Google Sheets Integration

For automatic Google Sheets integration:
1. Install: `pip install gspread`
2. Create OAuth credentials at https://console.cloud.google.com/
3. Run: `python main.py --google-sheets`

For manual import (no API setup needed):
1. Run the calculator to generate CSV files
2. In Google Sheets: File > Import > Upload `Staff workload model.csv`
