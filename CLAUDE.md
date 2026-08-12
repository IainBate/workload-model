# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Map: Where Things Live and Where Calculations Happen

### Core Principle: Command-Query Separation
```
data_loader.py    →   workload_calculator.py   →   output_generator.py
(extract)         →   (transform; business logic) →  (render; formatting only)
```

**The golden rule:** `workload_calculator.py` is the **ONLY** place where business/rate logic should run. Its output (`WorkloadResult`, including breakdown fields) is the single source of truth for every number shown anywhere downstream.

Output files must be pure rendering — they format already-computed numbers, never recompute or re-derive them. If a number isn't available on `WorkloadResult` or its breakdown dicts, add a field to `workload_calculator.py` and populate it there — **never compute it in an output/report file**, and **never parse it back out of a display string**.

### File Roles

| File | Purpose |
|------|---------|
| `data_loader.py` | CSV ingestion, staff name normalization, module mapping, data merging. Produces structured dataclasses (`YearData`, `ModuleData`, `StaffData`, `WorkloadResult`). |
| `workload_calculator.py` | **Business logic only** — applies multipliers from config to calculate workload hours. Returns `WorkloadResult` with pre-computed breakdowns. |
| `output_generator.py` | Pure rendering — formats pre-computed numbers into CSV, Excel, PNG charts, HTML reports (per-staff and department). No calculation. |

### Known Violations to Fix

**The following contain regex/string parsing that should be removed once Phase 3 is complete:**

- **output_generator.py**: Lines ~1084, ~1102, ~1205, ~1210, ~1314, ~1354, ~1359 — regex-parses free-text detail strings and re-reads config constants for display labels

**Phase 2 (completed):** `role_based_reports.py` has been removed. Its functionality (`generate_individual_reports`, `generate_department_summary`) was consolidated into `output_generator.py` (`generate_per_staff_reports`, and department summary via `generate_html_report`). The baseline outputs were updated to reflect this consolidation.

### Key Data Structures

#### WorkloadResult
The immutable DTO passed from calculator to output. Contains all pre-computed numbers:

| Field | Type | Purpose |
|-------|------|---------|
| `name`, `fte` | str, float | Staff identity and contract type |
| `total_hours`, `teaching_hours`, `research_hours`, `admin_hours` | float | Category totals |
| `category` | str | Contract category (e.g., "T and S", "ART") for normative comparison |
| `assumptions`, `missing_data` | tuple[str] | Tracking metadata |
| `nominal_hours` | float | FTE-adjusted nominal hours reference |
| **teaching_breakdown** | Dict[str, float] | Aggregated teaching components (delivery, practicals, marking, etc.) |
| **teaching_module_breakdowns** | Dict[str, Dict[str, float]] | Per-module teaching breakdowns |
| **research_breakdown** | Dict[str, float] | Research components (baseline, grants, PhD supervision) |
| **admin_breakdown** | Dict[str, float] | Admin components (departmental roles) |
| `teaching_detail`, `research_detail`, `admin_detail` | str | Human-readable strings for display only |

**Note:** The breakdown dicts (`teaching_breakdown`, `research_breakdown`, `admin_breakdown`) contain structured numeric data. **Read directly from these, never parse numbers out of the detail strings.**

### Authoritative Calculation Map

| Concept | Authoritative Function/File | Field on WorkloadResult |
|---------|----------------------------|------------------------|
| Contact hours with multiplier | `_calculate_teaching_workload()` in `workload_calculator.py` | `teaching_breakdown['delivery']`, `teaching_module_breakdowns[module]['delivery']` |
| Practical first-session rate | `_calculate_teaching_workload()` — reads `config.TEACHING_PROBLEM_CLASS` | See Phase 3 for structured field |
| Practical repeat sessions hours | `_calculate_teaching_workload()` — calculates with `config.REPETITION_MULTIPLIER` | See Phase 3 for structured field |
| Assessment setting hours | `_calculate_teaching_workload()` — reads from `ASSESSMENT_*` constants | `teaching_breakdown['assessment_setting']`, `teaching_module_breakdowns[module]['assessment_setting']` |
| Marking hours per script | `_calculate_teaching_workload()` — reads `MARKING_*` constants | `teaching_breakdown['marking']`, `teaching_module_breakdowns[module]['marking']` |
| Pastoral supervision hours | `_calculate_teaching_workload()` — `SUPERVISION_PASTORAL * student_count` | `teaching_breakdown['pastoral_supervision']`, `supervision_details` tuple |
| Project supervision hours | `_calculate_teaching_workload()` — UG/MSc rates × project count | `teaching_breakdown['project_supervision']` |
| Protected research baseline | `calculate_workload()` — 10% of nominal hours | `research_breakdown['protected_research_baseline']` |
| Research grant allocation | `_calculate_research_grants()` in `workload_calculator.py` | `research_breakdown['grant_X']` per grant |
| PhD supervision (primary) | `_calculate_research_workload()` — 80h/FTE | `research_breakdown['primary_supervisor']` |
| Admin role percentage | `_calculate_admin_workload()` in `workload_calculator.py` | `admin_breakdown[role_name]` |

**Consumer rule:** If you need a number for display that isn't already on `WorkloadResult` or its breakdown dicts, add a field to the breakdown in `workload_calculator.py` and populate it there — never compute it in an output/report file, and never parse it back out of a display string.

### Dead Code Removed in Phase 2

| Function | Location | Status |
|----------|----------|--------|
| `generate_hybrid_dashboard()` | `role_based_reports.py` line ~1518 | **Removed** (Phase 2) |
| `_generate_finance_report()` | `role_based_reports.py` line ~1892 | **Removed** (Phase 2) |

**Note:** `role_based_reports.py` was removed in Phase 2. Its functionality has been rationalized into `output_generator.py`.

### Function Size Hotspots (Refactor Targets)

| Function | Approximate Lines | Refactor Phase |
|----------|-------------------|----------------|
| `_calculate_teaching_workload()` | ~880 lines | Phase 5 |
| `generate_per_staff_reports()` / `format_teaching_section()` | ~574 lines | Phase 5 (output_generator.py) |
| `load_all_data()` | ~350 lines | Not in scope |

**Do not add more logic to these functions.** They are refactor targets for Phase 5.

## Project Overview
This project provides an automated system for calculating academic staff workloads based on a specified model. It processes module data from CSV files and applies a set of predefined multipliers to determine "calculation points" (workload units) that are shared among the teaching team for each module.

## Core Logic & Rules
- **Workload Calculation:** The engine calculates work as: `Base + Teaching + Assessment + Supervision + Online Extras`.
- **New Lecturer Rule:** If a lecturer is identified as "new" (not present in the previous year's dataset), they are assigned higher multipliers to account for initial content development.
- **Assessment Assumptions:** Currently assumes automated marking unless specified otherwise.
- **Supervision Defaults:** Based on current project parameters, each teacher accounts for 20 pastoral and 10 project students (scaled by the multiplier).

## Architecture & Data Flow

### Source of truth
- **`workload_parameters.yaml`** — Extracted from `Work Allocation Model.docx`. Human-readable reference spec.
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
- **Deterministic ordering**: When converting sets/lists to tuples for storage (e.g., saint_modules), use `tuple(sorted(set(...)))` instead of just `set()` or unsorted `list()`. This ensures hash-stable outputs that pass baseline comparison.

## Public API

### Programmatic Usage

```python
from data_loader import load_all_data
from workload_calculator import calculate_workload
from output_generator import generate_all_outputs

# Load data for a specific year
year_data = load_all_data(data_dir="data")

# Calculate workload
results = calculate_workload(year_data, validate_input=True)

# Generate all outputs to a directory
generate_all_outputs(results, year_data, output_dir="output")
```

### Key Data Classes

| Class | Purpose |
|-------|---------|
| `YearData` | Container for all data for an academic year (modules, staff, known lecturers) |
| `ModuleData` | Module information (teachers, credits, contact hours, assessments, teaching format, additional activities) |
| `StaffData` | Staff member details (FTE, roles, supervision loads, research projects) |
| `WorkloadResult` | Calculated workload for a single staff member |

### ModuleData Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Module name |
| `codes` | Tuple[str, ...] | Module codes (e.g., COM00015C) |
| `stage` | int | Stage code (1-3 UG, 4+ MSc, 7 PGR) |
| `semester` | int | Semester (1 or 2) |
| `credits` | int | Credit points (e.g., 20) |
| `cohort` | str | Student cohort name |
| `lead_name` | str | Module leader/lead lecturer |
| `teachers` | Tuple[str, ...] | List of teaching staff names |
| `practicals` | int | Number of practical sessions per week |
| `contact_hours` | float | Estimated contact hours from credits |
| `student_count` | int | Number of students (from CS Module Numbers) |
| `assessment_count` | int | Number of assessments |
| `marking_type` | str | "automated" or "manual" marking type |
| `new_content` | bool | True if this is new content for the teacher |
| `hw_lab_hours` | float | Additional HW/lab work hours (beyond contact) |
| `drop_in_sessions` | int | Number of drop-in support sessions |
| `teaching_format` | str | "standard", "video", or other format indicator |

### Teaching Multipliers

The calculator applies different multipliers based on teaching format and content status:

| Format | Standard | New Lecturer | New Content + New Lecturer | Video |
|--------|----------|--------------|---------------------------|-------|
| Multiplier | 2.5x | 5x | 7.5x | 10x |

**Additional Teaching Activities:**
- **Practical sessions**: Repetition multiplier of 1.5x for additional sessions
- **HW Lab hours**: Additional work beyond contact hours (configurable)
- **Drop-in sessions**: 1.5h per session for support
- **Online content development**: 800h/module (new lecturer + new content), 100h/module (refreshing)

### Workload Report Display Format

**The HTML report must clearly show how hours are calculated. The following display conventions apply:**

#### Lecture/Delivery Section

For lectures, show:
1. **Main line**: Total hours with lecturer type
2. **Calculation breakdown**: Show standard equivalent at 2.5x plus content development

**Format**:
```
Total = standard_equivalent + content_dev
Where: standard_equivalent = total / lecturer_multiplier × 2.5
       content_dev = total - standard_equivalent

Example for new lecturer (5x): "17.6h @ 2.5x + 26.4h content dev = 44.0h"
Example for standard lecturer: "37.5h @ 2.5x"
```

#### Practical Sessions Section

Practical sessions use two rates:
- **First session rate**: Standard problem class rate (TEACHING_PROBLEM_CLASS = 2.5)
- **Repeat session rate**: REPETITION_MULTIPLIER (1.5) applied to the first-session rate

**Display format**:

```
Practical Sessions: XX.Xh total

First time delivery:
  "{sessions_per_week} sessions/week @ {contact_hrs:.1f}h each = {weekly_contact:.1f}h/week × {weeks} weeks"
  Rate applied: {first_session_rate}x (standard rate for first session)

Repeated sessions:
  "{repeat_count} repeat(s) @ {repetition_rate}x = {total_repeat_hrs:.1f}h"
```

**Calculation example** for practicals=2, contact_hrs=2.0, weeks=11:

```
First session total: 2 × 2.0 × 2.5 × 11 = 110.0h
Repeat session (1 repeat): 1 × 2.0 × 2.5 × 1.5 × 11 = 82.5h
Total practical hours: 192.5h

Display as:
  2 sessions/week @ 2.0h each = 4.0h/week × 11 weeks
  Rate applied: 2.5x first session (standard), 1.5x repeats
```

**Important clarifications**:
- `contact_hrs` comes from module data (`practical_contact_hours` or default TEACHING_PROBLEM_CLASS)
- First session rate is always TEACHING_PROBLEM_CLASS (2.5 for problem classes)
- Repeat sessions get REPETITION_MULTIPLIER (1.5) applied to the standard rate
- Total per teacher = first_session_total + repeat_session_total, divided by number of teachers

#### Assessment Setting and Marking

**Setting**: Hours based on marking type (automated/manual) and whether it's a new assessment
**Marking**: Hours per script × number of students, split between initial and resit

Display shows total hours with calculation breakdown showing main + resit.

### Workload Calculation Formula

```
Total = Teaching + Research (Protected + Additional) + Admin
```

Where:
- **Teaching**: Contact hours × multipliers + assessment setting/marking + supervision + additional activities
- **Research**: Protected baseline (10% of nominal hours) + grants + PhD supervision
- **Admin**: Departmental roles as % of nominal hours

## Known Limitations
- H/M variant student numbers are combined; teaching/marking allocations from 2025-6 are not mapped to merged H/M modules.
- SAINTS modules (AI, LES, Safe AI 1/2) are excluded from teaching calculations but noted for staff who teach them.
- Cross-department roles (online team) are excluded from workload.
- The "Projects" module in 2026-7 has no teachers listed in the WTW file.
- Some WAW roles have no percentage specified in the .docx (shown as 0% in output).
