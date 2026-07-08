# Workload Model Calculator

Automated system for calculating academic staff workloads based on the Workload Model specification (Iain Bate, June 2026).

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
└── docs/              # Documentation
```

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the calculator from scripts directory
cd scripts/
python main.py
```

## Setup

### macOS / Linux
```bash
pip install -r ../requirements.txt
cd scripts/
python main.py
```

### Windows
```cmd
pip install -r ..\requirements.txt
cd scripts\
python main.py
```

## Running

```bash
# Full run: load data → calculate → generate outputs
python main.py

# Data summary only (no calculation)
python main.py --dry-run

# Prompt for unknown staff names
python main.py --interactive

# Custom output directory
python main.py --output-dir ../results

# Custom data directory
python main.py --data-dir ../custom_data
```

## Outputs

Generated files are written to `../output/` (or the directory specified by `--output-dir`):

| File | Description |
|------|-------------|
| `Staff workload model.csv` | Per-staff workload with detail columns |
| `Staff workload model.xlsx` | Excel file with charts and formatting |
| `workload_summary_boxplot.png` | Stacked bar chart: Teaching / Research / Admin |
| `workload_detailed_boxplot.png` | Detailed component breakdown |
| `workload_report.html` | HTML report with embedded charts and table |

## Configuration

### Roles needing percentage assignment

Some roles in WAW.csv do not have a percentage defined in the Workload Model docx. These are listed in `params/roles_needing_percentages.yaml` with suggested values. **You must review and assign percentages** before the calculator will use them.

### Staff name lookup

Edit `data/staff_name_lookup.json` to add or update name variants for staff members.

### Module mapping

Edit `data/module_mapping.json` when modules are renamed, dropped, or merged between academic years.

### WAW role name mapping

Edit `_WAW_ROLE_MAPPING` in `scripts/data_loader.py` when new roles appear in WAW.csv that don't match YAML role names.

## Data Sources

| File | Purpose |
|------|---------|
| `data/WTW 2026-7.csv` | Current year modules, teachers, checkers |
| `data/WTW 2025-6.csv` | Previous year (new lecturer detection) |
| `data/CS Module Numbers.csv` | Student counts per module code |
| `data/CS Module Assessment Numbers.csv` | Assessment counts per module |
| `data/pastoral_load.csv` | Per-staff pastoral supervisee counts |
| `data/project_load.csv` | FTE, project loads, citizenship levels |
| `data/PhD Supervision Data.csv` | PhD supervisor/co-supervisor counts |
| `data/% FTE for CS.csv` | Research grant FTE allocation |
| `data/WAW.csv` | Departmental roles (on-campus only) |
| `data/Part time.csv` | FTE multiplier per staff member |
| `params/workload_parameters.yaml` | Workload model parameters (from docx) |

## Architecture

```
WTW CSVs + CS CSVs → data_loader.py → YearData
                                    → StaffData (per staff)
                                    → ModuleData (per module)
                                    ↓
                          workload_calculator.py
                          (teaching + research + admin)
                                    ↓
                          output_generator.py
                          (CSV + PNG + HTML)
```

### Key modules

- **`scripts/config.py`** — Runtime constants loaded from `params/workload_parameters.yaml`
- **`scripts/data_loader.py`** — CSV ingestion, name normalization, data merging
- **`scripts/workload_calculator.py`** — Core workload calculation engine
- **`scripts/output_generator.py`** — CSV, PNG boxplots, HTML report generation
- **`scripts/main.py`** — Entry point, orchestrates the pipeline

## Moving this project

This project is fully portable. To move it to another machine or location:

### What to copy (essential files)

Copy the entire folder **as-is**. Everything needed to run the project is committed here.

### What gets regenerated (do not copy)

These are machine-specific or data-specific and will be recreated automatically:

| Item | Why | How to recreate |
|------|-----|-----------------|
| `.venv/` | Python virtual environment (OS-specific binaries) | `pip install -r requirements.txt` |
| `__pycache__/` | Python bytecode cache | Auto-generated on first import |
| `output/*.csv`, `*.png`, `*.html` | Generated workload results | `cd scripts && python main.py` |

### Step-by-step

1. **Copy the entire folder** to the new location
2. **On the new machine**, open a terminal in the project root
3. **Install dependencies**: `pip install -r requirements.txt`
4. **Verify input data files are present** in `data/` folder
5. **Run**: `cd scripts && python main.py`

### Essential input data files

These CSV/JSON/YAML files are your project's data and must be present:

- `data/WTW 2026-7.csv` — Current year modules, teachers, checkers
- `data/WTW 2025-6.csv` — Previous year (new lecturer detection)
- `data/CS Module Numbers.csv` — Student counts per module
- `data/CS Module Assessment Numbers.csv` — Assessment counts
- `data/pastoral_load.csv` — Pastoral supervisee counts
- `data/project_load.csv` — FTE, project loads, citizenship levels
- `data/PhD Supervision Data.csv` — PhD supervisor/co-supervisor counts
- `data/% FTE for CS.csv` — Research grant FTE allocation
- `data/WAW.csv` — Departmental roles
- `data/Part time.csv` — FTE multiplier per staff
- `data/staff_name_lookup.json` — Staff name normalization
- `data/module_mapping.json` — Module H/M merges, dropped/new modules
- `params/workload_parameters.yaml` — Workload model parameters

### Dependencies

- Python 3.8+
- PyYAML, matplotlib (installed via pip)

## Google Sheets Integration

For automatic Google Sheets integration:

1. Install: `pip install gspread`
2. Create OAuth credentials at https://console.cloud.google.com/
3. Run: `python main.py --google-sheets`

For manual import (no API setup needed):
1. Run the calculator to generate CSV files
2. In Google Sheets: File > Import > Upload `Staff workload model.csv`

## Known Limitations

- H/M variant student numbers are combined; teaching/marking allocations from the previous year are not mapped to merged H/M modules.
- SAINTS modules (AI, LES, Safe AI 1/2) are excluded from teaching calculations but noted for staff who teach them.
- Cross-department roles (online team) are excluded from workload.
- The "Projects" module in 2026-7 has no teachers listed in the WTW file.
- Some WAW roles have no percentage specified in the Workload Model docx — see `params/roles_needing_percentages.yaml`.
