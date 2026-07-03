# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
This project provides an automated system for calculating academic staff workloads based on a specified model. It processes module data from CSV files and applies a set of predefined multipliers to determine "calculation points" (workload units) that are shared among the teaching team for each module.

## Core Logic & Rules
- **Workload Calculation:** The engine calculates work as: `Base + Teaching + Assessment + Supervision + Online Extras`.
- **New Lecturer Rule:** If a lecturer is identified as "new" (not present in the previous year's dataset), they are assigned higher multipliers to account for initial content development.
- **Assessment Assumptions:** Currently assumes automated marking unless specified otherwise.
- **Supervision Defaults:** Based on current project parameters, each teacher accounts for 20 pastoral and 10 project students (scaled by the multiplier).

## Architecture & Data Flow

### Source of truth
- **`workload_parameters.yaml`** — Extracted from `Workload ModelFull Description.docx`. Human-readable reference spec.
- **`config.py`** — Runtime source of truth. Flat Python constants loaded from YAML. Imported by `calculator.py`.
- **`workload_model_parameters.py`** — Legacy intermediate Python dict (superseded by YAML).

### Data pipeline
```
WTW 2026-7.csv + WTW 2025-6.csv  →  Module data + known lecturers
CS Module Numbers.csv              →  Student counts per module
CS Module Assessment Numbers.csv   →  Assessment counts
pastoral_load.csv                  →  Pastoral supervision defaults
project_load.csv                   →  FTE, project loads, citizenship levels
PhD Supervision Data.csv           →  PhD supervisor/co-supervisor counts
% FTE for CS.csv                   →  Research grant FTE allocation
WAW.csv                            →  Departmental roles (on-campus only)
Part time.csv                      →  FTE multiplier per staff
```

### Key Modules
- `data_loader.py` — CSV ingestion, staff name normalization, module mapping, data merging, `YearData`/`ModuleData`/`StaffData` dataclasses.
- `config.py` — Flat constants loaded from `workload_parameters.yaml`.
- `workload_calculator.py` — Core logic: teaching, research, and admin calculations.
- `output_generator.py` — CSV output, PNG boxplots (summary + detailed), HTML report.
- `main.py` — Entry point. Orchestrates loading → calculation → output.

### Data files
- **WTW CSVs** (`WTW 2026-7.csv`, `WTW 2025-6.csv`): Module list, teachers, checkers. 2025-6 used for new lecturer detection.
- **`staff_name_lookup.json`**: Canonical name → aliases mapping for staff name normalization.
- **`module_mapping.json`**: Module H/M merges, unified project modules, dropped/new modules between years.
- **`workload_parameters.yaml`**: All workload parameters extracted from the .docx.

## Development & Execution
### Running the Calculator
```
python main.py                    # Full run: load → calculate → generate outputs
python main.py --dry-run          # Data summary only, no calculation
python main.py --interactive      # Prompt for unknown staff names
```

### Dependencies
```
pip install -r requirements.txt  # python-docx, matplotlib, pandas, pyyaml
```

### Output files
- `Staff workload model.csv` — Per-staff workload (Name, FTE, Total, Teaching, Research, Admin, detail columns)
- `workload_summary_boxplot.png` — Stacked bar chart: Teaching / Research / Admin
- `workload_detailed_boxplot.png` — Detailed component breakdown
- `workload_report.html` — HTML report with embedded charts and table

## Guidelines for Development
- **Type Hinting:** Maintain type hints in all function signatures (e.g., `List[ModuleData]`).
- **Configuration over Hardcoding:** New multipliers or constants should be added to `workload_parameters.yaml` and reflected in `config.py`.
- **Modularity:** Keep data parsing logic in `data_loader.py` and calculation logic in `workload_calculator.py`.
- **Staff name updates:** Add new name variants to `staff_name_lookup.json` when staff change.
- **Module mapping updates:** Update `module_mapping.json` when modules are renamed, dropped, or merged between academic years.
- **Role name normalization:** Add WAW→YAML role name mappings in `_WAW_ROLE_MAPPING` in `data_loader.py` when new roles appear.
- **No guessed data:** When data is genuinely missing, flag it in the output's "Missing Data" or "Assumptions" columns rather than silently defaulting.

## Known Limitations
- H/M variant student numbers are combined; teaching/marking allocations from 2025-6 are not mapped to merged H/M modules.
- SAINTS modules (AI, LES, Safe AI 1/2) are excluded from teaching calculations but noted for staff who teach them.
- Cross-department roles (online team) are excluded from workload.
- The "Projects" module in 2026-7 has no teachers listed in the WTW file.
- Some WAW roles have no percentage specified in the .docx (shown as 0% in output).
