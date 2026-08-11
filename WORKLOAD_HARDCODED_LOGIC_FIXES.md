# Workload Model — Hardcoded Individual/Module Logic: Fixes

Three prompts, run in order. Unlike a pure refactor, Prompts 1 and 2 are
expected to change real output numbers for the specific people affected —
that's the point, they're bug fixes. The requirement is different from a
refactor's "output must be identical": here, the affected person's numbers
should change to become *correct*, and nobody else's numbers should change
at all. Each prompt asks for a before/after report on exactly who's affected,
for a human to sign off against reality — don't treat a clean test run alone
as confirmation that a data-correctness fix is right.

If the characterization/golden-master test harness from the architecture
refactor plan (`check_against_baseline.py`) already exists, use it here too:
it should show a difference for only the specifically affected people in
Prompts 1-2, and zero differences anywhere else. If it shows changes for
anyone not expected to be affected, stop and report that rather than
proceeding.

---

## Prompt 1 — Investigate and fix new-lecturer detection for multi-code modules

```
In workload_calculator.py's _calculate_teaching_workload, the lookup that
determines which teachers taught a module last year (used for new-lecturer
multiplier detection) only checks module.codes[0]:

    module_code = module.codes[0] if module.codes else None
    known_teachers_this_module = known_lecturers_per_module.get(module_code)
    if known_teachers_this_module is None:
        known_teachers_this_module = known_lecturers_per_module.get(module.name)

known_lecturers_per_module itself is built correctly and generally (in
data_loader.py's load_all_data, from load_previous_wtw() reading the actual
previous year's WTW file, keyed under ALL of that module's codes plus its
name - see around line 1042-1060). The mismatch is that building the map
uses every code, but reading it only tries the first one.

There's a live debug trail on this exact question: four places in
_calculate_teaching_workload (search for "COM00029I" or "Crispin") gate
print() statements behind checking a specific module's teachers for a
specific person - clearly left over from investigating whether this exact
lookup was producing the wrong answer for one module. One of those blocks
(around where practical_hours_total gets set) has actual calculation logic
gated behind it, not just a print - track that down as part of this work too.

Please:

1. Using the actual current and previous-year WTW data files in this
   project, reproduce the scenario: find a module with more than one code
   (module.codes has length > 1) where a teacher is present this year. Check
   whether known_lecturers_per_module correctly identifies that teacher's
   prior-year status for that module regardless of which code happens to be
   module.codes[0] this year. You can use the existing debug print output
   for this - run the pipeline with it still in place and see what it
   actually shows for a multi-code module before changing anything.

2. If you find that codes[0]-only lookup misses a match that the fuller set
   of codes would have caught (i.e. the module's codes are ordered
   differently, or a different code was primary, between the two years' WTW
   files), fix the lookup to check ALL of module.codes against
   known_lecturers_per_module (falling back to module.name only if none of
   the codes match), not just the first one.

3. Report exactly which staff/module combinations change new-lecturer status
   as a result of this fix (before vs after), across the whole current
   dataset - not just the one module this was found on. This needs a human
   who knows the actual staff to confirm the change is correct, since
   getting new-lecturer detection wrong in either direction changes real
   people's real hours. Stop after this report and wait for confirmation
   before treating the fix as final.

4. Once confirmed: track down whether practical_hours_total (the variable
   currently only computed inside one of the Chris/SYS2-gated debug blocks)
   is read anywhere else in the codebase. If it's genuinely unused, remove
   it entirely rather than leaving dead code that looks load-bearing. If it
   turns out to be used somewhere, compute it unconditionally and correctly
   - the "no parallel groups" branch further down in the same function
   already does this correctly (practical_hours_total = practical_hours_one
   * n_teachers), so mirror that approach for the parallel-groups case
   rather than inventing a new formula.

5. Remove all four Chris/COM00029I/COM00018I-specific debug print blocks
   entirely - they've served their purpose once step 1-2 are resolved with a
   general fix, and they shouldn't remain in the calculation engine either
   way.

6. Add a regression test that reproduces the GENERAL shape of the bug, not
   the specific case: a fixture module with two codes, where the previous
   year's known-lecturers data is keyed under a code that is NOT this year's
   codes[0], and a teacher who taught it last year under that code. Assert
   they're correctly detected as NOT a new lecturer. Name the test after the
   scenario (e.g. test_new_lecturer_detection_with_reordered_module_codes),
   not after any specific person or module.

Verification: full test suite green, plus the specific staff/module diff
report from step 3 confirmed by a human before the fix is considered done.
```

---

## Prompt 2 — Generalise the hardcoded HoD staff-inclusion fallback
**Includes a scope decision that needs confirmation — don't guess it.**

```
data_loader.py (~line 1290) has a fallback for including the Head of
Department in the staff roster even when they don't appear in that year's
WTW file (reasonable need - a HoD may teach nothing in a given year):

    if "Iain Bate" not in staff:
        ...
        staff["Iain Bate"] = StaffData(
            canonical_name="Iain Bate",
            fte=1.0,
            ...
            research_projects=tuple([{"project_id": "SCHEME", "title": "SCHEME", "fte": "20%"}]),
            ...
        )

This hardcodes the current HoD's literal name, and fabricates most of the
record's content with hardcoded defaults instead of loading it from the same
data sources every other staff member's record comes from - including a
research grant entry ("SCHEME", 20% FTE) that appears to be made up rather
than read from the actual grants file. If this person is ever not in WTW in
a real year, their report would currently show a fictional grant instead of
whatever they're really funded on.

Before implementing anything, I need a decision on scope - please don't pick
one and proceed:

  (a) Role-based: include whoever currently holds the "Head of Department"
      role (looked up generically, not by name) if they're missing from WTW.
  (b) Broader: include ANY active staff member from the roster/name-lookup
      data who doesn't appear in WTW that year - e.g. someone on full
      research leave or a sabbatical would hit the same gap this year's code
      only patches for the HoD.

Investigate whether case (b) can actually happen given the current data
sources (are there other roles/situations where someone might legitimately
have zero WTW presence?), and present that finding alongside the two options
so the decision can be made with real information. Stop and wait for
confirmation of which to implement.

Once confirmed, implement it:

1. Replace the hardcoded name check and fabricated defaults with a generic
   rule matching whichever scope was confirmed, pulling FTE, roles, research
   grants, PhD supervision counts, pastoral/project load, etc. from the same
   loading functions used for every other staff member - not hardcoded
   literals. Remove the fabricated "SCHEME" grant entry entirely; if the
   person genuinely has no grants on record, that should show as no grants,
   not an invented one.

2. Report the before/after for this specific staff member's own record (all
   fields, not just totals) so it can be checked against what's actually
   true for them right now.

3. Add a test with a synthetic fixture (not the real person's name) covering
   "an active staff member not present in WTW should still appear in the
   final roster with their real data loaded, not fabricated defaults."

Verification: full test suite green, plus the before/after record diff from
step 2 confirmed by a human.
```

---

## Prompt 3 — Sweep for anything else, and add a rule to prevent recurrence

```
This project has now found two confirmed cases of business logic hardcoded
to a specific person or module rather than implemented generally (see
Prompts 1-2), both traceable to a debugging or prompting session that used a
concrete real example and ended up encoding the example itself rather than
the general rule it illustrated.

1. Do one more sweep across data_loader.py, workload_calculator.py,
   output_generator.py, role_based_reports.py, config.py, main.py, and
   validation.py for the same pattern: any conditional, debug gate, or
   default-value branch keyed on a literal staff name or module code, as
   opposed to those names/codes appearing as expected content in comments,
   docstring examples, or genuine reference data (e.g. the WAW role mapping,
   or a saint_module_map keyed by real people because it IS person-specific
   data by nature - that's fine, the concern is business logic branching on
   an identity, not data tables that are inherently about individuals).
   Report anything found rather than fixing it blindly - some of these may
   need the same kind of human sign-off as Prompts 1-2, not a silent fix.

2. Add a short standing rule to CLAUDE.md (from the architecture refactor
   plan, if that's been created) or a new CODING_GUIDELINES.md if not:
   business logic must never branch on a specific staff name or module code.
   If a real example surfaces a bug during development or debugging, the fix
   belongs in the general rule, and any test added to cover it should use a
   synthetic fixture reproducing the general shape of the problem (e.g. "a
   module with reordered codes between years", "a staff member absent from
   WTW") rather than the literal person/module the bug was first noticed on.
   Debug output, if needed during investigation, should never be gated on a
   specific identity either - use a general condition (e.g. "this module has
   more than one code") or a temporary flag that gets removed before commit,
   not a name check.

Verification: no code changes expected from step 1 unless something new is
found (in which case, stop and report before fixing, same as Prompts 1-2).
Step 2 is documentation only.
```
