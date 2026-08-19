"""
Feedback dashboard for workload model.

This module provides functionality to:
1. Generate HTML dashboard showing feedback status for all staff
2. Aggregate and display feedback responses
3. Track deadline compliance

Usage:
    from feedback_dashboard import generate_feedback_summary

    generate_feedback_summary(results, feedback_csv_path, output_dir)
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict


def generate_feedback_summary(results: List[object],
                              feedback_csv_path: str,
                              output_dir: str,
                              year_label: str = "2026-7",
                              deadline: str = None) -> str:
    """Generate HTML dashboard showing feedback status for all staff.

    Args:
        results: List of WorkloadResult objects
        feedback_csv_path: Path to exported feedback CSV from Google Forms
        output_dir: Directory to save the dashboard HTML file
        year_label: Academic year label (e.g., "2026-7")
        deadline: Optional deadline date string for display

    Returns:
        Path to generated HTML file
    """
    output_path = Path(output_dir) / f"feedback_summary_{year_label}.html"

    # Load feedback responses if file exists
    feedback_data = {}
    if feedback_csv_path and Path(feedback_csv_path).exists():
        feedback_data = _load_feedback_responses(feedback_csv_path)

    # Categorize staff by feedback status
    staff_status = _categorize_staff_status(results, feedback_data)

    # Aggregate statistics
    stats = _calculate_statistics(staff_status)

    # Get deadline display text
    deadline_text = deadline or "Not specified"

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Workload Model Feedback Summary - {year_label}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f7fa;
            color: #333;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{
            background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
            color: white;
            padding: 30px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        header h1 {{ margin: 0; font-size: 28px; }}
        header p {{ margin: 10px 0 0; opacity: 0.9; }}

        /* Stats Dashboard */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: white;
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .stat-value {{
            font-size: 36px;
            font-weight: bold;
            color: #4CAF50;
        }}
        .stat-label {{ font-size: 14px; color: #666; margin-top: 5px; }}

        /* Sections */
        section {{ background: white; padding: 25px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        section h2 {{
            margin-top: 0;
            color: #333;
            padding-bottom: 15px;
            border-bottom: 2px solid #eee;
        }}

        /* Status badges */
        .status-badge {{
            display: inline-block;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 13px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .status-submitted {{ background: #e8f5e9; color: #2e7d32; }}
        .status-pending {{ background: #fff3e0; color: #ef6c00; }}
        .status-overdue {{ background: #ffebee; color: #c62828; }}

        /* Staff table */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th, td {{
            padding: 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
            font-weight: 600;
            color: #333;
        }}
        tr:hover {{ background: #f8f9fa; }}

        /* Feedback summary */
        .feedback-item {{
            padding: 20px;
            border-left: 4px solid #4CAF50;
            margin-bottom: 15px;
            background: #fafafa;
        }}
        .feedback-item.poor {{ border-left-color: #f9a825; }}
        .feedback-item.negative {{ border-left-color: #c62828; }}
        .feedback-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .feedback-name {{ font-weight: bold; font-size: 16px; }}
        .feedback-date {{ font-size: 13px; color: #666; }}

        /* Action items */
        .action-item {{
            background: #fff3e0;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 15px;
            border-left: 4px solid #f9a825;
        }}
        .action-item h4 {{ margin: 0 0 10px; color: #ef6c00; }}

        /* Deadline banner */
        .deadline-banner {{
            padding: 15px 20px;
            border-radius: 6px;
            margin-bottom: 20px;
            font-weight: 500;
        }}
        .deadline-banner.urgent {{
            background: #ffebee;
            color: #c62828;
            border-left: 4px solid #c62828;
        }}
        .deadline-banner.approaching {{
            background: #fff3e0;
            color: #ef6c00;
            border-left: 4px solid #f9a825;
        }}
        .deadline-banner.passed {{
            background: #ffebee;
            color: #c62828;
            border-left: 4px solid #c62828;
        }}

        /* Charts */
        .chart-container {{
            display: flex;
            justify-content: space-around;
            margin-top: 30px;
        }}
        .chart {{
            width: 45%;
            text-align: center;
        }}
        .chart-bar {{
            background: #4CAF50;
            height: 40px;
            border-radius: 4px;
            position: relative;
            margin: 10px 0;
        }}
        .chart-label {{
            font-size: 14px;
            color: #666;
            margin-bottom: 5px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Workload Model Feedback Summary</h1>
            <p>{year_label} | {len(results)} staff members | Deadline: {deadline_text}</p>
        </header>

        {stats_html(stats)}

        {deadline_banner(deadline, stats)}

        {staff_status_section(staff_status)}

        {feedback_section(feedback_data)}

        {action_items_section(staff_status)}
    </div>
</body>
</html>"""

    output_path.write_text(html_content)
    print(f"Feedback summary generated: {output_path}")
    return str(output_path)


def _load_feedback_responses(csv_path: str) -> Dict[str, dict]:
    """Load feedback responses from CSV file."""
    responses = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try to match by name or email
            name = row.get('Staff Name') or row.get('Name')
            if name:
                responses[name.strip()] = row
    return responses


def _categorize_staff_status(results: List[object],
                             feedback_data: Dict[str, dict]) -> Dict[str, dict]:
    """Categorize staff by their feedback status."""
    staff_status = {}
    today = datetime.now()

    for result in results:
        name = getattr(result, 'name', 'Unknown')
        email = getattr(result, 'email', '')

        # Determine status
        if name in feedback_data or email in feedback_data:
            key = name if name in feedback_data else email
            response_date = _get_response_date(feedback_data.get(key, {}))
            staff_status[name] = {
                'status': 'submitted',
                'response_date': response_date,
                'result': result,
                'feedback': feedback_data.get(name) or feedback_data.get(email)
            }
        else:
            # Check if overdue (simplified: assume deadline was 2 weeks ago)
            staff_status[name] = {
                'status': 'pending',
                'result': result,
                'email': email
            }

    return staff_status


def _get_response_date(response_row: dict) -> Optional[datetime]:
    """Extract response date from feedback row."""
    for key in ['Timestamp', 'timestamp', 'Time', 'time']:
        if key in response_row:
            try:
                # Try to parse common timestamp formats
                date_str = response_row[key]
                for fmt in ['%m/%d/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M']:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue
            except Exception:
                pass
    return None


def _calculate_statistics(staff_status: Dict[str, dict]) -> dict:
    """Calculate summary statistics."""
    total = len(staff_status)
    submitted = sum(1 for s in staff_status.values() if s['status'] == 'submitted')
    pending = sum(1 for s in staff_status.values() if s['status'] == 'pending')

    return {
        'total': total,
        'submitted': submitted,
        'pending': pending,
        'response_rate': (submitted / total * 100) if total > 0 else 0
    }


def stats_html(stats: dict) -> str:
    """Generate HTML for statistics dashboard."""
    return f"""<div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{stats['total']}</div>
            <div class="stat-label">Total Staff</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['submitted']}</div>
            <div class="stat-label">Feedback Submitted</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['pending']}</div>
            <div class="stat-label">Pending Feedback</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{stats['response_rate']:.1f}%</div>
            <div class="stat-label">Response Rate</div>
        </div>
    </div>"""


def deadline_banner(deadline: str, stats: dict) -> str:
    """Generate deadline banner HTML."""
    if not deadline:
        return ""

    try:
        deadline_date = datetime.strptime(deadline, '%Y-%m-%d')
        days_remaining = (deadline_date - datetime.now()).days

        if days_remaining < 0:
            status_class = 'passed'
            message = f"Deadline passed: {deadline}"
        elif days_remaining <= 3:
            status_class = 'urgent'
            message = f"Deadline approaching! {abs(days_remaining)} day(s) remaining"
        elif days_remaining <= 7:
            status_class = 'approaching'
            message = f"Deadline in {days_remaining} day(s)"
        else:
            return ""

        return f"""<div class="deadline-banner {status_class}">
            {message}
        </div>"""
    except ValueError:
        return ""


def staff_status_section(staff_status: Dict[str, dict]) -> str:
    """Generate HTML for staff status table."""
    rows = []
    for name, data in sorted(staff_status.items()):
        status = data['status']
        badge_class = f"status-{status}"
        rows.append(f"""<tr>
            <td>{name}</td>
            <td><span class="status-badge {badge_class}">{status}</span></td>
            <td>{data.get('email', 'N/A')}</td>
        </tr>""")

    return f"""<section id="staff-status">
        <h2>Staff Feedback Status</h2>
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Email</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
    </section>"""


def feedback_section(feedback_data: Dict[str, dict]) -> str:
    """Generate HTML for feedback responses section."""
    if not feedback_data:
        return """<section id="feedback">
            <h2>Feedback Responses</h2>
            <p>No feedback responses received yet.</p>
        </section>"""

    rows = []
    for name, data in sorted(feedback_data.items()):
        # Extract workload status
        workload_status = data.get('Total Workload Status', 'N/A')

        # Determine feedback quality based on status
        if workload_status == 'Reasonable':
            badge_class = 'status-submitted'
        elif workload_status in ['Too High', 'Too Low']:
            badge_class = 'status-overdue'  # Using overdue class for emphasis
        else:
            badge_class = 'status-pending'

        rows.append(f"""<div class="feedback-item">
            <div class="feedback-header">
                <span class="feedback-name">{name}</span>
                <span class="status-badge {badge_class}">{workload_status}</span>
            </div>
        </div>""")

    return f"""<section id="feedback">
        <h2>Feedback Responses ({len(feedback_data)})</h2>
        {''.join(rows)}
    </section>"""


def action_items_section(staff_status: Dict[str, dict]) -> str:
    """Generate HTML for action items section."""
    action_items = []

    # Find staff who haven't responded
    for name, data in sorted(staff_status.items()):
        if data['status'] == 'pending':
            action_items.append(f"<li>{name} ({data.get('email', 'No email')}) - Follow up on feedback</li>")

    if not action_items:
        return ""

    return f"""<section id="action-items">
        <h2>Action Items</h2>
        <p>The following staff members have not yet submitted their feedback:</p>
        <ul>
            {''.join(action_items)}
        </ul>
    </section>"""


if __name__ == "__main__":
    print("Feedback Dashboard Generator for Workload Model")
    print("=" * 50)
    print()
    print("Usage:")
    print("  from feedback_dashboard import generate_feedback_summary")
    print()
    print("Example:")
    print("""
    results = [...]  # Your WorkloadResult objects
    generate_feedback_summary(
        results=results,
        feedback_csv_path='../output/feedback_responses.csv',
        output_dir='../output',
        year_label='2026-7',
        deadline='2026-09-30'
    )
    """)
