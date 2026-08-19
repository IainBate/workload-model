"""
Google Forms integration for the workload model.

This module provides functionality to:
1. Create Google Forms for staff feedback
2. Generate pre-filled URLs for each staff member
3. Export feedback responses

Usage:
    # Create a new form
    from google_forms import create_feedback_form, generate_prefilled_urls

    form_id = create_feedback_form("2026-7", "Workload Review 2026-7")
    urls = generate_prefilled_urls(results, form_id)

    # Export responses
    from google_forms import export_feedback_data
    export_feedback_data(form_id, "../output")

Note: This module requires Google API credentials setup. For a simpler approach,
consider using manual CSV-based feedback collection instead.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

# Try to import Google API client (optional)
try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


# Form field definitions
FORM_FIELDS = [
    {
        "title": "Staff Name",
        "type": "TEXT",
        "is_prefilled": True,
        "description": "Your full name (pre-filled)"
    },
    {
        "title": "Email Address",
        "type": "TEXT",
        "is_prefilled": True,
        "description": "Your email address (pre-filled)"
    },
    {
        "title": "Total Workload Status",
        "type": "RADIO",
        "options": ["Reasonable", "Too High", "Too Low", "Unsure"],
        "required": True
    },
    {
        "title": "Teaching Breakdown Feedback",
        "type": "TEXTAREA",
        "is_required": False,
        "description": "Please comment on your teaching workload breakdown:"
    },
    {
        "title": "Research Breakdown Feedback",
        "type": "TEXTAREA",
        "is_required": False,
        "description": "Please comment on your research workload breakdown:"
    },
    {
        "title": "Admin Breakdown Feedback",
        "type": "TEXTAREA",
        "is_required": False,
        "description": "Please comment on your admin workload breakdown:"
    },
    {
        "title": "Additional Concerns",
        "type": "TEXTAREA",
        "is_required": False
    },
    {
        "title": "Follow-up Meeting Requested?",
        "type": "CHECKBOX",
        "options": ["Yes - I'd like to discuss my workload"],
        "required": False
    }
]

# Template form title format
FORM_TITLE_TEMPLATE = "Workload Review {year_label}"


def _get_google_credentials() -> Optional[object]:
    """Get Google API credentials from environment or default location.

    Returns:
        Credentials object if available, None otherwise.
    """
    if not GOOGLE_API_AVAILABLE:
        return None

    # Try to get credentials from environment
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        try:
            creds_data = json.loads(creds_json)
            return Credentials.from_authorized_user_info(creds_data)
        except Exception:
            pass

    # Try default credentials location
    default_creds = Path.home() / ".config" / "google" / "credentials.json"
    if default_creds.exists():
        try:
            return Credentials.from_authorized_user_file(str(default_creds))
        except Exception:
            pass

    return None


def create_feedback_form(year_label: str,
                         form_title: str = None,
                         dry_run: bool = False) -> Optional[str]:
    """Create a new Google Form for staff feedback.

    Args:
        year_label: Academic year label (e.g., "2026-7")
        form_title: Custom form title. If None, uses template.
        dry_run: If True, don't actually create the form - just return a placeholder

    Returns:
        Form ID string on success, None if Google API not available or on error.

    Note: Requires Google API credentials to be set up via environment variables
    or default credentials file. For a simpler approach without OAuth, consider
    manually creating the form at https://docs.google.com/forms/u/0/
    """
    if dry_run:
        print(f"Dry run - would create form for {year_label}")
        return "test_form_id_placeholder"

    if not GOOGLE_API_AVAILABLE:
        print("Google API client not available.")
        print("Install with: pip install google-api-python-client google-auth")
        return None

    creds = _get_google_credentials()
    if not creds:
        print("Google credentials not found.")
        print("Set GOOGLE_CREDENTIALS environment variable or create default credentials file.")
        return None

    try:
        # Build the Forms API service
        service = build("forms", "v1", credentials=creds)

        # Create form title
        if not form_title:
            form_title = FORM_TITLE_TEMPLATE.format(year_label=year_label)

        # Form body structure
        form_body = {
            "info": {
                "title": form_title,
                "description": f"Please review your {year_label} workload model report and provide feedback."
            },
            "items": []
        }

        # Add each field to the form
        for field in FORM_FIELDS:
            item = _build_form_item(field)
            form_body["items"].append(item)

        # Create the form via API
        result = service.forms().create(body=form_body).execute()

        return result.get("formId")

    except HttpError as e:
        print(f"Google Forms API error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error creating form: {e}")
        return None


def _build_form_item(field: Dict) -> Dict:
    """Build a single form item from field definition."""
    item = {
        "title": field["title"],
        "description": field.get("description", "")
    }

    # Build the specific field type
    if field["type"] == "TEXT":
        item["questionItem"] = {
            "question": {
                "textQuestion": {}
            }
        }
    elif field["type"] == "RADIO":
        item["questionItem"] = {
            "question": {
                "choiceQuestion": {
                    "type": "RADIO",
                    "options": [{"value": opt} for opt in field["options"]]
                },
                "required": field.get("required", False)
            }
        }
    elif field["type"] == "TEXTAREA":
        item["questionItem"] = {
            "question": {
                "textQuestion": {
                    "paragraphTextEnabled": True
                },
                "required": field.get("is_required", False)
            }
        }
    elif field["type"] == "CHECKBOX":
        item["questionItem"] = {
            "question": {
                "choiceQuestion": {
                    "type": "CHECKBOX",
                    "options": [{"value": opt} for opt in field["options"]]
                },
                "required": field.get("required", False)
            }
        }

    return item


def generate_prefilled_urls(results: List[object],
                            form_id: str) -> Dict[str, str]:
    """Generate pre-filled form URLs for each staff member.

    Args:
        results: List of WorkloadResult objects from calculate_workload()
        form_id: Google Form ID

    Returns:
        Dict mapping staff name to pre-filled URL
    """
    if not GOOGLE_API_AVAILABLE:
        print("Google API client not available.")
        return {}

    # Build URLs using the prefilled response format
    # https://docs.google.com/forms/d/e/{form_id}/viewform?usp=pp_url&entry.{field_id}={value}
    #
    # NOTE: "entry.1"/"entry.2" below are placeholders, not real field IDs. A
    # real Google Form assigns each field a large, effectively-random numeric
    # ID (e.g. "entry.1974357890") visible only after the form exists - these
    # URLs will not actually pre-fill anything on a genuinely created form.
    # Wiring real IDs through needs the form's field metadata from the Forms
    # API at creation time (see _get_entry_id_for_question below), which this
    # function doesn't yet receive. Left as-is pending real OAuth/API access
    # to test against - flagging rather than guessing the wiring.
    base_url = f"https://docs.google.com/forms/d/e/{form_id}/viewform"

    from email_data import load_staff_emails
    emails = load_staff_emails()

    urls = {}
    for result in results:
        params = []

        name = getattr(result, "name", None)
        if name:
            params.append(f"entry.1={quote(name)}")
            if name in emails:
                params.append(f"entry.2={quote(emails[name])}")

        query_string = "&".join(params)
        full_url = f"{base_url}?{query_string}" if params else base_url

        urls[result.name] = full_url

    return urls


def export_feedback_data(form_id: str,
                         output_dir: str = None) -> Optional[str]:
    """Export Google Forms responses to CSV.

    Args:
        form_id: Google Form ID
        output_dir: Output directory for exported file

    Returns:
        Path to exported CSV file on success, None on failure.

    Note: This requires additional permissions to access form responses.
    """
    if not GOOGLE_API_AVAILABLE:
        print("Google API client not available.")
        return None

    creds = _get_google_credentials()
    if not creds:
        print("Google credentials not found.")
        return None

    try:
        # Build the Forms API service
        service = build("forms", "v1", credentials=creds)

        # Get form responses
        result = service.forms().responses().list(formId=form_id).execute()

        responses = result.get("responses", [])
        if not responses:
            print("No responses found for this form.")
            return None

        # Extract field definitions to determine response structure
        form_info = service.forms().get(formId=form_id).execute()
        items = form_info.get("items", [])

        # Build CSV content
        import csv
        from io import StringIO

        output_dir_path = Path(output_dir) if output_dir else Path.cwd()

        # Create CSV in memory first
        output = StringIO()
        writer = csv.writer(output)

        # Write header (from form questions)
        headers = ["Timestamp", "Form Response ID"]
        for item in items:
            question = item.get("questionItem", {}).get("question", {})
            headers.append(question.get("title", "Unknown"))
        writer.writerow(headers)

        # Write response rows
        for response in responses:
            row = [response.get("createTime"), response.get("responseId")]

            # Extract answers in order
            answer_data = response.get("answers", {})
            for item in items:
                question_title = item.get("questionItem", {}).get("question", {}).get("title", "")
                entry_id = _get_entry_id_for_question(item)

                if entry_id and entry_id in answer_data:
                    answers = answer_data[entry_id].get("textAnswers", {}).get("answers", [])
                    if answers:
                        row.append(answers[0].get("value", ""))
                    else:
                        # Try other answer types (choice, checkbox)
                        choice_answer = answer_data[entry_id].get("textAnswer", "")
                        row.append(choice_answer)
                else:
                    row.append("")

            writer.writerow(row)

        # Write to file
        output_path = output_dir_path / f"feedback_responses_{form_id}.csv"
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            f.write(output.getvalue())

        print(f"Exported {len(responses)} responses to {output_path}")
        return str(output_path)

    except HttpError as e:
        print(f"Google Forms API error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error exporting data: {e}")
        return None


def _get_entry_id_for_question(item: Dict) -> Optional[str]:
    """Extract the entry ID from a form item.

    Note: This is a simplified implementation. In practice, you may need to
    extract the entry ID from the form's HTML or use a more robust parsing method.
    """
    # The entry ID pattern is typically "entry.{number}"
    # For a production system, you'd want to parse this from the actual form
    return None


def print_form_instructions(form_id: str) -> None:
    """Print instructions for manually using a Google Form.

    Args:
        form_id: Google Form ID
    """
    base_url = f"https://docs.google.com/forms/d/e/{form_id}/viewform"

    print(f"""
Google Forms Instructions
=========================

Form ID: {form_id}

To view the form: {base_url}

To generate pre-filled URLs for staff:
1. Add entry.{i}={value} parameters to the URL
2. For multiple fields, join with & character

Example pre-filled URL:
{base_url}?entry.1=John+Smith&entry.2=john.smith@york.ac.uk

For automated form creation and URL generation, use:
    python -c "from google_forms import generate_prefilled_urls; ..."
""")


def quick_start_guide() -> str:
    """Return a quick start guide for using this module.

    Returns:
        String with step-by-step instructions.
    """
    return f"""
Quick Start Guide: Google Forms Integration
============================================

STEP 1: Create the form manually (recommended)
----------------------------------------------
1. Go to https://docs.google.com/forms/u/0/
2. Click Blank form
3. Title: {FORM_TITLE_TEMPLATE.format(year_label="2026-7")}
4. Add questions:
   - Staff Name (short answer, required, pre-filled)
   - Email Address (short answer, required, pre-filled)
   - Total Workload Status (multiple choice)
   - Feedback comments (paragraph text)
5. Get your form ID from the URL: forms.gle/{chr(123)}FORM_ID{chr(125)}

STEP 2: Generate pre-filled URLs for each staff member
-------------------------------------------------------
python -c "
from google_forms import generate_prefilled_urls

# Load your results (from existing calculation)
results = [...]  # Your WorkloadResult objects
form_id = 'YOUR_FORM_ID_HERE'

urls = generate_prefilled_urls(results, form_id)

# Save to file
import json
with open('../output/form_urls.json', 'w') as f:
    json.dump(urls, f, indent=2)
print(f'Generated {len(urls)} URLs')
"

STEP 3: Send emails with the form links
----------------------------------------
Use your preferred email system to send the URLs to each staff member.

The email should include:
- Subject: Your Workload Model Report for {FORM_TITLE_TEMPLATE.format(year_label="2026-7")}
- Body: Link to their personalized feedback form
- Deadline date

STEP 4: Collect and review feedback
------------------------------------
Responses will appear in the Google Form responses tab.
Export as CSV for analysis.
"""


if __name__ == "__main__":
    # Print quick start guide when run directly
    print(quick_start_guide())
