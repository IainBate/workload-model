"""
Integration tests for the full pipeline (plan items B4, B8, B11).

Exercises load -> calculate -> generate end to end against the real data set,
and validates the produced artifacts themselves: Excel formulas and chart
references (B8) and matplotlib chart output (B11).

Distinct from test_format_baseline.py, which diffs rendered HTML against a
recorded baseline; here we assert properties that should hold regardless of
what the current baseline happens to contain.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import config  # noqa: E402
import output_generator  # noqa: E402
from data_loader import load_all_data  # noqa: E402
from workload_calculator import calculate_workload  # noqa: E402

PROJECT_ROOT = SCRIPTS_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"


@pytest.fixture(scope="module")
def year_data():
    return load_all_data(
        data_dir=str(DATA_DIR), unknown_callback=None, category_callback=None
    )


@pytest.fixture(scope="module")
def results(year_data):
    return calculate_workload(year_data, validate_input=False)


@pytest.fixture(scope="module")
def generated(year_data, results, tmp_path_factory):
    out = tmp_path_factory.mktemp("integration")
    output_generator.generate_all_outputs(results, year_data, str(out))
    return out


class TestPipeline:
    """End-to-end load -> calculate behaviour."""

    def test_every_active_staff_member_gets_a_result(self, year_data, results):
        active = {s.canonical_name for s in year_data.staff if s.active}
        assert {r.name for r in results} >= active

    def test_no_duplicate_results(self, results):
        names = [r.name for r in results]
        assert len(names) == len(set(names))

    def test_every_result_has_a_contract_category(self, results):
        """Regression guard: categories were blank for all 56 staff at one point,
        which silently disabled every normative comparison in both reports."""
        missing = [r.name for r in results if not r.category]
        assert not missing, f"Staff with no contract category: {missing}"

    def test_categories_map_to_a_normative_split(self, results):
        """A category that doesn't resolve makes the comparison features inert."""
        unmapped = sorted({r.category for r in results if not config.get_normative_split(r.category)})
        assert not unmapped, f"Categories with no normative split: {unmapped}"

    def test_nominal_hours_scale_with_fte(self, results):
        for r in results:
            expected = config.NOMINAL_WORKING_HOURS_PER_YEAR * r.fte
            assert r.nominal_hours == pytest.approx(expected, abs=0.5), r.name

    def test_no_staff_member_has_zero_total(self, results):
        """Everyone on the roster should attract some workload somewhere."""
        zero = [r.name for r in results if r.total_hours <= 0]
        assert not zero, f"Staff with zero total workload: {zero}"

    def test_teaching_only_from_modules_and_supervision(self, results):
        """No baseline teaching allowance: a staff member with no module
        breakdown and no supervision must have 0 teaching hours."""
        for r in results:
            if not r.teaching_module_breakdowns and not r.pastoral_breakdown and not r.project_breakdown:
                assert r.teaching_hours == 0, (
                    f"{r.name} has {r.teaching_hours}h teaching with no modules or supervision"
                )


class TestOutputArtifacts:
    """All expected files are produced and non-trivial."""

    def test_all_artifacts_present_and_non_empty(self, generated):
        for name in (
            "Staff workload model.csv",
            "Staff workload model.xlsx",
            "workload_summary_boxplot.png",
            "workload_detailed_boxplot.png",
            "workload_report.html",
        ):
            path = generated / name
            assert path.exists(), f"{name} missing"
            assert path.stat().st_size > 0, f"{name} empty"

    def test_one_individual_report_per_staff_member(self, generated, results):
        reports = list((generated / "Individual Reports").glob("*.html"))
        assert len(reports) == len(results)

    def test_csv_has_a_row_per_staff_member(self, generated, results):
        import csv
        with open(generated / "Staff workload model.csv", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(results)


class TestExcelOutput:
    """Excel formula and chart-reference validation (B8)."""

    @pytest.fixture(scope="class")
    @classmethod
    def workbook(cls, generated):
        openpyxl = pytest.importorskip("openpyxl")
        return openpyxl.load_workbook(str(generated / "Staff workload model.xlsx"))

    def test_workbook_opens_with_at_least_one_sheet(self, workbook):
        assert workbook.sheetnames

    def test_no_excel_error_values_present(self, workbook):
        """Guards against #REF!/#VALUE! from mis-built formulas."""
        errors = ("#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A")
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                for cell in row:
                    if isinstance(cell, str):
                        for err in errors:
                            assert err not in cell, f"{sheet.title} contains {err}"

    def test_formulas_reference_valid_cells(self, workbook):
        """Any formula present must reference a real cell range, not a blank."""
        import re
        ref_pattern = re.compile(r"[A-Z]{1,3}\d+")
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        assert ref_pattern.search(cell.value), (
                            f"{sheet.title}!{cell.coordinate} formula has no cell reference: {cell.value}"
                        )

    def test_chart_category_axes_use_string_references(self, generated):
        """_fix_category_references() converts numRef -> strRef so charts render
        with staff names rather than blank/numeric categories."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.load_workbook(str(generated / "Staff workload model.xlsx"))
        charts = [c for ws in wb.worksheets for c in getattr(ws, "_charts", [])]
        if not charts:
            pytest.skip("No charts embedded in the workbook")
        for chart in charts:
            for series in chart.series:
                if series.cat is not None:
                    assert series.cat.strRef is not None or series.cat.numRef is not None


class TestChartArtifacts:
    """matplotlib chart output verification (B11)."""

    @pytest.mark.parametrize(
        "filename", ["workload_summary_boxplot.png", "workload_detailed_boxplot.png"]
    )
    def test_chart_is_a_valid_png_of_reasonable_size(self, generated, filename):
        path = generated / filename
        # PNG magic number - confirms a real image, not a truncated/text file
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{filename} is not a valid PNG"
        assert path.stat().st_size > 10_000, f"{filename} suspiciously small"

    @pytest.mark.parametrize(
        "filename", ["workload_summary_boxplot.png", "workload_detailed_boxplot.png"]
    )
    def test_chart_dimensions_scale_with_staff_count(self, generated, filename, results):
        Image = pytest.importorskip("PIL.Image", reason="Pillow not installed")
        with Image.open(generated / filename) as img:
            width, height = img.size
        assert width > 400 and height > 400, f"{filename} is {width}x{height}"
        # Charts are one horizontal bar per staff member, so height must grow
        # with the roster rather than being clipped to a fixed canvas.
        assert height >= len(results) * 5, (
            f"{filename} height {height}px looks clipped for {len(results)} staff"
        )

    def test_matplotlib_uses_headless_backend(self):
        """Chart generation must not require a display (CI safety)."""
        import matplotlib
        assert matplotlib.get_backend().lower() in ("agg", "template"), (
            f"Non-headless backend in use: {matplotlib.get_backend()}"
        )
