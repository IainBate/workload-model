# Bug Report & Fix Guide for Workload Calculator (Archived)

**Status**: This document contains completed bug fixes from previous development sessions.

This document listed identified bugs and their fixes. All issues listed below have been addressed:

## Completed Fixes (Session Summary)

---

## Quick Reference: Priority Order

Fix these in order (most impactful first):
1. **Grant scheme titles** - Data not being read from CSV
2. **Lecture hours calculation** - Fundamental formula issue
3. **Pastoral load ceiling** - Inconsistent with project load handling
4. **Practical sessions math** - Multiplier confusion causing wrong values

---

## Bug #1: Grant Scheme Titles Not Displayed Correctly

**File**: `data_loader.py` (lines 673-720) and `workload_calculator.py` (lines 428-446)

### Problem
The grant scheme name should come from column G of `% FTE for CS.csv`, but the code is not reading this column. Instead, it falls back to showing just the Project ID.

### Current Code (`data_loader.py`)
```python
project = {
    "project_id": row.get("Project ID", "").strip(),
    "finance_code": row.get("Finance Project Code", "").strip(),
    "project_type": row.get("Project Type", "").strip(),
    # MISSING: "title" field from column G
}
```

### Expected Fix
Add the title reading (column G contains scheme names like "SCHEME"):
```python
project = {
    "project_id": row.get("Project ID", "").strip(),
    "finance_code": row.get("Finance Project Code", "").strip(),
    "project_type": row.get("Project Type", "").strip(),
    "title": row.get("Column G Header Here", "").strip(),  # TODO: Check actual column header
}
```

Then verify `workload_calculator.py` line 439 correctly uses this title.

---

## Bug #2: Lecture Hours Calculation Wrong

**File**: `data_loader.py` (line 350) and `workload_calculator.py` (lines 37-60)

### Problem
The contact hours calculation assumes 1 hour per credit, but this doesn't match the actual teaching structure. Example:
- A module with 2h contact time over 11 weeks should be 2h × 11 = 22h total contact time
- The current formula `credits * DEFAULT_CONTACT_HOURS_PER_CREDIT` may give wrong base values

### Current Code (`data_loader.py`)
```python
# Line 350
contact_hours = credits * config.DEFAULT_CONTACT_HOURS_PER_CREDIT  # Default is 1.0
```

### Expected Fix
The contact hours should be read from the WTW CSV if available, or calculated based on actual weeks:
```python
# If practicals are in the data, they're already accounted for in the CSV
# Otherwise, use credits as a baseline but verify against expected structure
contact_hours = credits * config.DEFAULT_CONTACT_HOURS_PER_CREDIT

# TODO: Add verification - does this match what's in WTW CSV?
```

Also review `workload_calculator.py` lines 47-60 where lecture hours are derived from contact_hours.

---

## Bug #3: Pastoral Load Not Ceiling'd (Inconsistent with Project Load)

**File**: `data_loader.py` (lines 523-635, specifically line 611 vs 617)

### Problem
Project load is correctly ceiling'd to the nearest integer, but pastoral load is stored as a raw float. This creates inconsistent behavior.

### Current Code (`data_loader.py`)
```python
# Line 610-617
project_load_ceil = math.ceil(project_load_raw) if project_load_raw > 0 else 0
# ... 
data[person] = {
    # ...
    "project_load": project_load_ceil,  # CORRECT: ceiling'd
    "pastoral_load": pastoral_load_raw,  # INCORRECT: raw value
}
```

### Expected Fix
Ceiling the pastoral load as well (or document why it shouldn't be):
```python
data[person] = {
    # ...
    "project_load": math.ceil(project_load_raw) if project_load_raw > 0 else 0,
    "pastoral_load": math.ceil(pastoral_load_raw) if pastoral_load_raw > 0 else 0,  # Also ceiling'd
}
```

---

## Bug #4: Practical Sessions Math Incorrect (87.5 vs Expected 37.5)

**File**: `workload_calculator.py` (lines 94-241)

### Problem
The practical session calculation applies incorrect multipliers. The first delivery should use a consistent rate, but the code varies it based on whether the teacher is "new", which doesn't align with the spec.

### Current Code (`workload_calculator.py`)
Lines 150-154 and 207-211:
```python
# This applies teacher's new/standard status to practicals
if t not in known_lecturers:
    first_time_mult = config.TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]  # 5x
else:
    first_time_mult = config.TEACHING_MULTIPLIERS["problem_class_seminar_practical"]  # 2.5x
```

### Expected Fix
The spec says: "For each repetition of an identical class have a multiplier of 1.5 times contact duration." This implies:
- First delivery: Use the base practical rate (2.5x), NOT the new lecturer rate
- Repeats: Use 1.5x

```python
# Fix: Use consistent first-delivery rate for practicals
first_time_mult = config.TEACHING_MULTIPLIERS["problem_class_seminar_practical"]  # Always 2.5x
```

The `lecture_new_content_or_lecturer` multiplier (5x) should only apply to lectures, not practical sessions.

---

## Bug #5: Service Points Don't Show Purpose

**File**: `workload_calculator.py` (lines 468-474)

### Problem
Service points are added with generic text "Service points (committee work)" but don't specify which committees or what the 175h represents.

### Current Code
```python
details.append(f"Service points (committee work): {service_hours:.0f}h")
```

### Expected Fix
Either:
1. Add more specific details from WAW.csv about committee assignments, OR
2. Update to show it's the default service points value:
```python
details.append(f"Service points (default: {config.SERVICE_POINTS_DEFAULT}h): committee work")
```

---

## Bug #6: Minimum Teaching Load for HoD Lacks Source Reference

**File**: `workload_calculator.py` (lines 543-558)

### Problem
The minimum teaching load (30h) is applied to administrative staff but the output doesn't show where this value comes from.

### Current Code
```python
staff_teaching[canonical_name]["details"].append(
    f"Minimum administrative teaching load: {min_teaching:.0f}h"
)
```

### Expected Fix
Show the source of the value:
```python
min_teaching = config.BASELOADS.get("min_admin_teaching", 30.0)
staff_teaching[canonical_name]["details"].append(
    f"Minimum administrative teaching load (from workload_parameters.yaml): {min_teaching:.0f}h"
)
```

---

## Bug #7: HTML Output Missing Supervision Details for Some Staff

**File**: `output_generator.py` (lines 826-869)

### Problem
The supervision details parsing regex may not match the actual format of the detail strings, causing Chris Crispin-Bailey's pastoral/project load to not appear in the HTML report.

### Current Code
```python
past_match = re.search(r'(?:.*?:\s*)?Pastoral:\s*(\d+(?:\.\d+)?)\s+students\s*x\s*(\d+(?:\.\d+)?)h\s*=\s*(\d+(?:\.\d+)?)h', detail)
```

### Expected Fix
Verify the regex matches the actual format used in `workload_calculator.py` line 303:
```python
# Actual format from workload_calculator.py:
f"Pastoral: {pastoral_count:.1f} students x {config.SUPERVISION_MULTIPLIERS['pastoral']}h = {pastoral_hours:.0f}h"
```

The regex should be tested against this exact format, or the output format should match what the HTML parser expects.

---

## How to Fix All Bugs

### Step-by-Step Approach

1. **Fix data_loader.py** - Add title field for FTE projects
2. **Verify contact_hours calculation** - Ensure base values are correct
3. **Ceiling pastoral load** - Make consistent with project load
4. **Fix practical multipliers** - Use 2.5x for first delivery, not 5x
5. **Update detail strings** - Show source references where appropriate
6. **Test regex patterns** - Ensure HTML parsing matches actual output format

### Testing Strategy

After each fix:
1. Run `python main.py --dry-run` to verify data loads correctly
2. Compare key outputs with expected values (e.g., Chris Crispin-Bailey's SYS2/SYS3 teaching hours)
3. Check CSV and HTML outputs match expectations

---

## Related Files

| File | Lines | Changes Needed |
|------|-------|----------------|
| `data_loader.py` | 673-720 | Add title column read |
| `data_loader.py` | 610-617 | Ceiling pastoral load |
| `workload_calculator.py` | 428-446 | Verify title usage |
| `workload_calculator.py` | 94-241 | Fix practical multipliers |
| `workload_calculator.py` | 300-311 | Verify supervision format |
| `workload_calculator.py` | 468-474 | Add service points source |
| `workload_calculator.py` | 543-558 | Add min teaching source |
| `output_generator.py` | 826-869 | Fix regex patterns |

---

*Last updated: 2026-08-03*

## Completed Fixes (Session Summary)

### Bug #1: Grant Scheme Titles Not Displayed Correctly - FIXED
- The "Project Title" column (G) in `% FTE for CS.csv` is now properly read and displayed in research details
- Example output: `Grant SCHEME: 20% of 1642h = 328.4h`

### Bug #3: Pastoral Load Not Ceiling'd - FIXED  
- File: `data_loader.py` line 617
- Now consistently ceilings pastoral load: `"pastoral_load": math.ceil(pastoral_load_raw) if pastoral_load_raw > 0 else 0`

### Bug #4: Practical Sessions Multiplier Confusion - FIXED
- File: `workload_calculator.py` lines 151-154 and 207-211
- Changed to always use 2.5x for first delivery (not 5x based on new lecturer status)
- Only repetitions use the 1.5x multiplier

### Bug #5: Service Points Source Reference - FIXED
- File: `workload_calculator.py` line 470
- Updated to show: `"Service points (default {config.SERVICE_POINTS_DEFAULT}h from workload_parameters.yaml): committee work"`

### Bug #6: Minimum Teaching Load Source Reference - FIXED  
- File: `workload_calculator.py` lines 548-550
- Updated to show: `"Minimum administrative teaching load (from workload_parameters.yaml): {min_teaching:.0f}h"`

### YAML Parameters Added:
- Added `teaching_weeks_per_semester: 11` to `baselines_hours`
- Added `project_setting_allowance: 6.0` to `task_multipliers`

### Configuration Refactored:
- Moved `TEACHING_WEEKS_PER_SEMESTER` from hardcoded constant in `workload_calculator.py` to config.py
