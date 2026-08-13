"""
Experimental "New Individual Reports" — a side-by-side variant of the per-staff
HTML report for comparison against the existing Individual Reports.

This module does NOT modify or call generate_per_staff_reports() /
_create_individual_staff_report_html() / _format_teaching_section_for_staff()
in output_generator.py, and the existing "Individual Reports" folder is
untouched by anything here. It reuses the lower-level, purely-structural
formatting helpers (module delivery/practicals/assessment sections, and the
generic detail-section formatter used for research/admin) directly from
output_generator.py, since those already read from WorkloadResult's
structured breakdown fields and duplicating that calculation-display logic
would be redundant and error-prone.

Seven independently-toggleable proposals from WORKLOAD_OUTPUT_REDESIGN_PROMPTS.md
are implemented here, each guarded by a flag in NEW_REPORT_FEATURES:

    C1 headline_summary        - computed headline sentence at the top
    C2 normative_comparison    - actual vs. target split table per category
    C3 header_delta            - total hours + delta vs nominal in the header
    C4 fixed_footer_date       - real generation date instead of a hardcoded literal
    C5 positive_confirmation   - "no issues flagged" message when appropriate
    C6 sort_by_hours           - modules ordered by hours (largest first) instead of A-Z
    C7 standardized_wording    - "First session" label used consistently

With every flag set to False, the output is designed to match the content of
the current Individual Reports as closely as this separate render pathway
allows - useful as a sanity check and as the "remove everything" baseline.
To keep or drop a specific proposal, flip its entry in NEW_REPORT_FEATURES
and regenerate.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from output_generator import (
    OUTPUT_DIR,
    _determine_lecturer_type,
    _format_hours,
    _format_module_assessment_section,
    _format_module_delivery_section,
    _format_module_header,
    _format_module_practicals_section,
    format_detail_section,
)
from data_loader import WorkloadResult, YearData
import config


NEW_REPORT_FEATURES = {
    "headline_summary": True,       # C1
    "normative_comparison": True,   # C2
    "header_delta": True,           # C3
    "fixed_footer_date": True,      # C4
    "positive_confirmation": True,  # C5
    "sort_by_hours": True,          # C6
    "standardized_wording": True,   # C7
}

# Deviation comparison and thresholds are owned by reporting_helpers, shared
# with the department report, so the two surfaces cannot drift apart on what
# counts as "on target".
_compute_category_deviations = reporting_helpers.category_deviations


def _build_headline_summary(r: WorkloadResult, nominal_hours: float) -> str:
    """C1: computed headline sentence, e.g.
    "Total workload is 1,847h against a nominal 1,642h for 1.0 FTE - 12.5% over, mostly from teaching."
    """
    delta_hours = r.total_hours - nominal_hours
    delta_pct = (delta_hours / nominal_hours * 100) if nominal_hours > 0 else 0
    direction = "over" if delta_hours >= 0 else "under"

    sentence = (
        f"Total workload is {r.total_hours:,.0f}h against a nominal {nominal_hours:,.0f}h "
        f"for {r.fte:.1f} FTE &mdash; {abs(delta_pct):.1f}% {direction}"
    )

    deviations = _compute_category_deviations(r)
    if deviations:
        # "mostly from X" - the category with the largest deviation in the same
        # direction as the overall total (over total -> largest positive deviation, etc.)
        candidates = {
            label: d["deviation_pct"] for label, d in deviations.items()
            if (d["deviation_pct"] >= 0) == (delta_hours >= 0)
        }
        if candidates:
            biggest_driver = max(candidates, key=lambda k: abs(candidates[k]))
            sentence += f", mostly from {biggest_driver}"

    return sentence + "."


def _build_normative_comparison_table(r: WorkloadResult) -> str:
    """C2: compact table comparing actual % of total to the contract-type target."""
    deviations = _compute_category_deviations(r)
    if not deviations:
        return (
            '<div class="section-card" style="border-left-color:#999;">'
            '<p style="color:#777;margin:0;">No normative split available for category '
            f'"{r.category or "unknown"}" &mdash; showing actual hours only, no target comparison.</p>'
            '<div style="margin-top:12px;">'
            + "".join(
                f'<div class="detail-item" style="grid-template-columns:2fr 1fr;">'
                f'<span class="detail-name">{label.title()}</span>'
                f'<span class="detail-hours">{getattr(r, f"{label}_hours"):.1f}h</span></div>'
                for label in ("teaching", "research", "admin")
            )
            + "</div></div>"
        )

    _BAND_STYLES = {
        "ok": ("#2e7d32", "#e8f5e9", "On target"),
        "moderate": ("#ef6c00", "#fff3e0", "Moderate"),
        "high": ("#c62828", "#ffebee", "High"),
    }

    rows = []
    for label, d in deviations.items():
        band = reporting_helpers.deviation_band(d["deviation_pct"])
        badge_color, badge_bg, badge_text = _BAND_STYLES[band]

        rows.append(f"""
            <div class="detail-item" style="grid-template-columns:1.2fr 1fr 1fr 1fr;">
                <span class="detail-name">{label.title()}</span>
                <span class="detail-hours">{d['actual_pct']:.1f}% actual</span>
                <span class="detail-hours">{d['target_pct']:.1f}% target</span>
                <span class="detail-activity" style="background:{badge_bg};color:{badge_color};">{badge_text} ({d['deviation_pct']:+.1f}pp)</span>
            </div>""")

    return f"""<div class="section-card" style="border-left-color:#2196F3;">
        <div class="card-header"><span class="card-title">Normative Split Comparison</span></div>
        {''.join(rows)}
    </div>"""


def _build_header_delta(r: WorkloadResult, nominal_hours: float) -> str:
    """C3: total hours + delta meta-items, added alongside FTE/Nominal Hours."""
    delta_hours = r.total_hours - nominal_hours
    delta_pct = (delta_hours / nominal_hours * 100) if nominal_hours > 0 else 0
    sign = "+" if delta_hours >= 0 else ""
    return f"""
        <div class="meta-item">
            <span class="meta-label">Total Hours</span>
            <span class="meta-value">{r.total_hours:,.0f}h</span>
        </div>
        <div class="meta-item">
            <span class="meta-label">Delta vs Nominal</span>
            <span class="meta-value">{sign}{delta_hours:,.0f}h ({sign}{delta_pct:.1f}%)</span>
        </div>"""


def _format_teaching_section_sorted(
    result: WorkloadResult, title: str, hours: float, breakdown: Dict[str, float], css_class: str,
    known_lecturers_per_module: Optional[Dict[str, frozenset]],
    pastoral_breakdown: Dict[str, float],
    project_breakdown: Dict[str, float],
    sort_by_hours: bool,
    standardized_wording: bool,
) -> str:
    """Re-implementation of output_generator._format_teaching_section_for_staff's
    orchestration loop, reusing its per-module formatters, but with an
    optional hours-descending module order (C6) and standardized practicals
    wording (C7) instead of the fixed alphabetical order / legacy wording.
    """
    items_html_parts = []

    module_breakdowns = getattr(result, "teaching_module_breakdowns", {})
    stages: Dict[str, List[Dict[str, Any]]] = {}
    for module_name, mb in module_breakdowns.items():
        code_tuple = mb.get("module_codes", ())
        stages.setdefault(module_name, []).append({
            "stage": module_name,
            "code": code_tuple[0] if code_tuple else "",
            "codes": code_tuple,
            "module_breakdown": mb,
        })

    def _stage_total(modules_in_stage: List[Dict[str, Any]]) -> float:
        total = 0.0
        for mod in modules_in_stage:
            mb = mod.get("module_breakdown", {})
            for key in ["teaching", "practicals", "assessment_setting", "marking"]:
                if key in mb and isinstance(mb[key], (int, float)):
                    total += mb[key]
        return total

    if sort_by_hours:
        stage_order = sorted(stages.keys(), key=lambda s: -_stage_total(stages[s]))
    else:
        stage_order = sorted(stages.keys())

    for stage in stage_order:
        modules_in_stage = stages[stage]
        header_text = _format_module_header(stage, modules_in_stage)

        items_html_parts.append(f"""<div style="margin-bottom:25px;">
            <h4 style="color:#333;margin:0 0 10px 0;border-left:4px solid #2196F3;padding-left:10px;">{header_text}</h4>""")

        for mod in modules_in_stage:
            code = mod["code"]
            module_breakdown = mod["module_breakdown"]
            module_stage = mod.get("stage", "")
            is_new_lecturer = _determine_lecturer_type(result.name, module_stage, known_lecturers_per_module or {})

            items_html_parts.extend(_format_module_delivery_section(module_breakdown, is_new_lecturer, css_class, code))
            items_html_parts.extend(_format_module_practicals_section(
                module_breakdown, css_class, code, is_new_lecturer,
                standardized_wording=standardized_wording,
            ))
            items_html_parts.extend(_format_module_assessment_section(module_breakdown, css_class, code))

        items_html_parts.append("</div>")

        stage_total = _stage_total(modules_in_stage)
        if stage_total > 0:
            items_html_parts.append(f"""<div style="margin-bottom:15px;">
                <p style="font-size:1.1em;color:#4CAF50;margin:0 0 5px 20px;font-weight:bold;">- Total = {_format_hours(stage_total)}</p>
            </div>""")

    if pastoral_breakdown:
        past_hours_total = pastoral_breakdown.get("total", 0.0)
        past_students_total = pastoral_breakdown.get("student_count", 0)
        items_html_parts.append(f"""<div style="margin-bottom:25px;">
            <h4 style="color:#333;margin:0 0 10px 0;border-left:4px solid #2196F3;padding-left:10px;">Pastoral Supervision ({past_hours_total:.1f}h)</h4>
            <div style="margin-left:20px;">
                <div class="detail-item teaching-item">
                    <span class="detail-name">Students</span>
                    <span class="detail-hours">{past_students_total} students x {config.SUPERVISION_MULTIPLIERS['pastoral']}h each = {past_hours_total:.1f}h</span>
                    <span class="detail-activity teaching-activity"></span>
                </div>
            </div>
        </div>""")

    if project_breakdown:
        proj_hours_total = project_breakdown.get("total", 0.0)
        proj_projects_total = project_breakdown.get("project_count", 0)
        proj_level = project_breakdown.get("level", "UG")
        items_html_parts.append(f"""<div style="margin-bottom:25px;">
            <h4 style="color:#333;margin:0 0 10px 0;border-left:4px solid #2196F3;padding-left:10px;">Project Supervision ({proj_hours_total:.1f}h)</h4>
            <div style="margin-left:20px;">
                <div class="detail-item teaching-item">
                    <span class="detail-name">Projects</span>
                    <span class="detail-hours">{proj_projects_total} projects x {proj_level} = {proj_hours_total:.1f}h</span>
                    <span class="detail-activity teaching-activity"></span>
                </div>
            </div>
        </div>""")

    items_html = "".join(items_html_parts)
    return f"""<div class="section-card {css_class}">
        <div class="card-header">
            <span class="card-title">{title}</span>
            <span class="card-total">{hours:.1f}h</span>
        </div>
        {items_html}
        <p style="font-size:0.85em;color:#666;padding-top:10px;">Subtotal: {hours:.1f}h</p>
    </div>"""


def _create_new_style_report_html(r: WorkloadResult, year_data: YearData, features: Dict[str, bool]) -> str:
    css = (
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 30px; background: #f5f5f5; } "
        ".report-container { max-width: 1200px; margin: 0 auto; background: white; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-radius: 8px; } "
        "h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 15px; margin-top: 0; } "
        "h2 { color: #4CAF50; border-left: 4px solid #4CAF50; padding-left: 12px; margin-top: 35px; } "
        "h3 { color: #666; margin: 20px 0 10px 0; font-size: 1.1em; } "
        ".headline { background: #e8f5e9; border-left: 5px solid #4CAF50; border-radius: 6px; padding: 14px 20px; margin-bottom: 20px; font-size: 1.05em; color: #2e5c2e; } "
        ".staff-header { background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 25px; border-radius: 8px; margin-bottom: 30px; } "
        ".staff-name { font-size: 2em; font-weight: bold; } "
        ".staff-meta { display: flex; gap: 40px; margin-top: 10px; font-size: 1.1em; opacity: 0.95; flex-wrap: wrap; } "
        ".meta-item { display: flex; flex-direction: column; align-items: center; min-width: 80px; } "
        ".meta-label { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.8; margin-bottom: 4px; } "
        ".meta-value { font-weight: bold; font-size: 1.3em; } "
        ".section-card { background: #f9f9f9; border-radius: 8px; padding: 25px; margin-top: 20px; border-left: 5px solid #4CAF50; } "
        ".card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; } "
        ".card-title { font-weight: bold; color: #333; font-size: 1.2em; } "
        ".card-total { font-size: 1.4em; font-weight: bold; color: #4CAF50; } "
        ".detail-item { padding: 10px 0; border-bottom: 1px solid #eee; display: grid; grid-template-columns: 2fr 1fr 1.5fr; gap: 15px; align-items: center; } "
        ".detail-item:last-child { border-bottom: none; } "
        ".detail-name { font-weight: 500; color: #555; } "
        ".detail-hours { text-align: right; font-family: monospace; font-size: 1.1em; color: #666; } "
        ".detail-activity { text-align: center; padding: 4px 12px; border-radius: 4px; font-size: 0.85em; font-weight: bold; } "
        ".teaching-activity { background: #e3f2fd; color: #1565c0; } "
        ".research-activity { background: #fff3e0; color: #ef6c00; } "
        ".admin-activity { background: #fce4ec; color: #c2185b; } "
        ".calc-breakdown { font-size: 0.9em; color: #777; margin-top: 10px; padding-top: 15px; border-top: 2px dashed #ddd; line-height: 1.6; } "
        ".assumptions-box, .missing-data-box, .confirmation-box { background: #fff3e0; border-radius: 8px; padding: 20px; margin-top: 30px; } "
        ".assumptions-box h3, .missing-data-box h3 { color: #ef6c00; border-left-color: #ff9800; margin-top: 0; } "
        ".missing-data-box { background: #ffebee; } "
        ".missing-data-box h3 { color: #c62828; border-left-color: #e53935; } "
        ".confirmation-box { background: #e8f5e9; color: #2e5c2e; padding: 14px 20px; margin-top: 20px; } "
        ".footer { text-align: center; margin-top: 40px; padding-top: 20px; border-top: 2px solid #eee; font-size: 0.85em; color: #888; } "
    )

    teaching_breakdown = getattr(r, "teaching_breakdown", {}) or {}
    research_breakdown = getattr(r, "research_breakdown", {}) or {}
    admin_breakdown = getattr(r, "admin_breakdown", {}) or {}
    nominal_hours = r.nominal_hours or config.NOMINAL_WORKING_HOURS_PER_YEAR * r.fte
    pastoral_breakdown = getattr(r, "pastoral_breakdown", {}) or {}
    project_breakdown = getattr(r, "project_breakdown", {}) or {}

    # Teaching section: custom orchestration (reuses per-module formatters) so
    # C6/C7 can be applied; falls back to the plain "no activities" card if empty.
    if not teaching_breakdown or all(
        (v == 0 if isinstance(v, (int, float)) else False) for v in teaching_breakdown.values()
    ):
        teaching_section = f"""<div class="section-card teaching-item">
            <div class="card-header"><span class="card-title">Teaching Activities</span><span class="card-total">{r.teaching_hours:.1f}h</span></div>
            <p>No activities recorded for this category.</p>
        </div>"""
    else:
        teaching_section = _format_teaching_section_sorted(
            r, "Teaching Activities", r.teaching_hours, teaching_breakdown, "teaching-item",
            year_data.known_lecturers_per_module,
            pastoral_breakdown, project_breakdown,
            sort_by_hours=features["sort_by_hours"],
            standardized_wording=features["standardized_wording"],
        )

    # Research/admin sections are unchanged by any of C1-C7, and format_detail_section
    # already sorts their line items by hours descending - reused as-is.
    research_section = format_detail_section(r, "Research Activities", r.research_hours, research_breakdown, "research-item")
    admin_section = format_detail_section(r, "Admin Activities", r.admin_hours, admin_breakdown, "admin-item")

    # C1
    headline_html = ""
    if features["headline_summary"]:
        headline_html = f'<div class="headline">{_build_headline_summary(r, nominal_hours)}</div>'

    # C2
    normative_html = ""
    if features["normative_comparison"]:
        normative_html = _build_normative_comparison_table(r)

    # C3
    header_meta_extra = ""
    if features["header_delta"]:
        header_meta_extra = _build_header_delta(r, nominal_hours)

    # C5
    assumptions = getattr(r, "assumptions", ()) or ()
    missing_data = getattr(r, "missing_data", ()) or ()
    if assumptions:
        assumptions_section = f"""<div class="assumptions-box">
            <h3>Assumptions Made</h3>
            <ul>{''.join(f'<li>{a}</li>' for a in assumptions)}</ul>
        </div>"""
    else:
        assumptions_section = ""
    if missing_data:
        missing_data_section = f"""<div class="missing-data-box">
            <h3>Missing Data</h3>
            <ul>{''.join(f'<li>{m}</li>' for m in missing_data)}</ul>
            <p>Data marked as missing may affect the accuracy of this report.</p>
        </div>"""
    else:
        missing_data_section = ""
    confirmation_section = ""
    if features["positive_confirmation"] and not assumptions and not missing_data:
        confirmation_section = '<div class="confirmation-box">No data-quality issues flagged for this report.</div>'

    # C4
    if features["fixed_footer_date"]:
        generated_line = f"Generated on {datetime.now().strftime('%Y-%m-%d')} for academic year {year_data.year_label}"
    else:
        generated_line = f"Generated on 2026-07-14 for academic year {year_data.year_label}"

    total_for_display = r.total_hours

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Workload Report (New Style) - {r.name}</title>
    <style>{css}</style>
</head>
<body>
    <div class="report-container">
        {headline_html}
        <div class="staff-header">
            <div class="staff-name">{r.name}</div>
            <div class="staff-meta" style='flex-wrap:wrap;gap:20px'>
                <div class="meta-item">
                    <span class="meta-label">FTE</span>
                    <span class="meta-value">{r.fte:.2f}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Nominal Hours</span>
                    <span class="meta-value">{nominal_hours:.0f}h</span>
                </div>
                {header_meta_extra}
            </div>

            <div style="margin-top:25px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.3);">
                <h4 style="color:white;margin:0 0 15px 0;font-size:1em;">Overall Workload Summary</h4>
                <div style="display:flex;flex-direction:column;gap:8px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.2);">
                        <span style="color:white;font-size:1em;">Total Workload</span>
                        <strong style="color:white;font-size:1.3em;">{total_for_display:,.1f}h</strong>
                    </div>
                    <div style="display:flex;justify-content:space-between;align-items:center;padding-left:20px;border-bottom:1px solid rgba(255,255,255,0.1);">
                        <span style="color:white;font-size:0.9em;">Teaching</span>
                        <strong style="color:#e3f2fd;font-size:1.1em;">{r.teaching_hours:,.1f}h</strong>
                    </div>
                    <div style="display:flex;justify-content:space-between;align-items:center;padding-left:20px;border-bottom:1px solid rgba(255,255,255,0.1);">
                        <span style="color:white;font-size:0.9em;">Research</span>
                        <strong style="color:#fff3e0;font-size:1.1em;">{r.research_hours:,.1f}h</strong>
                    </div>
                    <div style="display:flex;justify-content:space-between;align-items:center;padding-left:20px;border-bottom:1px solid rgba(255,255,255,0.1);">
                        <span style="color:white;font-size:0.9em;">Admin</span>
                        <strong style="color:#fce4ec;font-size:1.1em;">{r.admin_hours:,.1f}h</strong>
                    </div>
                </div>
            </div>
        </div>

        {normative_html}
        {teaching_section}
        {research_section}
        {admin_section}

        <h2>Calculation Breakdown</h2>
        <div class="section-card">
            <p>The workload calculation follows the model formula:</p>
            <p style="font-family: monospace; font-size: 1.1em; text-align: center; margin: 20px 0;">
                Total = Teaching + Research (Protected + Additional) + Admin
            </p>
            <div class="calc-breakdown">
                <h3>Summary Totals</h3>
                <ul>
                    <li><strong>Teaching:</strong> {r.teaching_hours:.1f}h</li>
                    <li><strong>Research (protected baseline):</strong> {config.PROTECTED_RESEARCH_BASELINE * r.fte:.1f}h</li>
                    <li><strong>Research (additional - grants, supervision):</strong> {max(0, r.research_hours - config.PROTECTED_RESEARCH_BASELINE * r.fte):.1f}h</li>
                    <li><strong>Admin:</strong> {r.admin_hours:,.1f}h</li>
                </ul>
                <p style="margin-top:20px;"><em>Total: {total_for_display:,.1f} hours = {r.teaching_hours:,.1f} + {config.PROTECTED_RESEARCH_BASELINE * r.fte:.1f} + {max(0, r.research_hours - config.PROTECTED_RESEARCH_BASELINE * r.fte):.1f} + {r.admin_hours:,.1f}</em></p>
            </div>
        </div>

        {assumptions_section}
        {missing_data_section}
        {confirmation_section}

        <div class="footer">
            <p>{generated_line}</p>
            <p><em>This report was automatically generated by the Workload Model calculator (new-style variant).</em></p>
        </div>
    </div>
</body>
</html>"""

    return html


def generate_new_style_individual_reports(
    results: List[WorkloadResult], year_data: YearData, output_dir: str = None,
    features: Dict[str, bool] = None,
):
    """
    Generate the experimental "New Individual Reports" variant for every staff
    member, alongside (not replacing) the existing Individual Reports.

    Args:
        results: WorkloadResult list from calculate_workload()
        year_data: YearData used for the run
        output_dir: Base output directory (default: OUTPUT_DIR); reports are
            written to "{output_dir}/New Individual Reports/"
        features: Optional override of NEW_REPORT_FEATURES (e.g. to preview a
            specific combination without editing the module-level default)
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    features = features if features is not None else NEW_REPORT_FEATURES

    report_dir = os.path.join(output_dir, "New Individual Reports")
    os.makedirs(report_dir, exist_ok=True)

    for r in results:
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in r.name)
        report_path = os.path.join(report_dir, f"{safe_name}_workload.html")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(_create_new_style_report_html(r, year_data, features))

    print(f"New-style individual reports saved to {report_dir}")
