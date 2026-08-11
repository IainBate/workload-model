# Workload Model — Pipeline Architecture & Migration Plan

This supersedes remedial_actions.md's items 7-11: instead of patching those
bugs where they sit, this restructures the calculation engine so that class
of bug can't recur. Items 1-6 in remedial_actions.md (the hardcoded-logic
fixes, the P0 blocker, etc.) are unaffected and remain valid.

## Why this shape

Everything found in Remedial Actions 7-10 traces to the same cause: no
enforced boundary between "figure out a fact" and "use that fact," so facts
get silently re-derived, silently defaulted, or computed twice in ways that
drift apart. A pipeline of explicit stages, each with a typed output and a
validate/verify pair that runs at execution time (not just in tests), makes
that structurally hard to do by accident.

---

## Stage 0 — Parse

**Input:** file paths only — this year's WTW CSV, previous year's WTW CSV,
`staff_name_lookup.json`, `project_load.csv`, `pastoral_load.csv`,
`% FTE for CS.csv`, WAW role data, and any other source file currently read
by `data_loader.py`.

**Output:**

```python
@dataclass(frozen=True)
class RawWTWRow:
    module_name: str
    codes: Tuple[str, ...]              # split from the CSV cell, unmerged, unmatched across years
    stage: int
    credits: int
    contact_hours: float
    practicals: int
    practical_contact_hours: float
    practical_groups: int
    practical_weeks: Tuple[int, ...]    # as literally listed in the CSV, if the CSV specifies which weeks
    teachers: Tuple[str, ...]           # raw names exactly as written, NOT normalized
    lead_name: str
    student_count: int
    assessment_count: int
    marking_type: str                   # raw string from source, unvalidated
    source_file: str                    # for error messages
    source_row: int

@dataclass(frozen=True)
class RawStaffRow:
    raw_name: str
    fte_string: str                     # e.g. "100%", not yet parsed to float
    category: str

@dataclass(frozen=True)
class RawGrantRow:
    person_raw_name: str
    project_id: str
    title: str
    fte_string: str

@dataclass(frozen=True)
class RawSupervisionRow:
    person_raw_name: str
    project_load_raw: float
    pastoral_load_raw: float

@dataclass(frozen=True)
class RawRoleRow:
    role_name: str
    members_raw: Tuple[str, ...]

@dataclass(frozen=True)
class ParsedSourceData:
    year_label: str
    wtw_rows: Tuple[RawWTWRow, ...]
    staff_rows: Tuple[RawStaffRow, ...]
    grant_rows: Tuple[RawGrantRow, ...]
    supervision_rows: Tuple[RawSupervisionRow, ...]
    role_rows: Tuple[RawRoleRow, ...]
    name_lookup: Dict[str, Tuple[str, ...]]   # canonical -> aliases, straight from the JSON
    rejected_rows: Tuple[str, ...]            # human-readable reasons for any row that couldn't be parsed at all
```

Stage 0 is run twice — once for the current year's WTW file, once for the
previous year's — producing two `ParsedSourceData` objects. Everything else
(staff/grant/supervision/role data) is only meaningful for the current year.

**Constraints:**
- MUST NOT normalize, deduplicate, or match any name against anything else.
- MUST NOT merge module codes or cross-reference modules across years.
- MUST NOT compute any derived fact (no "is new," no rates, nothing).
- MUST NOT silently drop a malformed row — append it to `rejected_rows` with
  a reason instead.
- MUST NOT read or depend on any other stage's output.

---

## Stage 1 — Prepare

**Input:** one `ParsedSourceData` (Stage 0's output for a single year).

**Output:**

```python
@dataclass(frozen=True)
class GrantEntity:
    project_id: str
    title: str
    fte: float                          # parsed, e.g. 0.20 not "20%"

@dataclass(frozen=True)
class ModuleEntity:
    canonical_name: str
    all_codes: Tuple[str, ...]          # deduplicated, H/M variants merged
    stage: int
    credits: int
    contact_hours: float
    practicals: int
    practical_contact_hours: float
    practical_groups: int
    practical_weeks: Tuple[int, ...]
    teachers: Tuple[str, ...]           # normalized canonical names
    lead_name: str                      # normalized
    student_count: int
    assessment_count: int
    marking_type: str                   # normalized to exactly 'automated' or 'manual'

@dataclass(frozen=True)
class StaffEntity:
    canonical_name: str
    fte: float                          # parsed
    category: str
    roles: Tuple[str, ...]              # every role this person holds per WAW, normalized
    project_load: float
    pastoral_load: int
    research_grants: Tuple[GrantEntity, ...]
    phd_sole_count: int
    phd_co_supervisions: Tuple[Tuple[str, float], ...]
    found_in_wtw: bool                  # False for anyone included via a fallback (e.g. role-based HoD inclusion)

@dataclass(frozen=True)
class YearRoster:
    year_label: str
    modules: Tuple[ModuleEntity, ...]
    staff: Tuple[StaffEntity, ...]
    unresolved_names: Tuple[str, ...]   # appeared in source data, couldn't be matched to any staff entity
```

Called once per year — the same function, run against current-year and
previous-year `ParsedSourceData`, producing two comparable `YearRoster`
objects.

**Constraints:**
- MUST run every raw name through `normalize_name` before it appears as a
  `ModuleEntity.teachers` entry or a `StaffEntity.canonical_name`.
- MUST populate `unresolved_names` rather than silently dropping a name that
  doesn't resolve — this list must be checked (non-empty is a reportable
  condition, not swallowed).
- MUST NOT compute `is_new_lecturer` or any other fact requiring a
  year-to-year comparison — Stage 1 doesn't see two years at once.
- MUST NOT apply any rate or compute any hours.
- MUST be pure with respect to its `ParsedSourceData` input — no reading
  additional files, no reaching back to Stage 0's source paths.

---

## Stage 2 — Derive Facts

**Input:** `this_year: YearRoster`, `previous_year: Optional[YearRoster]`.

**Output:**

```python
@dataclass(frozen=True)
class TeachingAssignmentFacts:
    person: str
    module_name: str
    module_codes: Tuple[str, ...]

    is_new_lecturer: bool
    is_new_content: bool
    is_video: bool                          # from module.teaching_format only, never a name-substring guess
    raw_lecture_hours_per_week: float
    lecture_weeks: int
    co_teacher_count: int

    practical_sessions_per_week: int
    raw_practical_hours_per_week: float     # from ModuleEntity.practical_contact_hours specifically
    practical_weeks: int                    # len(ModuleEntity.practical_weeks) when populated
    practical_weeks_is_fallback: bool       # True only if real per-module week data was unavailable

    hw_lab_hours: float
    is_new_hw_lab: bool
    drop_in_sessions: int

    marking_type: str                       # 'automated' | 'manual'
    is_msc: bool
    is_new_assessment_or_format: bool
    is_checking_only: bool
    assessment_count: int
    student_count: int

@dataclass(frozen=True)
class ResearchFacts:
    person: str
    grants: Tuple[GrantEntity, ...]
    phd_sole_count: int
    phd_co_supervisions: Tuple[Tuple[str, float], ...]

@dataclass(frozen=True)
class AdminFacts:
    person: str
    fte: float
    category: str
    role_percentages: Tuple[Tuple[str, float], ...]   # (role_name, % of nominal) per config.ROLES_PERCENTAGE
    normative_split: Optional[Dict[str, float]]        # from config.get_normative_split(category)

@dataclass(frozen=True)
class SupervisionFacts:
    person: str
    pastoral_student_count: int
    project_count: int
    project_level: str                      # 'ug' | 'msc'

@dataclass(frozen=True)
class DerivedFacts:
    year_label: str
    teaching_facts: Tuple[TeachingAssignmentFacts, ...]
    research_facts: Tuple[ResearchFacts, ...]
    admin_facts: Tuple[AdminFacts, ...]
    supervision_facts: Tuple[SupervisionFacts, ...]
```

**Constraints:**
- MUST NOT apply any rate or compute any hours — facts only.
- MUST derive `is_new_lecturer` solely by checking whether `person` appears
  in the matching module's teacher list in `previous_year` — never by any
  name- or module-code-specific check.
- MUST source `raw_practical_hours_per_week` from
  `ModuleEntity.practical_contact_hours` by exact field name.
- MUST set `practical_weeks_is_fallback = True` whenever
  `ModuleEntity.practical_weeks` is empty and a semester-wide default had to
  be substituted — never substitute silently.
- MUST be the only stage that reads `previous_year` data. No stage from 3
  onward may accept a "previous year" argument at all.
- MUST produce exactly one `TeachingAssignmentFacts` per (person, module)
  pair that exists in `this_year.modules` — verified by
  `verify_stage2_output`, not assumed.

---

## Stage 3 — Calculate

### 3a — Task level

**Input:** one fact record (e.g. one `TeachingAssignmentFacts`) plus the
specific named config constants the task type needs (passed as arguments,
not looked up by ad hoc string keys inside the function).

**Output:**

```python
@dataclass(frozen=True)
class TaskResult:
    task_type: str        # one of a fixed set: 'lecture_delivery', 'practical_first_session',
                           # 'practical_repeat', 'marking', 'assessment_setting', 'hw_lab',
                           # 'drop_in', 'pastoral_supervision', 'project_supervision',
                           # 'pgr_supervision', 'admin_role', 'research_grant'
    person: str
    module_name: Optional[str]     # None for non-module tasks (admin roles, research grants)
    raw_quantity: float            # hours/week, student count, script count, etc. - whatever this task type's base unit is
    rate_applied: float            # the exact multiplier/rate used
    rate_source: str               # the config constant name it came from, e.g. "config.TEACHING_STANDARD" - for traceability
    weeks: Optional[int]
    hours: float                   # = raw_quantity * rate_applied * (weeks or 1), computed in this same expression
```

One function per `task_type`. A function MUST NOT branch across multiple
task types internally.

**Constraints:**
- MUST compute `hours` in the same expression that uses `rate_applied` — no
  function may produce a `TaskResult` where `rate_applied` was computed but
  not actually multiplied into `hours`.
- MUST source `rate_applied` from a named config constant
  (`config.TEACHING_STANDARD`, etc.) — never `config.SOME_DICT.get(key, default)`.
- MUST NOT read `YearRoster`, `ParsedSourceData`, or previous-year data —
  only the single fact record and explicit rate arguments it's given.
- MUST NOT read or write any other `TaskResult` — task-level functions are
  independent of each other.

### 3b/3c/3d — Aggregation

**Input:** Stage 3a's `TaskResult`s (module level), then `ModuleTeachingResult`s
(person level), then `WorkloadResult`s (department level).

**Output:**

```python
@dataclass(frozen=True)
class ModuleTeachingResult:
    person: str
    module_name: str
    task_results: Tuple[TaskResult, ...]
    total_hours: float             # sum(t.hours for t in task_results) - reconciled at runtime

@dataclass(frozen=True)
class WorkloadResult:
    name: str
    fte: float
    category: str
    module_results: Tuple[ModuleTeachingResult, ...]
    research_task_results: Tuple[TaskResult, ...]
    admin_task_results: Tuple[TaskResult, ...]
    supervision_task_results: Tuple[TaskResult, ...]
    teaching_hours: float          # reconciled sum
    research_hours: float          # reconciled sum
    admin_hours: float             # reconciled sum
    total_hours: float             # reconciled sum
    assumptions: Tuple[str, ...]
    missing_data: Tuple[str, ...]

@dataclass(frozen=True)
class DepartmentSummary:
    year_label: str
    person_results: Tuple[WorkloadResult, ...]
    total_fte: float
    total_hours: float
    average_teaching_hours: float
    average_research_hours: float
    average_admin_hours: float
    flagged_staff: Tuple[str, ...]
```

**Constraints:**
- MUST compute every total as a sum over stored child results — never
  independently recomputed from facts or raw data.
- MUST run a reconciliation check at each level (module total = sum of its
  tasks; person total = sum of their modules + research + admin +
  supervision; department total = sum of persons) and raise if it doesn't
  hold within a small floating-point tolerance — at runtime, not only in a
  test.
- MUST NOT accept `DerivedFacts`, `YearRoster`, or any earlier-stage type as
  an input — only the previous aggregation level's output.

---

## Stage 4 — Output

**Input:** `Tuple[WorkloadResult, ...]` and `DepartmentSummary` only.

**Output:** CSV, HTML, and xlsx files.

**Constraints:**
- MUST NOT import or reference `ModuleEntity`, `StaffEntity`,
  `TeachingAssignmentFacts`, `ParsedSourceData`, or any Stage 0-2 type.
- MUST NOT perform arithmetic beyond simple formatting (rounding for
  display, string concatenation, a percentage-of-total division purely for
  a chart axis) — no rate application, no re-derivation of any figure that
  should already exist on a `TaskResult` or `WorkloadResult`.
- Every number displayed MUST be traceable to a specific field on a Stage 3
  object — if it isn't there, that's a Stage 2 or 3a gap to fix, not
  something to compute here.

---

## Rules that prevent the bugs already found

1. Every stage's output is a frozen dataclass with named fields, never a
   loose dict. Wrong field names raise `AttributeError` instead of silently
   returning a default.
2. No `.get(key, default)` for a key that's supposed to always be present -
   use `[key]` so a typo'd or renamed key raises immediately. Where `.get()`
   genuinely is right (a field that's optional by design), say so in a
   comment at the call site.
3. A rate/multiplier is applied in exactly one place per task type - the
   same expression that produces the final hours, not a separate value
   computed only for a label.
4. Nothing after Stage 2 reads a CSV, a YAML file, or the previous year's
   raw data again. A downstream gap gets fixed by adding a field to Stage 2,
   never by reaching backward.
5. Every stage boundary's validate/verify pair actually runs during normal
   execution (raise on violation), not only inside test files.


Add these five rules to CLAUDE.md once Stage 0 of the migration lands, so
they're standing guidance for any future change, not just this migration.

---

## Migration prompts

Each prompt is deliberately narrow. Run in order. After each one: full test
suite, then `check_against_baseline.py`. Most prompts should show **zero**
output differences (pure restructuring). Prompts 4 and 5 are the exception -
they're expected to change real numbers, and each says so explicitly with a
sign-off checkpoint. Don't skip ahead if a "should be zero diff" prompt shows
any difference - stop and report it rather than proceeding, per the standing
rule from the architecture refactor plan (flag structurally significant or
unexpected findings, don't silently resolve them).

### Prompt 0 — Define the target data types (pure scaffolding, no behavior change)

```
Create the frozen dataclasses for every stage output described in the
pipeline architecture doc: Stage 0 raw row types, Stage 1's YearRoster /
ModuleEntity / StaffEntity, Stage 2's TeachingAssignmentFacts (and the
research/admin/supervision equivalents), Stage 3's TaskResult /
ModuleTeachingResult / WorkloadResult (extending the existing WorkloadResult
rather than replacing it wholesale, if that's simpler - your call, but
report which you chose and why).

Also define, as empty/stub functions for now, the validate/verify pair for
each stage boundary (validate_stage0_input, verify_stage0_output,
validate_stage1_input, verify_stage1_output, etc.) - signatures only, with a
comment describing what each will eventually check. These get filled in as
each stage is migrated in the following prompts, not now.

This step adds new code but doesn't wire any of it into the live pipeline
yet - the existing calculation path keeps running unchanged.

Verification: full test suite green (nothing existing should be affected).
check_against_baseline.py should show zero differences, since nothing live
has changed yet.
```

### Prompt 1 — Migrate Stage 0 (parsing)

```
Refactor the existing CSV/YAML reading code in data_loader.py to produce the
Stage 0 raw row dataclasses from Prompt 0, instead of (or in addition to,
during this transition) whatever it currently returns. Implement
validate_stage0_input (file exists, required columns present) and
verify_stage0_output (every row parsed or explicitly rejected with a reason)
for real, and call them as part of the parsing functions - not just in
tests.

This should be a pure restructuring of what already happens during parsing -
no calculation logic lives here, so there should be nothing to "fix" in this
step.

Verification: full test suite green, check_against_baseline.py zero
differences.
```

### Prompt 2 — Migrate Stage 1 (prepare / entity resolution)

```
Refactor the name-normalization, module code merging/H-M-variant handling,
and roster construction currently in data_loader.py (load_all_data and its
helpers) to consume Stage 0's raw rows and produce a YearRoster of
ModuleEntity/StaffEntity records. Implement validate_stage1_input and
verify_stage1_output for real: verify specifically must check that every
teacher name referenced by a module exists in the staff roster or carries an
explicit "unknown" flag - never silently dropped, never silently kept as an
unflagged raw string.

This is still restructuring existing logic, not new logic - the entity
resolution rules (normalize_name, the WAW role mapping, etc.) stay as they
are, just organized to produce the new typed output.

Verification: full test suite green, check_against_baseline.py zero
differences.
```

### Prompt 3 — Migrate Stage 2 (derive facts)
**This is the first genuinely new stage - it doesn't exist as a distinct
thing today. Take your time on this one; every later stage depends on it
being complete.**

```
Create the fact-derivation stage: given this year's and the previous year's
YearRoster (Prompt 2's output), produce one TeachingAssignmentFacts record
per (person, module) pair, pulling together logic that's currently scattered
inside _calculate_lecture_hours_and_multipliers,
_calculate_practical_hours_and_breakdown, and
_calculate_assessment_setting_hours in workload_calculator.py - the
new-lecturer detection (_get_prev_year_module_names), is_new_content,
is_msc (config.is_msc_level), marking_type, and the raw duration/week/
co-teacher facts that Remedial Action 11 found were missing.

Specifically include, as real fields (not something a later stage has to
re-derive): raw_lecture_hours_per_week, lecture_weeks, co_teacher_count,
practical_sessions_per_week, raw_practical_hours_per_week (read from
module.practical_contact_hours - the REAL field, fixing Remedial Action 9 as
part of this move), practical_weeks (from len(module.practical_weeks) when
populated, fixing Remedial Action 10 as part of this move - fall back to
TEACHING_WEEKS_PER_SEMESTER only when a module genuinely has no specific
week data, and flag that fallback rather than using it silently).

Do NOT apply any rates or compute any hours in this stage - it produces
facts only. Rate application is Stage 3a's job, next.

Implement validate_stage2_input and verify_stage2_output for real: verify
must check every fact field is populated from real source data, not a
placeholder default.

Verification: full test suite green. check_against_baseline.py is not
meaningful yet since nothing downstream consumes this new stage - instead,
add unit tests asserting specific fact values against known fixture data
(e.g. a module with practicals only in 3 of 11 weeks should produce
practical_weeks=3, not 11).

Then stop and show me a sample TeachingAssignmentFacts record for one real
module/person before continuing - I want to check the field set is actually
complete before three more stages get built on top of it.
```

### Prompt 4 — Migrate Stage 3a for lecture hours
**Expected to change real output for anyone affected by Remedial Action 7 -
sign-off required before treating this as done.**

```
Write the Stage 3a lecture-delivery task function: takes a
TeachingAssignmentFacts record and the config rate constants, and returns a
TaskResult with the rate applied to produce the final hours in the same
expression - no separate "hours" and "label" computation. Use the config
named constants directly (config.TEACHING_STANDARD, TEACHING_NEW_CONTENT,
TEACHING_NEW_BOTH, TEACHING_NEW_VIDEO) rather than re-deriving dict lookups
with new key strings, fixing Remedial Action 7 as part of writing this
function fresh rather than porting the old broken lookups.

Add a test that mutates a config value at runtime and asserts the function's
output changes accordingly, not just that it currently returns the right
number.

Wire this into the real pipeline (replacing the old lecture-hours logic),
run the full department's real data through both the old and new path, and
report every case where the two disagree, with the person/module and both
values. Given today's hardcoded defaults happen to match the real YAML
values, this diff should be empty or near-empty - if it's not, that's
worth understanding before proceeding, since it means the YAML has already
drifted from what the old hardcoded defaults assumed. Stop and show this
diff before treating the migration as final.

Verification: full test suite green. check_against_baseline.py will show
differences only for the specific people/modules in the diff report above -
confirm nothing else changed.
```

### Prompt 5 — Migrate Stage 3a for practical hours
**Expected to change real output materially - this is the first-session
multiplier fix. Sign-off required.**

```
Write the Stage 3a practical-session task functions (first session, repeat
session) the same way: TeachingAssignmentFacts + config rate in, TaskResult
with the rate actually applied to the hours out, in one expression. This
fixes Remedial Action 8 (first session rate was computed but never
multiplied in) by construction, since there's no longer a code path where a
rate can be computed for display without also being the rate used for the
total.

Wire this into the real pipeline, run the whole department's real data
through old vs new, and report every person/module where practical hours
change, with both values and the size of the change. This one WILL show
real differences for anyone who delivers practicals, potentially a lot of
people - that's the fix working, not a regression, but it needs your eyes
on the actual before/after numbers before it's treated as final, since it
changes real people's real workload totals.

Verification: full test suite green (including a test with a distinctive
practical_contact_hours value confirming it's read correctly per Remedial
Action 9, and a test with a module whose practical_weeks is shorter than a
full semester confirming that's respected per Remedial Action 10).
check_against_baseline.py differences should match exactly the diff report
above - nothing else.
```

### Prompt 6 — Migrate remaining Stage 3a task types

```
Apply the same pattern (facts + rate -> TaskResult, rate applied once, no
silent dict-key defaults) to the remaining task types: marking, assessment
setting, supervision (pastoral/project/PGR), admin roles, and online
programme teaching. Audit each existing config.SOMETHING.get(key, default)
call you migrate - confirm the key actually exists in the real YAML dict
(the way Remedial Action 7 didn't) before carrying the lookup forward.

These are expected to be behavior-preserving (Remedial Actions 7-10 were
specific to lecture and practical hours), but confirm that with the same
old-vs-new diff approach as Prompts 4-5 rather than assuming it.

Verification: full test suite green, check_against_baseline.py zero
differences (or a reported, explained diff if something else turns up -
don't silently absorb an unexpected difference here either).
```

### Prompt 7 — Migrate Stage 3b/3c/3d (aggregation)

```
Build the module/person/department aggregation levels as sums over Stage 3a
TaskResults, replacing the equivalent aggregation currently spread through
calculate_workload. Implement verify_stage3_output as a real runtime
reconciliation check at each level: module total equals the sum of its task
results, person total equals the sum of their module/research/admin
contributions, department total equals the sum of person totals - raise
immediately if any of these don't reconcile within a small floating-point
tolerance, rather than only catching it in a test.

Verification: full test suite green, check_against_baseline.py shows only
the differences already reported and understood from Prompts 4-6.
```

### Prompt 8 — Migrate Stage 4 (output) and apply the completeness test

```
Confirm every output routine (CSV, HTML, xlsx, per-staff and department
reports) reads only from Stage 3's stored WorkloadResult/TaskResult objects,
with no recomputation and no reaching back into module/staff/roster data
directly.

Apply the concrete acceptance test from Remedial Action 11: write the exact
plain-language sentence originally requested ("11 weeks of 2 hour lectures
split between 3 lecturers = Xh") as a function reading only fields already
on the Stage 3 objects, no access to raw module/teacher data, no
recomputation. If it needs a field that isn't there, that's a Stage 2 or 3a
gap - go add it there, don't reach backward from Stage 4 to get it. Use this
same test as the standing bar for any future "just change how this is
displayed" request - add it as a note in CLAUDE.md.

Verification: full test suite green, check_against_baseline.py zero
differences (Stage 4 is pure reformatting of already-correct Stage 3 data,
so nothing here should change output beyond what Prompts 4-6 already
introduced).
```

### Prompt 9 — Final integration and sign-off

```
Confirm every stage's validate/verify pair is wired into the live pipeline
(not just callable from tests) and actually raises on a deliberately broken
input for each stage (write one negative test per stage boundary confirming
this - e.g. feed Stage 2 a roster with a teacher not in the staff list and
confirm verify_stage1_output would have caught it, or an artificially
corrupted TaskResult sum and confirm verify_stage3_output raises).

Run the full test suite and check_against_baseline.py one final time.
Report: the complete, final list of every output difference from the
original pre-migration baseline, cross-referenced against which prompt
introduced each one (should be entirely accounted for by Prompts 4-6's
reported diffs, nothing unexplained), and the final module/file structure
(what lives in which stage, if you split files by stage - your call on
whether to do that or keep the current file layout with clearer internal
organization, but report which and why).
```