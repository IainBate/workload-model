# Publishing Strategy for Workload Model

## Overview

This document describes a publishing strategy that extends the workload model to:
1. Collect staff email addresses
2. Create Google Forms for feedback
3. Send automated emails with form links
4. Aggregate and display feedback in a dashboard

**Key Design Principle:** All new functionality is implemented as separate modules that import from existing code but don't modify any existing files or functions.

---

## Current State

### Existing Outputs
- CSV: `Staff workload model.csv` - per-staff workload data
- Excel: `Staff workload model.xlsx` - formatted spreadsheet with formulas
- HTML: `workload_report.html` - department dashboard
- Individual Reports: `Individual Reports/*.html` - detailed reports per staff member

### Missing Components
- No email distribution mechanism
- No feedback collection system
- Staff contact information not stored in data files

---

## New Components

### 1. Staff Email Data (`scripts/email_data.py`)

**File:** `data/Staff Emails.csv` (NEW - optional)

```csv
Name,Email
Adrian Bors,adrian.bors@york.ac.uk
Alena Denisova,alena.denisova@york.ac.uk
...
```

**Alternative:** Extend existing `Staff Categories and FTE.csv` with an optional Email column.

**Functions:**
- `load_staff_emails(data_dir)` - Load email addresses from CSV

---

### 2. Google Forms Integration (`scripts/google_forms.py`)

**Form Structure:**

| Field | Type | Entry ID Pattern |
|-------|------|------------------|
| Staff Name | Pre-filled short answer | entry.{id} |
| Email | Pre-filled short answer | entry.{id} |
| Total Workload | Read-only display | entry.{id} |
| Teaching Hours | Read-only display | entry{id} |
| Research Hours | Read-only display | entry.{id} |
| Admin Hours | Read-only display | entry.{id} |
| Feedback Comments | Paragraph text | entry.{id} |
| Concerns | Multiple choice checkboxes | entry.{id} |
| Follow-up Meeting Requested? | Yes/No | entry.{id} |

**Functions:**
- `create_feedback_form(year_label, form_title)` - Create new Google Form
- `generate_prefilled_urls(results, form_id)` - Generate unique URLs per staff member
- `export_feedback_data(form_id, output_dir)` - Export responses to CSV

---

### 3. Email Distribution (`scripts/email_sender.py`)

**Email Content:**
```
Subject: Your Workload Model Report for {year_label}

Hi {name},

Your workload model report is attached. Please review it and provide feedback via:
{form_url}

Key figures:
- Total: {total_hours}h
- Teaching: {teaching_hours}h  
- Research: {research_hours}h
- Admin: {admin_hours}h

If you have any concerns or corrections, please use the form above by {deadline}.

-- 
Workload Model Calculator
University of York
```

**Attachments:**
- `Staff Name_Workload_Report.html` - HTML version of individual report
- `Staff Name_Workload_Report.pdf` - PDF version of individual report (if generated)
- `Work Allocation Model.docx` - Specification document with workload calculation rules

**Functions:**
- `generate_email_body(result, form_url, year_label)` - Generate HTML email body
- `_build_email_message(result, form_url, year_label, output_dir)` - Build message with optional attachments
- `send_emails_via_smtp(results, smtp_config, dry_run, output_dir)` - Send emails via SMTP

**Attachment Logic:**
1. Searches for individual reports in both `Individual Reports/` and `New Individual Reports/`
2. Matches files using sanitized staff name patterns (e.g., "John_Smith.html")
3. Attaches the Work Allocation Model.docx from the docs folder (always included if present)

---

### 4. Feedback Dashboard (`scripts/feedback_dashboard.py`)

**New Output:** `output/feedback_summary.html`

Shows:
- List of all staff with feedback status (completed/pending)
- Aggregated comments summary
- Action items requiring attention
- Deadline tracking

---

## Implementation Plan

### Step 1: Email Data Collection

**Create new file:** `data/Staff Emails.csv`

```csv
Name,Email
```

Populate with staff email addresses. Format: `{first_name}.{last_name}@york.ac.uk` for University of York.

---

### Step 2: Create Google Form Template

1. Go to https://docs.google.com/forms/u/0/
2. Click Blank form
3. Configure form title: "Workload Review {year_label}"
4. Add questions per the form structure above
5. Get form ID from URL: `https://forms.gle/{form_id}` or create via API

**Optional:** Create a template form that can be copied for each academic year.

---

### Step 3: Implement New Modules

#### A. `scripts/email_data.py`

```python
import csv
from pathlib import Path
from typing import Dict, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

def load_staff_emails(data_dir: str = None) -> Dict[str, str]:
    """Load staff email addresses from optional CSV.
    
    Returns dict mapping canonical_name to email address.
    Falls back to Staff Categories and FTE.csv if Staff Emails.csv doesn't exist.
    """
```

#### B. `scripts/google_forms.py`

```python
import os
from typing import Dict, List, Optional

from data_loader import WorkloadResult

def create_feedback_form(year_label: str, form_title: str = None) -> Optional[str]:
    """Create a new Google Form for staff feedback.
    
    Returns form ID string on success, None on failure.
    """
    
def generate_prefilled_urls(results: List[WorkloadResult], 
                            form_id: str) -> Dict[str, str]:
    """Generate pre-filled form URLs for each staff member."""
    
def export_feedback_data(form_id: str, output_dir: str) -> Optional[str]:
    """Export Google Forms responses to CSV.
    
    Returns path to exported file on success.
    """
```

#### C. `scripts/email_sender.py`

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List

from data_loader import WorkloadResult

def generate_email_body(result: WorkloadResult, 
                        form_url: str, 
                        year_label: str) -> str:
    """Generate HTML email body for staff member."""
    
def send_emails_via_smtp(results: List[WorkloadResult],
                         smtp_config: Dict[str, str],
                         dry_run: bool = False) -> Dict[str, bool]:
    """Send emails via SMTP server.
    
    Returns dict mapping staff name to success status.
    """
```

#### D. `scripts/feedback_dashboard.py`

```python
from typing import List

def generate_feedback_summary(results: List[WorkloadResult],
                              feedback_csv_path: str,
                              output_dir: str) -> None:
    """Generate HTML dashboard showing all feedback."""
```

---

### Step 4: Update CLI Entry Point

**Update `scripts/main.py` with new flags:**

```python
parser.add_argument("--generate-forms", action="store_true",
                    help="Create Google Forms for staff feedback")
parser.add_argument("--form-title", type=str, default=None,
                    help="Title for the feedback form (default: 'Workload Review {year}')")
parser.add_argument("--send-emails", action="store_true",
                    help="Send emails with form links to staff")
parser.add_argument("--smtp-config", type=str, default=None,
                    help="Path to SMTP configuration YAML file")
parser.add_argument("--feedback-csv", type=str, default=None,
                    help="Path to exported feedback CSV (for dashboard)")
```

---

## Execution Flow

### Option A: Manual Form Creation

```bash
# 1. Run the calculator to generate reports
cd scripts/
python main.py

# 2. Manually create Google Form at https://docs.google.com/forms/u/0/

# 3. Generate pre-filled URLs using form ID
python -c "
from google_forms import generate_prefilled_urls, load_staff_emails
import json

results = [...]  # Load results from calculation
form_id = 'YOUR_FORM_ID'
urls = generate_prefilled_urls(results, form_id)

# Save to file for email sending
with open('../output/form_urls.json', 'w') as f:
    json.dump(urls, f)
"

# 4. Send emails (manually or via script)
```

### Option B: Programmatic Form Creation

```bash
# 1. Create form programmatically and send emails in one command
python main.py --generate-forms --form-title "Workload Review 2026-7" --send-emails --smtp-config ../smtp_config.yaml
```

---

## Verification Checks

### Pre-Implementation Verification

| Check | Command |
|-------|---------|
| Python version >= 3.8 | `python --version` |
| Required packages installed | `pip list \| grep -E "openpyxl\|yaml"` |

### Post-Implementation Verification

#### 1. Email Data Loading
```bash
python -c "
from email_data import load_staff_emails
emails = load_staff_emails('../data')
print(f'Loaded {len(emails)} email addresses')
for name, email in list(emails.items())[:3]:
    print(f'  {name}: {email}')
"
```

#### 2. Google Forms Form Creation (Test Only)
```bash
python -c "
from google_forms import create_feedback_form
# Test with a dry-run mode first
form_id = create_feedback_form('2026-7', form_title='TEST Feedback Form')
print(f'Form created: {form_id}')
"
```

#### 3. Prefilled URL Generation
```bash
python -c "
from google_forms import generate_prefilled_urls
import json

# Load results from existing calculation
results = [...]  # Load WorkloadResult objects
form_id = 'YOUR_TEST_FORM_ID'
urls = generate_prefilled_urls(results, form_id)

print(f'Generated {len(urls)} URLs')
with open('../output/form_urls.json', 'w') as f:
    json.dump(urls, f, indent=2)
"
```

#### 4. Email Body Generation
```bash
python -c "
from email_sender import generate_email_body
import json

# Load results
results = [...]  # Load WorkloadResult objects
with open('../output/form_urls.json') as f:
    urls = json.load(f)

result = results[0]
email_body = generate_email_body(result, urls[result.name], '2026-7')
print(email_body[:500])  # Preview first 500 chars
"
```

#### 5. Feedback Dashboard Generation
```bash
python -c "
from feedback_dashboard import generate_feedback_summary

# Run with test data
generate_feedback_summary(
    results=[...],
    feedback_csv_path='../output/feedback_responses.csv',
    output_dir='../output'
)
print('Dashboard generated at ../output/feedback_summary.html')
"
```

---

## SMTP Configuration Example

**File:** `smtp_config.yaml`

```yaml
host: smtp.york.ac.uk
port: 587
from_addr: workload@york.ac.uk
username: ${SMTP_USERNAME}  # Use environment variable
password: ${SMTP_PASSWORD}  # Use environment variable
use_tls: true
```

---

## Security Considerations

1. **Email addresses**: Stored in plain text CSV - ensure file permissions are set appropriately
2. **SMTP credentials**: Never commit to git; use environment variables or separate config file
3. **Form responses**: Google Forms stores data securely - ensure only authorized users can access the form responses sheet
4. **Individual reports**: Each staff member receives their own report via pre-filled URL

---

## Implementation Status

### Completed Modules

| Module | File | Purpose |
|--------|------|---------|
| `email_data.py` | `/scripts/email_data.py` | Load staff email addresses from CSV files with fallback mechanisms |
| `google_forms.py` | `/scripts/google_forms.py` | Google Form creation and pre-filled URL generation |
| `email_sender.py` | `/scripts/email_sender.py` | SMTP email distribution with HTML templates |
| `feedback_dashboard.py` | `/scripts/feedback_dashboard.py` | Generate feedback summary dashboard |

### Updated Files

| File | Changes |
|------|---------|
| `scripts/main.py` | Added CLI flags: `--generate-forms`, `--form-title`, `--send-emails`, `--smtp-config`, `--feedback-csv` |

## Future Enhancements

1. Add PDF export of individual reports for email attachments
2. Implement reminder emails after deadline approaching
3. Add analytics to feedback dashboard (word clouds, sentiment analysis)
4. Create a "responded" flag in workload_adjustments.csv for follow-up tracking

---

## Review Findings (2026-08-19)

The code as originally written did not run: `--send-emails` crashed with a
`NameError` before ever reaching the SMTP call, and the recipient address was
never actually connected to a real address even once that crash was fixed.
Fixed, along with several other issues found while verifying each path.

### Fixed

- **`main.py` `_handle_email_send` crashed immediately** (`NameError:
  output_dir`) - the variable was never passed into the function. `--send-emails`
  could not run at all before this fix.
- **Every email would have gone to nobody**: `send_emails_via_smtp()` sent to
  `result.email`, but `WorkloadResult` has no such field, so the recipient list
  was always `[""]`. The `emails` dict loaded via `get_all_staff_emails()` was
  never passed through to the sender - it's now a required argument, threaded
  from `main.py` through `send_emails_via_smtp()` to `_build_email_message()`.
- **Silently guessed email addresses**: `get_all_staff_emails()` fabricated
  `firstname.lastname@york.ac.uk` for anyone missing from a real source and
  returned it indistinguishably from a confirmed one - a workload report is
  personal data, so a wrong guess is a real privacy/delivery failure, not a
  cosmetic gap, and it directly contradicts this project's documented "no
  guessed data" rule (root CLAUDE.md). `get_all_staff_emails()` now returns
  `(emails, missing_names)` - only confirmed addresses, with anyone missing
  reported by name rather than guessed at. `main.py` skips missing staff and
  says so, instead of attempting to send.
- **Report attachments never matched the real files**: the glob patterns
  (`{name}.html`, `{name}_Workload_Report.html`) don't match the actual
  filename `output_generator.py` writes (`{name}_workload.html`), so only the
  fallback wildcard ever worked - and its name-sanitization *dropped* special
  characters instead of replacing them with `_` like the report generator
  does, so it silently failed for anyone with an apostrophe in their name
  (e.g. "Mike O'Dea" → "Mike ODea", not the real "Mike O_Dea"). Rewritten to
  match the report generator's sanitization exactly and look up the real
  filename directly.
- **Specification docx attachment**: confirmed working - it reads from
  `docs/Work Allocation Model.docx`, which matches where the file actually
  lives after the 2026-08-18 consolidation. **Yes, both the individual report
  and the specification docx are attached** once the fixes above are applied;
  verified end-to-end with a temporary `Staff Emails.csv`, including the
  apostrophe-name case.
- **Missing `f` prefix**: `create_feedback_form()`'s dry-run branch printed
  the literal string `"{year_label}"` instead of interpolating it.
- **No URL-encoding**: `generate_prefilled_urls()` interpolated names/emails
  directly into the query string - broken for any name containing a space,
  i.e. everyone. Now passed through `urllib.parse.quote()`.

### Known limitations (not fixed - flagging rather than guessing)

- **Form entry IDs are placeholders**: `generate_prefilled_urls()` hardcodes
  `entry.1`/`entry.2`. A real Google Form assigns large, effectively-random
  numeric field IDs, visible only after the form exists via the Forms API -
  these URLs will not pre-fill anything on a genuinely created form. Wiring
  real IDs through needs the form's field metadata at creation time, which
  isn't threaded to this function yet. Untested either way: `google-api-python-client`/
  `google-auth` are not installed in this environment, so `GOOGLE_API_AVAILABLE`
  is `False` and the whole OAuth-gated path (`create_feedback_form()`,
  `export_feedback_data()`) has not been exercised against a real form.
- **`_categorize_staff_status()`'s email-matching is dead code**: it checks
  `email in feedback_data`, but `WorkloadResult` has no `.email` field (so
  `email` is always `""`) and `_load_feedback_responses()` never keys
  `feedback_data` by email in the first place. Name-based matching (the
  primary path) works correctly; the email fallback simply never fires.
- **No SMTP dry-run from the CLI**: `--send-emails` has no way to preview
  without a working SMTP config, since the existing `--dry-run` flag exits
  before reaching the publishing-strategy section. Not currently a live risk
  - `data/Staff Emails.csv` doesn't exist yet, so `--send-emails` safely
  no-ops - but worth a dedicated flag before this is ever pointed at a real
  SMTP server.
