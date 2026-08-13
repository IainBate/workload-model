# Workload Model Architecture Improvements

## Current State

```
data_loader.py → workload_calculator.py → output_generator.py
                    ↓
              WorkloadResult (DTO)
                    ↓
              HTML/CSV/PNG Output
                    ↓
              baseline/ files (for comparison)
```

**Problems:**
1. Baseline comparison catches calculation bugs as "format changes"
2. No separation between "calculation is correct" vs "display is right"
3. Fixing a calculation bug requires updating all baseline HTML files

---

## Proposed Architecture

### Phase 1: Testing Strategy (Immediate)

```
tests/
├── test_calculations.py          # Unit tests for calculation logic
│   ├── test_teaching_calculation()
│   ├── test_research_calculation()
│   ├── test_admin_calculation()
│   └── test_new_lecturer_multiplier()
├── test_formatting.py            # Tests for display formatting only
│   ├── test_html_display_format()
│   ├── test_csv_column_order()
│   └── test_chart_data_labels()
└── baseline/
    └── expected_results.json     # Structured data, not rendered HTML
```

**Key change:** Baseline comparison uses structured JSON (not HTML):
```json
{
  "Christopher Crispin-Bailey": {
    "total_hours": 1123.1,
    "teaching_hours": 496.5,
    "research_hours": 164.2,
    "admin_hours": 462.4,
    "teaching_breakdown": {
      "delivery": 41.7,
      "practicals": 192.5,
      "assessment_setting": 12.5,
      "marking": 73.0
    }
  }
}
```

### Phase 2: Output Layer Refactoring

#### Current issue:
`output_generator.py` contains both formatting AND calculation logic (regex parsing).

#### Proposed refactoring:

```python
# output_generator.py - after refactor

def generate_html_report(results: List[WorkloadResult]) -> str:
    """Pure rendering function. Uses WorkloadResult data directly."""
    # Read structured data from WorkloadResult
    # Format using templates
    # Return HTML string
    pass


def format_teaching_section(result: WorkloadResult) -> str:
    """Format teaching section for display.
    
    Args:
        result: WorkloadResult with pre-computed breakdowns
        
    Returns:
        Formatted HTML string (no calculations)
    """
    # Use result.teaching_breakdown directly
    # Apply display formatting rules
    pass


def calculate_display_hours(hours: float, multiplier: str) -> str:
    """Simple formatting - no business logic.
    
    Args:
        hours: Pre-calculated hours from WorkloadResult
        multiplier: Display string for the multiplier used
        
    Returns:
        Formatted string like "100.0h @ 2.5x"
    """
    return f"{hours:.1f}h {multiplier}"
```

### Phase 3: Validation Pipeline (IMPLEMENTED)

The validation pipeline has been added to `validation.py`:

```python
# validation.py - IMPLEMENTED

def validate_workload_result(result: WorkloadResult, tolerance: float = 0.1) -> List[ValidationIssue]:
    """Validate a workload result for structural correctness.
    
    Checks:
    - Total = Teaching + Research + Admin (within tolerance)
    - No negative hours
    - Breakdowns sum to category totals
    
    Returns:
        List of issues found (empty if valid)
    """
    # Validates total, teaching/research/admin breakdowns

def validate_all_results(results: List[WorkloadResult]) -> Dict[str, List[ValidationIssue]]:
    """Validate all results and group by staff member."""

---

## Implementation Plan

### Step 1: Create baseline/expected_results.json

Generate once from current correct output:

```bash
python scripts/main.py --export-baseline baseline/expected_results.json
```

This exports the structured `WorkloadResult` data as JSON.

### Step 2: Update tests

```python
# tests/test_calculations.py

def test_christopher_crispin_bailey_workload():
    """Verify Christopher's workload calculation is correct."""
    year_data = load_test_data("christopher")
    results = calculate_workload(year_data)
    
    christopher = next(r for r in results if r.name == "Christopher Crispin-Bailey")
    
    # Verify calculated values
    assert abs(christopher.total_hours - 1123.1) < 0.1
    assert abs(christopher.teaching_hours - 496.5) < 0.1
    assert abs(christopher.research_hours - 164.2) < 0.1
    assert abs(christopher.admin_hours - 462.4) < 0.1
    
    # Verify breakdown components
    assert christopher.teaching_breakdown['delivery'] > 0
    assert christopher.teaching_breakdown['practicals'] > 0


def test_new_lecturer_multiplier():
    """Verify new lecturers get 5x multiplier."""
    module = ModuleData(codes=("COM00000X",), teachers=("New Lecturer",))
    # ... setup
    
    result = _calculate_teaching_workload(module, ["New Lecturer"], is_new_lecturer=True)
    
    assert result['delivery_multiplier'] == 5.0
```

### Step 3: Update baseline comparison

```python
# tests/test_formatting.py

def test_html_output_matches_baseline():
    """Verify HTML output format hasn't changed."""
    results = calculate_workload(load_all_data())
    
    # Generate HTML
    html = generate_html_report(results)
    
    # Load baseline HTML (for display format only)
    with open("baseline/output.html") as f:
        expected_html = f.read()
    
    # Compare (ignoring any non-display changes)
    assert normalize_whitespace(html) == normalize_whitespace(expected_html)
```

### Step 4: Add validation step (IMPLEMENTED)

```python
# scripts/main.py - IMPLEMENTED

def main():
    args = parse_args()
    
    year_data = load_all_data(args.data_dir)
    
    # Calculate workload
    results = calculate_workload(year_data, validate_input=True)
    
    # NEW: Validate all results before output (lines 145-149)
    print("\nValidating calculations...")
    if not run_validation_pipeline(results):
        print("\nValidation failed. Please check the errors above.")
        sys.exit(1)
    print("  All validations passed.")
    
    # Generate outputs
    generate_all_outputs(results, year_data, args.output_dir)
```

**Status:** Validation is now integrated into `main.py` and runs automatically.

---

## Benefits

### Before (Current State)
```
Bug fix: teacher_count calculation
    ↓
All 50+ baseline HTML files change
    ↓
Commit contains both code and data changes
    ↓
Hard to distinguish "calculation fix" from "format change"
```

### After (Proposed State)
```
Bug fix: teacher_count calculation
    ↓
Unit tests catch the bug immediately (42 tests, 0.06s)
    ↓
Baseline JSON shows changed values → intentional update
    ↓
HTML baseline unchanged (display format not affected)
    ↓
Clear separation: "calculation" vs "format"
```

---

## Migration Path

1. **Week 1**: Create `baseline/expected_results.json` from current output
2. **Week 2**: Add unit tests for major calculation scenarios
3. **Week 3**: Refactor `output_generator.py` to remove regex parsing
4. **Week 4**: Add validation pipeline and integrate into CI

---

## Testing Strategy

### Level 1: Unit Tests (Fast, Isolated)
- Test each multiplier in isolation
- Test FTE scaling
- Test new lecturer detection
- Run: `pytest tests/test_calculations.py` (~0.1s)

### Level 2: Integration Tests (Slower, End-to-End)
- Test full calculation pipeline
- Verify all categories sum correctly
- Run: `pytest tests/test_integration.py` (~5s)

### Level 3: Format Tests (Display Only)
- Compare HTML output to baseline
- Verify CSV column order
- Verify chart data labels
- Run: `pytest tests/test_formatting.py` (~2s)

### Level 4: Validation Tests (Data Quality)
- Verify total = teaching + research + admin
- Check for negative hours
- Check for impossible values (>2x nominal)
- Run: `python main.py --validate-only`

---

## Success Criteria

1. Unit tests cover 100% of calculation functions
2. Baseline failures indicate format changes only (not calculation changes)
3. Adding a new test case takes <5 minutes
4. Running all tests takes <10 seconds
5. Validation catches data errors before HTML generation
