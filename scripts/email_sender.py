"""
Email distribution for workload model feedback.

This module provides functionality to:
1. Generate email content with form links
2. Send emails via SMTP server with attachments

Usage:
    from email_sender import generate_email_body, send_emails_via_smtp

    body = generate_email_body(result, form_url, "2026-7")
    results = send_emails_via_smtp(results, smtp_config)
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Dict, List, Optional

# Get project root directory (parent of scripts folder)
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)

# Try to load environment variables (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False


def generate_email_body(result: object,
                        form_url: str,
                        year_label: str,
                        deadline: str = None) -> str:
    """Generate HTML email body for a staff member.

    Args:
        result: WorkloadResult object with calculated workload
        form_url: Pre-filled Google Form URL for this staff member
        year_label: Academic year label (e.g., "2026-7")
        deadline: Optional feedback deadline date string

    Returns:
        HTML email body string
    """
    # Extract values from result object
    name = getattr(result, 'name', 'Staff Member')
    total_hours = getattr(result, 'total_hours', 0)
    teaching_hours = getattr(result, 'teaching_hours', 0)
    research_hours = getattr(result, 'research_hours', 0)
    admin_hours = getattr(result, 'admin_hours', 0)
    fte = getattr(result, 'fte', 1.0)

    # Format hours
    total_str = f"{total_hours:.1f}h" if total_hours else "N/A"
    teach_str = f"{teaching_hours:.1f}h" if teaching_hours else "N/A"
    research_str = f"{research_hours:.1f}h" if research_hours else "N/A"
    admin_str = f"{admin_hours:.1f}h" if admin_hours else "N/A"

    # Deadline text
    deadline_text = f"Please submit your feedback by {deadline}" if deadline else "Please submit your feedback soon"

    html_body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); color: white; padding: 30px; border-radius: 8px 8px 0 0; }}
        .header h1 {{ margin: 0; font-size: 24px; }}
        .summary {{ background: #f9f9f9; padding: 25px; border-left: 5px solid #4CAF50; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin-top: 20px; }}
        .summary-item {{ background: white; padding: 15px; border-radius: 5px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .summary-value {{ font-size: 24px; font-weight: bold; color: #4CAF50; display: block; margin-top: 5px; }}
        .summary-label {{ font-size: 13px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
        .form-section {{ background: #fff8e1; padding: 25px; border-left: 5px solid #f9a825; margin: 25px 0; }}
        .btn {{ display: inline-block; background: #4CAF50; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 10px; }}
        .footer {{ background: #f5f5f5; padding: 20px; border-radius: 0 0 8px 8px; font-size: 13px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Your Workload Model Report</h1>
            <p>Academic Year {year_label}</p>
        </div>

        <div style="padding: 25px;">
            <p>Hi {name},</p>

            <p>Your workload model report for {year_label} is attached in both HTML and PDF format. Please review it carefully and provide feedback using the form below.</p>

            <div class="summary">
                <h3 style="margin-top: 0;">Workload Summary</h3>
                <div class="summary-grid">
                    <div class="summary-item">
                        <span class="summary-label">Total Workload</span>
                        <span class="summary-value">{total_str}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Teaching</span>
                        <span class="summary-value">{teach_str}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Research</span>
                        <span class="summary-value">{research_str}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Admin</span>
                        <span class="summary-value">{admin_str}</span>
                    </div>
                </div>
                <p style="margin-top: 20px; font-size: 13px; color: #666;">
                    FTE: {fte:.2f} | Nominal hours at 100% FTE: 1642h
                </p>
            </div>

            <div class="form-section">
                <h3 style="margin-top: 0;">Provide Feedback</h3>
                <p>{deadline_text}. Your feedback helps ensure the workload model accurately reflects your experience.</p>

                <a href="{form_url}" class="btn">Open Feedback Form</a>

                <p style="font-size: 13px; color: #666; margin-top: 20px;">
                    If the form doesn't open, copy and paste this URL into your browser:<br>
                    <a href="{form_url}">{form_url}</a>
                </p>
            </div>

            <h3>What to Check</h3>
            <ul>
                <li><strong>Contact hours:</strong> Are the teaching hours accurate?</li>
                <li><strong>Assessment:</strong> Do marking and assessment hours seem reasonable?</li>
                <li><strong>Supervision:</strong> Are pastoral and project supervision loads correct?</li>
                <li><strong>Research:</strong> Does your research baseline match your contract?</li>
                <li><strong>Admin:</strong> Are departmental role percentages accurate?</li>
            </ul>

            <p>If you have any questions or need clarification on any part of this report, please don't hesitate to ask.</p>

            <p>Best regards,<br>
            The Workload Model Team</p>
        </div>

        <div class="footer">
            <p><strong>Note:</strong> This email was automatically generated by the Workload Model calculator.</p>
            <p style="margin-top: 10px;">
                If you believe you received this email in error, or if your contact information needs updating,
                please contact HR.
            </p>
        </div>
    </div>
</body>
</html>"""

    return html_body


def generate_email_subject(year_label: str) -> str:
    """Generate email subject line.

    Args:
        year_label: Academic year label

    Returns:
        Subject string
    """
    return f"Your Workload Model Report for {year_label}"


def send_emails_via_smtp(results: List[object],
                         form_urls: Dict[str, str],
                         emails: Dict[str, str],
                         smtp_config: Dict,
                         dry_run: bool = False,
                         year_label: str = None,
                         output_dir: str = None) -> Dict[str, bool]:
    """Send emails via SMTP server.

    Args:
        results: List of WorkloadResult objects. Every entry must have a
            confirmed address in `emails` - callers should filter results
            down to sendable staff first (see main.py's _handle_email_send),
            since this function has no way to guess a missing one.
        form_urls: Dict mapping staff name to pre-filled form URL
        emails: Dict mapping staff name to their confirmed email address
            (from email_data.get_all_staff_emails() - never a guessed one)
        smtp_config: Configuration dict with keys:
            - host: SMTP server hostname
            - port: SMTP server port (default 587)
            - from_addr: Sender email address
            - username: SMTP username (optional if using system auth)
            - password: SMTP password (optional if using system auth)
            - use_tls: Use TLS encryption (default True)
        dry_run: If True, don't actually send emails
        year_label: Academic year label shown in the email subject/body
        output_dir: Output directory containing generated reports for attachment

    Returns:
        Dict mapping staff name to success status (True/False)
    """
    results_dict = {r.name: r for r in results}
    statuses = {}

    # Extract SMTP config with defaults
    host = smtp_config.get("host")
    port = int(smtp_config.get("port", 587))
    from_addr = smtp_config.get("from_addr")
    use_tls = smtp_config.get("use_tls", True)

    if not all([host, from_addr]):
        print("Error: SMTP config missing required fields (host, from_addr)")
        for name in results_dict:
            statuses[name] = False
        return statuses

    # Get credentials
    username = smtp_config.get("username")
    password = smtp_config.get("password")

    if not username:
        # Try environment variable
        username = os.environ.get("SMTP_USERNAME")

    if not password:
        # Try environment variable
        password = os.environ.get("SMTP_PASSWORD")

    if dry_run:
        print("DRY RUN - No emails will be sent")
        for name in results_dict:
            statuses[name] = True
            form_url = form_urls.get(name, "FORM_URL_NOT_FOUND")
            recipient = emails.get(name, "NO CONFIRMED ADDRESS")
            print(f"  Would send to {name} <{recipient}>: {form_url}")
            if output_dir:
                print(f"    Attachments: HTML report + PDF report from {output_dir}")
        return statuses

    # Try to connect and send emails
    try:
        context = ssl.create_default_context()

        with smtplib.SMTP(host, port) as server:
            if use_tls:
                server.starttls(context=context)

            # Login if credentials provided
            if username and password:
                server.login(username, password)

            for result in results:
                name = result.name
                form_url = form_urls.get(name, "")
                recipient = emails.get(name)
                if not recipient:
                    print(f"Error sending to {name}: no confirmed email address")
                    statuses[name] = False
                    continue

                try:
                    msg = _build_email_message(
                        result, form_url, recipient, year_label=year_label, output_dir=output_dir
                    )
                    server.sendmail(from_addr, [recipient], msg.as_string())
                    statuses[name] = True

                except Exception as e:
                    print(f"Error sending to {name}: {e}")
                    statuses[name] = False

    except Exception as e:
        print(f"SMTP connection error: {e}")
        for name in results_dict:
            statuses[name] = False

    # Print summary
    success_count = sum(1 for v in statuses.values() if v)
    fail_count = len(statuses) - success_count
    print(f"\nEmail send complete: {success_count} succeeded, {fail_count} failed")

    return statuses


def _build_email_message(result: object,
                         form_url: str,
                         recipient: str,
                         year_label: str = None,
                         output_dir: str = None,
                         include_attachments: bool = True) -> MIMEMultipart:
    """Build email message for a staff member.

    Args:
        result: WorkloadResult object
        form_url: Pre-filled Google Form URL
        recipient: Confirmed email address for this person (from
            email_data.get_all_staff_emails() - never guessed)
        year_label: Academic year label
        output_dir: Output directory containing generated reports (optional)
        include_attachments: If True, attach HTML and PDF individual reports

    Returns:
        MIMEMultipart message object with optional attachments
    """
    year_label = year_label or "2026-7"

    name = getattr(result, 'name', 'Staff Member')

    subject = generate_email_subject(year_label)
    body = generate_email_body(result, form_url, year_label)

    # Use multipart/related for embedded content and attachments
    msg = MIMEMultipart()
    msg['From'] = os.environ.get("SMTP_FROM_ADDR", "workload@york.ac.uk")
    msg['To'] = recipient
    msg['Subject'] = subject

    # Create alternative container for HTML body
    alt_part = MIMEMultipart('alternative')
    alt_part.attach(MIMEText(body, 'html'))
    msg.attach(alt_part)

    # Attach individual reports if output_dir is provided
    if include_attachments and output_dir:
        _attach_individual_reports(msg, result, output_dir)

    return msg


def _attach_individual_reports(msg: MIMEMultipart,
                                result: object,
                                output_dir: str) -> None:
    """Attach HTML and PDF versions of individual reports, plus specification docx.

    Args:
        msg: Email message to attach files to
        result: WorkloadResult object
        output_dir: Output directory containing generated reports
    """
    name = getattr(result, 'name', 'Staff Member')
    # Match output_generator.py's generate_per_staff_reports() sanitization
    # exactly (replace, don't drop, invalid characters) - a name with an
    # apostrophe like "Mike O'Dea" produces "Mike_O_Dea", which a
    # character-dropping scheme like the old `isalnum()` filter here would
    # instead turn into "Mike_ODea", never matching the real file on disk.
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)

    # Try to find the individual report files
    staff_report_dir = os.path.join(output_dir, "Individual Reports")
    new_report_dir = os.path.join(output_dir, "New Individual Reports")

    # Look for HTML report in both possible directories. The real filename
    # (both report generators) is "{safe_name}_workload.html" - lowercase,
    # no "_Report" suffix.
    html_file = None
    pdf_file = None

    for report_dir in [staff_report_dir, new_report_dir]:
        candidate = os.path.join(report_dir, f"{safe_name}_workload.html")
        if os.path.exists(candidate):
            html_file = candidate
            break

    # Look for PDF file in output directory. No PDF generator exists yet in
    # this project (see docs/publishing_strategy.md's "Future Enhancements"),
    # so this is always a no-op today - kept so attaching one becomes
    # automatic the moment such a generator is added.
    pdf_path = os.path.join(output_dir, f"{safe_name}_workload.pdf")
    if os.path.exists(pdf_path):
        pdf_file = pdf_path

    # Attach HTML report
    if html_file and os.path.exists(html_file):
        try:
            with open(html_file, 'rb') as f:
                html_part = MIMEBase('text', 'html')
                html_part.set_payload(f.read())
                encoders.encode_base64(html_part)
                html_part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{safe_name}_Workload_Report.html"'
                )
                msg.attach(html_part)
        except Exception as e:
            print(f"Warning: Could not attach HTML report for {name}: {e}")

    # Attach PDF report
    if pdf_file and os.path.exists(pdf_file):
        try:
            with open(pdf_file, 'rb') as f:
                pdf_part = MIMEBase('application', 'pdf')
                pdf_part.set_payload(f.read())
                encoders.encode_base64(pdf_part)
                pdf_part.add_header(
                    'Content-Disposition',
                    f'attachment; filename="{safe_name}_Workload_Report.pdf"'
                )
                msg.attach(pdf_part)
        except Exception as e:
            print(f"Warning: Could not attach PDF report for {name}: {e}")

    # Attach specification docx (from docs folder)
    spec_docx_path = os.path.join(PROJECT_ROOT, "docs", "Work Allocation Model.docx")
    if os.path.exists(spec_docx_path):
        try:
            with open(spec_docx_path, 'rb') as f:
                spec_part = MIMEBase('application', 'vnd.openxmlformats-officedocument.wordprocessingml.document')
                spec_part.set_payload(f.read())
                encoders.encode_base64(spec_part)
                spec_part.add_header(
                    'Content-Disposition',
                    'attachment; filename="Work Allocation Model.docx"'
                )
                msg.attach(spec_part)
        except Exception as e:
            print(f"Warning: Could not attach specification docx: {e}")


def send_test_email(smtp_config: Dict,
                    test_email: str,
                    form_url: str) -> bool:
    """Send a test email to verify SMTP configuration.

    Args:
        smtp_config: SMTP configuration dict
        test_email: Recipient email address for testing
        form_url: Form URL to include in test

    Returns:
        True if test email sent successfully, False otherwise
    """
    # Create a mock result object
    class MockResult:
        name = "Test User"
        total_hours = 1642.0
        teaching_hours = 750.0
        research_hours = 492.0
        admin_hours = 300.0
        fte = 1.0

    results = [MockResult()]
    form_urls = {"Test User": form_url}
    emails = {"Test User": test_email}

    result = send_emails_via_smtp(results, form_urls, emails, smtp_config, dry_run=False)

    return result.get("Test User", False)


def verify_smtp_config(smtp_config: Dict) -> bool:
    """Verify SMTP configuration is complete.

    Args:
        smtp_config: Configuration dict to verify

    Returns:
        True if all required fields are present
    """
    required_fields = ["host", "from_addr"]
    missing = [f for f in required_fields if not smtp_config.get(f)]

    if missing:
        print(f"Missing required SMTP config fields: {', '.join(missing)}")
        return False

    # Check port has default
    if "port" not in smtp_config:
        smtp_config["port"] = 587

    return True


if __name__ == "__main__":
    import sys

    print("Email Sender Module for Workload Model")
    print("=" * 40)
    print()
    print("Usage:")
    print("  from email_sender import generate_email_body, send_emails_via_smtp")
    print()
    print("Example:")
    print("""
    results = [...]  # Your WorkloadResult objects
    form_urls = {...}  # Dict of name -> URL

    smtp_config = {
        "host": "smtp.york.ac.uk",
        "port": 587,
        "from_addr": "workload@york.ac.uk",
        "username": os.environ.get("SMTP_USERNAME"),
        "password": os.environ.get("SMTP_PASSWORD")
    }

    results = send_emails_via_smtp(results, form_urls, smtp_config)
    """)
