"""
Output generation for the workload calculator.
Produces:
1. Staff workload model CSV (summary + detail columns)
2. Summary stacked bar chart (PNG and embedded in Excel)
3. Detailed stacked bar chart (PNG and embedded in Excel)
4. HTML report with embedded images
5. Excel (.xlsx) file with formulas and proper formatting

Uses openpyxl for Excel generation.
"""

import csv
import os
import re
from pathlib import Path
from typing import List, Optional

# Get project root directory (parent of scripts folder)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = Path(os.path.dirname(SCRIPTS_DIR))

OUTPUT_DIR = PROJECT_ROOT / "output"

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference, Series
from openpyxl.chart.data_source import StrRef
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.chart.label import DataLabelList

import config
from data_loader import WorkloadResult, YearData


def _fix_category_references(chart: BarChart) -> None:
    """
    Fix category axis references from numRef to strRef.

    openpyxl's BarChart.set_categories() always creates NumRef even when
    referencing text cells. This causes charts to render incorrectly with
    text categories (staff names). Convert to StrRef for proper rendering.
    """
    for ser in chart.series:
        if hasattr(ser.cat, 'numRef') and ser.cat.numRef is not None:
            # Preserve the formula reference but use strRef instead of numRef
            ser.cat.strRef = StrRef(f=ser.cat.numRef.f)
            ser.cat.numRef = None


def generate_csv(results: List[WorkloadResult], filepath: str = "Staff workload model.csv"):
    """Generate the staff workload model CSV output."""
    # If filepath is just a filename, prepend OUTPUT_DIR
    if not os.path.isabs(filepath) and "/" not in filepath and "\\" not in filepath:
        filepath = os.path.join(OUTPUT_DIR, filepath)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Header
        writer.writerow([
            "Name", "FTE", "Total Hours",
            "Teaching Hours", "Research Hours", "Admin Hours",
            "Teaching Detail", "Research Detail", "Admin Detail",
            "Assumptions", "Missing Data",
        ])

        for r in results:
            writer.writerow([
                r.name,
                r.fte,
                f"{r.total_hours:.1f}",
                f"{r.teaching_hours:.1f}",
                f"{r.research_hours:.1f}",
                f"{r.admin_hours:.1f}",
                r.teaching_detail,
                r.research_detail,
                r.admin_detail,
                "; ".join(r.assumptions) if r.assumptions else "None",
                "; ".join(r.missing_data) if r.missing_data else "None",
            ])

    print(f"CSV output written to {filepath}")


def _create_boxplot(results: List[WorkloadResult], title: str, components: List[str],
                    component_labels: List[str], output_path: str):
    """Create a stacked horizontal bar chart for workload components."""
    names = [r.name for r in results]
    data = [[getattr(r, comp) for r in results] for comp in components]

    # Dynamic figure size based on staff count
    fig, ax = plt.subplots(figsize=(16, max(8, len(names) * 0.4)))
    fig.suptitle(title, fontsize=14, fontweight="bold")

    bottom = [0.0] * len(names)
    colors = ["#4CAF50", "#2196F3", "#FF9800", "#9C27B0", "#F44336", "#795548"]

    for i, (comp, label) in enumerate(zip(components, component_labels)):
        values = data[i]
        bars = ax.barh(names, values, left=bottom, color=colors[i % len(colors)],
                       label=label, edgecolor="white", height=0.6)
        for j, (bar, val) in enumerate(zip(bars, values)):
            if val > 10:  # Only label significant values
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height() / 2,
                        f"{val:.0f}", ha="center", va="center", fontsize=7, color="white")
        bottom = [b + v for b, v in zip(bottom, data[i])]

    # Add expected workload lines
    fte_values = [r.fte for r in results]
    for comp, label, color in zip(components, component_labels, colors):
        expected = [r.nominal_hours * getattr(config.CONTRACT_NORMATIVE_DIVISIONS.get("TR_staff", {}),
                                               comp.lower().replace(" hours", "").replace(" ", "_"), 0)
                    for r in results]

    ax.set_xlabel("Hours")
    ax.set_ylabel("Staff")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Boxplot saved to {output_path}")


def generate_boxplots(results: List[WorkloadResult], output_dir: str = None):
    """Generate both summary and detailed stacked boxplots."""
    if output_dir is None:
        output_dir = OUTPUT_DIR

    names = [r.name for r in results]

    # --- Summary boxplot ---
    summary_components = ["teaching_hours", "research_hours", "admin_hours"]
    summary_labels = ["Teaching", "Research", "Administration"]

    # Larger figure size for better readability
    fig, ax = plt.subplots(figsize=(18, max(10, len(names) * 0.45)))
    fig.suptitle("Workload Summary: Teaching, Research & Administration",
                 fontsize=16, fontweight="bold")

    bottom = [0.0] * len(names)
    colors = ["#4CAF50", "#2196F3", "#FF9800"]

    for i, (comp, label) in enumerate(zip(summary_components, summary_labels)):
        values = [getattr(r, comp) for r in results]
        bars = ax.barh(names, values, left=bottom, color=colors[i],
                       label=label, edgecolor="white", height=0.7)
        for j, (bar, val) in enumerate(zip(bars, values)):
            if val > 15:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_y() + bar.get_height() / 2,
                        f"{val:.0f}", ha="center", va="center",
                        fontsize=8, color="white", fontweight="bold")
        bottom = [b + v for b, v in zip(bottom, values)]

    # Add expected workload reference lines (40% of nominal for ART staff)
    for y_pos, (name, fte) in enumerate(zip(names, [r.fte for r in results])):
        expected_teaching = config.NOMINAL_WORKING_HOURS_PER_YEAR * fte * 0.40
        expected_research = config.NOMINAL_WORKING_HOURS_PER_YEAR * fte * 0.40
        ax.axvline(x=expected_teaching, color="#4CAF50", alpha=0.3, linestyle="--", linewidth=1)
        ax.axvline(x=expected_teaching + expected_research, color="#2196F3", alpha=0.3,
                   linestyle="--", linewidth=1)

    # Total workload line
    total_expected = config.NOMINAL_WORKING_HOURS_PER_YEAR
    ax.axvline(x=total_expected, color="black", alpha=0.4, linestyle="-.", linewidth=1.5,
               label=f"Total Available ({total_expected}h)")

    ax.set_xlabel("Hours", fontsize=12)
    ax.set_ylabel("Staff", fontsize=12)
    ax.legend(loc="lower right", fontsize=10)
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()

    summary_path = os.path.join(output_dir, "workload_summary_boxplot.png")
    plt.savefig(summary_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Summary boxplot saved to {summary_path}")

    # --- Detailed boxplot ---
    detailed_components = ["teaching_hours", "research_hours", "admin_hours"]
    detailed_labels = ["Teaching", "Research", "Administration"]

    fig2, ax2 = plt.subplots(figsize=(18, max(10, len(names) * 0.45)))
    fig2.suptitle("Workload Breakdown: Detailed Components", fontsize=16, fontweight="bold")

    bottom2 = [0.0] * len(names)
    detailed_colors = ["#4CAF50", "#81C784", "#2196F3", "#64B5F6", "#FF9800", "#FFB74D"]

    for i, (comp, label) in enumerate(zip(detailed_components, detailed_labels)):
        values = [getattr(r, comp) for r in results]
        bars = ax2.barh(names, values, left=bottom2, color=detailed_colors[i],
                        label=label, edgecolor="white", height=0.7)
        for j, (bar, val) in enumerate(zip(bars, values)):
            if val > 15:
                ax2.text(bar.get_x() + bar.get_width() / 2,
                         bar.get_y() + bar.get_height() / 2,
                         f"{val:.0f}", ha="center", va="center",
                         fontsize=8, color="white", fontweight="bold")
        bottom2 = [b + v for b, v in zip(bottom2, values)]

    total_expected2 = config.NOMINAL_WORKING_HOURS_PER_YEAR
    ax2.axvline(x=total_expected2, color="black", alpha=0.4, linestyle="-.", linewidth=1.5,
                label=f"Total Available ({total_expected2}h)")

    ax2.set_xlabel("Hours", fontsize=12)
    ax2.set_ylabel("Staff", fontsize=12)
    ax2.legend(loc="lower right", fontsize=10)
    ax2.grid(axis="x", alpha=0.3)
    plt.tight_layout()

    detailed_path = os.path.join(output_dir, "workload_detailed_boxplot.png")
    plt.savefig(detailed_path, dpi=200, bbox_inches="tight")
    plt.close(fig2)
    print(f"Detailed boxplot saved to {detailed_path}")


def generate_excel_with_formulas(results: List[WorkloadResult], year_data: YearData,
                                  output_dir: str = None):
    """
    Generate an Excel (.xlsx) file with calculated values and formulas.

    This creates a properly formatted spreadsheet that can be:
    1. Used directly
    2. Uploaded to Google Sheets without formula errors

    Args:
        results: List of WorkloadResult objects
        year_data: YearData object for metadata
        output_dir: Output directory (default: output/)

    The spreadsheet includes:
    - Staff workload summary table
    - Formulas for calculating totals from components
    - Properly sized charts (not compressed)
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Staff Workload"

    # Remove any extra default sheets that may exist
    for sheet_name in list(wb.sheetnames):
        if sheet_name != "Staff Workload":
            del wb[sheet_name]

    # Define styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4CAF50", end_color="4CAF50", fill_type="solid")
    subheader_fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")

    border_thin = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Write header row
    headers = [
        "Name", "FTE", "Total Hours", "Teaching Hours", "Research Hours",
        "Admin Hours", "Teaching Detail", "Research Detail", "Admin Detail",
        "Assumptions", "Missing Data"
    ]

    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    # Write data rows
    for row_idx, r in enumerate(results, start=2):
        ws.cell(row=row_idx, column=1, value=r.name)
        ws.cell(row=row_idx, column=2, value=r.fte)

        # Total hours - static value (total of teaching + research + admin)
        total_cell = ws.cell(row=row_idx, column=3, value=r.total_hours)
        total_cell.number_format = "0.0"

        ws.cell(row=row_idx, column=4, value=r.teaching_hours).number_format = "0.0"
        ws.cell(row=row_idx, column=5, value=r.research_hours).number_format = "0.0"
        ws.cell(row=row_idx, column=6, value=r.admin_hours).number_format = "0.0"

        # Detail columns - wrap text
        for col, detail in enumerate([r.teaching_detail, r.research_detail, r.admin_detail], start=7):
            cell = ws.cell(row=row_idx, column=col, value=detail)
            cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

        # Assumptions and Missing Data
        assumptions_cell = ws.cell(row=row_idx, column=10,
                                   value="; ".join(r.assumptions) if r.assumptions else "None")
        assumptions_cell.alignment = Alignment(wrap_text=True)

        missing_cell = ws.cell(row=row_idx, column=11,
                               value="; ".join(r.missing_data) if r.missing_data else "None")
        missing_cell.alignment = Alignment(wrap_text=True)

    # Apply border to all data cells
    for row in range(1, len(results) + 2):
        for col in range(1, 12):
            ws.cell(row=row, column=col).border = border_thin

    # Auto-fit column widths (rough approximation)
    column_widths = {
        'A': 25,  # Name
        'B': 8,   # FTE
        'C': 14,  # Total Hours
        'D': 16,  # Teaching Hours
        'E': 16,  # Research Hours
        'F': 14,  # Admin Hours
        'G': 40,  # Teaching Detail
        'H': 35,  # Research Detail
        'I': 30,  # Admin Detail
        'J': 25,  # Assumptions
        'K': 25,  # Missing Data
    }

    for col, width in column_widths.items():
        ws.column_dimensions[col].width = width

    # Freeze header row
    ws.freeze_panes = "A2"

    # Create chart sheet - make it much larger for better visibility
    chart_ws = wb.create_sheet(title="Workload Charts")
    chart_ws.sheet_view.zoomScale = 80  # 80% zoom for better fit

    # Add summary bar chart (horizontal) - significantly larger
    chart1 = BarChart()
    chart1.type = "bar"
    chart1.style = 10
    chart1.title = "Workload Summary: Teaching, Research & Administration"
    chart1.y_axis.title = "Hours"
    chart1.x_axis.title = "Staff"
    # Larger dimensions for better readability (width=80, height=60)
    chart1.width = 80
    chart1.height = 60

    # Data for chart
    categories = Reference(ws, min_row=2, max_row=len(results) + 1, min_col=1)

    teaching_data = Reference(ws, min_row=1, max_row=len(results) + 1, min_col=4)
    research_data = Reference(ws, min_row=1, max_row=len(results) + 1, min_col=5)
    admin_data = Reference(ws, min_row=1, max_row=len(results) + 1, min_col=6)

    chart1.add_data(teaching_data, titles_from_data=True)
    chart1.add_data(research_data, titles_from_data=True)
    chart1.add_data(admin_data, titles_from_data=True)

    chart1.set_categories(categories)
    _fix_category_references(chart1)  # Fix numRef → strRef for text categories

    # For horizontal bar charts (barDir=bar), catAx is vertical (staff names)
    # and valAx is horizontal (hours). Swap titles to match.
    chart1.y_axis.title = "Hours"
    chart1.x_axis.title = "Staff"

    # Make data labels more readable
    chart1.dataLabels = DataLabelList()
    chart1.dataLabels.showVal = True
    chart1.dataLabels.showCatName = True

    # Position chart with margins for better layout
    chart1.anchor = "A1"
    chart_ws.add_chart(chart1, "A1")

    # Create a second sheet with detailed breakdown
    detail_ws = wb.create_sheet(title="Detailed Breakdown")

    # Add header
    detail_headers = ["Name", "Teaching", "Research", "Admin", "Total"]
    for col, header in enumerate(detail_headers, start=1):
        cell = detail_ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill

    # Add data with formulas
    for row_idx, r in enumerate(results, start=2):
        detail_ws.cell(row=row_idx, column=1, value=r.name)

        # Teaching hours
        detail_ws.cell(row=row_idx, column=2, value=r.teaching_hours).number_format = "0.0"

        # Research hours
        detail_ws.cell(row=row_idx, column=3, value=r.research_hours).number_format = "0.0"

        # Admin hours
        detail_ws.cell(row=row_idx, column=4, value=r.admin_hours).number_format = "0.0"

        # Total with formula
        total_formula = detail_ws.cell(row=row_idx, column=5,
                                        value=f"=SUM(B{row_idx}:D{row_idx})")
        total_formula.number_format = "0.0"

    # Auto-fit columns
    for col in ['A', 'B', 'C', 'D', 'E']:
        detail_ws.column_dimensions[col].width = 18

    detail_ws.freeze_panes = "A2"

    # Add detailed bar chart to this sheet - larger size
    chart2 = BarChart()
    chart2.type = "bar"
    chart2.style = 12
    chart2.title = "Detailed Workload Breakdown"
    chart2.y_axis.title = "Hours"
    chart2.x_axis.title = "Staff"
    # Larger dimensions for better readability (width=80, height=60)
    chart2.width = 80
    chart2.height = 60

    detail_categories = Reference(detail_ws, min_row=2, max_row=len(results) + 1, min_col=1)
    detail_teaching = Reference(detail_ws, min_row=1, max_row=len(results) + 1, min_col=2)
    detail_research = Reference(detail_ws, min_row=1, max_row=len(results) + 1, min_col=3)
    detail_admin = Reference(detail_ws, min_row=1, max_row=len(results) + 1, min_col=4)

    chart2.add_data(detail_teaching, titles_from_data=True)
    chart2.add_data(detail_research, titles_from_data=True)
    chart2.add_data(detail_admin, titles_from_data=True)
    chart2.set_categories(detail_categories)
    _fix_category_references(chart2)  # Fix numRef → strRef for text categories

    # For horizontal bar charts (barDir=bar), catAx is vertical (staff names)
    # and valAx is horizontal (hours). Swap titles to match.
    chart2.y_axis.title = "Hours"
    chart2.x_axis.title = "Staff"

    # Make data labels more readable
    chart2.dataLabels = DataLabelList()
    chart2.dataLabels.showVal = True
    chart2.dataLabels.showCatName = True

    # Position chart with margins for better layout
    chart2.anchor = "A1"
    detail_ws.add_chart(chart2, "A1")

    # Save the workbook
    if output_dir is None:
        output_dir = OUTPUT_DIR
    excel_path = os.path.join(output_dir, "Staff workload model.xlsx")
    wb.save(excel_path)
    print(f"Excel file saved to {excel_path}")


def generate_html_report(results: List[WorkloadResult], year_data: YearData,
                         output_dir: str = "."):
    """Generate an HTML report with embedded boxplots and summary table."""
    summary_path = os.path.join(output_dir, "workload_summary_boxplot.png")
    detailed_path = os.path.join(output_dir, "workload_detailed_boxplot.png")

    # CSS with doubled braces to escape f-string interpolation
    css = """body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f5f5f5; }
        h1 { color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }
        h2 { color: #555; margin-top: 30px; }
        .summary-table { border-collapse: collapse; width: 100%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .summary-table th { background: #4CAF50; color: white; padding: 12px 8px; text-align: left; font-size: 12px; }
        .summary-table td { padding: 10px 8px; border-bottom: 1px solid #eee; font-size: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .summary-table tr:hover { background: #f9f9f9; }
        .chart-container { background: white; padding: 24px; margin: 15px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 8px; }
        .chart-container img { max-width: 100%; height: auto; display: block; margin: 0 auto; }
        .legend { display: flex; gap: 24px; margin: 16px 0; font-size: 13px; flex-wrap: wrap; }
        .legend-item { display: flex; align-items: center; gap: 8px; }
        .legend-color { width: 18px; height: 18px; border-radius: 3px; }
        .footer { margin-top: 30px; padding: 16px; background: #fff3e0; border-left: 4px solid #FF9800; font-size: 13px; color: #666; }
        .total-row { font-weight: bold; background: #f0f0f0 !important; }
        @media print {{
            body {{ background: white; }}
            .chart-container img {{ max-width: 100%; }}
        }}"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Workload Model Report</title>
    <style>{css}</style>
</head>
<body>
    <h1>Workload Model Report</h1>
    <p>Generated for academic year <strong>{year_data.year_label}</strong></p>

    <h2>Summary Chart</h2>
    <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background:#4CAF50"></div>Teaching</div>
        <div class="legend-item"><div class="legend-color" style="background:#2196F3"></div>Research</div>
        <div class="legend-item"><div class="legend-color" style="background:#FF9800"></div>Administration</div>
    </div>
    <div class="chart-container">
        <img src="workload_summary_boxplot.png" alt="Workload Summary Chart" style="max-width: 1200px;">
    </div>

    <h2>Detailed Breakdown</h2>
    <div class="chart-container">
        <img src="workload_detailed_boxplot.png" alt="Workload Detailed Chart" style="max-width: 1200px;">
    </div>

    <h2>Staff Workload Table</h2>
    <table class="summary-table">
        <thead>
            <tr>
                <th>Name</th><th>FTE</th><th>Total</th>
                <th>Teaching</th><th>Research</th><th>Admin</th>
                <th>Teaching Detail</th><th>Research Detail</th><th>Admin Detail</th>
            </tr>
        </thead>
        <tbody>
"""

    for r in results:
        html += f"""            <tr>
                <td>{r.name}</td>
                <td>{r.fte:.2f}</td>
                <td>{r.total_hours:.1f}</td>
                <td>{r.teaching_hours:.1f}</td>
                <td>{r.research_hours:.1f}</td>
                <td>{r.admin_hours:.1f}</td>
                <td title="{r.teaching_detail.replace('"', '&quot;')}">{r.teaching_detail[:80]}...</td>
                <td title="{r.research_detail.replace('"', '&quot;')}">{r.research_detail[:80]}...</td>
                <td title="{r.admin_detail.replace('"', '&quot;')}">{r.admin_detail[:80]}...</td>
            </tr>
"""

    html += """        </tbody>
    </table>

    <div class="footer">
        <strong>Note:</strong> This report was generated automatically from the Workload Model calculator.
        Assumptions and missing data are noted in the CSV output.
        The model is based on the Workload ModelFull Description (Iain Bate, June 2026).
    </div>
</body>
</html>
"""

    output_path = os.path.join(output_dir, "workload_report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML report saved to {output_path}")


def generate_per_staff_reports(results: List[WorkloadResult], year_data: YearData,
                                output_dir: str = None):
    """Generate individual detailed workload reports for each staff member."""
    if output_dir is None:
        output_dir = OUTPUT_DIR

    # Create a subdirectory for per-staff reports
    staff_reports_dir = os.path.join(output_dir, "Staff Reports")
    os.makedirs(staff_reports_dir, exist_ok=True)

    css = """body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 30px; background: #f5f5f5; }
        .report-container { max-width: 1200px; margin: 0 auto; background: white; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-radius: 8px; }
        h1 { color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 15px; margin-top: 0; }
        h2 { color: #4CAF50; border-left: 4px solid #4CAF50; padding-left: 12px; margin-top: 35px; }
        h3 { color: #666; margin: 20px 0 10px 0; font-size: 1.1em; }
        .staff-header { background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 25px; border-radius: 8px; margin-bottom: 30px; }
        .staff-name { font-size: 2em; font-weight: bold; }
        .staff-meta { display: flex; gap: 40px; margin-top: 10px; font-size: 1.1em; opacity: 0.95; }
        .meta-item { display: flex; flex-direction: column; align-items: center; min-width: 80px; }
        .meta-label { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.8; margin-bottom: 4px; }
        .meta-value { font-weight: bold; font-size: 1.3em; }
        .section-card { background: #f9f9f9; border-radius: 8px; padding: 25px; margin-top: 20px; border-left: 5px solid #4CAF50; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .card-title { font-weight: bold; color: #333; font-size: 1.2em; }
        .card-total { font-size: 1.4em; font-weight: bold; color: #4CAF50; }
        .detail-item { padding: 10px 0; border-bottom: 1px solid #eee; display: grid; grid-template-columns: 2fr 1fr 1.5fr; gap: 15px; align-items: center; }
        .detail-item:last-child { border-bottom: none; }
        .detail-name { font-weight: 500; color: #555; }
        .detail-hours { text-align: right; font-family: monospace; font-size: 1.1em; color: #666; }
        .detail-activity { text-align: center; padding: 4px 12px; background: #e8f5e9; border-radius: 4px; font-size: 0.85em; color: #2e7d32; }
        .teaching-item .detail-activity { background: #e3f2fd; color: #1565c0; }
        .research-item .detail-activity { background: #fff3e0; color: #ef6c00; }
        .admin-item .detail-activity { background: #fce4ec; color: #c2185b; }
        .calc-breakdown { font-size: 0.9em; color: #777; margin-top: 10px; padding-top: 15px; border-top: 2px dashed #ddd; line-height: 1.6; }
        .assumptions-box, .missing-data-box { background: #fff3e0; border-radius: 8px; padding: 20px; margin-top: 30px; }
        .assumptions-box h3, .missing-data-box h3 { color: #ef6c00; border-left-color: #ff9800; margin-top: 0; }
        .missing-data-box { background: #ffebee; }
        .missing-data-box h3 { color: #c62828; border-left-color: #e53935; }
        .footer { text-align: center; margin-top: 40px; padding-top: 20px; border-top: 2px solid #eee; font-size: 0.85em; color: #888; }
        .total-bar { display: flex; align-items: center; gap: 15px; margin-top: 30px; padding: 20px; background: linear-gradient(90deg, #4CAF50 0%, #2e7d32 100%); border-radius: 8px; }
        .total-bar .label { color: white; font-size: 1.2em; font-weight: bold; min-width: 150px; }
        .total-bar .value { color: white; font-size: 2em; font-weight: bold; flex-grow: 1; text-align: right; }"""

    for r in results:
        # Get module details if available
        module_details = getattr(r, 'module_details', []) or []

        # Build a map of module names and count modules with various teaching components
        module_teaching_map = {}
        module_count = 0
        modules_with_practicals = []
        modules_with_supervision = []

        for detail in module_details:
            if '(' in detail and ')' in detail:
                # Extract module name like "SOF1 (COM00015C) [20cr, Stage 1]"
                parts = detail.split(' (')
                if len(parts) >= 2:
                    module_name = parts[0].strip()
                    module_info = '(' + parts[1] if ')' in parts[1] else detail
                    module_count += 1

                    # Track modules with different components
                    if 'practical' in detail.lower():
                        modules_with_practicals.append(module_name)

                    # Check for supervision-related terms (Pastoral, Projects, Supervision)
                    if any(term in detail for term in ['Pastoral:', 'Projects:', 'Supervision:']):
                        modules_with_supervision.append(module_name)

                    module_teaching_map[module_name] = {
                        'info': module_info,
                        'has_practicals': 'practical' in detail.lower(),
                        'has_supervision': any(term in detail for term in ['Pastoral:', 'Projects:', 'Supervision:'])
                    }
                    # Try to extract teacher count from the detail string
                    if 'per teacher' in detail.lower():
                        # Look for patterns like "1.0/teacher" or "3/teacher"
                        teacher_match = re.search(r'([\d.]+)\s*/\s*teacher', detail, re.IGNORECASE)
                        if teacher_match:
                            # Convert to int - round to nearest integer since teachers are whole people
                            num_teachers = int(round(float(teacher_match.group(1))))
                            module_teaching_map[module_name]['num_teachers'] = num_teachers

        def format_detail_section(title, hours, breakdown, css_class, is_teaching=False, supervision_details=None):
            if not breakdown or all(v == 0 for v in breakdown.values()):
                return f"""<div class="section-card {css_class}">
                <div class="card-header">
                    <span class="card-title">{title}</span>
                    <span class="card-total">{hours:.1f}h</span>
                </div>
                <p>No activities recorded for this category.</p>
            </div>"""

            # Special handling for teaching - show hierarchical structure
            if is_teaching:
                return format_teaching_section(title, hours, breakdown, css_class, supervision_details)

            # Group items by subcategory for research/admin
            def get_category(item_name):
                if item_name.startswith("grant_"):
                    return "Research Grants"
                elif item_name in ["primary_research_allowance", "protected_research_baseline"]:
                    return "Research Allowances"
                elif item_name in ["phd_supervision", "primary_supervisor", "co_supervisor", "assessor"]:
                    return "PhD Supervision"
                else:
                    return "Other"

            # Group items by subcategory
            categories = {}
            for name, value in breakdown.items():
                if value > 0:
                    cat = get_category(name)
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append((name, value))

            items_html_parts = []

            for category_name, items in sorted(categories.items()):
                # Category header with subtotal
                cat_total = sum(v for _, v in items)
                items_html_parts.append(f"""<div style="margin-bottom:20px;">
                    <h4 style="color:#333;margin:0 0 10px 0;border-left:4px solid #4CAF50;padding-left:10px;">{category_name} ({cat_total:.1f}h)</h4>""")

                if len(items) == 1:
                    item_name, item_value = items[0]
                    display_name = item_name.replace('_', ' ').title()
                    items_html_parts.append(f"""<div class="detail-item {css_class}">
                        <span class="detail-name">{display_name}</span>
                        <span class="detail-hours">{item_value:.1f}h</span>
                    </div>""")
                else:
                    # Multiple items - show as sub-list under category
                    for item_name, item_value in sorted(items, key=lambda x: -x[1]):
                        display_name = item_name.replace('_', ' ').title()
                        if item_name.startswith("grant_"):
                            project_id = item_name.replace('grant_', '')
                            if hasattr(r, 'grant_titles') and r.grant_titles:
                                display_name = r.grant_titles.get(project_id, f"Grant {project_id}")
                            else:
                                display_name = f"Grant {project_id}"
                        items_html_parts.append(f"""<div class="detail-item {css_class}">
                            <span class="detail-name">{display_name}</span>
                            <span class="detail-hours">{item_value:.1f}h</span>
                        </div>""")

                items_html_parts.append("</div>")  # Close category div

            items_html = ''.join(items_html_parts)

            return f"""<div class="section-card {css_class}">
                <div class="card-header">
                    <span class="card-title">{title}</span>
                    <span class="card-total">{hours:.1f}h</span>
                </div>
                {items_html}
                <p style="font-size:0.85em;color:#666;padding-top:10px;">Subtotal: {hours:.1f}h</p>
            </div>"""

        def format_teaching_section(title, hours, breakdown, css_class, supervision_details=None):
            """Format teaching section with hierarchical structure:
            - Modules grouped by stage (SYS2, SYS3)
              - Delivery (lectures)
              - Practicals
              - Assessment setting
              - Marking
            - Supervision (pastoral + projects as separate sections)
            """
            import re

            items_html_parts = []

            # Parse module details to extract module-level info
            module_info_list = []
            for detail in module_details or []:
                # Module name format: "SOF1 (20cr): Standard..." or "ELLA (20cr): New lecturer..."
                # We group by the first part before space/bracket which is like "SOF1", "SYS2", "ELLA"
                match = re.search(r'([A-Z]+(?:\d+)?)\s+\(([^)]+)\)', detail)
                if match:
                    stage_or_name = match.group(1)  # e.g., "SOF1", "SYS2", "THE3"
                    code_or_info = match.group(2)

                    # Extract remaining info after the module identifier
                    info_match = re.search(r'\)\s*(.+)$', detail)
                    info = info_match.group(1) if info_match else ""

                    module_info_list.append({
                        'stage': stage_or_name,
                        'code': code_or_info,  # Could be "20cr" or full module code like "COM00029I"
                        'info': info.strip(),
                        'detail': detail
                    })

            # Group modules by name/stage (SOF1, SYS2, THE3, etc.)
            stages = {}
            for mod in module_info_list:
                stage = mod['stage']
                if stage not in stages:
                    stages[stage] = []
                stages[stage].append(mod)

            # Process each stage with hierarchical breakdown
            for stage in sorted(stages.keys()):
                modules_in_stage = stages[stage]

                items_html_parts.append(f"""<div style="margin-bottom:25px;">
                    <h4 style="color:#333;margin:0 0 10px 0;border-left:4px solid #2196F3;padding-left:10px;">{stage} Modules ({len(modules_in_stage)} module(s))</h4>""")

                for mod in modules_in_stage:
                    code = mod['code']
                    info = mod['info']

                    items_html_parts.append(f"""<div style="margin-bottom:15px;padding-left:20px;border-left:2px solid #e0e0e0;">
                        <h5 style="color:#4CAF50;margin:0 0 8px 0;">{code} - {info}</h5>""")

                    detail = mod['detail']

                    # Delivery/lectures
                    delivery_match = re.search(r'(\d+(?:\.\d+)?)h\s+lectures?', detail, re.IGNORECASE)
                    if delivery_match:
                        del_hours = float(delivery_match.group(1))
                        items_html_parts.append(f"""<div class="detail-item {css_class}">
                            <span class="detail-name">Delivery (Lectures)</span>
                            <span class="detail-hours">{del_hours:.1f}h</span>
                            <span class="detail-activity" style="background:#e3f2fd;color:#1565c0;">Teaching</span>
                        </div>""")

                    # Practicals
                    practical_match = re.search(r'Practicals:\s*(\d+)', detail, re.IGNORECASE)
                    contact_per_prac_match = re.search(r'([\d.]+)h\s+each', detail, re.IGNORECASE)
                    prac_rate_match = re.search(r'x\s+([\d.]+)x', detail, re.IGNORECASE)

                    if practical_match:
                        # Extract practical hours directly from the detail string (not from breakdown)
                        # since each module has its own practical count and calculation
                        prac_hours_match = re.search(r'=\s*([\d.]+)h', detail, re.IGNORECASE)
                        prac_hours = float(prac_hours_match.group(1)) if prac_hours_match else 0

                        contact_per_prac = float(contact_per_prac_match.group(1)) if contact_per_prac_match else 0
                        rate = float(prac_rate_match.group(1)) if prac_rate_match else 2.5

                        # DEBUG: Print detail and values for verification
                        import sys
                        print(f"DEBUG: detail='{detail[:80]}...'", file=sys.stderr)
                        print(f"DEBUG: prac_hours={prac_hours}, contact_per_prac (initial)={contact_per_prac}, rate={rate}", file=sys.stderr)

                        # Extract parallel groups to calculate contact per practical if not found directly
                        if contact_per_prac == 0:
                            # Try to extract n_groups from "X parallel groups"
                            n_groups_match = re.search(r'(\d+(?:\.\d+)?)\s+parallel\s+groups?', detail, re.IGNORECASE)
                            n_groups = float(n_groups_match.group(1)) if n_groups_match else 0
                            print(f"DEBUG: n_groups={n_groups}", file=sys.stderr)
                            if n_groups > 0:
                                contact_per_prac = prac_hours / n_groups
                                print(f"DEBUG: calculated contact_per_prac={contact_per_prac}", file=sys.stderr)

                        items_html_parts.append(f"""<div class="detail-item {css_class}">
                            <span class="detail-name">Practical Sessions</span>
                            <span class="detail-hours">{prac_hours:.1f}h ({contact_per_prac:.1f}h contact x {rate}x)</span>
                            <span class="detail-activity" style="background:#fff3e0;color:#ef6c00;">Teaching</span>
                        </div>""")

                    # Assessment setting
                    ass_match = re.search(r'(\d+)\s+assessment', detail, re.IGNORECASE)
                    if ass_match:
                        ass_hours = breakdown.get('assessment_setting', 0) / max(len(modules_in_stage), 1)
                        items_html_parts.append(f"""<div class="detail-item {css_class}">
                            <span class="detail-name">Assessment Setting</span>
                            <span class="detail-hours">{ass_hours:.1f}h</span>
                            <span class="detail-activity" style="background:#e8f5e9;color:#2e7d32;">Teaching</span>
                        </div>""")

                    # Marking
                    mark_match = re.search(r'(\d+)\s+script', detail, re.IGNORECASE)
                    if mark_match:
                        mark_hours = breakdown.get('marking', 0) / max(len(modules_in_stage), 1)
                        items_html_parts.append(f"""<div class="detail-item {css_class}">
                            <span class="detail-name">Assessment Marking</span>
                            <span class="detail-hours">{mark_hours:.1f}h</span>
                            <span class="detail-activity" style="background:#e8f5e9;color:#2e7d32;">Teaching</span>
                        </div>""")

                    items_html_parts.append("</div>")  # Close module div

                items_html_parts.append("</div>")  # Close stage div

            # Supervision section - show pastoral and projects separately using actual details
            supervision_details_list = supervision_details or []
            if supervision_details_list:
                # Parse supervision details to extract pastoral and project hours
                past_hours_total = 0.0
                proj_hours_total = 0.0
                past_students_total = 0
                proj_projects_total = 0

                for detail in supervision_details_list:
                    # Pastoral: "Pastoral: X - Y students x Zh = Wh"
                    past_match = re.search(r'Pastoral:\s*[^-]*-\s*(\d+(?:\.\d+)?)\s+students\s*x\s*(\d+(?:\.\d+)?)h\s*=\s*(\d+(?:\.\d+)?)h', detail)
                    if past_match:
                        past_students_total += int(float(past_match.group(1)))
                        past_hours_total += float(past_match.group(3))

                    # Projects: "Projects: X - Y projects x Zh = Wh"
                    proj_match = re.search(r'Projects:\s*[^-]*-\s*(\d+(?:\.\d+)?)\s+projects\s*x\s*(\d+(?:\.\d+)?)h\s*=\s*(\d+(?:\.\d+)?)h', detail)
                    if proj_match:
                        proj_projects_total += int(float(proj_match.group(1)))
                        proj_hours_total += float(proj_match.group(3))

                items_html_parts.append(f"""<div style="margin-bottom:25px;">
                    <h4 style="color:#333;margin:0 0 10px 0;border-left:4px solid #FF9800;padding-left:10px;">Pastoral Supervision ({past_hours_total:.1f}h)</h4>
                    <div style="margin-left:20px;">
                        <div class="detail-item {css_class}">
                            <span class="detail-name">Students</span>
                            <span class="detail-hours">{past_students_total} students x {config.SUPERVISION_MULTIPLIERS['pastoral']}h each = {past_hours_total:.1f}h</span>
                            <span class="detail-activity" style="background:#fce4ec;color:#c2185b;">Supervision</span>
                        </div>
                    </div>
                </div>""")

                items_html_parts.append(f"""<div style="margin-bottom:25px;">
                    <h4 style="color:#333;margin:0 0 10px 0;border-left:4px solid #FF9800;padding-left:10px;">Project Supervision ({proj_hours_total:.1f}h)</h4>
                    <div style="margin-left:20px;">
                        <div class="detail-item {css_class}">
                            <span class="detail-name">Projects</span>
                            <span class="detail-hours">{proj_projects_total} projects x UG = {proj_hours_total:.1f}h</span>
                            <span class="detail-activity" style="background:#fce4ec;color:#c2185b;">Supervision</span>
                        </div>
                    </div>
                </div>""")

            # Minimum admin teaching load (if present)
            min_teaching = breakdown.get('minimum_admin_load', 0)
            if min_teaching > 0:
                items_html_parts.append(f"""<div class="detail-item {css_class}">
                    <span class="detail-name">Minimum Admin Teaching Load</span>
                    <span class="detail-hours">{min_teaching:.1f}h</span>
                    <span class="detail-activity" style="background:#e3f2fd;color:#1565c0;">Teaching</span>
                </div>""")

            items_html = ''.join(items_html_parts)

            return f"""<div class="section-card {css_class}">
                <div class="card-header">
                    <span class="card-title">{title}</span>
                    <span class="card-total">{hours:.1f}h</span>
                </div>
                {items_html}
                <p style="font-size:0.85em;color:#666;padding-top:10px;">Subtotal: {hours:.1f}h</p>
            </div>"""

        # Calculate breakdown totals
        teaching_breakdown = r.teaching_breakdown if hasattr(r, 'teaching_breakdown') and r.teaching_breakdown else {}
        research_breakdown = r.research_breakdown if hasattr(r, 'research_breakdown') and r.research_breakdown else {}
        admin_breakdown = r.admin_breakdown if hasattr(r, 'admin_breakdown') and r.admin_breakdown else {}

        # Calculate nominal hours if not set
        nominal_hours = r.nominal_hours or config.NOMINAL_WORKING_HOURS_PER_YEAR * r.fte

        # Get total for display - this should include all components including baseline
        total_for_display = r.total_hours

        teaching_section = format_detail_section(
            "Teaching Activities", r.teaching_hours, teaching_breakdown, "teaching-item", is_teaching=True,
            supervision_details=r.supervision_details or []
        )
        research_section = format_detail_section(
            "Research Activities", r.research_hours, research_breakdown, "research-item"
        )
        admin_section = format_detail_section(
            "Admin Activities", r.admin_hours, admin_breakdown, "admin-item"
        )

        # Calculate subtotal for display (excluding personal development which is baseline)
        subtotal = r.teaching_hours + r.research_hours + r.admin_hours

        # Format assumptions
        if r.assumptions:
            assumptions_items = ''.join(f'<li>{a}</li>' for a in r.assumptions)
            assumptions_section = f"""<div class="assumptions-box">
                <h3>Assumptions Made</h3>
                <ul>{assumptions_items}</ul>
            </div>"""
        else:
            assumptions_section = ""

        # Format missing data
        if r.missing_data:
            missing_items = ''.join(f'<li>{m}</li>' for m in r.missing_data)
            missing_data_section = f"""<div class="missing-data-box">
                <h3>Missing Data</h3>
                <ul>{missing_items}</ul>
                <p>Data marked as missing may affect the accuracy of this report.</p>
            </div>"""
        else:
            missing_data_section = ""

        # Generate HTML using f-string to avoid .format() brace issues
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Workload Report - {r.name}</title>
    <style>{css}</style>
</head>
<body>
    <div class="report-container">
        <div class="staff-header">
            <div class="staff-name">{r.name}</div>
            <div class="staff-meta">
                <div class="meta-item">
                    <span class="meta-label">FTE</span>
                    <span class="meta-value">{r.fte:.2f}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Nominal Hours</span>
                    <span class="meta-value">{nominal_hours:.0f}h</span>
                </div>
            </div>

            <!-- Total workload in green band at top of staff header -->
            <div style="margin-top:20px;padding-top:15px;border-top:1px solid rgba(255,255,255,0.3);">
                <span class="label" style="color:white;font-size:1.2em;font-weight:bold;">Total Workload:</span>
                <span class="value" style="color:white;font-size:2em;font-weight:bold;">{total_for_display:.1f} hours</span>
            </div>
        </div>

        {teaching_section}
        {research_section}
        {admin_section}

        <h2>Calculation Breakdown</h2>
        <div class="section-card">
            <p>The workload calculation follows the model formula:</p>
            <p style="font-family: monospace; font-size: 1.1em; text-align: center; margin: 20px 0;">
                Total = Teaching + Research (Protected + Additional) + Admin + General Baseline
            </p>
            <div class="calc-breakdown">
                <h3>Summary Totals</h3>
                <ul>
                    <li><strong>Teaching:</strong> {r.teaching_hours:.1f}h</li>
                    <li><strong>Research (protected baseline):</strong> {config.PROTECTED_RESEARCH_BASELINE * r.fte:.1f}h</li>
                    <li><strong>Research (additional - grants, supervision):</strong> {r.research_hours - config.PROTECTED_RESEARCH_BASELINE * r.fte:.1f}h</li>
                    <li><strong>Admin:</strong> {r.admin_hours:.1f}h</li>
                    <li><strong>General Baseline (engagement + personal dev):</strong> {(config.BASELOADS.get('engagement', 100) / len(results) + config.BASELOADS['personal_development'] * r.fte):.1f}h</li>
                </ul>
                <p style="margin-top:20px;"><em>Total: {total_for_display:.1f} hours = {r.teaching_hours:.1f} + {config.PROTECTED_RESEARCH_BASELINE * r.fte:.1f} + {r.research_hours - config.PROTECTED_RESEARCH_BASELINE * r.fte:.1f} + {r.admin_hours:.1f} + {(config.BASELOADS.get('engagement', 100) / len(results) + config.BASELOADS['personal_development'] * r.fte):.1f}</em></p>
            </div>
        </div>

        {assumptions_section}
        {missing_data_section}

        <div class="footer">
            <p>Generated on 2026-07-14 for academic year {year_data.year_label}</p>
            <p>This report was automatically generated by the Workload Model calculator.</p>
        </div>
    </div>
</body>
</html>"""

        # Sanitize filename
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in r.name)
        filepath = os.path.join(staff_reports_dir, f"{safe_name}_workload_report.html")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

    print(f"Per-staff reports saved to {staff_reports_dir}")


def generate_all_outputs(results: List[WorkloadResult], year_data: YearData,
                         output_dir: str = None):
    """Generate all output artifacts."""
    if output_dir is None:
        output_dir = OUTPUT_DIR

    # Generate CSV
    generate_csv(results, os.path.join(output_dir, "Staff workload model.csv"))

    # Generate Excel with formulas
    generate_excel_with_formulas(results, year_data, output_dir)

    # Generate boxplots
    generate_boxplots(results, output_dir)

    # Generate per-staff detailed reports
    generate_per_staff_reports(results, year_data, output_dir)

    # Generate HTML report
    generate_html_report(results, year_data, output_dir)
