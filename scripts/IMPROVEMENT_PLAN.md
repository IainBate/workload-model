# Improvement Plan (consolidated from 6 planning docs)

**Status:** Sections A and C complete. Section D found to be ~90% already built (see below —
this plan originally assumed it needed building from scratch; that assumption was wrong).
Section B (testing foundation) and the gated B10 refactor still to do. Built from
`architecture_improvements.md`, `architecture_improvements_v2.md`,
`academic_workload_test_strategy.md`, `BUGS_AND_FIXES.md`, `DISCREPANCIES.md`, and
`WORKLOAD_OUTPUT_REDESIGN_PROMPTS.md`, reconciled and cross-checked against the live codebase
(2026-08-12), plus decisions from Iain (recorded below).

## Decisions made (2026-08-12)

1. **Doc of record:** `Work Allocation Model.docx` is the sole source of truth. Code/config/
   report-footer citations updated accordingly.
2. **Ethics Committee Member %:** Confirmed **20%**. `workload_parameters.yaml` reverted to 0.20,
   self-contradictory prose caveat removed from the docx.
3. **Individual Report redesign proposals:** "Show me the list" → **done**: all 7 proposals
   built as independently-toggleable features in a brand-new `New Individual Reports/` folder,
   generated alongside (never replacing) the existing `Individual Reports/`. See Section C below
   for how to keep/drop individual pieces.
4. **`output_generator.py` pure-rendering refactor:** Approved, gated behind B1–B2 landing first.
   **Not started yet** — still pending Section B.

## Staff contract category — RESOLVED (2026-08-13)

Previously every one of the 56 active staff had a blank category, so
`config.get_normative_split()` returned `None` for everyone and every "actual % vs target %"
comparison silently degraded to "no data" — in both the department report and the new individual
reports. Now fixed.

**Source of truth:** `data/CS Data Collection on ART Performance 2026 - MASTER Overall Data
Capture.csv`, column B, which explicitly labels 64 staff as `ART` or `T&S`. Loaded by
`_load_art_ts_categories()` in `data_loader.py`.

Resolution order (in `_resolve_category_from_data()`):
1. ART Performance data capture sheet (authoritative)
2. `Part time.csv`'s Staff Category column
3. `data/staff_category_lookup.json` — previously-saved answers
4. Ask the user interactively (`--interactive`), then persist the answer to (3)

**Result: 47 ART, 9 T&S, 0 unresolved** across the active roster.

Supporting fixes made along the way:
- `pt_info` lookup in `data_loader.py` used a raw-name-only match instead of the canonical-name
  fallback the other three per-staff sources use — now uses the shared `_find_data()` helper.
- Added `"Steven Dai"` alias to `staff_name_lookup.json` (the ART sheet lists "Dai, Steven",
  which matched no existing alias for Steven Xiaotian Dai).
- One-off spelling correction for a typo in the source sheet ("Banerjee, Soumua" → Soumya),
  handled explicitly in `_ART_TS_NAME_CORRECTIONS` rather than by fuzzy matching.

### New: interactive prompting for staff whose category can't be deduced

Per your request, when a new name appears that isn't covered by any data source, the loader now
asks rather than silently defaulting:

```
Cannot determine contract category for 'Jane Doe'
(not found in the ART Performance sheet or Part time.csv).
Category? [1] ART  [2] T and S  [Enter to skip]:
```

- Runs only under `python main.py --interactive`. Non-interactive runs (including
  `generate_baseline.py` / `check_against_baseline.py`, both updated) leave it unresolved rather
  than blocking or guessing.
- Answers persist to `data/staff_category_lookup.json`, so you're asked once per person, ever.
- Deliberately asks **only about active staff who made the final roster**. An earlier version
  asked during roster construction and prompted 30 times, including historical names that never
  appear in a report; the resolution pass now runs after filtering, so it asks exactly as many
  times as there are genuinely-unresolved people (was 6, now 0).
- Skipping (pressing Enter) is safe — that person shows "no target available" and is re-asked on
  the next interactive run.

The six staff not covered by any sheet were resolved by asking you directly: Phoebe → T&S; Fang
Yan, Felix Ulrich-Oltean, James Stovold, Pourya Shamsolmoali, Robbert Jongeling → ART.

## Already verified as non-issues (no action needed)

- PhD supervision double-counting, teaching-breakdown-aggregation-missing (both claimed by
  `architecture_improvements_v2.md`) — checked live, both already correct.
- Most of `BUGS_AND_FIXES.md` (archived doc, 5/7 bugs already marked FIXED, including the regex-
  parsing concern — `output_generator.py` has zero `re.search`/`re.match` calls now).
- Most of `DISCREPANCIES.md`'s doc-text fixes — already incorporated into `Work Allocation
  Model.docx` (1,642h nominal hours, project setting under Supervision, 7.5× multiplier
  documented in Table 5).

---

## Section A — DONE

| # | Item | Status |
|---|------|--------|
| A1 | Add `ECR representative` / `ART staff representative` to `workload_parameters.yaml` (0%) + `_WAW_ROLE_MAPPING` | **Done.** Verified: Joe Cutting's admin breakdown now correctly shows `ECR representative: 0.0` instead of being unmapped. |
| A2 | Baseline teaching allowance | **Done (2026-08-13)** — see "A2 resolved" below. There is no baseline teaching; the 30h minimum has been removed from code and spec. |
| A3 | Flat 2h/week lecture-hours regardless of credits | **Done (2026-08-13)** — ruled correct; dead `contact_hours` field removed and the assumption documented. See "A3 resolved" below. |
| A4 | `--validate-only` CLI mode | **Done.** `python main.py --validate-only` runs load → calculate → validate and stops before output generation. Verified working. |

Verified: full pipeline re-run, tests pass (same 4 pre-existing failures), baseline matches.

### A2 resolved — there is no baseline teaching

**Ruling (Iain, 2026-08-13):** "There is no baseline teaching so if you are not associated with a
module then 0 hours. You still get the department baseline and professional development."

The 30h minimum admin teaching load has been removed end-to-end:

| Where | Change |
|---|---|
| `workload_calculator.py` | Removed the block that assigned `MIN_ADMIN_TEACHING_HOURS` to staff with no module teaching, plus the two downstream `minimum_admin_load` branches. |
| `config.py` | Removed `MIN_ADMIN_TEACHING_HOURS`. |
| `params/workload_parameters.yaml` | Removed `min_admin_teaching: 30`, replaced with a comment stating the rule explicitly so it can't be silently reintroduced. |
| `output_generator.py`, `new_individual_reports.py` | Removed the "Minimum Admin Teaching Load" line from both report renderers. |
| `Work Allocation Model.docx` | Removed the "Minimum administrative teaching load — 30" row from the baselines table; removed "minimum admin teaching" from the FTE-scaling list; **added an explicit statement of the rule**, which was A2's original problem (the model was never written down). |

**Impact: exactly one person, exactly as intended.** Iain Bate was the only staff member receiving
it. Teaching 30h → 0h, total 2,435.6h → 2,405.6h, with engagement (100h) and personal development
(75h) retained under admin. The B1 calculation baseline confirmed the diff touched nothing else:

```
Iain Bate.teaching_hours: expected 30, got 0.0
Iain Bate.total_hours:    expected 2435.6, got 2405.6
Iain Bate.teaching_breakdown: minimum_admin_load removed
```

This was the first real use of the B1/B2 safety net built earlier the same day, and it did its
job: three tests failed, the diff named the exact fields, and re-baselining was a reviewed
decision rather than a blind re-run.

**Correction to an earlier version of this plan:** it claimed the code applies a
`SERVICE_POINTS_DEFAULT = 175h` constant. That was taken from `DISCREPANCIES.md` without
verifying against the code — **no such constant exists anywhere** in `config.py`,
`workload_calculator.py`, or the YAML. The only trace is a comment noting that engagement (100h) +
personal development (75h) = 175h, and another reading "Admin hours already include service_points
(engagement + personal_dev)".

**Still open (small):** the docx baselines table still lists *"Service points (committee work) —
175"* as a separate row, alongside Engagement 100 and Personal development 75. Since the code
treats "service points" as the collective name for those same two baselines (175 = 100 + 75), the
table as written implies an admin staff member gets 350h of baselines when the model gives 175h.
Worth either deleting that row or rewording it to make clear it's the total of the two above — but
I've left it alone rather than guess, since it's a separate question from the teaching ruling.

### A3 explained — every module gets identical lecture hours regardless of size

`_calculate_lecture_hours_and_multipliers()` computes lecture time as:

```python
lecture_hours = DEFAULT_LECURE_HOURS_PER_WEEK * contact_weeks   # 2.0 × 11 = 22h, always
```

This value never varies by module. Concrete evidence — **GPIG is a 40-credit module**, double
every other module in the dataset (the only two credit values present are 20 and 40), yet its
report reads:

```
GPIG Module - 1 lecture (2h) per week split between two lecturers
[COM00138M] Delivery (Lectures): 22.0h contact @ 2 teachers = 11.0 each × 2.5x = 27.5h
```

— exactly the same 22.0h a 20-credit module gets.

Meanwhile `ModuleData.contact_hours` **is** computed from credits during loading
(`credits × DEFAULT_CONTACT_HOURS_PER_CREDIT`, which would give GPIG 40h) and is then **never
read anywhere** in the calculator or output code. Confirmed dead: `grep` for `.contact_hours`
excluding `practical_contact_hours` returns no consumers. So the codebase contains a
credit-proportional contact-hours figure sitting unused next to a flat rate that overrides it.

Note the docx frames all teaching multipliers as "hours per hour of contact" (Table 5) — i.e. the
model expects *actual contact hours* as its input, with the multiplier converting contact time to
workload. It doesn't specify how many contact hours a given module has; that's meant to come from
data. The flat 2h/week is the code substituting a constant for that data.

**Ruling (Iain, 2026-08-13): flat 2h/week is correct.** A module's extra credits reflect project
and independent-study time, not extra lecture contact. Actions taken:

- Removed `ModuleData.contact_hours` entirely — the field, its assignment in `data_loader.py`, its
  now-orphaned `validatecontacthours()` validator, and 25 constructor arguments across the two
  test files. It computed a credit-derived number that nothing consumed, which had already misled
  one unit test into asserting the wrong hours (see Test suite health).
- Documented the rule in `Work Allocation Model.docx` §2: lecture contact is 2h/week over 11 weeks
  (22h) for every module regardless of credit weighting, with the reasoning stated.

No hours changed — verified via calculation baseline and the full 61-test suite.

---

## Section B — Testing & architecture foundation (B1, B2, B12 DONE)

| # | Item | Status |
|---|------|--------|
| B1 | Structured JSON calculation baseline | **Done.** `calculation_baseline.py` + `main.py --export-baseline` writes `baseline/expected_results.json` (56 staff, numbers only — no wording). `test_calculation_baseline.py` asserts against it (7 tests). |
| B2 | Format-only HTML regression tests | **Done.** `test_format_baseline.py` (7 tests) — whitespace- and date-normalized comparison of all 56 individual reports + the department report, plus structural checks and a dangling-operator guard. Also covers B7. |
| B3 | Unit test suite for calculation logic | **Done** — B1 invariants + `test_invariants.py` (11 property tests) + the pre-existing `test_workload_calculator.py`. |
| B4 | Integration test suite for full pipeline | **Done** — `test_integration.py` (19 tests): load → calculate → generate, artifact checks, Excel and chart validation. |
| B5 | Validation pipeline wired into `main.py` | **Already done** (pre-existing) — `main.py` calls `run_validation_pipeline(results)` and exits on failure. |
| B6 | Unit tests: data loader & schema | **Done** — `test_data_loader.py` (29 tests). Also closed a real validation gap; see below. |
| B7 | Integration test: all artifacts produced and non-empty | **Done** — in both `test_format_baseline.py` and `test_integration.py`. |
| B8 | Integration test: Excel formula & chart reference validation | **Done** — `TestExcelOutput` in `test_integration.py`: no `#REF!`/`#VALUE!` cells, formulas reference real ranges, chart category axes resolve. |
| B9 | Property-based invariant testing (Hypothesis) | **Done** — `test_invariants.py`, 11 property tests. The "blocker" was stale; see below. |
| B10 | **`output_generator.py` pure-rendering refactor** (approved, gated) | **Done** — see below. |
| B11 | Visual regression: matplotlib chart artifact checks | **Done** — `TestChartArtifacts` in `test_integration.py`: valid PNG magic bytes, size floor, height scaling with roster size (catches clipped charts), headless backend. |
| B12 | Dead-code cleanup | **Done** — see below. |

**Section B is complete.** B9's "blocker" turned out to be stale (see below).

### B6 — a real validation gap found and closed

While writing the data-loader tests, `validate_module_data()` turned out never to check module
codes at all. Codes are the join key for student numbers, assessment counts, practical data and
previous-year lecturer lookups — so a module with a missing or placeholder code silently falls
back to defaults instead of real data. Two live modules are affected:

```
FOAM      codes=('<new for one year>',)   -> silently using DEFAULT_STUDENT_COUNT (100)
Projects  codes=('n/a',)                  -> silently using DEFAULT_STUDENT_COUNT (100)
```

That is exactly the "no guessed data" rule being broken quietly. `validate_module_data()` now
emits a WARNING naming the placeholder codes. **Worth a look:** both modules' student numbers are
currently fabricated defaults rather than real counts.

### B10 — `output_generator.py` is now a pure rendering layer (2026-08-13)

The regex parsing named in `CLAUDE.md` was already gone, but the renderer was still
**reverse-engineering numbers by dividing displayed totals** — recovering teacher counts from
`total_lecture_hours / lecture_contact_hours`, and the applied multiplier from
`this_teacher_hours / base_per_teacher`. Fragile (it inferred "new lecturer" from
`multiplier >= 4.5`) and a direct breach of the calculator-owns-the-numbers rule.

Fixed by emitting the values from the calculator and reading them in the renderer:

| New structured field | Replaces renderer arithmetic |
|---|---|
| `delivery_structured.teacher_count` | `round(total_lecture_hours / lecture_contact_hours)` |
| `delivery_structured.base_per_teacher` | `total_lecture_hours / teacher_count` |
| `delivery_structured.multiplier` / `.lecturer_type` | inferring the rate from an hours ratio, then thresholding at 4.5 |
| `delivery_structured.lectures_per_week` | `round(total_lecture_hours / (weeks * 2))` |
| `practicals_structured.applied_rate` | `practicals_per_module / base_per_teacher` |
| `practicals_structured.first_session_total` / `.repeat_total` | rate × hours × weeks, recomputed at render time |
| `practicals_structured.sessions_per_teacher` | `total / n_teachers / (contact_hrs * week_count)` |

Also removed the dead `format_teaching_section()` wrapper (139 lines) — never called, and it
carried a stale duplicate of the module-header logic with a hardcoded "(each 2h)".

**Verification — this is what the gate was for.** `test_format_baseline.py` passed *unchanged*
throughout, i.e. zero visible output difference. On the calculation side the change was provably
additive: a key-by-key walk of every staff member's `teaching_module_breakdowns` found
**0 existing values changed or removed** and exactly 6 new keys added. `CLAUDE.md`'s "Known
Violations" section has been updated to record that none remain.

### B9 — the blocker was stale

B9 was parked because the test-strategy doc said it needed `_calculate_teaching_workload` split
into named helpers, and `CLAUDE.md` describes that function as **~880 lines** and off-limits.
Measured with `ast`, it is **219 lines** and the decomposition already exists — the exact helpers
the doc wanted (`_calculate_lecture_hours_and_multipliers`,
`_calculate_practical_hours_and_breakdown`) are present, as are the `ModuleData` fields it assumed
missing. No refactor was required; the approved decomposition work was already done.

`test_invariants.py` adds 11 Hypothesis properties over those helpers and the full pipeline:
total = teaching + research + admin; no negative categories; per-teacher practical hours summing
exactly to the module total ("group distribution neutrality"); adding staff never increasing an
individual's share; nominal hours monotonic in FTE; marking monotonic in student count; every
applied multiplier being a configured value; and `repeat_hours` staying rate-free.

Both new suites were mutation-tested: pre-applying `REPETITION_MULTIPLIER` into `repeat_hours`,
and perturbing `total_hours`, each produced exactly the expected failure.

**Note for `CLAUDE.md`:** its "Function Size Hotspots" table is out of date — it lists
`_calculate_teaching_workload` at ~880 lines and `generate_per_staff_reports` /
`format_teaching_section` at ~574. Current largest is `calculate_workload` at 400 lines; the
`format_teaching_section` entry refers to a function that no longer exists.

### B12 — dead code removed (2026-08-13)

- **`_create_boxplot()` (73 lines)** — defined but never called anywhere; `generate_boxplots()` is
  the live path and already draws category-aware expected lines per staff member. This dead
  function is also the one the old planning docs described as having the "expected line never
  plotted / flat normative split" bugs, which is why those bugs never actually manifested in the
  charts. Removed, along with an orphaned module-level docstring that had been left floating
  between the two functions (a no-op string expression; `generate_boxplots()` has its own).
- **`INDIVIDUAL_DIR` / `DEPARTMENT_DIR`** — module-level path constants in `output_generator.py`
  that were only ever *assigned* (including being monkey-patched by both baseline scripts) and
  **never read by anything**. Report subdirectories are derived from the `output_dir` argument
  instead. These were an active trap: someone redirecting output by patching `INDIVIDUAL_DIR`
  would see no effect. Removed from all three files and replaced with a comment stating where
  paths actually come from.

Verified after cleanup: 61/61 tests pass, full pipeline runs, baseline regenerates and matches,
charts still produced.

### Nested `output/Individual Reports/Individual Reports/` — explained and removed

A stale duplicate set of 56 reports dated 12 Aug 11:36, one directory level too deep. Cause: not
the current code — both report-writing functions correctly do `os.path.join(output_dir,
"Individual Reports")` where `output_dir` is the *base* directory, and the same was true at that
commit. It was produced by a one-off run that passed an already-nested path as `--output-dir`
(e.g. `--output-dir "output/Individual Reports"`). Every file in it was superseded by the current
outer set, and `output/` is gitignored so nothing was tracked. Deleted, then confirmed a fresh
`python main.py` recreates only the correct two directories.

---

## Section C — Individual Report changes — DONE

Built as `scripts/new_individual_reports.py`, a wholly separate module that does **not** modify
`output_generator.py`'s individual-report code at all (only one small, backward-compatible
optional parameter was added to `_format_module_practicals_section` for C7 — default value
reproduces the exact existing behaviour). Existing `Individual Reports/` output is untouched:
verified byte-identical to baseline after this work.

Reports are written to **`output/New Individual Reports/`**, one per staff member, generated
automatically every time you run `python main.py` (added as one extra line in `main.py`,
alongside the existing `generate_all_outputs()` call — doesn't touch or gate it).

| # | Proposal | Flag in `NEW_REPORT_FEATURES` | Status |
|---|----------|-------------------------------|--------|
| C1 | Computed headline summary sentence | `headline_summary` | Built. Degrades gracefully to just the raw over/under % (no "mostly from X" clause) when category is unmapped — currently true for everyone, see the data-gap note above. |
| C2 | Normative-split comparison table | `normative_comparison` | Built. Shows actual-hours-only with an explicit "no normative split available" note when unmapped (currently everyone). |
| C3 | Header block: total hours + delta vs nominal | `header_delta` | Built. |
| C4 | Fix hardcoded footer date | `fixed_footer_date` | Built (`datetime.now()`). |
| C5 | Positive confirmation when no data-quality issues | `positive_confirmation` | Built. |
| C6 | Sort by hours descending | `sort_by_hours` | Built for teaching (modules ordered by their subtotal, largest first, instead of alphabetically). Research/admin sections were **already** sorting by value in the existing report code — reused as-is. |
| C7 | Standardized wording ("First session" used consistently) | `standardized_wording` | Built — the one small shared parameter change mentioned above. |

**Decision (2026-08-13): keep all seven.** All flags remain `True`.

**To drop one later:** edit the `NEW_REPORT_FEATURES` dict at the top of
`scripts/new_individual_reports.py` (each flag is independent — turning one off makes that
specific piece match the current report's behaviour, not blank/broken) and re-run
`python main.py`. With every flag off, the new report matches the current report's content
almost exactly (verified — only trivial whitespace/comment differences remain).

Now that staff categories resolve properly, C1 and C2 produce real output rather than degrading.
Example (Christopher Crispin-Bailey, ART):

> Total workload is 1,157h against a nominal 1,642h for 1.0 FTE — 29.6% under, mostly from research.

| Category | Actual | Target | Flag |
|---|---|---|---|
| Teaching | 45.8% | 40.0% | Moderate |
| Research | 14.2% | 40.0% | High |
| Admin | 40.0% | 20.0% | High |

Next step for this section is **E2** (extract the shared normative-comparison/deviation-threshold
logic so the individual and department reports use one implementation, not two).

---

## Section D — Departmental view improvements — mostly ALREADY BUILT (discovered, not built by me)

**Correction to the original version of this plan:** I had assumed this section needed building
from scratch, based on the planning docs describing a "before" state. While building Section C I
actually inspected `generate_html_report()` and `generate_boxplots()` directly for the first time
this session and found most of this already exists in the live code — presumably from earlier
work that predates this conversation, without the planning docs being updated to match.

| # | Item | Status |
|---|------|--------|
| D-prereq | `category` field on `WorkloadResult` + `config.get_normative_split()` | **Already built.** (Its data source is broken for the current roster — see the data-gap note above — but the plumbing itself exists and works correctly when category data is present.) |
| D1 | "Needs attention" triage section | **Already built.** Live in `workload_report.html` — staff >10% off nominal, plus anyone with assumptions/missing-data, sorted by deviation size. |
| D2 | Department summary block | **Already built.** Headcount, total FTE, total hours, average hours, nominal total, per-category splits with normative-comparison line. |
| D3 | Fix boxplot charts (unplotted expected line, flat split) | **Already built** — `generate_boxplots()` already draws category-aware expected lines per staff member. The `_create_boxplot()` function the old bug report was describing is dead code, never called (see B12 above). |
| D4 | Replace truncated detail columns | **Already built.** The staff table shows FTE/total/teaching/research/admin hours plus a normative-deviation indicator (On target / Moderate / High), not truncated free text. |
| D5 | Link staff names to individual reports | **Already built.** Table rows link to `Individual Reports/{name}_workload.html`. |
| D6 | Group/sort by contract category | **Already built.** Table is sorted by category then name. |
| D7 | Unit tests for department summary stats + needs-attention filter | **Done** — `test_reporting_helpers.py` (41 tests), testing the extracted helpers independently of HTML generation. |

**Section D is complete.**

---

## Section E — Integration & final pass

| # | Item | Status |
|---|------|--------|
| E1 | `generate_per_staff_reports()` runs before `generate_html_report()` | **Already correct** — confirmed in `generate_all_outputs()`. |
| E2 | Extract shared reporting-helper logic between department report and individual reports | **Done** — new `reporting_helpers.py`; see below. |
| E3 | Run full test suite together | **Done** — 161 tests, all passing. |
| E4 | Full-run visual sanity check, incl. graceful unmapped-category handling | **Done** — full pipeline runs clean; unmapped categories degrade to "no comparison available" rather than crashing (asserted in `test_reporting_helpers.py`). |

### E2 — one implementation of the comparison logic, not two

The department report and the per-staff reports were independently answering the same two
questions ("how far from the contract-type target?" and "is that far enough to flag?"), each with
its own copy of the 5pp / 10pp thresholds — free to drift apart silently.

New `reporting_helpers.py` owns those definitions: `deviation_band()`, `category_deviations()`,
`nominal_variance()` / `is_over_or_under_nominal()`, `needs_attention()`, `department_summary()`
and `category_statistics()`. It contains no workload calculation — it only compares and classifies
numbers the calculator already produced. Both reports were refactored onto it, removing the
duplicate thresholds and the inline recomputation of category averages inside
`generate_html_report()`.

**Verified by mutation:** changing `DEVIATION_ON_TARGET_PP` from 5 to 99 in the shared module
moved the department report's "On target" count from 1 to 57 *and* the individual reports' from
0 to 3 — proving a single constant now drives both surfaces. `test_reporting_helpers.py` also
asserts structurally that the old per-report constants are gone rather than merely unused.

---

## Data sources and housekeeping (2026-08-13)

**Switched project/pastoral loads to `Project and Pastoral Group Loads - Loadings.csv`.** It has
identical columns and row count to the old `project_load.csv` but fresher computed values, and was
sitting unused in `data/`. Impact was one person: **Paul Cairns' project load 0.40 → 1.62**, which
ceilings to 2 projects instead of 1 — exactly +16h teaching (one UG project), total 1,610.1h →
1,626.1h. Nobody else changed; pastoral loads were unaffected because they come from
`pastoral_load.csv` in preference. `project_load.csv` then deleted as superseded.

**CSV audit.** Every file in `data/` was checked against actual code usage:

| File | Status |
|---|---|
| `project_load.csv` | **Deleted** — superseded by Loadings.csv (recoverable from git). |
| `WTW 2025-6.csv` | **Kept — do not delete.** A filename grep shows it as unused, but it is loaded by `glob("WTW *.csv")` in `load_previous_wtw()` and supplies **52 known lecturers / 46 per-module entries** for new-lecturer detection. Deleting it would silently flip every returning lecturer to the 5× new-lecturer rate and massively inflate teaching hours. |
| `Part time.csv` | **Kept, but currently inert.** None of its 4 people (Carrington, Pumfrey, Sujan, Wilson) are in the active roster, and every roster member is 1.0 FTE — so it contributes nothing today. It is still the *mechanism* for part-time FTE, so deleting it would silently give any future part-time member 1.0 FTE. Flagged rather than removed. |
| All others | In active use. |

**Chris Smith** (left the department) — confirmed no workload report is produced for him: he is
`Active=FALSE` and absent from this year's WTW, so the roster filter already excludes him.

**Other housekeeping:** the `'Chris'` alias now resolves to Christopher Crispin-Bailey (it
previously resolved to the inactive Chris Smith, printing a warning on every run and risking a
silent misattribution if a bare "Chris" ever appeared); the empty vestigial
`baseline/Department Summary/` directory and its `mkdir` calls removed; the six superseded planning
docs moved to `docs/archive/`.

## Test suite health

**61/61 passing.** For most of this work the suite sat at "43 passed, 4 failed", with the four
failures carried as pre-existing. They have now been diagnosed and fixed — all four were **stale
tests, not code bugs**; the code had changed semantics and the assertions were never updated:

| Test | Why it failed | Fix |
|---|---|---|
| `test_phd_supervision_hours` | Asserted a flat `breakdown["phd_supervision"]` key. The code deliberately stores a nested `phd_students` dict instead — having both is what caused the historical double-counting bug. The test's *total* assertion passed. | Assert the nested per-type values, that they sum to the total, and that the flat key is absent. |
| `test_new_lecturer_detection_with_reordered_module_codes` | Hard-coded thresholds (`>= 80h`) derived from `contact_hours (40) × 2.5 = 100h`. The calculator uses a flat 2h/week, giving 55h. **This is direct evidence for A3** — the test documents that someone once expected `contact_hours` to drive lecture hours. | Derive expectations from the model constants, and assert it got the standard rate and *not* the new-lecturer rate. Mutation-tested: breaking the per-module lookup makes it fail. |
| `test_practical_display_matches_calculation_parallel_groups` | Expected `repeat_hours` to include rates. The code stores base hours with rates applied at render time (its comment says so). | Assert the documented base-hours semantics, plus that applying the rate reproduces the displayed total. |
| `test_display_math_is_correct_for_parallel_groups` | Same `repeat_hours` semantics mismatch. | Same. |

Care was taken not to "fix" these by deleting assertions — each test's original intent is
preserved, and the new-lecturer one was mutation-tested to confirm it still catches the
regression it was written for.

## What's left, in order

**All planned work is complete.** Sections A, B, C, D and E are done; every query has been
resolved. Test suite: **161 passing, 0 failing** (from 43 passing / 4 failing at the start).

### Test suite composition

| File | Tests | Covers |
|---|---|---|
| `test_workload_calculator.py` | 30 | Pre-existing calculation unit tests |
| `test_reporting_helpers.py` | 41 | Shared comparison logic, department stats, needs-attention (D7, E2) |
| `test_data_loader.py` | 29 | Name normalization, H/M merging, category resolution, validation (B6) |
| `test_integration.py` | 19 | Full pipeline, artifacts, Excel, charts (B4, B8, B11) |
| `test_invariants.py` | 11 | Hypothesis property tests (B9) |
| `test_calculation_baseline.py` | 7 | Calculation regression vs JSON baseline (B1) |
| `test_format_baseline.py` | 7 | Display-format regression vs HTML baseline (B2) |
| `test_practical_display.py` | 5 | Practical-session display semantics |

### Open items for you (none blocking)

1. **`FOAM` and `Projects` have placeholder module codes** and are silently using the default
   student count of 100 rather than real numbers (newly surfaced by the B6 validation check).
2. **`Part time.csv` is inert** — none of its four people are on the active roster and everyone is
   1.0 FTE. Retained because it is the part-time FTE mechanism; deleting it would silently give a
   future part-time member 1.0 FTE.
3. **Five staff were defaulted to ART** — Fang Yan, Felix Ulrich-Oltean, James Stovold, Pourya
   Shamsolmoali, Robbert Jongeling — and never explicitly confirmed. They sit in
   `data/staff_category_lookup.json`; a one-line edit changes any of them.
4. **Repo hygiene:** the auto-commit hook is producing a commit per tool call (~180 on this
   branch, all titled "chore: auto-commit before tool use"). Worth squashing before pushing.

**Decided and done:** staff contract category resolved (47 ART / 9 T&S / 0 unresolved) with
interactive prompting for future new names; all of C1–C7 kept and live in
`output/New Individual Reports/`; B1, B2, B7, B12 complete; test suite green.

---

## Once this is reviewed

Archive the six original planning docs (`architecture_improvements.md`,
`architecture_improvements_v2.md`, `academic_workload_test_strategy.md`, `BUGS_AND_FIXES.md`,
`DISCREPANCIES.md`, `WORKLOAD_OUTPUT_REDESIGN_PROMPTS.md`) — this file supersedes them, and two
rounds of "the docs described a state the code had already moved past" is a good sign they should
stop being treated as current.
