"""
Data loading and processing for the workload calculator.
Handles CSV ingestion, staff name normalization, module mapping, and data merging.
"""

import csv
import json
import glob
import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from pathlib import Path

# Get project root directory (parent of scripts folder)
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent

import config


@dataclass
class ModuleData:
    """Structured representation of a module from WTW CSV."""
    name: str
    codes: List[str]
    stage: int
    semester: int
    credits: int
    cohort: str
    lead_name: str
    teachers: List[str]
    extra_markers: List[str]
    expert_checker: str
    general_checker_required: bool
    general_checker: str
    practicals: int  # Number of practical sessions
    has_h_m_variants: bool
    contact_hours: float  # Estimated contact hours (from credits)
    practical_contact_hours: float = 0.0  # Actual contact hours per practical session (from CSV)
    student_count: int = 0  # From CS Module Numbers.csv
    assessment_count: int = 1  # From CS Module Assessment Numbers.csv
    source_year: str = ""  # e.g., "2026-7"


@dataclass
class StaffData:
    """Complete data for a single staff member."""
    canonical_name: str
    aliases: List[str]
    fte: float  # From Part time.csv
    employment_start: int
    active: bool
    category: str  # "ART" or "T and S"
    project_load: float
    pastoral_load: float
    adjusted_project_load: float
    adjusted_pastoral_load: float
    ecr_year: str
    ecr_value: float
    citizenship_level: int
    research_grant_income: str
    research_grant_income_value: float
    citizenship_value: float
    initial_fractional_project_load: float
    initial_fractional_pastoral_load: float
    notes: str
    roles: List[str]  # From WAW.csv
    phd_supervisions: int  # Sole supervisors from PhD Supervision Data.csv
    phd_co_supervisions: int  # Co-supervisors from PhD Supervision Data.csv
    phd_assessor_count: int  # TAP assessor instances from PhD Supervision Data.csv
    research_projects: List[dict]  # From % FTE for CS.csv
    saint_modules: List[str]  # SAINTS modules they teach
    unallocated_students: int = 0  # Remaining students after allocation


@dataclass
class WorkloadResult:
    """Complete workload calculation for a single staff member."""
    name: str
    fte: float
    total_hours: float
    teaching_hours: float
    research_hours: float
    admin_hours: float
    teaching_detail: str
    research_detail: str
    admin_detail: str
    assumptions: List[str]  # Items where data was guessed or defaulted
    missing_data: List[str]  # Items where data is genuinely missing
    nominal_hours: float = 0.0  # FTE-adjusted nominal hours for reference


@dataclass
class YearData:
    """All data for a single academic year."""
    year_label: str  # e.g., "2026-7"
    modules: List[ModuleData]
    student_counts: Dict[str, int]  # module_code -> count
    assessment_counts: Dict[str, int]  # module_code -> count
    staff: Dict[str, StaffData]  # canonical_name -> StaffData
    known_lecturers: Set[str]  # From previous year's WTW
    name_lookup: Dict[str, str] = field(default_factory=dict)  # alias -> canonical (reverse lookup)
    canonical_lookup: Dict[str, List[str]] = field(default_factory=dict)  # canonical -> aliases (for reference)


# --- Staff Name Normalization ---

DATA_DIR = PROJECT_ROOT / "data"

def _load_name_lookup(filepath: str = "staff_name_lookup.json") -> Dict[str, List[str]]:
    """Load the staff name lookup table."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("mappings", {})


def _build_reverse_lookup(mappings: Dict[str, List[str]]) -> Dict[str, str]:
    """Build a reverse lookup: alias -> canonical_name."""
    reverse = {}
    for canonical, aliases in mappings.items():
        for alias in aliases:
            reverse[alias.strip().lower()] = canonical
    return reverse


# Known non-person entries that should be skipped
_NON_PERSON_ENTRIES = {
    "as below", "n/a", "none", "tbd", "law school", "projects",
    "not applicable", "tba", "as_bellow", "as_below",
    "saints", "scse", "hcit", "acs", "ug1", "ug2", "ug3", "ug4", "ug4 only",
    "meng", "pg", "msc", "pgcap", "frepeats",
    "true", "false",
    "total fte", "students per fte", "allocated students", "unallocated students",
    "number of pastoral students", "number of project students", "adjusted number of t&s staff",
    "column 1", "column 2", "column 3", "column 4", "column 5", "column 6", "column 7",
    "column 8", "column 9", "column 10", "column 11", "column 12", "column 13", "column 14",
    "column 15", "column 16", "column 17", "column 18", "column 19", "column 20",
    "notes", "code(s)", "cohort", "stage", "semester", "credits",
    "who teaches what (wtw) lead", "teaching", "extra markers",
    "expert checker", "general checker", "general checker required?",
    "module has h and m variants", "practicals", "markers", "notes",
    "allocation counter", "total", "lead", "teaching", "marking",
    "expert checker", "sOF1", "tHE1", "hCIN", "sOF2", "sYS1",
}


def normalize_name(name: str, reverse_lookup: Dict[str, str],
                   unknown_callback=None) -> Optional[str]:
    """
    Normalize a staff name to its canonical form.
    If the name is not in the lookup, prompt the user if unknown_callback is provided.
    """
    if not name:
        return None
    stripped = name.strip()
    if stripped.lower() in _NON_PERSON_ENTRIES or len(stripped) < 2:
        return None

    name = name.strip()
    key = name.lower()

    if key in reverse_lookup:
        return reverse_lookup[key]

    # Try partial match (e.g., "Iain B" should match "Iain Bate")
    for alias, canonical in reverse_lookup.items():
        if key == alias.lower():
            return canonical
        # Only match if the input is a clear short form (initials, first name, or known prefix)
        # Be conservative: only match if input is <= 3 chars or contains a space (partial name)
        if (len(key) <= 3 and key == alias.lower()[:len(key)]) or \
           (' ' in key and key == alias.lower()[:len(key)]):
            if unknown_callback:
                if unknown_callback(name, canonical):
                    return canonical
            return canonical

    # If nothing matches, ask the user or return as-is
    if unknown_callback:
        if unknown_callback(name, None):
            return name
    # Non-interactive mode: return the raw name (will be flagged later)
    # Also skip obvious non-person entries
    if name.strip().lower() in _NON_PERSON_ENTRIES:
        return None
    return name.strip() if name.strip() else None


def _prompt_name_match(user_name: str, canonical_name: Optional[str]) -> bool:
    """
    Callback for unknown names. Returns True if the user confirms a match.
    """
    if canonical_name:
        response = input(f"Does '{user_name}' refer to '{canonical_name}'? (y/n): ").strip().lower()
        return response == "y"
    else:
        response = input(f"Unknown name: '{user_name}'. Use this as-is? (y/n): ").strip().lower()
        return response == "y"


# --- WTW CSV Loading ---

def _detect_year_from_filename(filename: str) -> str:
    """Extract year label from WTW filename, e.g., 'WTW 2026-7.csv' -> '2026-7'."""
    base = os.path.basename(filename)
    # Look for pattern YYYY-X
    match = re.search(r'(\d{4})-(\d)', base)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return base


def _parse_wtw_csv(filepath: str, known_lecturers: Set[str] = None) -> List[ModuleData]:
    """
    Parse a WTW CSV file into ModuleData objects.
    Handles both 2025-6 and 2026-7 formats.
    """
    modules = []
    year_label = _detect_year_from_filename(filepath)

    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read().splitlines()

    # Find the header row (contains "Code(s)" or "Who Teaches What")
    header_idx = -1
    for i, line in enumerate(content):
        if "Code(s)" in line or "Who Teaches What" in line:
            header_idx = i
            break

    if header_idx == -1:
        return modules

    # Parse rows starting after the header
    reader = csv.reader(content[header_idx + 1:])
    for row in reader:
        if len(row) < 2:
            continue

        # Skip empty or header-like rows
        if not row[0].strip() or row[0].strip().startswith("Allocation"):
            continue

        try:
            # Module name
            name = row[0].strip()
            if not name:
                continue

            # Module codes
            codes_str = row[1] if len(row) > 1 else ""
            codes = [c.strip() for c in codes_str.split(",") if c.strip()]
            if not codes:
                continue

            # Stage
            stage = int(row[2]) if len(row) > 2 and row[2].strip().isdigit() else 0

            # Semester
            semester = 0
            if len(row) > 3:
                s = row[3].strip()
                if s.isdigit():
                    semester = int(s)
                elif "-" in s:
                    semester = int(s.split("-")[0])  # e.g., "1-2"

            # Credits
            credits = int(row[4]) if len(row) > 4 and row[4].strip().isdigit() else 0

            # Cohort
            cohort = row[5].strip() if len(row) > 5 else ""

            # Lead name
            lead_name = row[6].strip() if len(row) > 6 else ""

            # Teachers - varies by year format
            teachers = []
            if year_label.startswith("2026"):
                # 2026-7 format: columns 7, 8 are teachers
                for idx in [7, 8]:
                    if len(row) > idx and row[idx].strip():
                        teachers.append(row[idx].strip())
            else:
                # 2025-6 format: columns 4, 5, 6 are teachers (different layout)
                for idx in [4, 5, 6]:
                    if len(row) > idx and row[idx].strip():
                        teachers.append(row[idx].strip())

            # Extra markers
            extra_markers = []
            if len(row) > 9 and row[9].strip():
                extra_markers = [m.strip() for m in row[9].split(",") if m.strip()]

            # Expert checker
            expert_checker = ""
            if len(row) > 10:
                val = row[10].strip()
                if val and val.upper() not in ("N/A", "NONE", "TBD"):
                    expert_checker = val

            # General checker required
            general_checker_required = False
            if len(row) > 11:
                val = row[11].strip().upper()
                general_checker_required = "TRUE" in val

            # General checker
            general_checker = ""
            if len(row) > 12:
                val = row[12].strip()
                if val and val.upper() not in ("N/A", "NONE", "TBD"):
                    general_checker = val

            # Has H/M variants
            has_h_m_variants = False
            if len(row) > 14:
                val = row[14].strip().upper()
                has_h_m_variants = "TRUE" in val

            # Estimate contact hours from credits (1 hour per credit as standard)
            contact_hours = credits * config.DEFAULT_CONTACT_HOURS_PER_CREDIT

            # Read practicals count from column 13 (new column)
            practicals = 0
            if len(row) > 13 and row[13].strip():
                try:
                    practicals = int(row[13].strip())
                except ValueError:
                    practicals = 0

            module = ModuleData(
                name=name,
                codes=codes,
                stage=stage,
                semester=semester,
                credits=credits,
                cohort=cohort,
                lead_name=lead_name,
                teachers=teachers,
                extra_markers=extra_markers,
                expert_checker=expert_checker,
                general_checker_required=general_checker_required,
                general_checker=general_checker,
                practicals=practicals,
                has_h_m_variants=has_h_m_variants,
                contact_hours=contact_hours,
                student_count=config.DEFAULT_STUDENT_COUNT,
                assessment_count=1,
                source_year=year_label,
            )
            modules.append(module)

        except (IndexError, ValueError):
            continue

    return modules


def _load_student_counts(filepath: str = "CS Module Numbers.csv") -> Dict[str, int]:
    """Load student counts from CS Module Numbers.csv. Returns {module_code: count}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    counts = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("Module Code", "").strip()
            acronym = row.get("Acronym", "").strip()
            count_str = row.get("Student Numbers", "0").strip()
            try:
                count = int(count_str)
                counts[code] = count
                counts[acronym] = count  # Also index by acronym
            except ValueError:
                pass
    return counts


def _load_assessment_counts(filepath: str = "CS Module Assessment Numbers.csv") -> Dict[str, int]:
    """Load assessment counts from CS Module Assessment Numbers.csv. Returns {module_code: count}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    counts = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("Module Code", "").strip()
            acronym = row.get("Module Acronym", "").strip()
            count_str = row.get("Number of Assessments", "1").strip()
            try:
                count = int(count_str)
                counts[code] = count
                counts[acronym] = count
            except ValueError:
                pass
    return counts


def _load_practical_data(filepath: str = "CS Module Assessment Numbers.csv") -> Dict[str, dict]:
    """Load practical data from CS Module Assessment Numbers.csv.
    Returns {module_code: {practicals: int, practical_contact_hours: float}}.
    practical_contact_hours = Total Duration / Number of Practicals (hours per session).
    """
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    data = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("Module Code", "").strip()
            acronym = row.get("Module Acronym", "").strip()
            n_str = row.get("Number of Practicals", "").strip()
            duration_str = row.get("Total Duration", "").strip()
            if not n_str or n_str.upper() == "NA":
                continue
            try:
                n_practicals = int(n_str)
            except ValueError:
                continue
            # Parse duration: "X hours" or "Y hours"
            duration_hours = 0.0
            if duration_str:
                dur_match = re.search(r"([\d.]+)\s*hours?", duration_str)
                if dur_match:
                    duration_hours = float(dur_match.group(1))
            # Contact hours per practical session
            contact_per = duration_hours / n_practicals if n_practicals > 0 else 0.0
            data[code] = {"practicals": n_practicals, "practical_contact_hours": contact_per}
            data[acronym] = {"practicals": n_practicals, "practical_contact_hours": contact_per}
    return data


def _load_pastoral_load(filepath: str = "pastoral_load.csv") -> Dict[str, int]:
    """Load pastoral load data. Returns {supervisor_name: total_students}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    data = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            supervisor = row.get("Supervisor", "").strip().upper()
            total = row.get("UG & PGT Supervisees", "0").strip()
            try:
                data[supervisor] = int(total)
            except ValueError:
                pass
    return data


def _load_project_load(filepath: str = "project_load.csv") -> Dict[str, dict]:
    """Load project load data from project_load.csv. Returns {canonical_name: data_dict}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    data = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            person = row.get("Person", "").strip()
            if not person or person == "Total FTE":
                continue
            try:
                data[person] = {
                    "employment_start": int(row.get("Employment Start", 0) or 0),
                    "active": row.get("Active", "TRUE").strip().upper() == "TRUE",
                    "project_load": float(row.get("Base project load", 0) or 0),
                    "pastoral_load": float(row.get("Base pastoral load", 0) or 0),
                    "ecr_year": row.get("ECR Year", "N/A").strip(),
                    "ecr_value": float(row.get("ECR Value", 0) or 0),
                    "citizenship_level": int(row.get("Citizenship Level", 0) or 0),
                    "research_grant_income": row.get("Research Grant Income", "N/A").strip(),
                    "research_grant_income_value": float(row.get("Research Grant Income Value", 0) or 0),
                    "citizenship_value": float(row.get("Citizen value", 0) or 0),
                    "initial_fractional_project_load": float(row.get("Initial Fractional Project Load", 0) or 0),
                    "initial_fractional_pastoral_load": float(row.get("Initial Fractional Pastoral Group Load", 0) or 0),
                    "adjusted_project_load": float(row.get("Adjusted Project Load", 0) or 0),
                    "adjusted_pastoral_load": float(row.get("Adjusted Pastoral Group Load", 0) or 0),
                    "project_load_raw": float(row.get("Project Load", 0) or 0),
                    "pastoral_load_raw": float(row.get("Pastoral Load", 0) or 0),
                    "notes": row.get("Notes", "").strip(),
                }
            except (ValueError, KeyError):
                pass
    return data


def _load_phd_supervision(filepath: str = "PhD Supervision Data.csv") -> Dict[str, dict]:
    """Load PhD supervision data. Returns {name: {total, sole, co, tap, combined}}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    data = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            staff = row.get("Staff member", "").strip()
            if not staff or staff == "Total as supervisor":
                continue
            try:
                data[staff] = {
                    "total_as_supervisor": int(row.get("Total as supervisor", 0) or 0),
                    "sole_supervisor": int(row.get("Sole supervisor", 0) or 0),
                    "co_supervisor": int(row.get("Co-supervisor", 0) or 0),
                    "tap_member": int(row.get("TAP member", 0) or 0),
                    "combined": int(row.get("Total as supervisor (sole or co-supervisor) AND TAP member", 0) or 0),
                }
            except (ValueError, KeyError):
                pass
    return data


def _load_fte_data(filepath: str = "% FTE for CS.csv") -> Dict[str, list]:
    """Load research grant/FTE data. Returns {person: [projects]}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    data = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lead = row.get("Project Lead", "").strip()
            if not lead or lead == "Project Lead":
                continue
            project = {
                "project_id": row.get("Project ID", "").strip(),
                "finance_code": row.get("Finance Project Code", "").strip(),
                "project_type": row.get("Project Type", "").strip(),
                "title": row.get("Project Title", "").strip(),
                "fte": row.get("% FTE", "0%").strip(),
                "role": row.get("PI or Co-I", "").strip(),
                "start_date": row.get("Project Dates Start", "").strip(),
                "end_date": row.get("Project Dates End", "").strip(),
            }
            data.setdefault(lead, []).append(project)
    return data


def _load_waw_roles(filepath: str = "WAW.csv") -> Dict[str, list]:
    """Load departmental roles from WAW.csv. Returns {role_name: [(staff_name, percentage)]}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    # Parse the WAW CSV which has a specific structure
    roles = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            role = row[0].strip()
            # WAW structure: col0=role, col1=on-campus staff, col2=empty, col3=online staff
            staff_on_campus = row[1].strip() if len(row) > 1 else ""
            staff_online = row[3].strip() if len(row) > 3 else ""
            # Skip header and non-role rows
            if not role or role.startswith("Departmental") or role.startswith("Green"):
                continue
            if role.startswith("Red indicates"):
                continue
            # Only include on-campus staff (skip online team)
            if staff_on_campus:
                roles.setdefault(role, []).append(staff_on_campus)
    return roles


def _load_part_time(filepath: str = "Part time.csv") -> Dict[str, dict]:
    """Load part-time data. Returns {person_name: {fte, ...}}."""
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    data = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            surname = row.get("Surname", "").strip()
            if not surname or surname == "Total":
                continue
            try:
                data[surname] = {
                    "staff_category": row.get("Staff Category", "").strip(),
                    "fte": float(row.get("FTE", 0) or 0),
                    "total_hours": float(row.get("Total available hours (all sections)", 0) or 0),
                    "teaching_admin_hours": float(row.get("Total available teaching and admin hours", 0) or 0),
                    "teaching_score": float(row.get("Teaching total score", 0) or 0),
                    "admin_score": float(row.get("Admin total score", 0) or 0),
                    "research_hours": float(row.get("Total Research/Scholarship available hours", 0) or 0),
                    "research": row.get("Research", "").strip(),
                    "notes": row.get("Notes for 25-26", "").strip(),
                }
            except (ValueError, KeyError):
                pass
    return data


def load_wtw_files(base_dir: str = None) -> Tuple[List[ModuleData], str]:
    """
    Load the current year's WTW file. Returns (modules, year_label).
    Auto-detects the latest WTW file.

    Args:
        base_dir: Directory containing WTW files. Defaults to data folder.
    """
    if base_dir is None:
        base_dir = DATA_DIR

    wtw_files = sorted(glob.glob(os.path.join(base_dir, "WTW *.csv")))
    if not wtw_files:
        raise FileNotFoundError("No WTW CSV files found in the data directory.")

    # Use the latest file (highest year number)
    latest = wtw_files[-1]
    year = _detect_year_from_filename(latest)
    modules = _parse_wtw_csv(latest)
    return modules, year


def load_previous_wtw(base_dir: str = None) -> Optional[List[ModuleData]]:
    """Load the previous year's WTW file for new lecturer detection.

    Args:
        base_dir: Directory containing WTW files. Defaults to data folder.
    """
    if base_dir is None:
        base_dir = DATA_DIR

    wtw_files = sorted(glob.glob(os.path.join(base_dir, "WTW *.csv")))
    if len(wtw_files) < 2:
        return None
    # Second-to-last file
    prev = wtw_files[-2]
    return _parse_wtw_csv(prev)


# WAW role names → YAML role names mapping
_WAW_ROLE_MAPPING = {
    "Director for Students": "Director of Students",
    "Chair of Equality, Diversity and Inclusion Committee ": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of Equality, Diversity and Inclusion Committee": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Deputy Head of Department (On-campus teaching)": "Deputy Head of Department (On-campus teaching)",
    "Deputy Head of Department (Online teaching)": "Deputy Head of Department (Online teaching)",
    "Deputy Head (Research) and Chair DRC": "Deputy Head (Research)",
    "Chair of the Board of Examiners": "Chair of the Board of Examiners",
    "Deputy CBoE (paper checking for on-campus)": "Deputy CBoEs",
    "Deputy CBoE (marking for on-campus) and student prizes": "Deputy CBoEs",
    "Deputy CBoE (academic misconduct for on-campus)": "Deputy CBoEs",
    "EC Officer (on-campus)": "EC Officer (on-campus)",
    "Chair ECA committee (online)": "Chair ECA committee (online)",
    "Undergraduate Programme Leader": "UG PL",
    "Undergraduate Programme Leader: CS/Maths": "Other PLs",
    "Postgraduate Team Leader (Online): Cyber": "Other PLs",
    "Postgraduate Programme Leader (Online): CS": "Other PLs",
    "Postgraduate Programme Leader: SCSE": "Other PLs",
    "Postgraduate Programme Leader: HCIT": "Other PLs",
    "Postgraduate Programme Leader: ACS": "Other PLs",
    "Postgraduate Programme Leader: Data Science": "Other PLs",
    "Postgraduate Programme Leader: AI": "Other PLs",
    "Postgraduate Programme Leader: Cyber": "Other PLs",
    "Project Team Leader (Online)": "Other PLs",
    "Software Team Leader (Online)": "Other PLs",
    "Data and AI Team Leader (Online)": "Other PLs",
    "Infrastructure Team Leader (Online)": "Other PLs",
    "Programme Leader for CPD": "Other PLs",
    "Taught Project Coordinator": "Taught Project Coordinator",
    "GTA Coordinator": "GTA Coordinator",
    "Internationalisation and Visitors Coordinator": "Internationalisation and Visitors Coordinator",
    "CSCSE SQA Partnership Leader": "CSCSE HAP Partnership Leader",
    "Outreach and Recruitment Coordinator": "Outreach and Extra-Curricular Activities",
    "Academic Ambassador for UG Student Recruitment and Outreach": "Academic Admissions Team",
    "Director of Admissions & Outreach": "Director of Admissions",
    "Undergraduate Admissions Tutor": "Deputy Director of Admissions (UG Admissions)",
    "Deputy Graduate Chair": "Deputy Graduate Chair",
    "Graduate School Board (PGR Supervisor Representative)": "Graduate School Board (Ordinary member)",
    "Chair of the Research Progression Panel": "Progression Panel Chair",
    "Research Progression Panel member": "Progression Panel",
    "PhD Training Officer": "PhD Training Officer",
    "Internally Distributed Funding panel reviewer": "Internally Distributed Funding panel reviewer",
    "REF lead": "REF Lead",
    "Research Impact (including REF impact submission)": "Impact",
    "Group Leads": None,  # Not a specific role
    "Real-Time and Distributed Systems": None,
    "Human-Centered Interactive Technologies": None,
    "Software Engineering for Robotics": None,
    "Automated Software Engineering": None,
    "Cyber Security and Privacy": None,
    "High Integrity Systems": None,
    "Artificial Intelligence": None,
    "Quantum Information": None,
    "Vision, Graphics and Learning": None,
    "Chair of the Department Education Committee": "Chair of the Department Education Committee",
    "Deputy Director of Admissions (POVD etc)": "Deputy Director of Admissions (POVD etc)",
    "Deputy Director of Admissions (UG Admissions)": "Deputy Director of Admissions (UG Admissions)",
    "Chair of Equality, Diversity and Inclusion Committee": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of Equality, Diversity and Inclusion Committee ": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of the Board of Examiners": "Chair of the Board of Examiners",
    "Chair of the ECA committee": "Chair ECA committee (online)",
    "Chair of the Department Education Committee": "Chair of the Department Education Committee",
    "Chair of the Research Progression Panel": "Progression Panel Chair",
    "Chair of Equality, Diversity and Inclusion (EDI) Committee": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of Equality, Diversity and Inclusion Committee": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of Equality, Diversity and Inclusion Committee ": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of the Board of Examiners": "Chair of the Board of Examiners",
    "Chair of the Department Education Committee": "Chair of the Department Education Committee",
    "Chair of the Research Progression Panel": "Progression Panel Chair",
    "Chair of the ECA committee": "Chair ECA committee (online)",
    "Chair of the Ethics Committee": "Ethics",
    "Chair of the Ethics Committee ": "Ethics",
    "Chair of the Research Progression Panel": "Progression Panel Chair",
    "Chair of the Department Education Committee": "Chair of the Department Education Committee",
    "Chair of the Board of Examiners": "Chair of the Board of Examiners",
    "Chair of Equality, Diversity and Inclusion (EDI) Committee": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of Equality, Diversity and Inclusion Committee": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of Equality, Diversity and Inclusion Committee ": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of the Board of Examiners": "Chair of the Board of Examiners",
    "Chair of the Department Education Committee": "Chair of the Department Education Committee",
    "Chair of the Research Progression Panel": "Progression Panel Chair",
    "Chair of the ECA committee": "Chair ECA committee (online)",
    "Chair of the Ethics Committee": "Ethics",
    "Chair of the Ethics Committee ": "Ethics",
    "Chair of the Research Progression Panel": "Progression Panel Chair",
}


_UNSET = object()

def load_all_data(data_dir: str = None,
                  unknown_callback=_UNSET) -> YearData:
    """
    Load all data sources and merge into a YearData object.
    This is the main entry point for data loading.

    Args:
        data_dir: Directory containing data files. Defaults to 'data' folder.
        unknown_callback: Callback for unknown names, or _UNSET for auto-detect.
                          Pass None for non-interactive mode (keep names as-is).
                          Pass _UNSET or omit to auto-detect (use interactive prompt).
    """
    if data_dir is None:
        data_dir = DATA_DIR

    if unknown_callback is _UNSET:
        unknown_callback = _prompt_name_match

    # Load name lookup and build reverse lookup (DATA_DIR is used internally)
    mappings = _load_name_lookup()
    reverse_lookup = _build_reverse_lookup(mappings)

    # Load current year WTW (data_dir is passed to load_wtw_files)
    modules, year_label = load_wtw_files(data_dir)

    # Load previous year WTW for known lecturers (data_dir is passed to load_previous_wtw)
    prev_modules = load_previous_wtw(data_dir)
    known_lecturers = set()
    if prev_modules:
        for m in prev_modules:
            for t in m.teachers:
                name = normalize_name(t, reverse_lookup, unknown_callback)
                if name:
                    known_lecturers.add(name)

    # Load student counts, assessment counts, and practical data (DATA_DIR is used internally)
    student_counts = _load_student_counts()
    assessment_counts = _load_assessment_counts()
    practical_data = _load_practical_data()

    # Merge student counts for H/M variants (combine numbers for same module)
    # e.g., COM00056H (NETS-H) + COM00188M (NETS-M) should be combined
    merged_student_counts = {}
    for code, count in student_counts.items():
        # Check if this code is part of an H/M pair
        base_code = code
        if code.endswith("H") and code[:-1] + "M" in student_counts:
            # This is the H variant; combine with M
            m_code = code[:-1] + "M"
            merged_student_counts[code] = count + student_counts[m_code]
            merged_student_counts[m_code] = count + student_counts[m_code]
        elif code.endswith("M") and code[:-1] + "H" in student_counts:
            # This is the M variant; already handled above
            pass
        else:
            merged_student_counts[code] = count

    # Apply student counts to modules
    for module in modules:
        total_students = 0
        for code in module.codes:
            if code in merged_student_counts:
                total_students += merged_student_counts[code]
        if total_students > 0:
            module.student_count = total_students

        # Apply assessment counts
        for code in module.codes:
            if code in assessment_counts:
                module.assessment_count = assessment_counts[code]
                break
        # If no code match, try by acronym
        if module.assessment_count == 1 and module.name in assessment_counts:
            module.assessment_count = assessment_counts[module.name]

        # Apply practical data (real contact hours per session)
        for code in module.codes:
            if code in practical_data:
                pdata = practical_data[code]
                module.practicals = pdata["practicals"]
                module.practical_contact_hours = pdata["practical_contact_hours"]
                break
        # If no code match, try by acronym
        if module.practical_contact_hours == 0.0 and module.name in practical_data:
            pdata = practical_data[module.name]
            module.practicals = pdata["practicals"]
            module.practical_contact_hours = pdata["practical_contact_hours"]

    # Load supplementary data (DATA_DIR is used internally for all file loading)
    project_load_data = _load_project_load()
    phd_data = _load_phd_supervision()
    fte_data = _load_fte_data()
    waw_roles = _load_waw_roles()
    part_time_data = _load_part_time()

    # Build staff roster from all data sources
    staff = {}

    # Collect all names from all sources
    all_names = set()
    for m in modules:
        all_names.add(m.lead_name)
        for t in m.teachers:
            all_names.add(t)
        if m.expert_checker:
            all_names.add(m.expert_checker)
        if m.general_checker:
            all_names.add(m.general_checker)
    for name in project_load_data:
        all_names.add(name)
    for name in phd_data:
        all_names.add(name)
    for name in fte_data:
        all_names.add(name)
    for name in part_time_data:
        all_names.add(name)

    # Process each name
    saint_module_map = {
        "Richard W": ["Artificial Intelligence (AI)"],
        "Frank": ["Artificial Intelligence (AI)"],
        "Phillip Morgan": ["Law, Ethics and Society (LES)"],
        "Jennifer Chubb": ["Law, Ethics and Society (LES)"],
        "Tom Stoneham": ["Law, Ethics and Society (LES)"],
        "Ibrahim": ["Foundations of Safe AI (Safe AI 1)"],
        "Yan": ["Foundations of Safe AI (Safe AI 1)", "Designing Safe AI (Safe AI 2)"],
        "Colin": ["Designing Safe AI (Safe AI 2)"],
    }

    for raw_name in all_names:
        canonical = normalize_name(raw_name, reverse_lookup, unknown_callback)
        if not canonical:
            continue

        # Find matching data from all sources
        proj_data = None
        for key, val in project_load_data.items():
            if key.upper() == raw_name.upper() or key.lower() == raw_name.lower():
                proj_data = val
                break
        if not proj_data:
            # Try canonical name
            for key, val in project_load_data.items():
                norm_key = normalize_name(key, reverse_lookup, unknown_callback)
                if norm_key == canonical:
                    proj_data = val
                    break

        phd_info = None
        for key, val in phd_data.items():
            if key.upper() == raw_name.upper() or key.lower() == raw_name.lower():
                phd_info = val
                break
        if not phd_info:
            for key, val in phd_data.items():
                norm_key = normalize_name(key, reverse_lookup, unknown_callback)
                if norm_key == canonical:
                    phd_info = val
                    break

        fte_info = None
        for key, val in fte_data.items():
            if key.upper() == raw_name.upper() or key.lower() == raw_name.lower():
                fte_info = val
                break
        if not fte_info:
            for key, val in fte_data.items():
                norm_key = normalize_name(key, reverse_lookup, unknown_callback)
                if norm_key == canonical:
                    fte_info = val
                    break

        pt_info = None
        for key, val in part_time_data.items():
            if key.upper() == raw_name.upper() or key.lower() == raw_name.lower():
                pt_info = val
                break

        # Assign roles from WAW (apply name mapping to resolve WAW→YAML differences)
        staff_roles = []
        for role, members in waw_roles.items():
            yaml_role = _WAW_ROLE_MAPPING.get(role, role)
            if yaml_role is None:
                continue  # Skip non-role entries like "Group Leads"
            for member in members:
                norm_member = normalize_name(member, reverse_lookup, unknown_callback)
                if norm_member == canonical:
                    staff_roles.append(yaml_role)

        # Check for SAINTS modules
        saint_modules = []
        for saint_name, modules_list in saint_module_map.items():
            if raw_name.upper() == saint_name.upper() or \
               canonical in saint_name or \
               saint_name.lower() in raw_name.lower():
                saint_modules.extend(modules_list)

        if canonical not in staff:
            staff[canonical] = StaffData(
                canonical_name=canonical,
                aliases=mappings.get(canonical, [canonical]),
                fte=pt_info["fte"] if pt_info else 1.0,
                employment_start=proj_data["employment_start"] if proj_data else 0,
                active=proj_data["active"] if proj_data else True,
                category=pt_info["staff_category"] if pt_info else "",
                project_load=proj_data["project_load"] if proj_data else 0,
                pastoral_load=proj_data["pastoral_load"] if proj_data else 0,
                adjusted_project_load=proj_data["adjusted_project_load"] if proj_data else 0,
                adjusted_pastoral_load=proj_data["adjusted_pastoral_load"] if proj_data else 0,
                ecr_year=proj_data["ecr_year"] if proj_data else "N/A",
                ecr_value=proj_data["ecr_value"] if proj_data else 0,
                citizenship_level=proj_data["citizenship_level"] if proj_data else 0,
                research_grant_income=proj_data["research_grant_income"] if proj_data else "N/A",
                research_grant_income_value=proj_data["research_grant_income_value"] if proj_data else 0,
                citizenship_value=proj_data["citizenship_value"] if proj_data else 0,
                initial_fractional_project_load=proj_data["initial_fractional_project_load"] if proj_data else 0,
                initial_fractional_pastoral_load=proj_data["initial_fractional_pastoral_load"] if proj_data else 0,
                notes=proj_data["notes"] if proj_data else "",
                roles=staff_roles,
                phd_supervisions=phd_info["sole_supervisor"] if phd_info else 0,
                phd_co_supervisions=phd_info["co_supervisor"] if phd_info else 0,
                phd_assessor_count=phd_info["tap_member"] if phd_info else 0,
                research_projects=fte_info if fte_info else [],
                saint_modules=list(set(saint_modules)),
            )

    # Deduplicate staff roster
    staff = _deduplicate_staff(staff, mappings)

    # Filter: only include staff who appear in WTW modules (teachers, module leader, or checker)
    wtw_staff = set()
    for m in modules:
        wtw_staff.add(m.lead_name)
        for t in m.teachers:
            wtw_staff.add(t)
        if m.expert_checker:
            wtw_staff.add(m.expert_checker)
        if m.general_checker:
            wtw_staff.add(m.general_checker)

    filtered_staff = {}
    for name, data in staff.items():
        # Check if this staff member appears in WTW (by name or alias)
        in_wtw = False
        for wtw_name in wtw_staff:
            norm = normalize_name(wtw_name, reverse_lookup, unknown_callback=None)
            if norm == name:
                in_wtw = True
                break
        if in_wtw:
            filtered_staff[name] = data

    staff = filtered_staff

    # Include HoD even if not in WTW (for completeness)
    if "Iain Bate" not in staff:
        # Look up Iain's PhD info specifically
        iain_phd_info = None
        for key, val in phd_data.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
            if norm_key == "Iain Bate":
                iain_phd_info = val
                break

        staff["Iain Bate"] = StaffData(
            canonical_name="Iain Bate",
            aliases=mappings.get("Iain Bate", ["Iain B", "Iain Bate"]),
            fte=1.0,
            employment_start=0,
            active=True,
            category="ART",
            project_load=0,
            pastoral_load=0,
            adjusted_project_load=0,
            adjusted_pastoral_load=0,
            ecr_year="N/A",
            ecr_value=0,
            citizenship_level=0,
            research_grant_income="N/A",
            research_grant_income_value=0,
            citizenship_value=0,
            initial_fractional_project_load=0,
            initial_fractional_pastoral_load=0,
            notes="HoD - added for completeness, not in WTW",
            roles=["Head of Department"],
            phd_supervisions=iain_phd_info["sole_supervisor"] if iain_phd_info else 0,
            phd_co_supervisions=iain_phd_info["co_supervisor"] if iain_phd_info else 0,
            phd_assessor_count=iain_phd_info["tap_member"] if iain_phd_info else 0,
            research_projects=[{"project_id": "SCHEME", "title": "SCHEME", "fte": "20%"}],
            saint_modules=[],
        )

    return YearData(
        year_label=year_label,
        modules=modules,
        student_counts=merged_student_counts,
        assessment_counts=assessment_counts,
        staff=staff,
        known_lecturers=known_lecturers,
        name_lookup=reverse_lookup,
        canonical_lookup=mappings,
    )


def _deduplicate_staff(staff: Dict[str, StaffData], mappings: Dict[str, List[str]]) -> Dict[str, StaffData]:
    """
    Second-pass deduplication: merge staff entries that share the same lookup mapping.
    E.g., 'Chris Crispin-Bailey' and 'Christopher Crispin-Bailey' should be merged.
    """
    # Build reverse: alias -> canonical
    alias_to_canonical = {}
    for canonical, aliases in mappings.items():
        for alias in aliases:
            alias_to_canonical[alias.strip().lower()] = canonical

    # Group staff by their resolved canonical name
    groups = {}
    for name, data in staff.items():
        # Find which canonical name this maps to
        resolved = alias_to_canonical.get(name.lower(), name)
        groups.setdefault(resolved, []).append((name, data))

    # Merge each group
    merged = {}
    for canonical, entries in groups.items():
        if len(entries) == 1:
            merged[canonical] = entries[0][1]
        else:
            # Merge: prefer non-zero/non-empty values
            merged_data = entries[0][1]
            for _, data in entries[1:]:
                if data.fte and data.fte > 0:
                    merged_data.fte = data.fte
                if data.category:
                    merged_data.category = data.category
                if data.notes:
                    merged_data.notes = merged_data.notes + "; " + data.notes if merged_data.notes else data.notes
                if data.roles:
                    merged_data.roles = list(set(merged_data.roles + data.roles))
                if data.research_projects:
                    merged_data.research_projects = list(set(
                        str(p) for p in merged_data.research_projects + data.research_projects
                    ))
                # Merge PhD supervision counts (take max for each type)
                merged_data.phd_supervisions = max(merged_data.phd_supervisions, data.phd_supervisions)
                merged_data.phd_co_supervisions = max(merged_data.phd_co_supervisions, data.phd_co_supervisions)
                merged_data.phd_assessor_count = max(merged_data.phd_assessor_count, data.phd_assessor_count)
                if data.saint_modules:
                    merged_data.saint_modules = list(set(merged_data.saint_modules + data.saint_modules))
            merged[canonical] = merged_data

    return merged
