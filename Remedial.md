# Workload Model — Remedial Actions
Review of the updated codebase against the Architecture Refactor Plan and the
Hardcoded Logic Fixes. Overall: substantially and carefully implemented, not
superficial. This file covers what's left, evidenced by reading the code and
by actually running the test suite (37/39 pass; the 2 failures are detailed
below).

**Update:** Remedial Actions 7-10 below were found in a follow-up check of
the lecture and practical multiplier logic specifically, and are more
serious than anything above — they affect real computed hours for most
teaching staff today, not just future risk. Treat these as the priority.

---

## Status summary

| Item | Status | Evidence |
|---|---|---|
| Chris/SYS2/COM00029I debug scaffolding | **Fixed** | Zero hits outside legitimate docstring examples |
| Dead `practical_hours_total` variable | **Fixed** | Removed entirely, not just patched |
| Multi-code new-lecturer lookup | **Fixed, thoroughly** | `_get_prev_year_module_names()` checks all codes + name + H/M variant mapping |
| Iain Bate hardcoded fallback | **Fixed** | Now a role-based WAW lookup; fabricated grant replaced with real data |
| Stage threshold inconsistency (4 vs 10) | **Fixed** | Both sites now use `config.is_msc_level()` |
| Assessment setting auto/UG/new-assessment rates | **Fixed** | `test_assessment_setting_automated_marking` etc. pass |
| `--interactive` "no" answer bug | **Fixed** | `test_normalize_name_rejects_no_answer` passes |
| Missing `Any` import (P0 blocker) | **Fixed** | `test_data_loader_imports_any` passes |
| `assumptions` list population | **Fixed** | Real fixture-based test, no longer a stub |
| `DetailParser`-style string re-parsing | **Fixed** | Zero `re.search`/`.split(';')` hits left in output_generator.py |
| `_calculate_teaching_workload` decomposition | **Fixed** | 880 → 160 lines, split into named sub-functions |
| role_based_reports.py duplication | **Resolved in the live pipeline** | `generate_all_outputs` no longer calls it — see Remedial Action 5 for the loose end |
| Regression test: reordered module codes | **Missing** | See Remedial Action 1 |
| Regression test: HoD/staff not in WTW | **Missing** | See Remedial Action 1 |
| `STAGE_MSC_LEVEL` uncertainty flag | **Dropped** | See Remedial Action 2 |
| `get_normative_split()` for ART / T&S | **2 test failures** | See Remedial Action 3 |
| HoD fallback: roles beyond "Head of Department" | **Narrower than a normal staff record** | See Remedial Action 4 |
| `calculate_workload`, `load_all_data`, `_create_individual_staff_report_html`, `generate_html_report` | **Still large (330-475 lines)** | Lower priority per the original staging, not urgent |
| PNG comparison in `check_against_baseline.py` | **No pixel-level fallback** | See Remedial Action 6 |
| CLAUDE.md | **Unconfirmed** | Not part of this upload — confirm separately |

---

## Remedial Action 1 — Add the two regression tests that were specified but never written

```
Two fixes in this codebase are solid but have no regression test locking
them in, so a future change could silently reintroduce either bug with
nothing to catch it:

1. The new-lecturer detection fix in workload_calculator.py
   (_get_prev_year_module_names, used by _calculate_lecture_hours_and_multipliers
   and _calculate_practical_hours_and_breakdown) - checks all of a module's
   codes, its name, and previous-year H/M-variant mappings, not just
   module.codes[0].

2. The HoD/staff-not-in-WTW fix in data_loader.py (~line 1402 onward) - looks
   up the Head of Department role generically via WAW rather than a hardcoded
   name, and sources their FTE/grants/PhD supervision from the real data
   files rather than fabricating defaults.

Please add:

1. test_new_lecturer_detection_with_reordered_module_codes (or similar) in
   test_workload_calculator.py: a fixture module with two codes, where the
   previous year's known-lecturers data is keyed under a code that is NOT
   this year's codes[0] (e.g. this year's module.codes = ["COM00099X",
   "COM00088Y"], but known_lecturers_per_module only has an entry under
   "COM00088Y"). Assert a teacher present in that entry is correctly detected
   as NOT a new lecturer (i.e. gets the 2.5x standard rate, not 5x).

2. test_hod_not_in_wtw_uses_real_data (or similar): a fixture where a staff
   member holds the "Head of Department" role in WAW data but does not
   appear in the WTW teacher list, with real FTE/grant/PhD-supervision
   fixture data available. Assert they appear in the final staff roster with
   that real data populated - not defaults, and specifically not any
   fabricated research grant entry.

Run the full test suite afterward and confirm both new tests pass alongside
the existing 39.
```

---

## Remedial Action 2 — Restore (or resolve) the STAGE_MSC_LEVEL uncertainty flag

```
config.py's STAGE_MSC_LEVEL is defined as:

    STAGE_MSC_LEVEL: int = 4   # Master's level (stage >= 4 typically)

The word "typically" is a live signal that this threshold was never actually
confirmed against real WTW stage-code data - it was carried over unchanged
when the stage>=10 inconsistency elsewhere in the code was fixed to also use
this constant. Making the two call sites consistent was the right fix, but
the underlying question of whether 4 is really correct was supposed to be
flagged, not silently inherited.

Please do one of the two, not silently pick one:

1. If this has already been checked against real WTW stage data and 4 is
   confirmed correct: update the comment to say so plainly (drop
   "typically"), and note briefly how it was confirmed (e.g. "confirmed
   against WTW 2026-7: MSc modules are coded stage 4+").

2. If it hasn't been checked: add a comment directly on STAGE_MSC_LEVEL -
   # TODO(human): confirm this against real WTW stage codes - does 4 mean
   integrated-masters-year, and is there a separate encoding (e.g. 10+) for
   standalone MSc modules that needs its own constant? - and stop there
   rather than proceeding further on this point.

Either way, report which of the two applies so it's clear whether this is
settled or still open.
```

---

## Remedial Action 3 — Fix or verify `get_normative_split()` against the real YAML

```
Running the test suite surfaces two failures:

    FAILED test_get_normative_split_art - assert 'teaching_hours' in {}
    FAILED test_get_normative_split_t_and_s - assert None is not None

These were run against a reconstructed test workload_parameters.yaml, not
the project's real one, so this may be a test-environment artifact rather
than a live bug - but the failure points at something worth checking either
way: get_normative_split() and normative_key_for_category() in config.py
only recognise a small, specific set of key names -
CONTRACT_NORMATIVE_DIVISIONS["TS_staff_lecturer_and_above"], and sub-keys
"teaching" / "research_and_scholarship" or "scholarship" / "citizenship".
If the real workload_parameters.yaml uses different key names for any of
these, the function will silently return an empty or partial dict rather
than raising an error - the same "silent failure" pattern flagged multiple
times earlier in this project.

Please:

1. Run test_get_normative_split_art and test_get_normative_split_t_and_s
   against the project's REAL workload_parameters.yaml (not a reconstructed
   one) and confirm whether they pass. Report the actual keys present in the
   real file's contract_normative_divisions section.

2. If they fail against the real file too: fix normative_key_for_category
   and/or get_normative_split to match the real key names, and make the
   failure mode explicit if a real category can't be matched at all (e.g.
   log a warning) rather than quietly returning {}.

3. Add one integration-style test that loads the actual project YAML (not a
   fixture) and asserts get_normative_split() returns a complete, non-empty
   split for every category value actually present in the real staff roster
   - this is a stronger check than a synthetic-fixture unit test, since it
   catches exactly this class of YAML-key-drift problem.
```

---

## Remedial Action 4 — HoD fallback still only records one role

```
In data_loader.py's generalized HoD-inclusion block (~line 1453-1479), the
synthesized StaffData record sets:

    roles=tuple([hod_role])

This only ever records "Head of Department" - if the same person also holds
other roles in WAW (e.g. also chairs a committee), those would be silently
dropped for this fallback record, unlike a normal staff member found via the
regular WTW-present pipeline, whose full role list would come from WAW.

Please change this to collect ALL roles this person holds in waw_roles
(mapped through _WAW_ROLE_MAPPING), the same way a normal staff record's
roles are populated elsewhere in this file - not just the one role being
searched for. Add a test with a fixture HoD who holds a second role in WAW,
asserting both roles appear in the synthesized record.
```

---

## Remedial Action 5 — Confirm role_based_reports.py's actual status

```
generate_all_outputs() in output_generator.py no longer calls anything from
role_based_reports.py (confirmed by reading the current file), so the
duplicate-report-generation problem is resolved in the live pipeline.
However, this review can't confirm whether role_based_reports.py still
exists as an orphaned file in the repository (it wasn't part of the most
recent set of changes reviewed here).

Please confirm: if the file still exists and generate_hybrid_dashboard /
_generate_finance_report / generate_individual_reports /
generate_department_summary are genuinely unused now, delete the file
entirely rather than leaving it as a dead module someone could accidentally
import or copy from later. If anything in it is still wanted (e.g. the
finance report), that should be migrated into output_generator.py properly,
not left as a second module.
```

---

## Remedial Action 6 — Make the PNG comparison in check_against_baseline.py reliable

```
compare_files() in check_against_baseline.py currently does a raw byte
comparison for .png files and reports any difference as-is:

    if baseline_bytes != output_bytes:
        differences.append("PNG bytes differ (may be due to metadata or matplotlib changes)")

This was flagged as a risk when the harness was first specified: if
matplotlib embeds any non-deterministic metadata (timestamps, library
versions) even when the visual content is identical, this harness will
report a false-positive difference on every single run, which will quickly
train whoever's using it to ignore its PNG warnings entirely - defeating the
point of having it.

Please verify whether this is actually happening: generate the baseline,
then immediately run check_against_baseline.py against the exact same code
and data with no changes at all. If it reports PNG differences despite
nothing having changed, add a pixel-level fallback comparison (e.g. via PIL:
load both images and compare pixel arrays) instead of relying on raw bytes,
and only report a real difference when the pixel content itself differs.
```

---

## Remedial Action 7 — Lecture multiplier lookup ignores the real config values

```
_calculate_lecture_hours_and_multipliers in workload_calculator.py selects a
teacher's lecture rate via config.TEACHING_MULTIPLIERS.get(key, default)
using keys 'video', 'new_lecturer_new_content', 'new_lecturer',
'existing_lecturer_new_content', 'standard'. None of these exist in the real
YAML - the actual keys (see config.py's own derivation of TEACHING_STANDARD,
TEACHING_NEW_CONTENT, TEACHING_NEW_BOTH, etc.) are 'lecture_standard',
'lecture_new_content_or_lecturer', 'lecture_new_content_and_lecturer',
'lecture_new_video'. Every lookup therefore falls through to its hardcoded
Python default. This can be proven directly: mutate
config.TEACHING_MULTIPLIERS['lecture_new_content_or_lecturer'] at runtime and
call the function again - the result doesn't change. Today's output is only
numerically correct because the hardcoded defaults happen to match the
current YAML values; any future change to a rate in workload_parameters.yaml
would be silently ignored.

Please:

1. Fix all five lookups to use the real YAML keys (use the existing named
   constants already derived correctly in config.py - TEACHING_STANDARD,
   TEACHING_NEW_CONTENT, TEACHING_NEW_BOTH, TEACHING_NEW_VIDEO - rather than
   re-deriving dict lookups with new key strings inside this function).

2. Add a test that mutates a config value at runtime and asserts the
   function's output changes accordingly - a "does this function actually
   read from config" test, not just a "does it return the currently-correct
   number" test. This is the class of bug a normal unit test won't catch,
   since the hardcoded defaults currently agree with the real values.

3. Do the same audit on every other function that was split out of the old
   _calculate_teaching_workload during the god-function decomposition
   (_calculate_assessment_setting_hours and any others) - check each
   config.SOMETHING_DICT.get(key, default) call's key against the real dict's
   actual keys, not just against what looks plausible.
```

---

## Remedial Action 8 — First practical session's multiplier is computed but never applied

```
_calculate_practical_hours_and_breakdown in workload_calculator.py computes
and stores a "first_session_rate" in its breakdown dict (2.5 or whatever the
standard/new rate is), and this value is even used to build the display
detail string - but it is never multiplied into the actual hours total:

    first_session_total = weekly_hrs * contact_weeks                                    # no rate applied
    repeat_session_total = repeat_sessions * weekly_hrs * repeat_rate * contact_weeks    # rate correctly applied

This is true in both the parallel-groups branch (~line 261) and the
no-parallel-groups branch (~line 298 and 319, including the single-session
case). Only repeat sessions get a real multiplier; the first session of the
week is charged at raw contact hours, effectively 1x instead of 2.5x (or 5x
if it should carry the new-content-or-lecturer rate). This under-counts
practical workload for essentially everyone who teaches a practical, and
does so silently - the breakdown dict's own "first_session_rate" field
implies the multiplier was applied when it wasn't.

Please fix all three cases (parallel-groups, multi-session no-parallel-
groups, and single-session no-parallel-groups) so the relevant rate is
actually multiplied into the first session's total, not just stored
alongside it for display. Add a test asserting that changing
config.TEACHING_PROBLEM_CLASS changes the calculated first-session hours,
for the same "does this function actually use the rate it displays" reason
as Remedial Action 7.
```

---

## Remedial Action 9 — Practical hours read a module attribute that doesn't exist

```
The no-parallel-groups branch of _calculate_practical_hours_and_breakdown
reads:

    std_first_session_weekly = getattr(module, 'practical_hours_per_week', config.TEACHING_PROBLEM_CLASS)

ModuleData has no field called practical_hours_per_week - the real field is
practical_contact_hours (confirmed via the dataclass definition, and used
correctly a few lines earlier in the parallel-groups branch at ~line 245).
This getattr always falls through to the default, meaning a module's actual
practical contact hours are ignored in this branch regardless of what's in
the source data - compounding Remedial Action 8 (the default that gets used
is itself the multiplier value being mistaken for an hours figure).

Please fix the attribute name to practical_contact_hours, consistent with
the parallel-groups branch, and add a test with a module whose
practical_contact_hours is set to a distinctive, non-default value (e.g. 3.0)
confirming it's actually used rather than silently replaced by
config.TEACHING_PROBLEM_CLASS.
```

---

## Remedial Action 10 — Practical weeks uses a flat constant, not the module's actual practical weeks

```
_calculate_practical_hours_and_breakdown sets:

    contact_weeks = TEACHING_WEEKS_PER_SEMESTER

for every module, rather than deriving it from module.practical_weeks (the
per-module tuple of which weeks the practical actually runs). This directly
contradicts a documented business rule from early in this project: some
modules only run practicals in specific weeks rather than every teaching
week (the original example given was a module with practicals only in weeks
7, 8, 9, and optionally 11). Using a flat semester-wide constant instead of
the module's real practical_weeks data would overcount practical hours for
any module that doesn't run practicals every single week.

Please derive contact_weeks from len(module.practical_weeks) when that data
is populated, falling back to TEACHING_WEEKS_PER_SEMESTER only when a module
genuinely has no specific week data recorded (and consider whether that
fallback should instead be flagged as missing data rather than silently
assumed). Add a test with a module whose practical_weeks has fewer entries
than a full semester, asserting the calculated hours reflect that smaller
week count, not the full semester default.
```

---

## Remedial Action 11 — Architectural: breakdown DTOs need to carry raw facts, not just totals and labels

```
This one prompted the investigation above: a request to change a report's
first line from an opaque "26.7h @ New lecturer (5x)" to a plain description
("11 weeks of 2 hour lectures split between 3 lecturers = Xh") reportedly
took much more work than a display change should. The reason is now clear -
the breakdown dicts returned by _calculate_lecture_hours_and_multipliers and
_calculate_practical_hours_and_breakdown carry final totals and a rate
label, but not the raw components (weeks, hours-per-week before any
multiplier, number of co-teachers sharing a module) that a plain-language
sentence needs. Producing one requires either re-deriving those facts from
the original module/teacher data at display time - reintroducing the
re-derivation problem this whole refactor was meant to eliminate - or
extending the calculation layer, which is a bigger change than a display
tweak should require.

This is the Phase 3a/3b work from the architecture refactor plan not fully
realized: the breakdown structures gained more fields, but not necessarily
the right ones, and (per Remedial Actions 7-9) some of the fields present
aren't even reliably connected to the real computation.

Please extend the lecture and practical breakdown dicts to also carry the
raw components: weeks used in the calculation, raw hours-per-week (before
any multiplier), and number of co-teachers sharing the module/session. Then
apply a concrete acceptance test before considering this done: write the
exact plain-language sentence from the original request ("11 weeks of 2
hour lectures split between 3 lecturers = Xh") as a function that reads
ONLY fields already on the breakdown dict, with no access to the original
module/teacher objects and no recomputation. If that function needs
anything not already on the dict, the dict is still incomplete - add the
missing field rather than reaching back into raw data. Use this same test
as the bar for any future "just change how this is displayed" request.
```

---

## Also worth a direct answer, not a code task

Two of the fixes (new-lecturer detection, HoD fallback scope) were
specifically written to stop and get a human sign-off before being treated
as final - a staff/module diff for the first, a scope decision (role-based
vs. broader) for the second. Static review of the code can't tell whether
that conversation actually happened. If it didn't, it's worth doing before
trusting either fix's real-world output, even though the code itself looks
correct on inspection.
