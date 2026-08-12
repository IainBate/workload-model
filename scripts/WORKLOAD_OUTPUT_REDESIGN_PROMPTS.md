# Workload Model — Output Redesign Prompts

Four prompts, meant to be fed to Claude one at a time, in order. Each is
self-contained (context + requirements + verification) so it can be a
separate session or PR. Don't start Prompt 2 or 3 until Prompt 0 is done and
tested — both later prompts depend on it.

All four assume the current codebase: `data_loader.py`, `workload_calculator.py`,
`output_generator.py`, `config.py`, `test_workload_calculator.py`.

---

## Prompt 0 — Carry contract category through to WorkloadResult

```
In this workload calculator, StaffData.category holds each staff member's
contract type (values seen in real data include "T and S" and "ART"), but
WorkloadResult — the object output_generator.py actually works with — has no
category field at all. config.CONTRACT_NORMATIVE_DIVISIONS holds the target
teaching/research/admin split per contract type, but its keys ("TR_staff",
"TS_staff", "TS_associate") don't match the free-text category strings
actually stored on StaffData, so there's no working link between a person and
their target split today.

Please:

1. Add a `category: str` field to WorkloadResult (data_loader.py) and set it
   from the corresponding StaffData when workload_calculator.calculate_workload
   builds each result.
2. Add a small mapping function (e.g. `config.normative_key_for_category(category: str) -> Optional[str]`)
   that translates the real category strings found in the data into the keys
   used by CONTRACT_NORMATIVE_DIVISIONS. Look at what values StaffData.category
   actually takes across the data loading code (data_loader.py) rather than
   guessing — I've seen "T and S" and "ART" in the code, there may be others.
   If a category doesn't have an obvious mapping, the function should return
   None rather than silently guessing, and callers should treat that as "no
   normative comparison available for this person" rather than defaulting to
   one category's figures.
3. Add a helper, e.g. `config.get_normative_split(category: str) -> Optional[Dict[str, float]]`,
   that combines the two steps above and returns the {"teaching_hours":...,
   "research_hours":..., "admin_hours":...} dict for a category, or None.

Add tests in test_workload_calculator.py covering: a known category resolves
to the right split; an unrecognised category returns None rather than a
default; WorkloadResult.category is populated correctly by
calculate_workload() for a staff fixture.

Run the full test suite when done and confirm it's green before stopping.
```

---

## Prompt 1 — Redesign the individual (per-staff) report

```
Context: generate_per_staff_reports() in output_generator.py builds one HTML
file per staff member. The visual design (colour-coded cards per category) is
good and should be kept, but the report currently only shows raw hours — it
never tells the person whether their split is expected for their contract
type, and the total is just a number sitting next to nominal hours rather
than a stated comparison. This depends on Prompt 0 (WorkloadResult.category
and config.get_normative_split) already being done.

Please make these changes to generate_per_staff_reports (and
format_detail_section / format_teaching_section as needed):

1. Headline summary line at the top of the report, above the existing
   staff-header block: one sentence, generated from the numbers, e.g.
   "Total workload is 1,847h against a nominal 1,642h for 1.0 FTE — 12.5%
   over, mostly from teaching." Compute the "mostly from X" part by comparing
   each category's share of the over/under to what get_normative_split()
   would predict, don't hand-write a category. If get_normative_split()
   returns None for this person's category, omit the comparison clause and
   just state the raw total vs nominal.

2. A normative-split comparison, shown as a compact table or small inline SVG
   bar chart (no new dependencies — matplotlib is overkill for a single
   person's 3-way split; hand-built SVG is fine) showing, per category
   (teaching/research/admin): this person's % of total, and the target % from
   get_normative_split() for their category. Visually flag (colour/icon) any
   category more than ~10 percentage points off target. If no normative split
   is available for their category, show their actual split only, without a
   fabricated target.

3. In the staff-header block, replace the current side-by-side "FTE / Nominal
   Hours" meta items with FTE, nominal hours, AND total hours, and show the
   delta (+/- hours and %) between total and nominal directly, not left for
   the reader to subtract.

4. Fix the hardcoded footer date. It currently reads:
   `Generated on 2026-07-14 for academic year {year_data.year_label}`
   — a literal string, not computed. Use the actual generation timestamp
   (e.g. datetime.now().strftime(...)).

5. When r.assumptions and r.missing_data are both empty, show a small
   positive confirmation (e.g. "No data-quality issues flagged for this
   report") instead of just omitting both boxes silently — so an absent box
   reads as "checked, nothing found" rather than looking unfinished.

6. Within each category's detail list (format_detail_section /
   format_teaching_section), sort items by hours descending, so the biggest
   time contributors are visible first without the reader scanning
   everything.

Keep the existing card layout, colour scheme, and the "Calculation Breakdown"
section as-is — this is additive, not a rewrite of the whole template.

Verification: generate a report for a couple of the staff fixtures already
used in test_workload_calculator.py (or add new ones — one T&R-heavy,
one clearly over nominal) and confirm by inspection that the headline,
delta, and normative comparison all show sensible values. Add a unit test
for the headline-generation logic (the sentence-building function) separate
from the HTML string it's embedded in, so it's testable without parsing HTML.
```

---

## Prompt 2 — Build a consolidated department manager report

```
Context: generate_html_report() in output_generator.py currently produces one
HTML page with two boxplot chart images and a single flat table (name, FTE,
totals, and three detail columns truncated to 80 characters with a hover
tooltip). It has no summary statistics, doesn't surface which staff have
assumptions/missing data flagged (that data exists on each WorkloadResult but
never reaches this report), and doesn't compare anyone against their
contract-type's normative split. It also has zero connection to the
per-staff reports generated separately by generate_per_staff_reports() — a
manager reading this can't get from a row to that person's detail page.

This depends on Prompt 0 (WorkloadResult.category, config.get_normative_split)
and benefits from Prompt 1 already being done (so per-staff report filenames
and their content are stable to link to).

Rework generate_html_report() into a genuine department dashboard:

1. Summary block at the top, above the existing charts: total headcount,
   total FTE, total hours committed, and average teaching/research/admin
   hours per FTE — plus one generated sentence comparing the department-wide
   average split against the overall normative target(s) in play (e.g. "T&R
   staff are collectively running N points above target on teaching").
   Compute this, don't hand-write it.

2. A "needs attention" section, before the full table: list staff whose
   total_hours is more than ~10% above or below their nominal_hours, and
   separately list anyone with non-empty assumptions or missing_data —
   pulling the actual message strings, not just a count. This is the single
   most useful addition for a manager triaging where to look first, so give
   it real visual prominence, not a footnote.

3. Replace the current truncated detail-string columns in the main table with:
   FTE, total, teaching/research/admin hours, and — for each category — a
   compact indicator of how far that person is from their normative target
   for their contract type (using config.get_normative_split(); if it
   returns None for someone, show their category as unmapped rather than
   guessing). Drop the ellipsis-truncated free-text detail columns entirely —
   that information belongs on the per-staff report, not crammed into a
   table cell.

4. Make each row's name a link to that person's file under
   `Staff Reports/{safe_name}_workload_report.html` (match the filename
   sanitisation already used in generate_per_staff_reports — reuse that
   function rather than reimplementing it) so the manager can click through
   for the full breakdown.

5. Keep the two existing boxplot images, but note in a comment that they
   currently have two known issues to fix as part of this work if not
   already fixed: the `expected` line computed in _create_boxplot is never
   actually plotted, and both boxplot functions currently compare every
   staff member against one flat split regardless of their real category.
   Wire the boxplots to use config.get_normative_split() per person the same
   way the new table does, so the table and the charts agree with each other.

6. Group or allow sorting the main table by contract category, so patterns
   within T&R vs T&S vs other categories are visible together rather than
   staff being listed in arbitrary order.

Keep the existing visual style (card containers, colour palette) consistent
with the per-staff reports from Prompt 1, so the two feel like one system
rather than two different tools.

Verification: run against the existing test fixtures (or add 3-4 staff
fixtures spanning different categories and at least one clearly over-nominal
and one with a populated assumptions list) and confirm the "needs attention"
section actually picks up the right people. Add a unit test for the
department-summary-statistics function and the "needs attention" filter
logic, separate from the HTML generation, so both are testable without
parsing HTML output.
```

---

## Prompt 3 — Wire it into generate_all_outputs and do a final pass

```
Context: generate_all_outputs() in output_generator.py orchestrates all the
individual output functions (CSV, boxplots, Excel, department HTML report,
per-staff reports). Prompts 0-2 changed several of these; this prompt is a
final integration and consistency pass.

Please:

1. Confirm generate_all_outputs() calls things in an order where
   generate_per_staff_reports() runs before generate_html_report(), since the
   department report now links to individual report filenames.

2. Do a consistency check across the department report (Prompt 2) and the
   per-staff reports (Prompt 1): the normative-split comparison, the
   over/under-nominal framing, and the colour/threshold conventions for
   flagging deviation should use the same underlying helper functions and the
   same thresholds in both places, not two independently-tuned
   implementations. Extract shared logic into one place (e.g. a small
   reporting-helpers section) if it currently isn't.

3. Run the full test suite (`pytest test_workload_calculator.py -v`) and
   confirm everything from Prompts 0-2 is still green together, not just
   individually.

4. Generate a full run against the existing test fixtures data and visually
   sanity-check: department report loads, links to per-staff reports resolve,
   per-staff reports show sensible headline sentences and normative
   comparisons, and nobody with a None-mapped category causes a crash rather
   than a graceful "no comparison available" state.

Report back: what shared helpers you extracted (if any), and the full
pytest -v output.
```
