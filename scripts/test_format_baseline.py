"""
Display-format regression tests (plan item B2).

Complements test_calculation_baseline.py (B1): that file asserts the *numbers*
are right, this one asserts the *rendering* hasn't drifted. Splitting them means
a cosmetic edit fails only here (expected, re-baseline it), while a changed hour
value fails only there (investigate).

This is also the safety net that gates the B10 `output_generator.py`
pure-rendering refactor: that refactor is supposed to be behaviour-preserving,
so these tests passing unchanged across it is the evidence for that claim.

Comparison is whitespace-normalized and date-normalized so it doesn't fail on
reflowed HTML or simply being run on a different day.

To re-baseline after an intended display change:

    python generate_baseline.py
"""

import re
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import load_all_data  # noqa: E402
from workload_calculator import calculate_workload  # noqa: E402
import output_generator  # noqa: E402

PROJECT_ROOT = SCRIPTS_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
BASELINE_DIR = PROJECT_ROOT / "baseline"

_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_WS_RE = re.compile(r"\s+")


def normalize_html(html: str) -> str:
    """Collapse whitespace and mask dates so comparison is stable across runs."""
    html = _DATE_RE.sub("<DATE>", html)
    html = _WS_RE.sub(" ", html)
    return html.strip()


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """Generate a full set of outputs into a temp dir (never touches output/)."""
    out_dir = tmp_path_factory.mktemp("format_check")
    year_data = load_all_data(
        data_dir=str(DATA_DIR), unknown_callback=None, category_callback=None
    )
    results = calculate_workload(year_data, validate_input=False)
    output_generator.generate_all_outputs(results, year_data, str(out_dir))
    return out_dir


def _baseline_individual_reports():
    d = BASELINE_DIR / "Individual Reports"
    return sorted(d.glob("*.html")) if d.exists() else []


@pytest.mark.skipif(
    not (BASELINE_DIR / "Individual Reports").exists(),
    reason="No baseline Individual Reports - run generate_baseline.py first",
)
def test_individual_reports_match_baseline_format(generated):
    """Every per-staff report renders identically to its baseline."""
    baseline_files = _baseline_individual_reports()
    assert baseline_files, "Baseline Individual Reports directory is empty"

    generated_dir = generated / "Individual Reports"
    mismatches = []
    for baseline_file in baseline_files:
        generated_file = generated_dir / baseline_file.name
        if not generated_file.exists():
            mismatches.append(f"{baseline_file.name}: not generated")
            continue
        expected = normalize_html(baseline_file.read_text(encoding="utf-8"))
        actual = normalize_html(generated_file.read_text(encoding="utf-8"))
        if expected != actual:
            mismatches.append(f"{baseline_file.name}: rendered output differs")

    assert not mismatches, (
        f"{len(mismatches)} individual report(s) differ from baseline:\n  "
        + "\n  ".join(mismatches[:15])
    )


def test_no_extra_or_missing_individual_reports(generated):
    """The set of staff getting a report hasn't silently changed."""
    baseline_names = {f.name for f in _baseline_individual_reports()}
    if not baseline_names:
        pytest.skip("No baseline Individual Reports")
    generated_names = {f.name for f in (generated / "Individual Reports").glob("*.html")}
    assert generated_names == baseline_names


@pytest.mark.skipif(
    not (BASELINE_DIR / "workload_report.html").exists(),
    reason="No baseline department report - run generate_baseline.py first",
)
def test_department_report_matches_baseline_format(generated):
    """The department dashboard renders identically to its baseline."""
    expected = normalize_html(
        (BASELINE_DIR / "workload_report.html").read_text(encoding="utf-8")
    )
    actual = normalize_html(
        (generated / "workload_report.html").read_text(encoding="utf-8")
    )
    assert expected == actual, "Department report rendering differs from baseline"


def test_all_expected_artifacts_produced(generated):
    """Smoke test: the pipeline produces every artifact, all non-empty (B7)."""
    expected_files = [
        "Staff workload model.csv",
        "Staff workload model.xlsx",
        "workload_summary_boxplot.png",
        "workload_detailed_boxplot.png",
        "workload_report.html",
    ]
    for name in expected_files:
        path = generated / name
        assert path.exists(), f"{name} was not generated"
        assert path.stat().st_size > 0, f"{name} is empty"

    individual = list((generated / "Individual Reports").glob("*.html"))
    assert individual, "No individual reports generated"
    for f in individual:
        assert f.stat().st_size > 0, f"{f.name} is empty"


def test_individual_reports_have_expected_structure(generated):
    """Each report contains the sections the layout depends on.

    Structural rather than byte-exact, so it stays meaningful after an
    intentional re-baseline (and would catch a section vanishing entirely).
    """
    for report in sorted((generated / "Individual Reports").glob("*.html"))[:10]:
        html = report.read_text(encoding="utf-8")
        for fragment in (
            '<div class="staff-header">',
            "Overall Workload Summary",
            "Teaching Activities",
            "Research Activities",
            "Admin Activities",
            "Calculation Breakdown",
            '<div class="footer">',
        ):
            assert fragment in html, f"{report.name} is missing {fragment!r}"


def test_no_unrendered_placeholders(generated):
    """Catch f-string/template slips leaking into shipped HTML."""
    suspicious = ["{r.", "{self.", "None h", ">nan<", "NaN", "{'", "= =", "@ x"]
    for report in sorted((generated / "Individual Reports").glob("*.html")):
        html = report.read_text(encoding="utf-8")
        for token in suspicious:
            assert token not in html, f"{report.name} contains suspicious text {token!r}"


def test_detail_lines_do_not_end_on_operator(generated):
    """Guards the 'truncated detail line' class of bug (e.g. a trailing '=').

    Was called out in academic_workload_test_strategy.md as a real past defect.
    """
    dangling = re.compile(r"(=|\+|×|/)\s*</span>")
    for report in sorted((generated / "Individual Reports").glob("*.html")):
        html = report.read_text(encoding="utf-8")
        match = dangling.search(html)
        assert match is None, (
            f"{report.name} has a detail line ending on an operator: "
            f"...{html[max(0, match.start() - 60):match.end()]}"
        )
