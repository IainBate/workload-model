# Improvement Plan (consolidated from 6 planning docs)

**Status:** Draft for review. Built from `architecture_improvements.md`, `architecture_improvements_v2.md`,
`academic_workload_test_strategy.md`, `BUGS_AND_FIXES.md`, `DISCREPANCIES.md`, and
`WORKLOAD_OUTPUT_REDESIGN_PROMPTS.md`, reconciled and cross-checked against the live codebase
(2026-08-12), plus four scoping decisions from Iain (recorded below). Supersedes those six
source docs as the working plan — they can be archived once this is reviewed.

## Decisions already made (2026-08-12)

1. **Doc of record:** `Work Allocation Model.docx` is now the sole source of truth (not the
   older `Workload ModelFull Description.docx`). Code/config/report-footer citations have
   already been updated to reflect this (`config.py`, `workload_parameters.yaml` header,
   `output_generator.py` footer, root `CLAUDE.md`).
2. **Ethics Committee Member %:** Confirmed **20%** is correct. `workload_parameters.yaml` has
   been reverted to 0.20 (it had drifted to 0.10), and the self-contradictory prose caveat in
   `Work Allocation Model.docx` (paragraph that referenced a "10% update... please confirm") has
   been removed since Appendix A's table (20%) is simply correct. Verified via full pipeline
   re-run + baseline regeneration — no other numbers affected besides Ethics Committee Member
   holders' admin hours.
3. **Individual Report redesign proposals:** Not decided yet — enumerated as a pick-list below
   (Section C) per Iain's request. None have been started.
4. **`output_generator.py` pure-rendering refactor:** Approved, but **gated** behind the
   JSON-baseline + format-diff test infrastructure (Section B, items B1–B2) landing first, so
   any accidental visible-output drift is caught automatically rather than by eye.

## Already verified as non-issues (no action needed)

Two "bugs" from `architecture_improvements_v2.md` were checked against the current code and
are **already resolved** — the codebase has moved on since that doc was written:
- PhD supervision double-counting in `research_breakdown` — checked live: breakdown sums to
  `research_hours` exactly (e.g. Adrian Bors: `{protected_research_baseline: 164.2, phd_students:
  {supervision: 240, assessor: 8}}` sums to `research_hours` = 412.2). The flat `phd_supervision`
  key the doc describes doesn't exist in current code.
- Teaching breakdown not aggregating per-staff — checked live: `teaching_breakdown` sums to
  `teaching_hours` exactly (Christopher Crispin-Bailey: 530.1 = 530.1).

Most of `BUGS_AND_FIXES.md` is also already resolved (it's an archived doc; 5 of its 7 bugs are
marked FIXED in its own "Completed Fixes" section) — including Bug #7's regex-parsing concern
(`output_generator.py` now has zero `re.search`/`re.match` calls, confirmed by grep).

`DISCREPANCIES.md`'s doc-text fixes appear to be **already incorporated** into
`Work Allocation Model.docx` — spot-checked several: nominal hours already state 1,642h (§2),
project setting is already placed under Supervision not general baselines (§2), and the 7.5×
combined multiplier is already in Table 5. Two of its items are *not* just wording — see A2/A3
below, which are still live.

---

## Section A — Do now (low-risk, high-value, no further sign-off needed)

Small, additive, or purely corrective. None change existing displayed numbers for anyone not
directly affected, and none redesign anything.

| # | Item | Source | Effort | Notes |
|---|------|--------|--------|-------|
| A1 | Add missing `ECR representative` and `ART staff representative` roles to `workload_parameters.yaml` at 0% | DISCREPANCIES.md | S | Confirmed real gap — both roles exist in `Work Allocation Model.docx` Appendix A at 0%, and two real people (Joe Cutting, Richard Wilson) hold them in `WAW.csv` today but are currently unmapped. Additive only — 0% allocation, so no hours change, but their admin-role listing will go from "unmapped/missing" to correctly shown. |
| A2 | Verify baseline documentation for min admin teaching hours (30h) and service points (175h) | DISCREPANCIES.md | S | Spot-checked: `Work Allocation Model.docx` names these baseline categories (§2, "Set of baselines" / part-time FTE-scaling paragraph) but I did not find the numeric values (30h / 175h) written anywhere in the doc text. Needs a look — either add the numbers to the doc, or confirm they're intentionally left as departmental discretion. |
| A3 | Investigate: lecture contact hours are a flat 2h/week × 11 weeks = 22h for **every** module, regardless of credits | BUGS_AND_FIXES.md (Bug #2, never marked fixed) | S (investigate) | New finding, not fully resolved in any doc. `module.contact_hours` (computed from credits) is calculated during data loading but **never read anywhere** in `workload_calculator.py` or `output_generator.py` — it's dead code. Every module's lecture hours use the same fixed rate. Needs your call: is a flat 2h/week correct for every module regardless of size, or should larger/smaller modules get proportionally more/less lecture time? If the latter, this is a real calculation gap, not just doc cleanup. |
| A4 | `--validate-only` CLI mode | architecture_improvements.md | S | Small, self-contained, no dependencies beyond the already-implemented validation pipeline. |

**Recommended order:** A1 → A2 → A4 (all trivial, can be done together) → A3 (needs your
domain input before any code change, so raise it and move on rather than blocking on it).

---

## Section B — Testing & architecture foundation

This is the prerequisite work for doing the department-view rebuild (Section D) and the
individual-report refactor (Section E) safely. Ordered so risk is front-loaded into cheap,
reversible steps.

| # | Item | Source(s) | Effort | Depends on |
|---|------|-----------|--------|------------|
| B1 | Structured JSON calculation baseline (`baseline/expected_results.json` via `--export-baseline`) | architecture_improvements.md + v2 | M | — |
| B2 | Format-only HTML regression tests (whitespace-normalized diff against saved baseline HTML) | architecture_improvements.md + v2 | M | B1 (conceptually paired — separates "is the math right" from "does it look the same") |
| B3 | Unit test suite for calculation logic (`test_calculations.py`) | architecture_improvements.md + v2, test_strategy.md | M | B1 |
| B4 | Integration test suite for full pipeline (`test_integration.py`) | architecture_improvements.md + v2, test_strategy.md | M | B3 |
| B5 | Confirm validation-pipeline status in current `main.py`/`validation.py` | architecture_improvements.md + v2 | S | — |
| B6 | Unit tests: data loader & schema (name normalization, module merge logic, input validation) | test_strategy.md | S | — |
| B7 | Integration test: all output artifacts produced and non-empty (CSV/XLSX/PNGs/both HTML report types) | test_strategy.md | S | B4 |
| B8 | Integration test: Excel formula & chart reference validation | test_strategy.md | S | — |
| B9 | Property-based invariant testing (Hypothesis) | test_strategy.md | M | **Blocked** — assumes `_calculate_teaching_workload` has been split into named helpers that don't exist. CLAUDE.md explicitly flags this ~880-line function as a Phase 5 target and says "do not add more logic to these functions." Re-scope or defer until that refactor happens, don't force it now. |
| B10 | **`output_generator.py` pure-rendering refactor** (approved, gated per your decision) | architecture_improvements.md, test_strategy.md | L | B1 + B2 must be green first; B2 is the safety net that proves zero visible output changed |
| B11 | Visual regression: matplotlib chart artifact checks (size/dimensions, headless render) | test_strategy.md | S | — |

**Recommended order:** B1 → B2 → B5 (quick status check, do anytime) → B6 → B3 → B4 → B7 → B8 →
B11 → **B10 (the gated refactor)** → B9 (only if/when the calc-engine decomposition happens
separately).

Note: B9's dependency on a large function decomposition isn't in scope of this plan unless you
want it — flagging it as blocked rather than silently dropping it.

---

## Section C — Individual Report changes (menu — nothing here is scheduled, pick what you want)

You said you're happy with the current individual reports and asked to see the specific list
rather than have me decide. Each is independent and small; none require the others.

| # | Proposal | What it does | Effort |
|---|----------|---------------|--------|
| C1 | Computed headline summary sentence | One sentence at the top: "Total workload is 1,847h against a nominal 1,642h for 1.0 FTE — 12.5% over, mostly from teaching." Needs the category/normative-split plumbing (C-prereq below) to generate the "mostly from X" clause. | S |
| C2 | Normative-split comparison (table or inline SVG bars) | Per-category (teaching/research/admin) actual % vs. target % for the person's contract type, flagging >~10pp deviations. Needs C-prereq. | M |
| C3 | Header block shows total hours + delta vs nominal | Replaces the FTE/Nominal side-by-side with FTE, nominal, total, and the +/- delta computed directly instead of left for you to subtract. | S |
| C4 | Fix hardcoded footer date | Footer currently has a literal string `Generated on 2026-07-14...` instead of the real generation date — this is a plain bug, listed here only because it's in the same output file; happy to just fix it regardless of the rest of C. | S |
| C5 | Positive confirmation message when no data-quality issues | When assumptions/missing-data are both empty, show "No data-quality issues flagged" instead of silently showing nothing. | S |
| C6 | Sort detail-section items by hours descending | Biggest time contributors shown first within each category. | S |
| C7 | Standardize practicals-section wording ("First session" vs "First time delivery") | Note: this proposal's suggested wording conflicts with what CLAUDE.md currently documents as the standard ("First time delivery") — needs reconciling either way, not a free pick. | S |

*C-prereq (shared plumbing, only needed if you pick C1 or C2): add `category` field to
`WorkloadResult` + `config.get_normative_split()` helper. M effort, tested separately (see D-prereq
below — same piece of work, shared with the department view).*

**My read, given you said your priority is departmental views:** C4 (trivial bug fix) is worth
doing regardless. The rest (C1/C2/C3/C5/C6/C7) can wait indefinitely with zero cost — say which
ones, if any, you want and I'll slot them in; otherwise they stay parked here.

---

## Section D — Departmental view improvements (your stated priority)

This is what you said you actually want: reports/graphs to manage departmental workload and see
where time is going. Ordered to build the shared data plumbing first, then the highest-value
manager-facing addition, then the rest.

| # | Item | Why it matters for you | Effort | Depends on |
|---|------|------------------------|--------|------------|
| D-prereq | Add `category` field to `WorkloadResult` + `config.get_normative_split()` mapping | Foundation for everything below — without it there's no way to compare anyone's actual split to their contract-type target. Shared with C1/C2 if you pick those later. | M | — |
| D1 | **"Needs attention" triage section** | The source doc calls this "the single most useful addition for a manager" — a section before the main table listing staff >~10% over/under nominal hours, plus anyone with non-empty assumptions/missing-data (actual message text shown). This is probably your fastest path to "where is time going / who needs a conversation." | M | D-prereq |
| D2 | Department summary block | Headcount, total FTE, total hours, average teaching/research/admin per FTE, one generated sentence comparing dept-wide average split to normative target. | M | D-prereq |
| D3 | Fix boxplot charts: unplotted "expected" line + flat normative split | Two known bugs: the "expected" comparison line is computed but never actually drawn, and both boxplot charts currently compare everyone against one flat split regardless of their real contract category. Fixing this makes the charts actually show what they're supposed to. | M | D-prereq |
| D4 | Replace truncated free-text detail columns with structured hours + per-category deviation indicator | Main table currently has 80-char-truncated tooltip text; replace with FTE/total/teaching/research/admin hours and a compact "how far from target" indicator per category. | M | D-prereq |
| D5 | Link staff names to their individual report | Click through from the summary table to the full per-staff breakdown. | S | Stable individual-report filenames (already the case) |
| D6 | Group/sort main table by contract category | See T&R vs T&S patterns together rather than arbitrary order. | S | D-prereq |
| D7 | Unit tests for department summary stats + needs-attention filter | Tested independent of HTML generation. | S | D1, D2 |

**Recommended order:** D-prereq → **D1** (highest value, do this first) → D3 (fixes visibly
broken charts) → D2 → D4 → D5 → D6 → D7.

---

## Section E — Integration & final pass

| # | Item | Depends on |
|---|------|------------|
| E1 | Confirm `generate_all_outputs()` runs per-staff reports before the department report (department report links to individual filenames) | D5 |
| E2 | Extract shared reporting-helper logic (normative-comparison, over/under framing, colour/threshold conventions) so the two report types don't diverge | Whichever of C/D items land |
| E3 | Run full test suite together, not just per-change | All of B/D/E |
| E4 | Full-run visual sanity check, incl. graceful handling of an unmapped category (no crash) | E3 |

---

## Suggested overall sequence

1. **Section A** (A1, A2, A4 now; A3 raised for your input)
2. **Section B1–B2** (JSON baseline + format-diff tests — the safety net everything else leans on)
3. **Section D-prereq + D1** (category/normative plumbing, then the "needs attention" view — your stated priority, unblocked as soon as the safety net exists)
4. **Section D3–D7** (rest of the departmental view)
5. **Section B3–B8, B11** (remaining test coverage, can run in parallel with step 4 — independent)
6. **Section B10** (the gated `output_generator.py` refactor — only once B1/B2 are solid)
7. **Section C** — only the items you actually pick, whenever you pick them; C4 (footer date bug) can happen any time
8. **Section E** (integration/consistency pass, once whichever of C/D was built)

B9 stays explicitly parked (blocked on a large function decomposition not otherwise in scope).

---

## Once this is reviewed

- Archive `architecture_improvements.md`, `architecture_improvements_v2.md`,
  `academic_workload_test_strategy.md`, `BUGS_AND_FIXES.md`, `DISCREPANCIES.md`, and
  `WORKLOAD_OUTPUT_REDESIGN_PROMPTS.md` (e.g. move to a `docs/archive/` folder) since this file
  supersedes them — keeping all six around invites them drifting out of sync with this plan the
  way they'd drifted out of sync with the code and each other.
