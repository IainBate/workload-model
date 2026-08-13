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
| A2 | Verify baseline docs for min admin teaching hours (30h) / service points (175h) | **Awaiting your decision** — see "A2 explained" below. |
| A3 | Investigate flat 2h/week lecture-hours regardless of credits | **Awaiting your decision** — see "A3 explained" below. Confirmed a real inconsistency; needs a domain judgement before any code change. |
| A4 | `--validate-only` CLI mode | **Done.** `python main.py --validate-only` runs load → calculate → validate and stops before output generation. Verified working. |

Verified: full pipeline re-run, tests pass (same 4 pre-existing failures), baseline matches.

### A2 explained — two numbers the code applies that the spec never states

The code hardcodes two baselines, both in `workload_parameters.yaml`:

| Constant | Value | What it does |
|---|---|---|
| `MIN_ADMIN_TEACHING_HOURS` | 30h | A floor on teaching hours for HoD/admin staff who teach no modules — without it they'd show 0h teaching. |
| `SERVICE_POINTS_DEFAULT` | 175h | Committee-work allowance for the same population. |

`Work Allocation Model.docx` *names* both concepts — §2's part-time paragraph lists "minimum admin
teaching" and "service points" among the baselines that scale by FTE — but **never states the
numbers**. So nothing is calculating wrong, but there's no documented figure to audit 30h/175h
against, and no way for anyone else to check they're still right or update them from a stated
source.

**Decision needed:** either (a) add "30 hours" and "175 hours" to the docx's baselines section so
the code can be checked against it, or (b) if these are meant to be discretionary rather than
fixed departmental policy, say so explicitly in the doc — so it's clear the code is applying a
default rather than implementing a rule.

Low urgency, but it's the only remaining place where a live number has no documented origin.

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

**Decision needed:** is a flat 2h/week actually right for every module regardless of size (i.e.
GPIG genuinely has one 2-hour lecture slot a week like everything else, and its 40 credits reflect
project/independent-study time rather than extra lectures)? Or should lecture hours scale with
credits / come from a real timetable column?

- If flat is correct → the fix is to delete the unused `contact_hours` field so it stops looking
  like a live input, and note in the docx that lecture contact is assumed at 2h/week.
- If it should scale → this is a genuine calculation gap affecting every 40-credit module's
  teaching hours, and we'd need either a contact-hours column in the WTW data or an agreed
  credits→contact-hours rule.

I've deliberately not changed anything here: both options are defensible and only you know how
GPIG is actually timetabled.

---

## Section B — Testing & architecture foundation (not started)

Prerequisite work for the gated B10 refactor. Nothing here has been built yet.

| # | Item | Effort | Depends on |
|---|------|--------|------------|
| B1 | Structured JSON calculation baseline (`baseline/expected_results.json` via `--export-baseline`) | M | — |
| B2 | Format-only HTML regression tests (whitespace-normalized diff against saved baseline) | M | B1 |
| B3 | Unit test suite for calculation logic (`test_calculations.py`) | M | B1 |
| B4 | Integration test suite for full pipeline (`test_integration.py`) | M | B3 |
| B5 | Validation pipeline wired into `main.py` | — | **Already done** — confirmed live: `main.py` calls `run_validation_pipeline(results)` and exits on failure. No action needed. |
| B6 | Unit tests: data loader & schema (name normalization, module merge, input validation) | S | — |
| B7 | Integration test: all output artifacts produced and non-empty | S | B4 |
| B8 | Integration test: Excel formula & chart reference validation | S | — |
| B9 | Property-based invariant testing (Hypothesis) | M | **Blocked** — needs `_calculate_teaching_workload` decomposed into named helpers, which CLAUDE.md explicitly says not to do yet (Phase 5 target). Parked. |
| B10 | **`output_generator.py` pure-rendering refactor** (approved, gated) | L | B1 + B2 green first |
| B11 | Visual regression: matplotlib chart artifact checks | S | — |
| B12 | Dead-code cleanup: remove unused `_create_boxplot()` function (`output_generator.py` ~line 222) | S | New finding — confirmed via grep that this function is never called anywhere; `generate_boxplots()` is the actual live path and already does its own category-aware chart drawing. |

**Recommended order:** B1 → B2 → B6 → B3 → B4 → B7 → B8 → B11 → B12 → **B10** → B9 (parked).

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

**To keep some and drop others:** edit the `NEW_REPORT_FEATURES` dict at the top of
`scripts/new_individual_reports.py` (each flag is independent — turning one off makes that
specific piece match the current report's behaviour, not blank/broken) and re-run
`python main.py`. With every flag off, the new report matches the current report's content
almost exactly (verified — only trivial whitespace/comment differences remain).

Once you've decided what to keep, the natural next step is **E2** (extract the shared
normative-comparison/deviation-threshold logic so the kept pieces and the department report use
one implementation, not two) — not done yet, deliberately deferred until you've picked.

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
| D7 | Unit tests for department summary stats + needs-attention filter | **Not done** — genuinely missing, confirmed via search (no test file references `needs_attention` or `category_stats`). This is the one real remaining piece of Section D. |

**Remaining Section D work: just D7**, plus B12 (dead-code cleanup) from Section B above.

---

## Section E — Integration & final pass

| # | Item | Status |
|---|------|--------|
| E1 | `generate_per_staff_reports()` runs before `generate_html_report()` | **Already correct** — confirmed in `generate_all_outputs()`. |
| E2 | Extract shared reporting-helper logic between department report and individual reports | **Not done** — genuinely useful now that Section C exists with its own independent normative-comparison implementation; do this once you've decided which C items to keep. |
| E3 | Run full test suite together | Ongoing — done after every change so far, same 4 pre-existing failures throughout, no regressions introduced. |
| E4 | Full-run visual sanity check, incl. graceful unmapped-category handling | Done for Section A/C changes — no crashes, graceful degradation confirmed for the current all-unmapped-category state. |

---

## What's left, in order

1. **You:** point me at a data source for staff contract category (or confirm there isn't one
   yet), and weigh in on A2 (baseline hour docs) and A3 (flat lecture-hours question).
2. **You:** review `output/New Individual Reports/` and decide which of C1–C7 to keep.
3. **Me, once you're ready:** B1 → B2 (JSON baseline + format-diff safety net) → B6 → B3 → B4 →
   B7 → B8 → B11 → B12 (cleanup) → D7 → **B10** (the gated refactor) → E2 (once C is decided).

B9 stays parked (blocked on a large function decomposition not otherwise in scope).

---

## Once this is reviewed

Archive the six original planning docs (`architecture_improvements.md`,
`architecture_improvements_v2.md`, `academic_workload_test_strategy.md`, `BUGS_AND_FIXES.md`,
`DISCREPANCIES.md`, `WORKLOAD_OUTPUT_REDESIGN_PROMPTS.md`) — this file supersedes them, and two
rounds of "the docs described a state the code had already moved past" is a good sign they should
stop being treated as current.
