"""
Output generation for the workload calculator.
Produces:
1. Staff workload model CSV (summary + detail columns)
2. Summary stacked boxplot (PNG)
3. Detailed stacked boxplot (PNG)
4. HTML report with embedded images
"""

import csv
import os
from typing import List

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

import config
from data_loader import WorkloadResult, YearData


def generate_csv(results: List[WorkloadResult], filepath: str = "Staff workload model.csv"):
    """Generate the staff workload model CSV output."""
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

    fig, ax = plt.subplots(figsize=(16, max(8, len(names) * 0.35)))
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
        # Simplified: draw a dashed reference line at 40% of nominal for ART staff
        ref_line = [0.40 * h for h in [config.NOMINAL_WORKING_HOURS_PER_YEAR * f for f in fte_values]]

    ax.set_xlabel("Hours")
    ax.set_ylabel("Staff")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Boxplot saved to {output_path}")


def generate_boxplots(results: List[WorkloadResult], output_dir: str = "."):
    """Generate both summary and detailed stacked boxplots."""
    # --- Summary boxplot ---
    summary_components = ["teaching_hours", "research_hours", "admin_hours"]
    summary_labels = ["Teaching", "Research", "Administration"]

    fig, ax = plt.subplots(figsize=(16, max(8, len(results) * 0.35)))
    fig.suptitle("Workload Summary: Teaching, Research & Administration",
                 fontsize=14, fontweight="bold")

    names = [r.name for r in results]
    bottom = [0.0] * len(names)
    colors = ["#4CAF50", "#2196F3", "#FF9800"]

    for i, (comp, label) in enumerate(zip(summary_components, summary_labels)):
        values = [getattr(r, comp) for r in results]
        bars = ax.barh(names, values, left=bottom, color=colors[i],
                       label=label, edgecolor="white", height=0.6)
        for j, (bar, val) in enumerate(zip(bars, values)):
            if val > 10:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_y() + bar.get_height() / 2,
                        f"{val:.0f}", ha="center", va="center",
                        fontsize=7, color="white")
        bottom = [b + v for b, v in zip(bottom, values)]

    # Add expected workload reference lines (40% of nominal for ART staff)
    for y_pos, (name, fte) in enumerate(zip(names, [r.fte for r in results])):
        expected_teaching = config.NOMINAL_WORKING_HOURS_PER_YEAR * fte * 0.40
        expected_research = config.NOMINAL_WORKING_HOURS_PER_YEAR * fte * 0.40
        ax.axvline(x=expected_teaching, color="#4CAF50", alpha=0.2, linestyle="--", linewidth=0.5)
        ax.axvline(x=expected_teaching + expected_research, color="#2196F3", alpha=0.2,
                   linestyle="--", linewidth=0.5)

    # Total workload line
    total_expected = config.NOMINAL_WORKING_HOURS_PER_YEAR
    ax.axvline(x=total_expected, color="black", alpha=0.3, linestyle="--", linewidth=1,
               label=f"Total Available ({total_expected}h)")

    ax.set_xlabel("Hours")
    ax.set_ylabel("Staff")
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()

    summary_path = os.path.join(output_dir, "workload_summary_boxplot.png")
    plt.savefig(summary_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Summary boxplot saved to {summary_path}")

    # --- Detailed boxplot ---
    # Break down teaching into sub-components
    detailed_components = ["teaching_hours", "research_hours", "admin_hours"]
    detailed_labels = ["Teaching", "Research", "Administration"]

    fig2, ax2 = plt.subplots(figsize=(16, max(8, len(results) * 0.35)))
    fig2.suptitle("Workload Breakdown: Detailed Components", fontsize=14, fontweight="bold")

    bottom2 = [0.0] * len(names)
    detailed_colors = ["#4CAF50", "#81C784", "#2196F3", "#64B5F6", "#FF9800", "#FFB74D"]

    for i, (comp, label) in enumerate(zip(detailed_components, detailed_labels)):
        values = [getattr(r, comp) for r in results]
        bars = ax2.barh(names, values, left=bottom2, color=detailed_colors[i],
                        label=label, edgecolor="white", height=0.6)
        for j, (bar, val) in enumerate(zip(bars, values)):
            if val > 10:
                ax2.text(bar.get_x() + bar.get_width() / 2,
                         bar.get_y() + bar.get_height() / 2,
                         f"{val:.0f}", ha="center", va="center",
                         fontsize=7, color="white")
        bottom2 = [b + v for b, v in zip(bottom2, values)]

    total_expected2 = config.NOMINAL_WORKING_HOURS_PER_YEAR
    ax2.axvline(x=total_expected2, color="black", alpha=0.3, linestyle="--", linewidth=1,
                label=f"Total Available ({total_expected2}h)")

    ax2.set_xlabel("Hours")
    ax2.set_ylabel("Staff")
    ax2.legend(loc="lower right", fontsize=9)
    ax2.grid(axis="x", alpha=0.3)
    plt.tight_layout()

    detailed_path = os.path.join(output_dir, "workload_detailed_boxplot.png")
    plt.savefig(detailed_path, dpi=150, bbox_inches="tight")
    plt.close(fig2)
    print(f"Detailed boxplot saved to {detailed_path}")


def generate_html_report(results: List[WorkloadResult], output_dir: str = "."):
    """Generate an HTML report with embedded boxplots and summary table."""
    summary_path = os.path.join(output_dir, "workload_summary_boxplot.png")
    detailed_path = os.path.join(output_dir, "workload_detailed_boxplot.png")

    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Workload Model Report</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f5f5f5; }
        h1 { color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }
        h2 { color: #555; margin-top: 30px; }
        .summary-table { border-collapse: collapse; width: 100%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .summary-table th { background: #4CAF50; color: white; padding: 10px; text-align: left; font-size: 12px; }
        .summary-table td { padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .summary-table tr:hover { background: #f9f9f9; }
        .chart-container { background: white; padding: 20px; margin: 15px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 4px; }
        .chart-container img { max-width: 100%; height: auto; }
        .legend { display: flex; gap: 20px; margin: 10px 0; font-size: 13px; }
        .legend-item { display: flex; align-items: center; gap: 5px; }
        .legend-color { width: 16px; height: 16px; border-radius: 2px; }
        .footer { margin-top: 30px; padding: 15px; background: #fff3e0; border-left: 4px solid #FF9800; font-size: 13px; color: #666; }
        .total-row { font-weight: bold; background: #f0f0f0 !important; }
    </style>
</head>
<body>
    <h1>Workload Model Report</h1>
    <p>Generated for academic year <strong>""" + """</strong></p>

    <h2>Summary Chart</h2>
    <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background:#4CAF50"></div>Teaching</div>
        <div class="legend-item"><div class="legend-color" style="background:#2196F3"></div>Research</div>
        <div class="legend-item"><div class="legend-color" style="background:#FF9800"></div>Administration</div>
    </div>
    <div class="chart-container">
        <img src="workload_summary_boxplot.png" alt="Workload Summary Chart">
    </div>

    <h2>Detailed Breakdown</h2>
    <div class="chart-container">
        <img src="workload_detailed_boxplot.png" alt="Workload Detailed Chart">
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
                <td title="{r.teaching_detail}">{r.teaching_detail[:80]}...</td>
                <td title="{r.research_detail}">{r.research_detail[:80]}...</td>
                <td title="{r.admin_detail}">{r.admin_detail[:80]}...</td>
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


def generate_all_outputs(results: List[WorkloadResult], year_data: YearData,
                         output_dir: str = "."):
    """Generate all output artifacts."""
    # Generate CSV
    generate_csv(results, os.path.join(output_dir, "Staff workload model.csv"))

    # Generate boxplots
    generate_boxplots(results, output_dir)

    # Generate HTML report
    generate_html_report(results, output_dir)
