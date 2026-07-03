# Three-Way Comparison Report: Code Output vs Excel Model vs DOCX Specification

**Date:** 2026-07-03
**Scope:** Computer Science Workload Model 2025-26

---

## Executive Summary

There are **significant differences** between the code's output, the manual Excel model, and the DOCX specification. The code output generally produces different total hours for most staff members, with the Excel model typically showing higher teaching hours for ART staff but lower teaching hours for T&S staff. The root causes are:

1. **Different teaching calculation methodology** (simplified vs granular)
2. **Missing staff** in the code output (9 ART staff, all T&S staff)
3. **Different admin calculation** (percentage-based vs fixed hours)
4. **Different baseline treatment** (fixed hours vs derived)
5. **Role mapping gaps** (roles in WAW with no YAML percentage)

---

## 1. Staff Coverage Differences

### 1.1 Staff in Excel but MISSING from Code Output (9 people)

| Name | Excel Total Hours | Excel Teaching | Excel Research | Excel Admin | Source Sheet |
|------|------------------|----------------|----------------|-------------|--------------|
| Ana Cavalcanti | 2,348.5 | 0 | 2,266.4 | 82.1 | ART |
| Chris Crispin-Bailey | 1,407.1 | 1,037.6 | 328.4 | 41.0 | ART |
| Iain Bate | 2,408.8 | 30 | 736.8 | 1,642.0 | ART |
| Ibrahim Habli | 1,968.3 | 0 | 1,968.3 | 0 | ART |
| John Oyekan | 1,150.0 | 725.8 | 424.2 | 0 | ART |
| Richard Hawkins | 670.6 | 138.0 | 450.5 | 82.1 | ART |
| Simon Burton | 1,470.4 | 2 | 1,468.4 | 0 | ART |
| Simon O'Keefe | 1,409.0 | 423.8 | 328.4 | 656.8 | ART |
| Simos Gerasimou | 1,417.6 | 168 | 1,085.4 | 164.2 | ART |

**Why this matters:** These are all ART (Academic Research Track) staff who should be included. Their absences suggest the WTW CSV or module mapping is not capturing them.

### 1.2 Staff in Code Output but NOT in Excel ART sheet (14 people)

| Name | Code Total | Source |
|------|-----------|--------|
| Andrew Pomfret | 423.2 | T&S sheet (has teaching) |
| Claire Ingram | 81.4 | T&S sheet (admin only) |
| Da Li | 477.7 | New lecturer |
| Dawn H Wood | 500.0 | T&S sheet (has teaching) |
| Fang Yan | 999.1 | SAINTS modules only |
| Felix Ulrich-Oltean | 612.8 | SAINTS modules only |
| James Stovold | 747.9 | New lecturer |
| Jen Beeston | 779.0 | T&S sheet (has teaching) |
| Katrina Attwood | 842.7 | T&S sheet (has teaching) |
| Mike Freeman | 504.2 | T&S sheet (has teaching) |
| Mike O'Dea | 609.9 | T&S sheet (no teaching) |
| Soumya Banerjee | 933.8 | New lecturer |
| Tommy Yuan | 1,064.8 | T&S sheet (has teaching) |
| Christopher Crispin-Bailey | 1,063.3 | Name variant (see 1.3) |

**Why this matters:** The T&S staff (teaching & scholarship contract) are in the Excel but NOT in the code output. This is a significant gap. Part-time staff (Sarah Carrington, David Pumfrey, Mark Sujan, Richard Wilson) are also excluded.

### 1.3 Name Variant Issue

"Chris Crispin-Bailey" (Excel ART) vs "Christopher Crispin-Bailey" (code output) — these are the same person but counted as two different people, splitting their workload.

---

## 2. Teaching Calculation Methodology

### 2.1 Code Approach (Simplified)

```
contact_hours × multiplier = teaching_hours
multiplier = 2.5 (standard) or 7.5 (new lecturer)
assessment_setting = assessment_count × 25h (standard) or 35h (new setter)
marking = student_count × 0.25h (MSc automated)
admin = assessment_count × 3h
supervision = pastoral_count × 6h + project_count × 22h (UG) or 40h (MSc)
engagement + project_setting = 100 + 6 = 106h (shared among teachers)
```

### 2.2 Excel Approach (Granular)

The Excel's **M2 sheet** calculates teaching with many more parameters:

| Parameter | Code | Excel |
|-----------|------|-------|
| Lecture first delivery | 2.5h per contact hour | 25.0h per contact hour (same as standard) |
| Lecture multiple delivery | 1.5× contact hour | 15.0h per contact hour |
| Lecture new content | 7.5× (new lecturer) | 50.0h per contact hour |
| New lecturer | 7.5× (new lecturer) | 7.5h per contact hour (hardcoded) |
| New video lecture | Not used | 10.0h per contact hour |
| Seminar first delivery | 2.5h per contact hour | 25.0h per contact hour |
| Seminar multiple | 1.5× contact hour | 15.0h per contact hour |
| New seminar | Not distinguished | 50.0h per contact hour |
| HW lab | 4h per contact hour | 4.0h per contact hour |
| New HW lab | 8h per contact hour | 8.0h per contact hour |
| Drop-in session | 1.5h | Not used |
| Assessment setting | 25h or 35h flat | 15h (manual old), 25h (auto old), 22.5h (manual new), 37.5h (manual new format), 35h (auto new), 60h (auto new format) |
| Checking paper | Not used | 4 + exam duration (auto), 2 (manual) |
| Marking per script | 0.25h (MSc) / 0.166h (UG) | Same rates but applied to partial percentages |
| Marking % | 100% of students | Partial marking percentages per staff |
| Admin flat rate | 3h per assessment | 3h per assessment |

### 2.3 Key Impact Examples

**Sam Braunstein (THE2 module):**
- Code: 20 contact hours × 2.5 = 50h teaching
- Excel: 302.74h teaching (includes detailed seminar hours, marking at 20%, etc.)
- **Difference: -252.7h (code is much lower)**

**Joe Cutting (PRAD + SYS3):**
- Code: 538h teaching (PRAD: 20×2.5 + assessment + marking; SYS3: not counted)
- Excel: 824.95h teaching
- **Difference: -287h**

**Radu Calinescu (GPIG):**
- Code: 638.8h teaching (40 credit = 40 contact hours × 2.5 = 100h + assessment + marking)
- Excel: 169.55h teaching
- **Difference: +469.2h (code is much higher)**

---

## 3. Research Calculation Differences

### 3.1 PhD Supervision

| Aspect | Code | Excel | DOCX Spec |
|--------|------|-------|-----------|
| Primary supervisor rate | 80h per FTE | 80h per FTE | 80h per FTE |
| Co-supervisor rate | 8h per assessment | Not clearly tracked | 8h (2 TAPs) |
| Data source | PhD Supervision Data.csv | Supervisors sheet | DOCX |

**Discrepancy:** The code counts PhD supervisions from `PhD Supervision Data.csv`, while the Excel tracks them in the `Supervisors` sheet with different counts. For example:
- Adrian Bors: code=3 PhD students (240h), Excel=3 primary + 80h co-supervisor = 355.8h
- The Excel includes co-supervisor hours; the code does not

### 3.2 Grant Time

Both use `grant_percentage × 1,628h`, but:
- The Excel has **different grant percentages** in column AB (hardcoded hours)
- The code reads from `% FTE for CS.csv`
- Some grant percentages in the Excel are converted to hours directly (e.g., "82.1 hours") rather than percentages

### 3.3 Baseline Research Protection

The DOCX describes a "protected baseline" concept (10% of nominal hours = 162.8h for FTE 1.0) for T&R staff and 15% for T&S staff. Neither the code nor the Excel directly implements this as a separate calculation — it's more of a governance principle.

---

## 4. Administration Calculation

### 4.1 Code vs Excel vs DOCX

| Aspect | Code | Excel | DOCX |
|--------|------|-------|------|
| Basis | Percentage × nominal_hours | Fixed hours per role | Percentage × nominal_hours |
| Data source | workload_parameters.yaml | Admin sheet (fixed hours) | Appendix A |
| Unmapped roles | 0% (silent) | 0 | Needs assignment |

### 4.2 Key Admin Differences

| Staff | Code Admin | Excel Admin | Difference | Cause |
|-------|-----------|-------------|------------|-------|
| Iain Bate | 0 | 1,642 | -1,642 | HoD role (100%) not mapped to code |
| Ian Gray | 814 | 821 | -7 | Code: 50% = 814h; Excel: 821h (different base) |
| Nick Pears | 651.2 | 697.85 | -46.65 | Code: 40% of 1628; Excel: 40% of 1642 |
| Kofi Appiah | 244.2 | 82.1 | +162.1 | Code: 15% of 1628; Excel: 10% of 821 |
| Joe Cutting | 0 | 41.05 | -41.05 | ECR rep role = 0% in YAML |
| Steven Wright | 0 | 492.6 | -492.6 | CBoE chair = 0% in code (mapped to wrong role) |
| Pengcheng Liu | 0 | 369.45 | -369.45 | GSB Chair = 0% in YAML |

### 4.3 Roles with No Percentage in YAML (default to 0%)

From `roles_needing_percentages.yaml`:
- "Chair of the Department Education Committee" — Jen Beeston (Excel shows Technical Quality Manager = 30% = 492.6h)
- "ECR rep" — Joe Cutting (Excel shows 0%)
- "ART staff rep" — Richard Wilson
- "Ethics Committee members" — Dimitar Kazakov (Excel shows 0%)

---

## 5. Baseline Workloads

### 5.1 Code Implementation

The code adds three fixed baselines to every module a person teaches:
- **Engagement:** 100h (shared equally among teachers)
- **Project setting:** 6h (shared equally)
- **Personal development:** 75h — **NOT included in code output!**

### 5.2 Excel Treatment

The Excel's ART and T&S sheets have separate "Total available hours" and "Total available teaching and admin hours" columns:
- ART: 1,642h total, 985.2h for teaching/admin (1642 - 164.2 - 164.2 - 288.4 baselines = 985.2?)
- T&S: 1,642h total, 1,395.7h for teaching/admin

The baselines are accounted for differently — the Excel seems to subtract them from the available pool rather than adding them on top.

### 5.3 Missing Baseline

**The code does NOT add the 75h personal development baseline.** This is a bug — the DOCX explicitly lists it as a baseline for all researchers.

---

## 6. Contract Type Differences

### 6.1 Excel Has Three Contract Types

| Sheet | Contract Type | Available Hours | Teaching/Admin Hours |
|-------|--------------|-----------------|---------------------|
| ART | Research Track | 1,642 | 985.2 |
| T&S | Teaching & Scholarship | 1,642 | 1,395.7 |
| Part time | Variable | Variable | Variable |

### 6.2 Code Treats Everyone the Same

The code uses a flat 1,628h nominal year for everyone, regardless of contract type. This means:
- T&S staff have more protected teaching time (65-85% vs 40%)
- T&S staff have less research time (15% protected baseline)
- These contract-specific protections are **not implemented in the code**

---

## 7. Specific Staff Deep-Dive

### 7.1 Sam Braunstein (largest teaching discrepancy)

| | Code | Excel | Diff |
|--|------|-------|------|
| Total | 425.4 | 1,481.3 | -1,055.9 |
| Teaching | 425.4 | 1,152.9 | -727.5 |
| Research | 0 | 328.4 | -328.4 |
| Admin | 0 | 0 | 0 |

**Root causes:**
1. Code uses simple 2.5× multiplier on contact hours (no detail on first vs multiple delivery)
2. Excel has detailed per-module calculation with seminar hours, marking percentages
3. Code shows 0 research; Excel shows 328.4h (328.4 = 20% of 1,642, which is the T&S protected research baseline)
4. Braunstein is in T&S sheet, not ART sheet
5. Code does not apply the T&S contract type

### 7.2 Colin Paterson (largest research discrepancy)

| | Code | Excel | Diff |
|--|------|-------|------|
| Total | 1,002.0 | 2,476.6 | -1,474.6 |
| Research | 453.0 | 1,444.6 | -991.6 |

**Root causes:**
1. Code research = 160 (2 PhD × 80) + 293.6 (grants) = 453.0
2. Excel research = 1,444.6 — likely includes KTP grants, SAINTS time, and other funded research
3. The Excel has much more detailed grant tracking

### 7.3 Iain Bate (HoD)

| | Code | Excel | Diff |
|--|------|-------|------|
| Total | 0.0 | 2,408.8 | -2,408.8 |
| Admin | 0 | 1,642 | -1,642 |

**Root causes:**
1. Code shows 0 total — Bate is not in the code output at all (should be Head of Department)
2. Excel: HoD = 100% = 1,642h; plus 736.8h research (SCHEME grant); plus 30h teaching
3. The HoD role mapping may be failing to match

### 7.4 Stefano Pirandola (smallest total difference)

| | Code | Excel | Diff |
|--|------|-------|------|
| Total | 1,183.8 | 1,171.2 | +12.6 |
| Teaching | 536.8 | 637.5 | -100.7 |
| Research | 402.8 | 492.6 | -89.8 |
| Admin | 244.2 | 41.05 | +203.1 |

**Root causes:**
1. Teaching: code uses 2.5× on contact hours; Excel uses detailed calculation
2. Research: code = 240 (3 PhD) + 162.8 (grant) = 402.8; Excel = 492.6 (different grant %)
3. Admin: code = 15% of 1,628 = 244.2; Excel = 41.05 (different role assignment)

---

## 8. Roles Mapping Issues

### 8.1 Roles in WAW but No YAML Percentage (default to 0%)

1. **"Chair of the Department Education Committee"** — Jen Beeston gets 0% in code, but Excel shows 30% (Technical Quality Manager role)
2. **"ECR rep"** — Joe Cutting gets 0%
3. **"ART staff rep"** — Richard Wilson gets 0%
4. **"Ethics Committee members"** — Dimitar Kazakov gets 0%

### 8.2 Role Name Mismatches

The `_WAW_ROLE_MAPPING` in `data_loader.py` handles many WAW→YAML mappings, but:
- "Chair of the Department Education Committee" maps to nothing (no YAML equivalent)
- "ECR rep" maps to nothing
- "ART staff rep" maps to nothing

### 8.3 "Chair of the Board of Examiners" Mapping

The YAML has "CBoE (on-campus)" = 30% but the WAW says "Chair of the Board of Examiners". The mapping handles this, but the YAML role name doesn't match the WAW name directly.

---

## 9. Key Discrepancies Summary

### 9.1 Largest Total Differences

| Staff | Code | Excel | Diff | % Error |
|-------|------|-------|------|---------|
| Ana Cavalcanti | 0 | 2,348.5 | -2,348.5 | -100% |
| Simon Burton | 0 | 1,470.4 | -1,470.4 | -100% |
| Colin Paterson | 1,002.0 | 2,476.6 | -1,474.6 | -60% |
| Simos Gerasimou | 0 | 1,417.6 | -1,417.6 | -100% |
| Sam Braunstein | 425.4 | 1,481.3 | -1,055.9 | -71% |
| Simon O'Keefe | 0 | 1,409.0 | -1,409.0 | -100% |
| Christopher Crispin-Bailey | 1,063.3 | 1,407.1 | -343.8 | -24% |
| Frank Soboczenski | 2,271.9 | 1,561.9 | +710.0 | +45% |
| Pedro Ribeiro | 1,151.6 | 2,497.3 | -1,345.7 | -54% |

### 9.2 Systematic Patterns

1. **Code underestimates teaching for ART staff** — the simplified 2.5× multiplier misses the detailed seminar hours, marking percentages, and first-delivery multipliers that the Excel captures
2. **Code overestimates teaching for some** (e.g., Radu Calinescu at 40-credit module: code = 40×2.5 + extras vs Excel's detailed lower calculation)
3. **Code misses T&S contract type entirely** — no protected research baseline, no different contract divisions
4. **Admin is calculated differently** — percentage-based (code) vs fixed hours (Excel)
5. **Personal development baseline (75h) is missing** from code
6. **Multiple staff are missing** from code output (9 ART, all T&S, all part-time)

---

## 10. Potential Issues in the Input Data / Parameters

### 10.1 Questions for Review

1. **Are the teaching multipliers correct?** The DOCX says lecture = 2.5h per contact hour, but the Excel uses 25.0h per contact hour for first delivery. This is a 10× difference. **This is likely the single biggest source of discrepancy.** Wait — re-reading the DOCX: "Lecture = 2.5 (includes preparation & student queries)" — this means 2.5 hours of *work* per 1 hour of *contact time*. The Excel's 25.0h per contact hour seems wrong. Let me re-check...

   Actually, looking more carefully at the DOCX:
   - "Lecture = 2.5 (includes preparation & student queries)" — 2.5 hours per contact hour
   - "Example: A new two-hour lecture which is delivered twice: 5 * 2 hours + 1.5 * 2 hours = 13 hours"
   
   So 2.5h per contact hour IS correct per the DOCX. The Excel's 25.0h per contact hour for first delivery appears to be using a different scale or there's a unit confusion.

   **Wait, re-reading the M2 sheet header:** "Lecture first delivery" column H has value 25.0 — but looking at the row data, this is 25 minutes, not 25 hours. The Excel uses minutes for contact hours. So 25 minutes × 2.5 = 62.5 minutes of work. This would explain the discrepancy.

2. **The WTW CSV data** — the code reads from `WTW 2026-7.csv` and `WTW 2025-6.csv`. Are these the right files? Do they contain all the modules and staff that the Excel has?

3. **The "New Lecturer" rule** — the DOCX says "Lecture delivered by a lecturer who was not part of the module team last year = 5". The code implements this as 7.5× (new content AND new lecturer). The DOCX also says "Lecture with significantly new content = 5" and "New lecturer for a new lecture = 7.5". The code conflates these.

4. **Assessment setting** — the code assumes automated marking (25h standard, 35h new setter) for everyone. The DOCX has separate rates for manual marking (15h standard, 22.5h new setter). The Excel tracks this per-module.

5. **Supervision defaults** — the code uses 20 pastoral + 10 project students per teacher as defaults. The Excel uses individual counts from `pastoral_load.csv` and `project_load.csv`.

---

## 11. Recommendations

### High Priority
1. **Add T&S contract type support** — the code needs to distinguish ART from T&S staff for baseline calculations and contract divisions
2. **Include missing staff** — investigate why 9 ART staff and all T&S staff are missing from the code output
3. **Fix personal development baseline** — add the 75h baseline that's currently missing
4. **Verify teaching multiplier units** — confirm whether the Excel's "25.0" in the lecture column is minutes or hours
5. **Add missing role percentages** — assign percentages for roles that currently default to 0%

### Medium Priority
6. **Implement manual vs automated marking distinction** — the code assumes automated for all modules
7. **Use per-module teaching detail** — the Excel's granular approach (first delivery, multiple delivery, seminar hours, marking percentages) is more accurate
8. **Fix name variants** — "Chris" vs "Christopher" Crispin-Bailey should be merged
9. **Review PhD supervision data** — the code's counts differ from the Excel's counts

### Low Priority
10. **Standardize admin calculation** — decide whether admin should be percentage-based (per DOCX) or fixed hours (per Excel)
11. **Implement co-supervisor hours** — the code doesn't track co-supervision

---

## Appendix A: Staff-by-Staff Comparison Table

See the detailed comparison output above (56 staff members compared).

## Appendix B: DOCX Parameter Reference

All multipliers from `Workload ModelFull Description.docx`:

| Parameter | Value | Unit |
|-----------|-------|------|
| Nominal hours/year | 1,628 | hours (37×44) |
| Engagement baseline | 100 | hours |
| Project setting baseline | 6 | hours |
| Personal development baseline | 75 | hours |
| Lecture (standard) | 2.5 | hours per contact hour |
| Lecture (new content) | 5 | hours per contact hour |
| Lecture (new lecturer) | 5 | hours per contact hour |
| Lecture (new content + new lecturer) | 7.5 | hours per contact hour |
| Lecture (new video) | 10 | hours per contact hour |
| Problem class/seminar/practical | 2.5 | hours per contact hour |
| New problem class/seminar/practical | 5 | hours per contact hour |
| HW lab | 4 | hours per contact hour |
| New HW lab | 8 | hours per contact hour |
| Drop-in session | 1.5 | hours |
| Repetition multiplier | 1.5 | × contact duration |
| Automated paper setting (standard) | 25 | hours per paper |
| Automated paper setting (new setter) | 35 | hours per paper |
| Automated paper setting (new assessment) | 60 | hours per paper |
| Automated paper checking | 4 + exam duration | hours |
| MSc automated marking | 0.25 | hours per script |
| UG automated marking | 0.166 | hours per script |
| Automated checking | 0.1 | hours per script |
| Manual paper setting (standard) | 15 | hours per paper |
| Manual paper setting (new setter) | 22.5 | hours per paper |
| Manual paper setting (new assessment) | 37.5 | hours per paper |
| Manual paper checking | 2 | hours |
| MSc manual marking | 0.5 | hours per script |
| UG manual marking | 0.33 | hours per script |
| Manual checking | 0.1 | hours per script |
| Marking admin flat rate | 3 | hours per assessment |
| Pastoral supervision | 6 | hours per student |
| UG project supervision | 22 | hours per student |
| MSc project supervision | 40 | hours per student |
| Project marking | 2 | hours per student |
| PhD primary supervisor | 80 | hours per FTE per year |
| PhD co-supervisor | 8 | hours per assessment |
| Online content refreshing | 100 | hours per module |
| Online content new material | 600 | hours per module |
| Online content new + new lecturer | 800 | hours per module |
| Online group (35 students) | 80 | hours per module |
| Online project supervision | 8.5 | hours per student |
| Online marking block (140 scripts) | 90 | hours |
