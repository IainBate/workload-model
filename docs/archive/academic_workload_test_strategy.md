# Comprehensive Test Strategy for Academic Workload System

This test strategy establishes a multi-layered verification framework for the workload calculator codebase, ensuring correctness from raw data ingestion through calculation logic to final artifact generation (CSV, Excel, HTML reports, and charts).

---

## 1. Architectural Strategy for 100% Display–Calculation Consistency

Discrepancies between calculated values and visual display text occur when output generators re-perform math or parse unstructured text. Achieving 100% verified consistency requires combining architectural constraints with automated validation.

### System Data Flow

```text
       ┌───────────────────────────────┐
       │   workload_calculator.py      │
       │  (Calculates Workload Result) │
       └──────────────┬────────────────┘
                      │ Emits Structured DTOs
                      ▼
     ┌───────────────────────────────────┐
     │      WorkloadResult Payload       │
     │  - teaching_module_breakdowns     │
     │  - practicals_structured          │
     │  - research_breakdown             │
     └────────────────┬──────────────────┘
                      │
           ┌──────────┴──────────┐
           ▼                     ▼
┌────────────────────┐ ┌──────────────────────────────────┐
│ output_generator.py│ │ DOM Extraction Test Pipeline     │
│ (Consumes Payload) │ │ (Parses HTML with BeautifulSoup) │
└──────────┬─────────┘ └─────────────────┬────────────────┘
           │ Renders                     │
           ▼                             │ Cross-Asserts
┌────────────────────┐                   │ Numerical Exactness
│ Rendered HTML/XLSX │◄──────────────────┘
└────────────────────┘
```

### Architectural Guardrails

* **Single Source of Truth (Payload Contracts):** `output_generator.py` must never recalculate multipliers, hours, or group allocations. All numerical values displayed in HTML, Excel, or CSV must originate directly from structured dictionary contracts emitted by `workload_calculator.py` (e.g., `practicals_structured`, `teaching_module_breakdowns`).
* **Zero Text-Parsing Dependency:** Display generation logic must consume typed fields (e.g., `first_session_hours`, `repeat_hours`, `n_teachers`) rather than regex-parsing formatted strings.

### Consistency Verification Test Pipeline

To guarantee 100% visual parity, implement an automated DOM extraction test suite using BeautifulSoup to parse generated HTML reports and assert exact equivalence against the underlying `WorkloadResult` data model.

```python
import pytest
from bs4 import BeautifulSoup
from workload_calculator import calculate_workload
from output_generator import generate_html_report, _create_individual_staff_report_html


def test_100_percent_display_calculation_parity(sample_year_data):
    """Guarantees 100% consistency between internal mathematical calculations
    and generated visual display elements in HTML reports."""
    results = calculate_workload(sample_year_data, validate_input=False)

    for result in results:
        # Render the individual HTML report
        html_content = _create_individual_staff_report_html(result, sample_year_data)
        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Verify Top-Level Header Totals
        rendered_total = float(
            soup.find("strong", style=lambda s: s and "#4CAF50" in s)
            .text.replace("h", "")
        )
        assert abs(rendered_total - result.total_hours) < 1e-4, (
            f"Mismatch for {result.name}: Calculated {result.total_hours}h, "
            f"Displayed {rendered_total}h"
        )

        # 2. Verify Teaching Subtotal
        teaching_card = soup.find("div", class_="section-card teaching-item")
        rendered_teaching = float(
            teaching_card.find("span", class_="card-total").text.replace("h", "")
        )
        assert abs(rendered_teaching - result.teaching_hours) < 1e-4, (
            f"Teaching mismatch for {result.name}: Calculated {result.teaching_hours}h, "
            f"Displayed {rendered_teaching}h"
        )

        # 3. Verify Module-Level Structured Breakdown Parity
        for code, breakdown in result.teaching_module_breakdowns.items():
            practicals = breakdown.get("practicals_structured", {})
            if practicals:
                # Extract line item from HTML DOM for this module
                line_item = soup.find(text=lambda t: t and f"[{code}] Practical Sessions" in t)
                if line_item:
                    item_container = line_item.find_parent("div", class_="detail-item")
                    displayed_hours = float(
                        item_container.find("span", class_="detail-hours")
                        .text.replace("h total", "").replace("h", "").strip()
                    )
                    expected_hours = breakdown.get("practicals", 0.0)
                    assert abs(displayed_hours - expected_hours) < 1e-4, (
                        f"Practical display mismatch for {code}: Calculated {expected_hours}h, "
                        f"Displayed {displayed_hours}h"
                    )
```

---

## 2. Comprehensive Multi-Stage Testing Framework

| Test Stage | Focus Area | Key Targets | Primary Tooling |
| :--- | :--- | :--- | :--- |
| **Stage 1: Unit** | Pure logic & data models | Data structures, multiplier selection, individual calculation functions | `pytest` |
| **Stage 2: Consistency** | Parity guarantees | HTML/XLSX text elements vs. calculated DTO values | `BeautifulSoup4`, `pytest` |
| **Stage 3: Integration** | Cross-module workflow | Loader → Calculator → Generator pipelines | `pytest`, `openpyxl` |
| **Stage 4: Property-Based** | Boundary conditions | Mathematical invariants, non-negativity, monotonicity | `hypothesis` |
| **Stage 5: Visual/Regression** | Output artifacts | Bar chart rendering, CSV column alignment, file outputs | `pytest-regressions`, `filecmp` |

---

## 3. Stage 1: Component Unit Testing

Unit tests focus on individual functions in isolation, covering standard executions, edge cases, and invalid inputs.

### A. Data Loader & Schema Validation (`data_loader.py`, `validation.py`)

* **Canonical Name Normalization:** Verify whitespace trimming, accent handling, and case sensitivity.
* **Module Mapping Lookup:** Verify merging logic (e.g., combining `AURO-H` and `AURO-M` into `AURO`).
* **Validation Level Checks:** Ensure input validation correctly raises warnings or errors for missing staff FTEs, negative student counts, or missing module codes.

### B. Core Workload Calculation Engine (`workload_calculator.py`)

Unit test each helper function independently before testing `calculate_workload`:

#### `_calculate_lecture_hours_and_multipliers`
* **New lecturer (not in previous year):** Verify `5.0×` multiplier applied.
* **New lecturer + new content module:** Verify `7.5×` multiplier applied.
* **Standard lecturer (existing):** Verify `2.5×` multiplier applied.
* **Video/online format teaching:** Verify `10.0×` multiplier applied.
* **Split teaching load:** Verify correct contact hour distribution when $N$ teachers share a module.

#### `_calculate_practical_hours_and_breakdown`
* **Single teacher, no parallel groups:** $	ext{Practical Hours} = 	ext{Sessions} 	imes 	ext{Duration} 	imes 	ext{Rate}$.
* **Parallel groups with repeats:** Verify first-session rate (`TEACHING_PROBLEM_CLASS`) vs. repeat-session rate (`REPETITION_MULTIPLIER`).
* **Formula verification for weekly repeat hours:**

$$	ext{Weekly Repeat Hours} = \left(rac{	ext{Total Groups}}{N_{	ext{teachers}}} - 1ight) 	imes 	ext{First Session Hours} 	imes 	ext{Base Rate} 	imes 	ext{Repeat Multiplier}$$

```python
def test_calculate_practical_hours_repeat_logic():
    """Verify practical calculation with 4 parallel groups and 2 teachers."""
    module = ModuleData(
        name="Advanced Systems",
        codes=["CS001"],
        credits=20,
        stage=3,
        contact_hours=20,
        practicals=1,
        practical_contact_hours=2.0,
        parallel_groups=4,
        teachers=["Teacher A", "Teacher B"],
        lead_name=None,
        practical_weeks=list(range(1, 12))
    )

    # 4 groups / 2 teachers = 2 groups per teacher (1 first session, 1 repeat session)
    result = _calculate_practical_hours_and_breakdown(
        module=module,
        teachers=["Teacher A", "Teacher B"],
        lecturer_types=[("Teacher A", "standard"), ("Teacher B", "standard")]
    )

    # Each teacher gets 1 first session (2h * 2.5x) + 1 repeat (2h * 2.5x * 1.5x)
    # First = 5.0h, Repeat = 7.5h -> Total per teacher = 12.5h per week * weeks factor
    assert "Teacher A" in result["individual_practical_hours"]
    assert result["individual_practical_hours"]["Teacher A"] > 0
```

---

## 4. Stage 3: Integration & Pipeline Testing

Integration testing verifies that data passes correctly across module boundaries without corruption or precision loss.

### A. End-to-End Pipeline Workflow

Verify the complete execution flow from raw input through output generation:

1. Construct a fully populated `YearData` instance.
2. Run `calculate_workload(year_data)`.
3. Pass results to `generate_all_outputs(results, year_data, tmp_path)`.
4. Assert presence and non-zero size of generated files:
   * `Staff workload model.csv`
   * `Staff workload model.xlsx`
   * `workload_summary_boxplot.png`
   * `workload_detailed_boxplot.png`
   * `workload_report.html`
   * `Individual Reports/*.html`

### B. Excel Formula & Structure Validation (`generate_excel_with_formulas`)

* **Formula Validity:** Ensure formulas written using `openpyxl` (e.g., `=SUM(B2:D2)`) reference correct cell coordinates and do not create `#REF!` or `#VALUE!` errors.
* **StrRef Conversion:** Test that `_fix_category_references(chart)` converts `numRef` to `strRef` on category axes, preventing broken chart renderings in Excel.

```python
import openpyxl


def test_excel_formula_integrity(tmp_path, sample_workload_results, sample_year_data):
    """Verify generated Excel workbook contains valid formulas and references."""
    output_file = tmp_path / "Staff workload model.xlsx"
    generate_excel_with_formulas(sample_workload_results, sample_year_data, output_dir=str(tmp_path))

    wb = openpyxl.load_workbook(output_file, data_only=False)
    ws = wb["Detailed Breakdown"]

    # Assert formula structure in total column
    assert ws["E2"].value == "=SUM(B2:D2)"

    # Verify openpyxl charts exist
    assert len(ws._charts) > 0
```

---

## 5. Stage 4: Property-Based & Invariant Testing

Using `hypothesis`, generate random, valid datasets to test system invariants that must always hold true regardless of input values.

### Mathematical Invariants to Enforce

* **Conservation of Total Workload:** $	ext{Total Hours} = 	ext{Teaching Hours} + 	ext{Research Hours} + 	ext{Admin Hours}$
* **Monotonicity of FTE:** $	ext{FTE}_A > 	ext{FTE}_B \implies 	ext{Nominal Hours}_A > 	ext{Nominal Hours}_B$ (all else equal)
* **Non-Negativity:** $orall r \in 	ext{Results}, \min(	ext{Teaching}, 	ext{Research}, 	ext{Admin}, 	ext{Total}) \ge 0.0$
* **Group Distribution Neutrality:** $\sum (	ext{Teacher Practical Hours}) = 	ext{Module Total Practical Hours}$

```python
from hypothesis import given, strategies as st


@given(
    fte=st.floats(min_value=0.1, max_value=1.0),
    contact_hours=st.floats(min_value=0.0, max_value=100.0),
    student_count=st.integers(min_value=0, max_value=500)
)
def test_workload_invariants(fte, contact_hours, student_count):
    """Property-based test to verify mathematical invariants hold across inputs."""
    module = ModuleData(
        name="Generic Module",
        codes=["GEN001"],
        credits=20,
        stage=1,
        contact_hours=contact_hours,
        practicals=1,
        practical_contact_hours=2.0,
        practical_groups=2,
        practical_weeks=[1, 2, 3],
        assessment_count=1,
        student_count=student_count,
        teachers=["Staff A"],
        lead_name=None
    )

    staff = StaffData("Staff A", fte, [], 0, 0, 0, [], [], True)
    year_data = YearData.create("2026-7", [module], {}, {}, {"Staff A": staff}, set(), {})

    results = calculate_workload(year_data, validate_input=False)
    r = results[0]

    # Invariant 1: Sum of parts equals total
    assert abs(r.total_hours - (r.teaching_hours + r.research_hours + r.admin_hours)) < 1e-4

    # Invariant 2: Non-negativity
    assert r.total_hours >= 0.0
    assert r.teaching_hours >= 0.0
    assert r.research_hours >= 0.0
    assert r.admin_hours >= 0.0
```

---

## 6. Stage 5: Visual Regression & Snapshot Testing

Visual output generators require testing to prevent formatting regressions, sentence truncation, or chart alignment breaks.

### A. HTML String & Sentence Termination

* **Syntax & Operators:** Verify generated HTML lines do not terminate abruptly in trailing operators (e.g., `assert not part.endswith('=')`).
* **Terminology Uniformity:** Ensure terminology remains strictly consistent across standard and repeat session sections (e.g., using `"First session"` consistently rather than mixing `"First time delivery"` and `"Initial run"`).

### B. Matplotlib Image Rendering Verification

* **Artifact Creation:** Assert chart image files (`.png`) are correctly created with expected dimensions and non-zero file sizes.
* **CI Environment Rendering:** Verify that `matplotlib` Agg backend executes headless without throwing display errors in CI environment pipelines.
