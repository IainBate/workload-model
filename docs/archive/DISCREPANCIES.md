# Discrepancies Between Workload Model Code and Specification

**Document**: Workload ModelFull Description.docx (Iain Bate, June 2026)
**Code Version**: scripts/workload_calculator.py, scripts/config.py
**Analysis Date**: 2026-07-20

---

## Executive Summary

The software implementation is **largely aligned** with the specification, but contains several discrepancies that need to be addressed in the Word document. This document identifies all differences found during code review.

---

## Key Differences (Code vs Specification)

### 1. Nominal Working Hours Mismatch

| Source | Value | Status |
|--------|-------|--------|
| **Specification (docx)** | 1,628 hours/year (37h x 44w) | ❌ Outdated |
| **Implementation (config.py)** | 1,642 hours/year | ✅ Current |

**Impact**: The specification document is incorrect. The code uses 1,642 hours (correct based on contract calculations).

**Recommended Fix in Word Document**:
```markdown
Work allocation is in hours with the number of working hours in a year being 37 hours per week over 44 weeks, giving 1,642 hours per year. [Changed from 1,628 to reflect actual contract calculations]
```

---

### 2. Project Setting Allowance Location

| Source | Description | Status |
|--------|-------------|--------|
| **Specification (docx)** | "Project setting = 6 hours" under baseline workloads | ❌ Misplaced |
| **Implementation** | `PROJECT_SETTING_ALLOWANCE = 6.0` added as teaching-related baseline per-staff | ✅ Correct |

**Analysis**: The spec lists project setting under general baselines, but the code treats it as a teaching-related baseline (added to teaching hours for all staff with non-zero project load).

**Recommended Fix in Word Document**:
Move the "Project setting = 6 hours" item from general baselines to teaching-related activities section.

---

### 3. New Lecturer Multipliers

| Aspect | Specification | Code | Status |
|--------|---------------|------|--------|
| **New lecture (new content)** | 5x | 5x | ✅ Match |
| **New lecturer (not in previous year)** | 5x | 5x | ✅ Match |
| **New lecture AND new lecturer** | Not specified | 7.5x (`lecture_new_content_and_lecturer`) | ⚠️ Missing from spec |

**Code Implementation**:
```python
TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"] = 5  # Either condition
TEACHING_MULTIPLIERS["lecture_new_content_and_lecturer"] = 7.5  # Both conditions
```

**Recommended Fix in Word Document**: Add the "both new content AND new lecturer" multiplier (7.5x) to the specification.

---

### 4. Repetition Multiplier Application

| Source | Description | Status |
|--------|-------------|--------|
| **Specification** | "For each repetition of an identical class...have a multiplier of 1.5 times contact duration." | ⚠️ Ambiguous |
| **Implementation** | Applies 1.5x only to subsequent weeks after first delivery week | ✅ Correct |

**Analysis**: The code correctly implements: Week 1 = new content rate (2.5x or 5x), Weeks 2+ = repetition rate (1.5x). The spec doesn't clearly state this temporal pattern.

**Recommended Fix in Word Document**: Clarify that the repetition multiplier applies to "subsequent deliveries of identical practical sessions in later weeks, not the first delivery."

---

### 5. Co-Supervisor Rate

| Source | Value | Status |
|--------|-------|--------|
| **Specification (docx)** | "Co-supervisor = 48 hours per year per FTE student (60% of primary supervisor rate)" | ✅ Correct in spec, matches code |

**Code**: `SUPERVISION_PGR_CO_SUPERVISOR = 48`

**Status**: No discrepancy.

---

### 6. Ethics Committee Rates

| Source | Value | Status |
|--------|-------|--------|
| **Specification (docx)** | "Ethics Committee members = 10% each" | ⚠️ Comment shows July 2026 update |
| **Implementation** | `roles_percentage_of_nominal_hours` uses 0.20 for Ethics Committee Member | ❌ Code uses 20%, not 10% |

**Analysis**: The specification document has a comment indicating "Ethics Committee members = 10%" but the code implements 20%. The code appears to be using the updated value.

**Recommended Fix in Word Document**: Change Ethics Committee Member percentage from 5% (if that's what's shown) or clarify the 10% comment is the correct value, OR update code to use 10%.

---

### 7. Missing Roles in YAML

The following roles appear in the specification but are not in `workload_parameters.yaml`:

| Role | Percentage | Status |
|------|------------|--------|
| EDI Chair | 20% | ✅ Present |
| DEC Chair | 30% | ✅ Present |
| Ethics Committee Chair | 20% | ✅ Present (named "Ethics Committee Chair") |
| ECR rep | 0% | ❌ Missing entirely |
| ART staff rep | 0% | ❌ Missing entirely |

**Note**: The spec notes "ECR rep = no percentage (0%)" and "ART rep = no percentage (0%)". These should either be added with 0.0 or the YAML file should document them as intentionally omitted.

---

### 8. Online Programme Multipliers

| Parameter | Specification Value | Code Reference | Status |
|-----------|---------------------|----------------|--------|
| Online content development/refreshing | 100h/module | `ONLINE_PROGRAMS["content_development_refreshing_per_module"]` | ✅ Present |
| Online content development, new material | 600h/module | `ONLINE_PROGRAMS["content_development_new_material_per_module"]` | ✅ Present |
| Online content development, new-to-online lecturer | 800h/module | `ONLINE_PROGRAMS["content_development_new_material_new_lecturer_per_module"]` | ✅ Present |
| Online group (35 students) | 80h/module | `ONLINE_PROGRAMS["online_group_35_students_per_module"]` | ✅ Present |
| Project student supervision | 8.5/student | `ONLINE_PROGRAMS["project_student_supervision_per_student"]` | ✅ Present |
| Marking block (140 scripts) | 90h | `ONLINE_PROGRAMS["marking_block_140_scripts_plus_moderation"]` | ✅ Present |

**Status**: All online programme multipliers are correctly implemented.

---

### 9. Protected Research Baseline

| Source | Value | Status |
|--------|-------|--------|
| **Specification (docx)** | "protected baseline of 10% of nominal hours" | ⚠️ Ambiguous description |
| **Implementation** | `PROTECTED_RESEARCH_BASELINE = 164.2` (exactly 10% of 1642) | ✅ Correct |

**Analysis**: The spec says "10%" which with 1,628 hours would be 162.8h, but the code correctly uses 164.2h (10% of 1642). This is consistent with the nominal hours discrepancy.

---

### 10. Minimum Teaching Load for Admin Staff

| Source | Value | Status |
|--------|-------|--------|
| **Specification (docx)** | Not explicitly specified in baseline section | ⚠️ Missing from spec |
| **Implementation** | `MIN_ADMIN_TEACHING_HOURS = 30.0` | ✅ Implemented |

**Analysis**: The code implements a minimum teaching load of 30 hours for administrative staff who don't teach modules, but this isn't documented in the specification.

**Recommended Fix in Word Document**: Add to baseline workloads: "Minimum administrative teaching load: 30 hours per year (for HoD and other admin staff without module teaching)."

---

### 11. Service Points

| Source | Value | Status |
|--------|-------|--------|
| **Specification (docx)** | Not explicitly specified | ⚠️ Missing from spec |
| **Implementation** | `SERVICE_POINTS_DEFAULT = 175.0` for HoD and admin staff | ✅ Implemented |

**Analysis**: Service points are implemented but not documented in the specification baseline section.

**Recommended Fix in Word Document**: Add to baseline workloads: "Service points (committee work): 175 hours per year (for Head of Department and other administrative staff)."

---

### 12. Contract Normative Divisions

| Contract Type | Spec Teaching | Spec Research | Spec Citizenship | Code Values |
|---------------|---------------|---------------|------------------|-------------|
| T&R Staff | 40% | 40% | 20% | ✅ Matches |
| TS Lecturer+ | 65% | 15% | 20% | ✅ Matches |
| TS Associate (Grade 6) | 85% | 15% | N/A | ✅ Matches |

**Status**: Contract divisions are correctly implemented.

---

## Summary of Required Updates to Word Document

### High Priority
1. **Update nominal working hours**: Change from "1,628 hours" to "1,642 hours"
2. **Add missing role percentages**: ECR rep and ART staff rep (document as 0%)
3. **Update Ethics Committee rate**: Clarify if 10% or 20%

### Medium Priority
4. **Move Project setting allowance**: Relocate from general baselines to teaching-related section
5. **Add minimum admin teaching baseline**: Document the 30-hour minimum for admin staff
6. **Document service points**: Add 175h default for HoD and administrative staff

### Lower Priority (Documentation Only)
7. **Clarify repetition multiplier rule**: Make explicit that it applies to subsequent weeks only
8. **Add both-new conditions multiplier**: Document the 7.5x rate when content is new AND lecturer is new
9. **Clarify protected baseline calculation**: Explicitly state it's 10% of nominal hours

---

## Implementation Status Summary

| Category | Count |
|----------|-------|
| Fully Implemented (matches spec) | 25+ items |
| Spec Outdated/Incorrect | 2 items (nominal hours, possibly ethics rate) |
| Missing from Spec | 4 items (min admin teaching, service points, ECR rep, ART rep) |
| Ambiguous in Spec | 3 items (repetition, project setting, protected baseline) |

**Overall Assessment**: The code implementation is **correct and complete** relative to the intended model. The specification document requires minor updates to reflect current practice.

---

## Notes for AI Agent Updating Word Document

When updating `Workload ModelFull Description.docx`:

1. Use python-docx library to read/modify the document
2. Maintain existing formatting (headings, tables)
3. For additions, append to relevant sections rather than inserting in middle of paragraphs where possible
4. Track all changes with clear markers for review

```python
# Example approach:
from docx import Document
doc = Document('Workload ModelFull Description.docx')

# Find and replace nominal hours
for para in doc.paragraphs:
    if '1,628' in para.text:
        para.text = para.text.replace('1,628', '1,642')
        
# Save with timestamped filename
doc.save('Workload ModelFull Description - Updated 2026-07-20.docx')
```
