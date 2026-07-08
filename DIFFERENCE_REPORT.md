# Three-Way Difference Report

**Comparing:** Input Data → Calculation Logic → Output Results

---

## SECTION 1: INPUT DATA

### 1.1 WTW Data (Module Assignments)
- **WTW 2026-7.csv**: 55 modules with teacher assignments
- **WTW 2025-6.csv**: Used for new lecturer detection

### 1.2 Student Counts
- Student counts per module from `CS Module Numbers.csv`
- Sample: 75 modules in the file

### 1.3 Assessment Data
- Assessment counts from `CS Module Assessment Numbers.csv`
- Columns: Module Acronym, Module Code, Number of Assessments, Number of Practicals, Total Duration, Number of Practical Groups, Notes on practicals

### 1.4 Staff FTE & Category Data
- FTE multipliers from `Part time.csv`: 4 entries (part-time staff)
- Staff categories from `project_load.csv`

### 1.5 Supervision Data
- PhD supervision from `PhD Supervision Data.csv`
- Pastoral supervision from `pastoral_load.csv`

### 1.6 Administrative Roles (WAW.csv)
- WAW roles: 85 entries
- Role percentages defined in `params/workload_parameters.yaml`

---

## SECTION 2: CALCULATIONS PERFORMED

### 2.1 Teaching Hours Calculation

For each module assigned to a staff member:
- Contact hours × teaching multiplier (2.5x standard, 5x new lecturer)
- Practical sessions: first delivery x 2.5x, repeats x 1.5x
- Assessment setting: based on marking type and novelty
  - Automated marking: 25h/standard paper, 35h/new setter same format, 60h/new assessment
  - Manual marking: 15h/standard paper, 22.5h/new setter same format, 37.5h/new assessment
- Script marking: MSc=0.5h/script (manual), UG=0.33h/script (manual)
- Pastoral care: 6h/student
- Project supervision: 22h/UG student, 40h/MSc student

### 2.2 Research Hours Calculation

Components:
- Primary research allowance (ART): 328.4 hours/year
- PhD supervision: 80h primary supervisor, 48h co-supervisor, 8h assessor
- Research grants: Percentage of nominal hours (1642) per grant

### 2.3 Administrative Hours Calculation

From WAW.csv roles:
| Role | Percentage | Hours |
|------|------------|-------|
| Head of Department | 100% | 1642h |
| Deputy Head (Research) | 40% | 657h |
| Deputy Head (Teaching) | 50% | 821h |
| CBoE (on-campus) | 30% | 493h |
| Programme Leads | 5-10% | 82-164h |

### 2.4 New Lecturer Detection

Staff not in WTW 2025-6.csv get new lecturer multiplier (5x instead of 2.5x)

---

## SECTION 3: OUTPUT RESULTS

### 3.1 Total Hours Summary

| System | Staff Count | Data Type |
|--------|-------------|-----------|
| Old Excel (WAW-based) | 66 staff | Admin totals only from WAW roles |
| New system | 55 staff | Full breakdown with teaching, research, admin |

### 3.2 Sample Comparison (Top 5 by Total Hours)

| Name | Teaching | Research | Admin | Total | Old Excel (WAW only) |
|------|----------|----------|-------|-------|---------------------|
| Frank Soboczenski | 569.0h | 1958.6h | 257.1h | 2859.7h | 175.0h |
| Iain Bate | 30.0h | 752.8h | 1817.0h | 2674.8h | 175.0h |
| Poonam Yadav | 442.6h | 1277.0h | 339.2h | 2133.8h | 175.0h |
| Ian Gray | 541.5h | 512.4h | 996.0h | 2124.9h | 175.0h |
| Jo Iacovides | 1092.5h | 512.4h | 339.2h | 2019.1h | 175.0h |

### 3.3 Component Breakdown Example: Iain Bate (Head of Department)

```
Teaching:    30.0h (Minimum administrative teaching load: 30h)
Research:    752.8h 
             - Primary research allowance: 328.4h
             - PhD supervision: 1x primary supervisor (80h each); 2x assessor (8h each) = 96.0h
             - Grant SCHEME: 20% of 1642h = 328.4h (SCHEME)
Admin:       1817.0h 
             - Head of Department: 100% of 1642h = 1642.0h
             - Service points (committee work): 175h
```

---

## SUMMARY OF DIFFERENCES

### Key Differences Between Old Excel and New System:

1. **DATA INPUT**
   - Old: Manual entry in Excel with WAW role percentages
   - New: CSV files (WTW, CS Module Numbers, Assessment Numbers, etc.)

2. **CALCULATION APPROACH**
   - Old: Pre-calculated totals per staff member in Admin sheet; Research calculated separately
   - New: Automated calculation from first principles:
     - Teaching hours from module assignments with detailed breakdowns
     - Research hours from grants and supervision
     - Admin hours from WAW role percentages

3. **OUTPUT FORMAT**
   - Old: Single Excel workbook with multiple sheets (Staff, T and S, Admin, Research, etc.)
   - New: Multiple output formats:
     - CSV file (`Staff workload model.csv`)
     - Excel file with charts (`Staff workload model.xlsx`)
     - PNG charts (`workload_summary_boxplot.png`, `workload_detailed_boxplot.png`)
     - HTML report with embedded charts and tables

4. **NEW FEATURES IN RECALCULATION**
   - Explicit teaching detail showing per-module calculations
   - Research detail showing grant-specific hours
   - Admin detail showing role-specific hours
   - Missing data and assumptions flags for transparency

5. **TOTAL HOURS DIFFERENCES**

The fundamental difference is that the old Excel file only showed the **admin component** from WAW roles, while the new system calculates the **full workload** including teaching, research, and admin components.

**Example: Iain Bate (Head of Department)**
- Old Excel: 175h (admin component only from WAW roles)
- New System: 2674.8h total = 30h teaching + 752.8h research + 1817h admin

---

*Report generated on 2026-07-08*
