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

import data_loader as dl  # noqa: E402
import validation  # noqa: E402
from data_loader import ModuleData, StaffData  # noqa: E402
from workload_calculator import _classify_marking_levels  # noqa: E402


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
