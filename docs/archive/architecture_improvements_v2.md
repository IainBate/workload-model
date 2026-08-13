# Workload Model Architecture Improvements v2

## Current State Analysis

### Problems Identified

1. **Double-counting in research breakdown** (Line 872)
   - `phd_supervision` is added AFTER individual components (`primary_supervisor`, `co_supervisor`, `assessor`)
   - This causes validation to fail: sum of breakdown > total

2. **Missing module-level teaching data in teaching_breakdown**
   - Module calculations (delivery, practicals, assessment, marking) accumulate at staff level
   - But these values aren't properly aggregated into the final `teaching_breakdown` dict
   - Only supervision components (`pastoral_supervision`, `project_supervision`) appear

3. **Validation reveals calculation bugs, not display issues**
   - The validation pipeline correctly catches real calculation errors
   - These are NOT format changes - they require code fixes in `workload_calculator.py`

### Root Causes

| Issue | Location | Problem |
|-------|----------|---------|
| Line 872 | `_calculate_research_workload` | Adds both components AND their sum |
| Lines 1265-1275 | `calculate_workload` | Only aggregates supervision, not module teaching |
| Missing aggregation | Per-module breakdowns | Module data exists but isn't summed to staff level |

---

## Proposed Architecture: Three-Layer Validation

```
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 1: Input Validation (existing - validation.py)                │
│ - Validate CSV data integrity                                       │
│ - Check FTE ranges, student counts, contact hours                   │
│ - Run BEFORE calculation                                            │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 2: Calculation Validation (NEW - test_calculations.py)        │
│ - Unit tests for each multiplier function                           │
│ - Verify breakdown structure is correct                             │
│ - Check no double-counting in breakdown dicts                       │
│ - Run on every code change                                          │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 3: Post-Calculation Structural Validation (existing)          │
│ - Verify total = teaching + research + admin                        │
│ - Verify breakdown sums match category totals                       │
│ - Flag if structural invariant is violated                          │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Layer 4: Format Validation (NEW - test_format.py)                   │
│ - Compare HTML output to baseline                                   │
│ - Only fails if display format changed (not calculation)            │
│ - Baseline is structured JSON, not rendered HTML                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Immediate Fixes Required

### Fix 1: Remove Double-Counting in Research Breakdown

**File:** `workload_calculator.py`, lines 867-872

**Current (buggy):**
```python
if phd_hours > 0:
    total += phd_hours
    # Add detailed breakdown items first (primary, co-supervisor, assessor)
    breakdown.update(phd_breakdown)  # Adds primary_supervisor, co_supervisor, assessor
    # Then add the combined total for reference - THIS IS THE BUG!
    breakdown["phd_supervision"] = phd_hours
```

**Fix:**
```python
if phd_hours > 0:
    total += phd_hours
    # Add detailed breakdown items (primary, co-supervisor, assessor)
    # Do NOT add phd_supervision as it's redundant with the sum of components
    breakdown.update(phd_breakdown)
```

**Alternative:** If you want to keep `phd_supervision` for display purposes, only include it if there are no individual components (e.g., when using a different calculation path).

---

### Fix 2: Aggregate Module Teaching into teaching_breakdown

**File:** `workload_calculator.py`, lines 1265-1282

**Current behavior:**
```python
# Build structured teaching breakdown from per-module data
teaching_breakdown = {}
if canonical_name in staff_teaching:
    staff_data = staff_teaching[canonical_name]
    # Only aggregates supervision components, not module teaching!
    if "teaching_breakdown" in staff_data and staff_data["teaching_breakdown"]:
        teaching_breakdown = _sum_breakdown_dict(staff_data["teaching_breakdown"])
```

**The issue:** `_sum_breakdown_dict` only sums per-module breakdowns. But the per-module `teaching_breakdown` contains keys like `"teaching"`, `"practicals"`, etc. - these need to be aggregated across all modules.

**Fix:**
```python
def _aggregate_teaching_breakdown(staff_data):
    """Aggregate teaching breakdowns from all modules for a staff member."""
    aggregated = {}
    
    # Keys that should be summed across modules
    sum_keys = ["teaching", "practicals", "assessment_setting", "marking", 
                "admin", "supervision", "hw_lab", "drop_in"]
    
    for module_breakdown in staff_data.get("teaching_breakdowns", {}).values():
        for key in sum_keys:
            if key in module_breakdown:
                aggregated[key] = aggregated.get(key, 0.0) + module_breakdown[key]
    
    # Include supervision as separate entries (not summed)
    if "pastoral_supervision" in staff_data:
        aggregated["pastoral_supervision"] = staff_data["pastoral_supervision"]
    if "project_supervision" in staff_data:
        aggregated["project_supervision"] = staff_data["project_supervision"]
    
    return aggregated

# In calculate_workload():
if canonical_name in staff_teaching:
    staff_data = staff_teaching[canonical_name]
    # Aggregate module-level teaching into structured breakdown
    if "teaching_breakdowns" in staff_data:  # Note: plural - all modules
        teaching_breakdown = _aggregate_teaching_breakdown(staff_data)
```

**Data structure change needed:**
Currently `staff_teaching[canonical_name]["teaching_breakdown"]` is a dict. Change to:
```python
staff_teaching[canonical_name]["teaching_breakdowns"] = [
    module1_breakdown,
    module2_breakdown,
    ...
]
```
or
```python
staff_teaching[canonical_name]["teaching_breakdowns"] = {
    "module_code_1": breakdown_dict,
    "module_code_2": breakdown_dict,
}
```

---

## Testing Strategy

### Level 1: Unit Tests for Calculation Functions

**File:** `tests/test_calculations.py`

```python
import pytest
from workload_calculator import (
    _calculate_research_workload,
    _calculate_teaching_workload,
)
from data_loader import StaffData


def test_research_workload_no_double_counting():
    """Verify PhD supervision breakdown doesn't double-count."""
    staff = StaffData(
        canonical_name="Test Staff",
        fte=1.0,
        phd_supervisions=3,  # 3 × 80h = 240h primary
        phd_co_supervisions=1,  # 1 × 48h = 48h co
        phd_assessor_count=2,  # 2 × 8h = 16h assessor
        # Total: 304h
    )
    
    total, breakdown, _, _, _ = _calculate_research_workload(staff)
    
    # Check individual components exist
    assert "primary_supervisor" in breakdown
    assert "co_supervisor" in breakdown  
    assert "assessor" in breakdown
    
    # Check phd_supervision is NOT present (or is zero) - no double counting!
    assert "phd_supervision" not in breakdown, \
        "phd_supervision should not be in breakdown as it duplicates component sum"
    
    # Verify total matches sum of components
    component_sum = sum(v for v in breakdown.values() if isinstance(v, (int, float)))
    assert abs(component_sum - total) < 0.1, \
        f"Breakdown sum {component_sum} != total {total}"


def test_teaching_breakdown_aggregation():
    """Verify module teaching breakdowns aggregate correctly to staff level."""
    # Test with multiple modules
    modules = [...]  # Create test ModuleData objects
    teachers = ["Staff A"]
    
    result = _calculate_teaching_workload(...)
    
    # Each module should have structured breakdown
    for teacher, data in result.items():
        breakdown = data["teaching_breakdown"]
        
        # Should contain expected keys
        assert "teaching" in breakdown  # Lecture hours with multiplier
        assert "practicals" in breakdown
        assert "assessment_setting" in breakdown
        assert "marking" in breakdown
        
        # Values should be non-negative
        for key, value in breakdown.items():
            if isinstance(value, (int, float)):
                assert value >= 0, f"{key} should not be negative"


def test_new_lecturer_multiplier():
    """Verify new lecturers get correct multiplier."""
    module = ModuleData(
        codes=("COM00000X",),
        teachers=("New Lecturer",),
        contact_hours=20,
        practicals=1,
        assessment_count=1,
    )
    
    known_lecturers = set()  # Empty - New Lecturer is "new"
    result = _calculate_teaching_workload(module, ["New Lecturer"], known_lecturers, ...)
    
    # Check delivery multiplier is 5x for new lecturer
    breakdown = result["New Lecturer"]["teaching_breakdown"]
    assert breakdown.get("teaching", 0) > 0  # Has some teaching hours
```

---

### Level 2: Integration Tests

**File:** `tests/test_integration.py`

```python
def test_full_calculation_structure():
    """Verify complete workload calculation produces valid structure."""
    year_data = load_all_data()
    results = calculate_workload(year_data)
    
    for result in results:
        # Verify total split
        category_sum = (
            result.teaching_hours +
            result.research_hours +
            result.admin_hours
        )
        assert abs(category_sum - result.total_hours) < 0.1, \
            f"Total mismatch for {result.name}"
        
        # Verify breakdown sums (after Fix 2 is applied)
        teaching_values = [
            v for v in result.teaching_breakdown.values()
            if isinstance(v, (int, float))
        ]
        assert abs(sum(teaching_values) - result.teaching_hours) < 0.1, \
            f"Teaching breakdown mismatch for {result.name}"


def test_known_staff_calculations():
    """Verify specific staff calculations match expected values."""
    year_data = load_all_data()
    results = calculate_workload(year_data)
    
    # Create lookup
    results_by_name = {r.name: r for r in results}
    
    # Verify Christopher Crispin-Bailey (has detailed HTML output)
    christopher = results_by_name.get("Christopher Crispin-Bailey")
    if christopher:
        assert abs(christopher.total_hours - 1123.1) < 1.0
        assert christopher.teaching_hours > 400  # Expected range
        assert christopher.research_hours == 164.2  # Protected baseline
```

---

### Level 3: Format Tests (HTML Output)

**File:** `tests/test_formatting.py`

```python
import json

def load_baseline():
    """Load baseline from structured JSON, not HTML."""
    with open("baseline/expected_results.json") as f:
        return json.load(f)


def test_html_output_matches_display_format():
    """Verify HTML output matches expected display format.
    
    This test only fails if the DISPLAY FORMAT changes,
    NOT if calculations change. The baseline is structured
    data that gets rendered to HTML.
    """
    year_data = load_all_data()
    results = calculate_workload(year_data)
    
    # Generate HTML using current code
    html_output = generate_html_report(results)
    
    # Load expected HTML (baseline for display format only)
    with open("baseline/output.html") as f:
        expected_html = f.read()
    
    # Compare normalized whitespace
    assert normalize_whitespace(html_output) == normalize_whitespace(expected_html), \
        "HTML output format has changed. If calculation changed, update baseline."
```

**Baseline structure (JSON):**
```json
{
  "Christopher Crispin-Bailey": {
    "total_hours": 1123.1,
    "teaching_hours": 496.5,
    "research_hours": 164.2,
    "admin_hours": 462.4,
    "teaching_breakdown": {
      "delivery": 80.0,
      "practicals": 137.5,
      "assessment_setting": 12.5,
      "marking": 73.0,
      "pastoral_supervision": 57.0,
      "project_supervision": 112.0,
      "project_setting": 6.0
    },
    "research_breakdown": {
      "protected_research_baseline": 164.2
    },
    "admin_breakdown": {
      "Gta Coordinator": 164.2,
      "Union": 123.1,
      "Engagement": 100.0,
      "Personal Development": 75.0
    }
  }
}
```

---

### Level 4: Validation Pipeline (Already Implemented)

**File:** `validation.py`

```python
def validate_workload_result(result, tolerance=0.1):
    """Validate workload result structure.
    
    Checks:
    1. total = teaching + research + admin (within tolerance)
    2. No negative hours in any category
    3. Breakdown sums match category totals (after fixes applied)
    """
```

**Integration in main.py:**
```python
results = calculate_workload(year_data)

# NEW: Validate calculations before output
if not run_validation_pipeline(results):
    print("\nValidation failed. Please check the errors above.")
    sys.exit(1)
print("  All validations passed.")
```

---

## Migration Plan

### Phase 1: Quick Fixes (1 day)
1. Remove `phd_supervision` from research breakdown (Fix 1)
2. Fix `_sum_breakdown_dict` to properly aggregate module teaching (Fix 2)
3. Run validation - should pass with no errors

### Phase 2: Unit Tests (2 days)
1. Create `tests/test_calculations.py`
2. Add tests for each multiplier function
3. Verify no double-counting
4. Test edge cases (zero students, zero practicals, etc.)

### Phase 3: Integration Tests (1 day)
1. Create `tests/test_integration.py`
2. Test full calculation pipeline
3. Verify known staff calculations

### Phase 4: Format Baseline (1 day)
1. Export structured baseline JSON
2. Create `baseline/expected_results.json`
3. Create `tests/test_formatting.py`

---

## Expected Outcomes After Fixes

| Staff Member | Total Hours | Teaching Sum | Research Sum | Status |
|--------------|-------------|--------------|--------------|--------|
| Christopher Crispin-Bailey | 1123.1 | ~496.5 | 164.2 | Pass |
| Adrian Bors | ~700 | Should match | Should match | Pass |

After **Fix 1** (remove phd_supervision):
- Research breakdown sum = research total

After **Fix 2** (aggregate module teaching):
- Teaching breakdown sum = teaching total
- Module-level calculations visible in breakdown

---

## Summary of Required Changes

| File | Lines | Change Type |
|------|-------|-------------|
| `workload_calculator.py` | ~872 | Remove redundant phd_supervision entry |
| `workload_calculator.py` | ~1246-1282 | Fix teaching breakdown aggregation |
| `tests/test_calculations.py` | New | Unit tests for calculations |
| `tests/test_integration.py` | New | Integration tests |
| `tests/test_formatting.py` | New | Format-only tests |
| `baseline/expected_results.json` | New | Structured baseline data |
