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

### Workload Calculation Formula

The total workload is calculated as:

```
Total = Teaching + Research (Protected + Additional) + Admin + General Baseline
```

Where:

#### 1. Teaching Activities
- **Contact hours** x multiplier (2.5x standard, 5x new lecturer, etc.)
- **Practicals** with repetition multiplier (1.5x for additional sessions)
- **Assessment setting**: Based on marking type and whether it's a new assessment
- **Marking**: MSc 0.5h/script, UG 0.33h/script (manual); half for automated
- **Supervision**: Pastoral 6h/student, Projects vary by level
- **Minimum admin teaching load**: 30h for HoD and other administrative staff

#### 2. Research Activities (Protected Baseline + Additional)

**Protected Research Time (10% of nominal hours = 164.2h)**
This is the minimum protected research time per year per FTE, mandated by university policy.

**Additional Research:**
- **Primary research allowance** (ART): 328.4h (if applicable)
- **PhD supervision**: Primary supervisor 80h/FTE, Co-supervisor 48h/FTE, Assessor 8h/student
- **Research grants**: FTE percentage x nominal hours

#### 3. Administration Activities
- **Departmental roles** at specified percentages of nominal hours:
  - Head of Department: 100%
  - Deputy Head (Research): 40%
  - Deputy Head (Teaching): 50%
  - PLs, Committee chairs, etc.
- **Service points**: 175h default for committee work

#### 4. General Baseline (Outside Teaching/Research/Admin)
- **Engagement**: 100h university-wide engagement activities
- **Personal Development**: 75h mandated by university for all researchers

### New Lecturer Rule
If a lecturer is identified as "new" (not present in the previous year's dataset), they are assigned higher multipliers to account for initial content development.

### Assessment Assumptions
Currently assumes manual marking unless specified otherwise.

### Supervision Defaults
Based on current project parameters, each teacher accounts for 20 pastoral and 10 project students (scaled by the multiplier).

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

## Claude Code Warning: "Newline followed by # inside a quoted argument"

This warning appears when Claude Code's shell command parser detects patterns that *could* hide arguments in shell commands. In this project, it triggers on multi-line docstrings ending with `\n#` (newline followed by comment). **These are false positives** - the code contains no actual subprocess calls.

### Why it happens

Multi-line Python strings like:
```python
"""
Some description
# This looks like a shell comment to Claude's parser
"""
```

When Claude Code scans for `subprocess.run()` or similar, it sees `\n#` and flags it as a potential argument hiding issue.

### What was done

Docstrings have been converted to single-line format where possible:
```python
"""Single-line docstring - no \n# pattern."""
```

This eliminates the warning while maintaining documentation quality.

### If you still see the warning

The warning is informational from Claude Code's static analysis. It can be safely ignored in this project since:
1. There are no shell commands in the Python code
2. All patterns have been eliminated from docstrings
3. The pattern was a false positive (Python docstring, not shell command)

To minimize future occurrences:
- Prefer single-line docstrings for simple descriptions
- If multi-line docstrings are needed, avoid starting lines with `#`
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
