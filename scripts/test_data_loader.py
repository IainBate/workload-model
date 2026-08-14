"""
Data loader and schema/validation unit tests (plan item B6).

Covers the ingestion layer that everything downstream depends on: staff name
normalization, H/M module-variant merging, contract-category resolution, and
the input validation guards. These run against small in-memory fixtures rather
than the real CSVs, so they stay valid as the data changes year to year.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import csv

import data_loader as dl  # noqa: E402
import validation  # noqa: E402
from data_loader import ModuleData, StaffData, AdjustmentRecord  # noqa: E402
from workload_calculator import _classify_marking_levels  # noqa: E402


def _write_adjustments_csv(path, rows):
    """Write a workload_adjustments.csv with the standard header + given rows
    (each row a dict keyed by column name; missing columns default to '')."""
    header = ["Person", "Teaching Module", "Teaching Adjustment", "Teaching Rationale",
              "Research Adjustment", "Research Rationale",
              "Admin Adjustment", "Admin Rationale"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in header})


class TestNameNormalization:
    """Canonical staff-name resolution."""

    @pytest.fixture
    def lookup(self):
        mappings = {
            "Christopher Crispin-Bailey": ["Chris CB", "Christopher", "Christopher Crispin-Bailey"],
            "Steven Xiaotian Dai": ["Xiaotian", "Steven Dai", "Steven Xiaotian Dai"],
            "Mike O'Dea": ["Mike O'D", "Mike O'Dea"],
        }
        reverse, warnings = dl._build_reverse_lookup(mappings)
        return reverse, warnings, mappings

    def test_alias_resolves_to_canonical(self, lookup):
        reverse, _, mappings = lookup
        assert dl.normalize_name("Chris CB", reverse, None, mappings) == "Christopher Crispin-Bailey"
        assert dl.normalize_name("Steven Dai", reverse, None, mappings) == "Steven Xiaotian Dai"

    def test_normalization_is_case_insensitive(self, lookup):
        reverse, _, mappings = lookup
        assert dl.normalize_name("chris cb", reverse, None, mappings) == "Christopher Crispin-Bailey"
        assert dl.normalize_name("CHRIS CB", reverse, None, mappings) == "Christopher Crispin-Bailey"

    def test_surrounding_whitespace_ignored(self, lookup):
        reverse, _, mappings = lookup
        assert dl.normalize_name("  Chris CB  ", reverse, None, mappings) == "Christopher Crispin-Bailey"

    def test_apostrophes_preserved(self, lookup):
        reverse, _, mappings = lookup
        assert dl.normalize_name("Mike O'D", reverse, None, mappings) == "Mike O'Dea"

    def test_non_person_entries_rejected(self, lookup):
        reverse, _, mappings = lookup
        for junk in ("N/A", "TBD", "none", "Total", "TRUE", "Projects"):
            assert dl.normalize_name(junk, reverse, None, mappings) is None, junk

    def test_empty_input_returns_none(self, lookup):
        reverse, _, mappings = lookup
        assert dl.normalize_name("", reverse, None, mappings) is None
        assert dl.normalize_name(None, reverse, None, mappings) is None

    def test_duplicate_alias_is_reported(self):
        """A clashing alias must surface a warning, not silently pick one."""
        _, warnings = dl._build_reverse_lookup({
            "Person One": ["Ambiguous", "Person One"],
            "Person Two": ["Ambiguous", "Person Two"],
        })
        assert any("Ambiguous" in w for w in warnings)

    def test_real_lookup_file_has_no_duplicate_aliases(self):
        """Regression guard: the shipped lookup must stay unambiguous.

        A duplicate here silently routes a name to the wrong person - this is
        what sent bare 'Chris' to the inactive Chris Smith.
        """
        _, warnings = dl._build_reverse_lookup(dl._load_name_lookup())
        assert warnings == [], f"Duplicate aliases in staff_name_lookup.json: {warnings}"


class TestCategoryResolution:
    """Contract-category (ART / T and S) resolution precedence."""

    def test_art_sheet_takes_precedence(self):
        got = dl._resolve_category_from_data(
            "Someone", "ART", {"staff_category": "T and S"}, {"Someone": "T and S"}
        )
        assert got == "ART"

    def test_falls_back_to_part_time_csv(self):
        got = dl._resolve_category_from_data(
            "Someone", None, {"staff_category": "T and S"}, {}
        )
        assert got == "T and S"

    def test_falls_back_to_saved_override(self):
        got = dl._resolve_category_from_data("Someone", None, None, {"Someone": "ART"})
        assert got == "ART"

    def test_unknown_returns_empty_not_a_guess(self):
        """Must return '' so callers can ask, rather than inventing a category."""
        assert dl._resolve_category_from_data("Nobody", None, None, {}) == ""

    def test_art_sheet_parses_lastname_firstname(self):
        """The sheet is 'Lastname, Firstname'; some rows omit the comma."""
        data = dl._load_art_ts_categories()
        assert data.get("Sarah Carrington") == "T and S"
        assert data.get("Rob Alexander") == "ART"
        # Comma-less rows still resolve
        assert data.get("Mike O'Dea") == "T and S"
        assert data.get("Richard Wilson") == "ART"

    def test_art_sheet_typo_correction_applied(self):
        """'Banerjee, Soumua' in the source is a typo for Soumya."""
        assert dl._load_art_ts_categories().get("Soumya Banerjee") == "ART"


class TestModuleVariantMerging:
    """H/M variant handling - the same class taught to UG and MSc cohorts."""

    def test_h_and_m_split_into_two_marking_levels(self):
        module = ModuleData(
            name="AURO", codes=("COM00052H", "COM00186M"), stage=3,
            student_count=104,
            student_count_by_code={"COM00052H": 62, "COM00186M": 42},
        )
        levels = _classify_marking_levels(module)
        assert len(levels) == 2
        by_label = {lv["label"]: lv for lv in levels}
        assert by_label["H level"]["student_count"] == 62
        assert by_label["H level"]["is_msc"] is False
        assert by_label["M level"]["student_count"] == 42
        assert by_label["M level"]["is_msc"] is True

    def test_single_code_module_has_one_unlabelled_level(self):
        module = ModuleData(
            name="SYS3", codes=("COM00018I",), stage=2, student_count=275,
            student_count_by_code={"COM00018I": 275},
        )
        levels = _classify_marking_levels(module)
        assert len(levels) == 1
        assert levels[0]["label"] is None
        assert levels[0]["is_msc"] is False

    def test_m_only_module_is_msc_regardless_of_stage(self):
        """A pure-MSc module must get the MSc rate even though WTW records it
        at stage 3 - the bug that had PRAD/GPIG billed at the UG rate."""
        module = ModuleData(
            name="PRAD", codes=("COM00195M",), stage=3, student_count=56,
            student_count_by_code={"COM00195M": 56},
        )
        levels = _classify_marking_levels(module)
        assert len(levels) == 1
        assert levels[0]["is_msc"] is True

    def test_module_with_no_students_yields_no_levels(self):
        module = ModuleData(name="X", codes=("C1",), stage=1, student_count=0)
        assert _classify_marking_levels(module) == []


class TestPlaceholderCodeFallback:
    """A WTW row with a placeholder code must still resolve real data.

    FOAM's WTW code is '<new for one year>', but its real numbers are recorded
    against acronym FOAM / code COM00196M. Without the acronym fallback it
    silently used DEFAULT_STUDENT_COUNT *and* the UG marking rate, because the
    missing 'M' suffix made it look like an undergraduate module.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def year_data(cls):
        return dl.load_all_data(
            data_dir=str(Path(__file__).parent.parent / "data"),
            unknown_callback=None, category_callback=None,
        )

    def test_foam_resolves_real_student_count(self, year_data):
        foam = next((m for m in year_data.modules if m.name == "FOAM"), None)
        assert foam is not None, "FOAM module missing from roster"
        assert foam.student_count == 30

    def test_foam_resolves_its_real_module_code(self, year_data):
        foam = next(m for m in year_data.modules if m.name == "FOAM")
        assert "COM00196M" in foam.student_count_by_code

    def test_foam_marked_at_msc_rate(self, year_data):
        """The recovered 'M' suffix must drive the marking level."""
        foam = next(m for m in year_data.modules if m.name == "FOAM")
        levels = _classify_marking_levels(foam)
        assert len(levels) == 1
        assert levels[0]["is_msc"] is True, "FOAM should mark at the MSc rate"


class TestModuleExclusions:
    """Modules whose work is credited elsewhere are excluded from teaching."""

    @pytest.fixture(scope="class")
    @classmethod
    def year_data(cls):
        return dl.load_all_data(
            data_dir=str(Path(__file__).parent.parent / "data"),
            unknown_callback=None, category_callback=None,
        )

    def test_projects_module_excluded(self, year_data):
        """'Projects' is credited via the Taught Project Coordinator admin role."""
        assert not any(m.name == "Projects" for m in year_data.modules)

    def test_exclusions_are_configured_not_hardcoded(self):
        mapping = dl._load_module_mapping()
        assert "Projects" in mapping.get("excluded_modules", {})
        assert mapping["excluded_modules"]["Projects"].get("reason")

    def test_other_modules_unaffected(self, year_data):
        """Exclusion must remove only the named module."""
        names = {m.name for m in year_data.modules}
        assert {"HCIN", "SYS2", "SYS3", "FOAM"} <= names


class TestInputValidation:
    """Validation guards on incoming data."""

    @pytest.mark.parametrize("fte", [-0.5, -1])
    def test_negative_fte_rejected(self, fte):
        assert not validation.validatefte(fte).valid

    def test_zero_fte_rejected_unless_allowed(self):
        assert not validation.validatefte(0).valid
        assert validation.validatefte(0, allow_zero=True).valid

    @pytest.mark.parametrize("fte", [0.2, 0.5, 1.0])
    def test_plausible_fte_accepted(self, fte):
        assert validation.validatefte(fte).valid

    def test_negative_student_count_rejected(self):
        assert not validation.validatestudentcount(-5).valid

    def test_zero_students_allowed(self):
        """Legitimate for a module that hasn't recruited yet."""
        assert validation.validatestudentcount(0).valid

    def test_module_missing_codes_flagged(self):
        result = validation.validate_module_data(
            ModuleData(name="NoCodes", codes=(), stage=1, credits=20, student_count=10)
        )
        assert any("code" in str(i).lower() for i in result.issues)

    def test_non_positive_credits_flagged(self):
        result = validation.validate_module_data(
            ModuleData(name="M", codes=("C1",), stage=1, credits=0, student_count=10)
        )
        assert any("credit" in str(i).lower() for i in result.issues)


class TestSupervisionAllocation:
    """allocate_supervision() is a pure projection of staff data."""

    def test_allocation_mirrors_staff_records(self):
        staff = {
            "A": StaffData(canonical_name="A", fte=1.0, pastoral_students=7,
                           project_load=3, phd_supervisions=2),
            "B": StaffData(canonical_name="B", fte=0.5, pastoral_students=0,
                           project_load=0, phd_supervisions=0),
        }
        alloc = dl.allocate_supervision(staff)
        assert alloc.pastoral_students["A"] == 7
        assert alloc.project_loads["A"] == 3
        assert alloc.pastoral_students["B"] == 0
        assert alloc.project_loads["B"] == 0


class TestAdjustmentParsing:
    """workload_adjustments.csv cell grammar and loader (_parse_adjustment_cell,
    _load_adjustments)."""

    # --- Cell grammar ---

    @pytest.mark.parametrize("cell,expected_value", [
        ("+100", 100.0),
        ("-50", -50.0),
        ("12.5", 12.5),
        ("0", 0.0),
    ])
    def test_delta_forms_accepted(self, cell, expected_value):
        mode, value = dl._parse_adjustment_cell(cell)
        assert mode == "delta"
        assert value == expected_value

    @pytest.mark.parametrize("cell", [
        "SET 250", "set 250", "Set 250", "SET   250", "  SET 250  ", "SET -10",
    ])
    def test_absolute_forms_accepted(self, cell):
        mode, value = dl._parse_adjustment_cell(cell)
        assert mode == "absolute"

    def test_absolute_value_parsed_correctly(self):
        mode, value = dl._parse_adjustment_cell("SET 250")
        assert (mode, value) == ("absolute", 250.0)

    def test_leading_equals_sign_rejected(self):
        """Regression guard: '=250' must NOT be treated as an absolute override.
        Excel/Sheets evaluates a leading '=' as a formula and drops it on CSV
        re-save, which would make absolute overrides indistinguishable from
        deltas after a spreadsheet round-trip - so it must be rejected outright,
        not silently reinterpreted as anything."""
        with pytest.raises(ValueError):
            dl._parse_adjustment_cell("=250")

    @pytest.mark.parametrize("cell", [
        "abc", "SET", "SET abc", "N/A", "TBD", "++5", "SET SET 5", "",
    ])
    def test_other_malformed_cells_rejected(self, cell):
        with pytest.raises(ValueError):
            dl._parse_adjustment_cell(cell)

    # --- File loader ---

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        result = dl._load_adjustments()
        assert result == ({}, {}, [])

    def test_stacking_rows_same_person_spelling(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        _write_adjustments_csv(tmp_path / "workload_adjustments.csv", [
            {"Person": "Test Person", "Teaching Adjustment": "+10",
             "Teaching Rationale": "extra marking"},
            {"Person": "Test Person", "Teaching Adjustment": "+5",
             "Teaching Rationale": "extra cover"},
        ])
        adjustments, warnings, unattributed = dl._load_adjustments()
        assert unattributed == []
        assert warnings == {}
        records = adjustments["Test Person"]
        assert len(records) == 2
        assert all(isinstance(r, AdjustmentRecord) for r in records)
        assert [r.value for r in records] == [10.0, 5.0]
        assert [r.source_row for r in records] == [2, 3]

    def test_rationale_blank_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        _write_adjustments_csv(tmp_path / "workload_adjustments.csv", [
            {"Person": "Test Person", "Teaching Adjustment": "+10",
             "Teaching Rationale": ""},
        ])
        adjustments, warnings, unattributed = dl._load_adjustments()
        assert adjustments == {}
        assert "Test Person" in warnings
        assert "no rationale" in warnings["Test Person"][0]

    def test_malformed_cell_produces_warning_not_record(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        _write_adjustments_csv(tmp_path / "workload_adjustments.csv", [
            {"Person": "Test Person", "Research Adjustment": "=250",
             "Research Rationale": "grant admin"},
        ])
        adjustments, warnings, unattributed = dl._load_adjustments()
        assert adjustments == {}
        assert "Test Person" in warnings
        assert "not a valid adjustment" in warnings["Test Person"][0]

    def test_blank_person_with_data_is_unattributed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        _write_adjustments_csv(tmp_path / "workload_adjustments.csv", [
            {"Person": "", "Admin Adjustment": "+5", "Admin Rationale": "extra committee work"},
        ])
        adjustments, warnings, unattributed = dl._load_adjustments()
        assert adjustments == {}
        assert warnings == {}
        assert len(unattributed) == 1
        assert "Person is blank" in unattributed[0]

    def test_blank_row_entirely_skipped_silently(self, tmp_path, monkeypatch):
        """A row with a blank Person AND no adjustment data (e.g. a stray blank
        CSV line) should not be flagged at all."""
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        _write_adjustments_csv(tmp_path / "workload_adjustments.csv", [
            {"Person": "", "Teaching Adjustment": "", "Teaching Rationale": ""},
        ])
        adjustments, warnings, unattributed = dl._load_adjustments()
        assert (adjustments, warnings, unattributed) == ({}, {}, [])

    def test_multiple_categories_on_one_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        _write_adjustments_csv(tmp_path / "workload_adjustments.csv", [
            {"Person": "Test Person",
             "Teaching Adjustment": "SET 100", "Teaching Rationale": "ENG1 unconventional",
             "Admin Adjustment": "+20", "Admin Rationale": "extra committee work"},
        ])
        adjustments, warnings, unattributed = dl._load_adjustments()
        records = adjustments["Test Person"]
        categories = {r.category: r for r in records}
        assert categories["teaching"].mode == "absolute"
        assert categories["teaching"].value == 100.0
        assert categories["admin"].mode == "delta"
        assert categories["admin"].value == 20.0


def _make_year_data(staff_list, mappings=None):
    """Build a minimal YearData with a real reverse_lookup for sync_adjustment_names
    tests, without going through the full load_all_data() pipeline."""
    mappings = mappings or {}
    reverse_lookup, _ = dl._build_reverse_lookup(mappings)
    return dl.YearData(
        year_label="2026-7",
        modules=(),
        student_counts={},
        assessment_counts={},
        staff=tuple(staff_list),
        known_lecturers=frozenset(),
        known_lecturers_per_module={},
        reverse_lookup=reverse_lookup,
        canonical_lookup=mappings,
    )


class TestSyncAdjustmentNames:
    """sync_adjustment_names() - additive, idempotent housekeeping that keeps
    workload_adjustments.csv covering every active staff member."""

    def test_missing_file_creates_header_and_all_active_staff(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        year_data = _make_year_data([
            StaffData(canonical_name="Bob Brown", active=True),
            StaffData(canonical_name="Alice Adams", active=True),
        ])
        path = tmp_path / "workload_adjustments.csv"
        assert not path.exists()

        added = dl.sync_adjustment_names(year_data)

        assert added == ("Alice Adams", "Bob Brown")
        assert path.exists()
        with open(path, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert rows[0] == dl._ADJUSTMENTS_HEADER
        assert rows[1] == ["Alice Adams", "", "", "", "", "", "", ""]
        assert rows[2] == ["Bob Brown", "", "", "", "", "", "", ""]
        assert len(rows) == 3

    def test_all_covered_is_a_true_no_op(self, tmp_path, monkeypatch):
        """When every active staff member is already present, the file must be
        left completely untouched - not just 'no crash', byte-identical."""
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        year_data = _make_year_data([
            StaffData(canonical_name="Alice Adams", active=True),
            StaffData(canonical_name="Bob Brown", active=True),
        ])
        path = tmp_path / "workload_adjustments.csv"
        _write_adjustments_csv(path, [
            {"Person": "Alice Adams"},
            {"Person": "Bob Brown"},
        ])
        before_bytes = path.read_bytes()
        before_mtime = path.stat().st_mtime_ns

        added = dl.sync_adjustment_names(year_data)

        assert added == ()
        assert path.read_bytes() == before_bytes
        assert path.stat().st_mtime_ns == before_mtime

    def test_partial_coverage_appends_only_missing_and_preserves_prefix(self, tmp_path, monkeypatch):
        """Covers an alias spelling (not the exact canonical string) resolving
        via normalize_name, plus a genuinely missing person."""
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        mappings = {
            "Christopher Crispin-Bailey": ["Chris CB", "Christopher", "Christopher Crispin-Bailey"],
        }
        year_data = _make_year_data([
            StaffData(canonical_name="Christopher Crispin-Bailey", active=True),
            StaffData(canonical_name="Zara Zeta", active=True),
        ], mappings=mappings)
        path = tmp_path / "workload_adjustments.csv"
        _write_adjustments_csv(path, [
            {"Person": "Chris CB"},  # alias spelling, not the canonical string
        ])
        before_content = path.read_text(encoding="utf-8")

        added = dl.sync_adjustment_names(year_data)

        assert added == ("Zara Zeta",)
        after_content = path.read_text(encoding="utf-8")
        assert after_content.startswith(before_content)
        assert "Zara Zeta" in after_content
        assert after_content.count("Christopher") == 0  # not duplicated under canonical spelling

    def test_existing_real_adjustment_data_preserved_exactly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        year_data = _make_year_data([
            StaffData(canonical_name="Alice Adams", active=True),
            StaffData(canonical_name="Bob Brown", active=True),
        ])
        path = tmp_path / "workload_adjustments.csv"
        _write_adjustments_csv(path, [
            {"Person": "Alice Adams", "Teaching Adjustment": "+10",
             "Teaching Rationale": "extra marking cover"},
        ])
        before_content = path.read_text(encoding="utf-8")

        added = dl.sync_adjustment_names(year_data)

        assert added == ("Bob Brown",)
        after_content = path.read_text(encoding="utf-8")
        assert after_content.startswith(before_content)
        # The Alice row itself, not just some prefix, is untouched.
        rows = list(csv.reader(after_content.splitlines()))
        alice_row = next(r for r in rows if r and r[0] == "Alice Adams")
        assert alice_row == ["Alice Adams", "+10", "extra marking cover", "", "", "", ""]

    def test_inactive_staff_never_added(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        year_data = _make_year_data([
            StaffData(canonical_name="Alice Adams", active=True),
            StaffData(canonical_name="Retired Rachel", active=False),
        ])
        path = tmp_path / "workload_adjustments.csv"

        added = dl.sync_adjustment_names(year_data)

        assert added == ("Alice Adams",)
        content = path.read_text(encoding="utf-8")
        assert "Retired Rachel" not in content

    def test_two_consecutive_calls_second_is_a_no_op(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        year_data = _make_year_data([
            StaffData(canonical_name="Alice Adams", active=True),
            StaffData(canonical_name="Bob Brown", active=True),
        ])

        first = dl.sync_adjustment_names(year_data)
        assert first == ("Alice Adams", "Bob Brown")

        path = tmp_path / "workload_adjustments.csv"
        after_first = path.read_bytes()

        second = dl.sync_adjustment_names(year_data)
        assert second == ()
        assert path.read_bytes() == after_first

    def test_stale_unresolvable_person_cell_does_not_crash_or_duplicate(self, tmp_path, monkeypatch):
        """A Person cell that normalize_name cannot resolve at all (returns None
        - e.g. a stale placeholder left in the sheet) must not crash sync. The
        row is left exactly as-is (never rewritten), and running sync again
        afterwards must not pile up a second copy of whatever got appended."""
        monkeypatch.setattr(dl, "DATA_DIR", tmp_path)
        year_data = _make_year_data([
            StaffData(canonical_name="Alice Adams", active=True),
        ])
        path = tmp_path / "workload_adjustments.csv"
        _write_adjustments_csv(path, [
            {"Person": "TBD"},  # unresolvable placeholder -> normalize_name returns None
        ])
        before_content = path.read_text(encoding="utf-8")

        added = dl.sync_adjustment_names(year_data)

        # Alice Adams is genuinely missing (the "TBD" row covers no one in
        # particular), so she gets appended; the stale row is untouched.
        assert added == ("Alice Adams",)
        after_content = path.read_text(encoding="utf-8")
        assert after_content.startswith(before_content)
        assert after_content.count("TBD") == 1

        # Idempotent: a second run must not re-add or duplicate anything.
        second = dl.sync_adjustment_names(year_data)
        assert second == ()
        assert path.read_text(encoding="utf-8") == after_content


class TestAdjustmentDeduplicationMerge:
    """_deduplicate_staff() must not drop adjustments/adjustment_warnings when
    merging duplicate-name entries - it rebuilds StaffData from an explicit
    field list with no catch-all, so a forgotten field silently vanishes for
    anyone whose record gets merged (e.g. 'Chris CB' / 'Christopher Crispin-Bailey',
    a real alias pair already in staff_name_lookup.json)."""

    def test_merge_preserves_adjustments_from_both_entries(self):
        mappings = {
            "Christopher Crispin-Bailey": ["Chris CB", "Christopher", "Christopher Crispin-Bailey"],
        }
        adj_a = AdjustmentRecord(category="teaching", mode="delta", value=10.0,
                                  rationale="cover", source_row=2, raw_person="Chris CB")
        adj_b = AdjustmentRecord(category="research", mode="absolute", value=200.0,
                                  rationale="override", source_row=3,
                                  raw_person="Christopher Crispin-Bailey")

        staff = {
            "Chris CB": StaffData(canonical_name="Chris CB", fte=1.0,
                                   adjustments=(adj_a,),
                                   adjustment_warnings=("warn A",)),
            "Christopher Crispin-Bailey": StaffData(
                canonical_name="Christopher Crispin-Bailey", fte=1.0,
                adjustments=(adj_b,),
                adjustment_warnings=("warn B",)),
        }

        merged = dl._deduplicate_staff(staff, mappings)
        assert len(merged) == 1
        result = merged["Christopher Crispin-Bailey"]
        assert set(result.adjustments) == {adj_a, adj_b}
        assert set(result.adjustment_warnings) == {"warn A", "warn B"}

    def test_merge_single_entry_group_keeps_adjustments_untouched(self):
        """A canonical name with only one contributing entry (no merge needed)
        must pass its adjustments through unchanged (entries[0][1] path)."""
        adj = AdjustmentRecord(category="admin", mode="delta", value=5.0,
                                rationale="extra", source_row=2, raw_person="Solo Person")
        staff = {
            "Solo Person": StaffData(canonical_name="Solo Person", fte=1.0, adjustments=(adj,)),
        }
        merged = dl._deduplicate_staff(staff, mappings={})
        assert merged["Solo Person"].adjustments == (adj,)
