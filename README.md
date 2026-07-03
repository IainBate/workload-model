# Workload Model Calculator

Automated system for calculating academic staff workloads based on the Workload Model specification (Iain Bate, June 2026).

## Quick Start

```bash
# 1. Install dependencies
./setup.sh        # macOS/Linux
# or
setup.bat         # Windows

# 2. Run the calculator
python main.py
```

## Setup

This project uses a Python virtual environment. To set it up on any machine:

### macOS / Linux
```bash
chmod +x setup.sh
./setup.sh
```

### Windows
```cmd
setup.bat
```

### Manual setup
```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# or
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
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
python main.py --output-dir results
```

## Outputs

Generated files are written to `output/` (or the directory specified by `--output-dir`):

| File | Description |
|------|-------------|
| `Staff workload model.csv` | Per-staff workload with detail columns |
| `workload_summary_boxplot.png` | Stacked bar chart: Teaching / Research / Admin |
| `workload_detailed_boxplot.png` | Detailed component breakdown |
| `workload_report.html` | HTML report with embedded charts and table |

## Configuration

### Roles needing percentage assignment

Some roles in WAW.csv do not have a percentage defined in the Workload Model docx. These are listed in `roles_needing_percentages.yaml` with suggested values. **You must review and assign percentages** before the calculator will use them.

### Staff name lookup

Edit `staff_name_lookup.json` to add or update name variants for staff members.

### Module mapping

Edit `module_mapping.json` when modules are renamed, dropped, or merged between academic years.

### WAW role name mapping

Edit `_WAW_ROLE_MAPPING` in `data_loader.py` when new roles appear in WAW.csv that don't match YAML role names.

## Data Sources

| File | Purpose |
|------|---------|
| `WTW 2026-7.csv` | Current year modules, teachers, checkers |
| `WTW 2025-6.csv` | Previous year (new lecturer detection) |
| `CS Module Numbers.csv` | Student counts per module code |
| `CS Module Assessment Numbers.csv` | Assessment counts per module |
| `pastoral_load.csv` | Per-staff pastoral supervisee counts |
| `project_load.csv` | FTE, project loads, citizenship levels |
| `PhD Supervision Data.csv` | PhD supervisor/co-supervisor counts |
| `% FTE for CS.csv` | Research grant FTE allocation |
| `WAW.csv` | Departmental roles (on-campus only) |
| `Part time.csv` | FTE multiplier per staff member |
| `workload_parameters.yaml` | Workload model parameters (from docx) |
| `roles_needing_percentages.yaml` | Roles missing percentages (review required) |

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

- **`config.py`** — Runtime constants loaded from `workload_parameters.yaml`
- **`data_loader.py`** — CSV ingestion, name normalization, data merging
- **`workload_calculator.py`** — Core workload calculation engine
- **`output_generator.py`** — CSV, PNG boxplots, HTML report generation
- **`main.py`** — Entry point, orchestrates the pipeline

## Moving this project

This project is fully portable. To move it to another machine or location:

### What to copy (essential files)

Copy the entire folder **as-is**. Everything needed to run the project is committed here.

### What gets regenerated (do not copy)

These are machine-specific or data-specific and will be recreated automatically:

| Item | Why | How to recreate |
|------|-----|-----------------|
| `.venv/` | Python virtual environment (OS-specific binaries) | `./setup.sh` or `setup.bat` |
| `__pycache__/` | Python bytecode cache | Auto-generated on first import |
| `output/*.csv`, `*.png`, `*.html` | Generated workload results | `python main.py` |
| `workload_report.html`, `workload_*_boxplot.png` | Generated reports (in root) | `python main.py` |
| `Staff workload model.csv` | Generated output | `python main.py` |

### Step-by-step

1. **Copy the entire folder** to the new location (e.g., drag the `Workload Model` folder)
2. **On the new machine**, open a terminal in the folder
3. **Install dependencies**: `./setup.sh` (macOS/Linux) or `setup.bat` (Windows)
4. **Verify input data files are present** (listed in the table below)
5. **Run**: `python main.py`

### Essential input data files

These CSV/JSON/YAML files are your project's data and must be present:

- `WTW 2026-7.csv` — Current year modules, teachers, checkers
- `WTW 2025-6.csv` — Previous year (new lecturer detection)
- `CS Module Numbers.csv` — Student counts per module
- `CS Module Assessment Numbers.csv` — Assessment counts
- `pastoral_load.csv` — Pastoral supervisee counts
- `project_load.csv` — FTE, project loads, citizenship levels
- `PhD Supervision Data.csv` — PhD supervisor/co-supervisor counts
- `% FTE for CS.csv` — Research grant FTE allocation
- `WAW.csv` — Departmental roles
- `Part time.csv` — FTE multiplier per staff
- `staff_name_lookup.json` — Staff name normalization
- `module_mapping.json` — Module H/M merges, dropped/new modules
- `workload_parameters.yaml` — Workload model parameters
- `roles_needing_percentages.yaml` — Roles missing percentages (review required)

### Dependencies

- Python 3.8+
- PyYAML, python-docx, matplotlib, pandas (installed via setup script)

## Known Limitations

- H/M variant student numbers are combined; teaching/marking allocations from the previous year are not mapped to merged H/M modules.
- SAINTS modules (AI, LES, Safe AI 1/2) are excluded from teaching calculations but noted for staff who teach them.
- Cross-department roles (online team) are excluded from workload.
- The "Projects" module in 2026-7 has no teachers listed in the WTW file.
- Some WAW roles have no percentage specified in the Workload Model docx — see `roles_needing_percentages.yaml`.
