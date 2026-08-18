"""
Data loading and processing for the workload calculator.
Handles CSV ingestion, staff name normalization, module mapping, and data merging.
"""

import csv
import functools
import json
import math
import glob
import os
import re
from dataclasses import dataclass, field, replace
from typing import List, Dict, Optional, Set, Tuple, Any
from pathlib import Path

# Get project root directory (parent of scripts folder)
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent

import config


# Custom exceptions for standardized error handling
class WorkloadModelError(Exception):
    """Base exception for workload model errors."""
    pass


class DataLoadError(WorkloadModelError):
    """Raised when data loading fails."""
    pass


class ValidationError(WorkloadModelError):
    """Raised when data validation fails."""
    pass


@dataclass(frozen=True)
class SupervisionAllocation:
    """Immutable record of supervision hours allocated to each staff member.

    This is a pure data container - no side effects or calculations.
    Each teacher receives their supervision allocation exactly once per calculation run.

    Note: While frozen=True prevents reassignment, the Dict values are still mutable
    references. Callers should treat these as read-only.
    """
    pastoral_students: Dict[str, int] = field(default_factory=dict)
    project_loads: Dict[str, float] = field(default_factory=dict)
    phd_supervisions: Dict[str, int] = field(default_factory=dict)


@dataclass
class ModuleData:
    """Structured representation of a module from WTW CSV.

    Fields are mutable to allow enrichment during loading (student counts, assessment counts).
    After load_all_data() completes, the data should be treated as immutable.
    """
    name: str = ""
    codes: Tuple[str, ...] = field(default_factory=tuple)
    stage: int = 0
    semester: int = 1
    credits: int = 20
    cohort: str = "standard"
    lead_name: str = ""
    teachers: Tuple[str, ...] = field(default_factory=tuple)
    extra_markers: Tuple[str, ...] = field(default_factory=tuple)
    expert_checker: str = ""
    general_checker_required: bool = False
    general_checker: str = ""
    practicals: int = 0
    has_h_m_variants: bool = False
    practical_contact_hours: float = 0.0  # Actual contact hours per practical session (from CSV)
    # Total lecture contact hours for the module, when it is not the flat weekly
    # default. Semesterised modules leave this at 0.0 and get
    # DEFAULT_LECURE_HOURS_PER_WEEK x TEACHING_WEEKS_PER_SEMESTER regardless of
    # credits; block-taught SCSE modules set it from their credit weighting.
    lecture_contact_hours: float = 0.0
    practical_groups: int = 0  # Number of parallel groups for practicals
    practical_weeks: Tuple[int, ...] = field(default_factory=tuple)  # Weeks when practicals occur (immutable)
    student_count: int = 0  # From CS Module Numbers.csv - set during loading
    student_count_by_code: Dict[str, int] = field(default_factory=dict)  # Per-code counts (e.g. H vs M variant), from CS Module Numbers.csv
    assessment_count: int = 1  # From CS Module Assessment Numbers.csv - set during loading
    source_year: str = ""  # e.g., "2026-7"
    marking_type: str = "manual"  # "automated" or "manual"
    new_content: bool = False  # True if this is new content for the teacher
    new_assessment: bool = False  # True if this is a wholly new assessment/format
    checking_only: bool = False  # True if this teacher only checks papers (doesn't set them)

    # Additional teaching format hours (in addition to contact hours)
    hw_lab_hours: float = 0.0  # Homework/lab work hours
    drop_in_sessions: int = 0  # Number of drop-in sessions
    teaching_format: str = "standard"  # "standard", "video", or other format indicators



@dataclass(frozen=True)
class StaffData:
    """Complete data for a single staff member."""
    canonical_name: str = ""
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    fte: float = 1.0
    employment_start: int = 2020
    active: bool = True
    category: str = "T and S"
    project_load: float = 0.0
    pastoral_load: float = 0.0
    adjusted_project_load: float = 0.0
    adjusted_pastoral_load: float = 0.0
    ecr_year: str = ""
    ecr_value: float = 0.0
    citizenship_level: int = 1
    research_grant_income: str = "None"
    research_grant_income_value: float = 0.0
    citizenship_value: float = 0.0
    initial_fractional_project_load: float = 0.0
    initial_fractional_pastoral_load: float = 0.0
    notes: str = ""
    roles: Tuple[str, ...] = field(default_factory=tuple)
    phd_supervisions: int = 0
    phd_co_supervisions: int = 0
    phd_assessor_count: int = 0
    research_projects: Tuple[dict, ...] = field(default_factory=tuple)
    saint_modules: Tuple[str, ...] = field(default_factory=tuple)
    unallocated_students: int = 0  # Remaining students after allocation
    pastoral_students: int = 0  # Number of pastoral students assigned
    adjustments: Tuple["AdjustmentRecord", ...] = field(default_factory=tuple)  # Parsed workload_adjustments.csv rows for this person
    adjustment_warnings: Tuple[str, ...] = field(default_factory=tuple)  # Malformed/incomplete adjustment rows for this person (not applied)


@dataclass(frozen=True)
class AdjustmentRecord:
    """One parsed, validated adjustment cell from workload_adjustments.csv."""
    category: str        # "teaching" | "research" | "admin"
    mode: str             # "delta" | "absolute"
    value: float           # signed delta amount, or absolute override target hours
    rationale: str
    source_row: int        # 1-based row as it appears in a spreadsheet (header = row 1)
    raw_person: str        # Person cell text as written, for diagnostics
    module: str = ""        # Teaching Module cell text, as written; only ever set for category == "teaching"


@dataclass(frozen=True)
class WorkloadResult:
    """Complete workload calculation for a single staff member.

    The breakdown dicts support hierarchical display with nested structures:
    - teaching_breakdown: Aggregated teaching components, with per-module details in teaching_module_breakdowns
    - research_breakdown: Research components including protected baseline, grants, and PhD supervision (nested)
    - admin_breakdown: Admin components including departmental roles, engagement, and personal development
    """
    name: str
    fte: float
    total_hours: float
    teaching_hours: float
    research_hours: float
    admin_hours: float
    category: str  # Contract type category (from StaffData)
    assumptions: Tuple[str, ...]  # Immutable tuple for assumptions
    missing_data: Tuple[str, ...]  # Immutable tuple for missing data

    teaching_detail: str = ""
    research_detail: str = ""
    admin_detail: str = ""
    nominal_hours: float = 0.0  # FTE-adjusted nominal hours for reference

    # Teaching breakdown: aggregated top-level components
    # Per-module details stored in teaching_module_breakdowns with full hierarchy
    teaching_breakdown: Dict[str, Any] = field(default_factory=dict)  # Aggregated teaching components (delivery, practicals, assessment_setting, marking, pastoral_supervision, project_supervision, project_setting)

    # Per-module teaching breakdowns - each module contains:
    # { 'delivery': X, 'practicals': Y, 'assessment_setting': Z, 'marking': W,
    #   'practicals_breakdown': {'first_time': A, 'repeated': B}, ... }
    teaching_module_breakdowns: Dict[str, Any] = field(default_factory=dict)  # Per-module teaching breakdowns with full hierarchy

    # Research breakdown: contains protected_research_baseline as top-level,
    # then grant_X entries, and phd_students nested dict
    research_breakdown: Dict[str, Any] = field(default_factory=dict)  # Research components (protected baseline, grants, PhD supervision)

    # Admin breakdown: departmental roles, engagement, personal development at same level
    admin_breakdown: Dict[str, float] = field(default_factory=dict)  # Admin components

    grant_titles: Dict[str, str] = field(default_factory=dict)  # Mapping of project IDs to display titles
    module_details: Tuple[str, ...] = ()  # Details of modules taught (immutable tuple)
    supervision_details: Tuple[str, ...] = ()  # Supervision details (to be shown separately)
    pastoral_breakdown: Dict[str, float] = field(default_factory=dict)  # Structured pastoral supervision breakdown
    project_breakdown: Dict[str, float] = field(default_factory=dict)  # Structured project supervision breakdown
    adjustments_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # Manual workload_adjustments.csv overrides applied, keyed by 'teaching'/'research'/'admin'



@dataclass(frozen=True)
class YearData:
    """All data for a single academic year.

    This is the root immutable container for all loaded data. Once created,
    no fields should be modified - any "updates" require creating a new instance.
    """
    year_label: str  # e.g., "2026-7"
    modules: Tuple[ModuleData, ...]  # Immutable tuple of modules
    student_counts: Dict[str, int]  # module_code -> count (value is immutable int)
    assessment_counts: Dict[str, int]  # module_code -> count (value is immutable int)
    staff: Tuple[StaffData, ...]  # Immutable tuple of staff data
    known_lecturers: frozenset  # From previous year's WTW - global set (immutable set)
    known_lecturers_per_module: Dict[str, frozenset]  # module_code -> frozenset of teachers from prev year
    reverse_lookup: Dict[str, str] = field(default_factory=dict)  # alias -> canonical (reverse lookup)
    canonical_lookup: Dict[str, List[str]] = field(default_factory=dict)  # canonical -> aliases (for reference)

    @classmethod
    def create(cls, year_label: str, modules: List[ModuleData], student_counts: Dict[str, int],
               assessment_counts: Dict[str, int], staff: Dict[str, StaffData],
               known_lecturers: Set[str], known_lecturers_per_module: Dict[str, Set[str]]) -> "YearData":
        """Factory method to create a YearData instance with proper immutability."""
        # Convert all module teacher sets to frozensets
        frozen_per_module = {code: frozenset(teachers) for code, teachers in known_lecturers_per_module.items()}
        return cls(
            year_label=year_label,
            modules=tuple(modules),
            student_counts=dict(student_counts),
            assessment_counts=dict(assessment_counts),
            staff=tuple(staff.values()),
            known_lecturers=frozenset(known_lecturers),
            known_lecturers_per_module=frozen_per_module,
            reverse_lookup={},
            canonical_lookup={}
        )


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


def _build_reverse_lookup(mappings: Dict[str, List[str]]) -> Tuple[Dict[str, str], List[str]]:
    """Build a reverse lookup: alias -> canonical_name.

    Returns:
        Tuple of (reverse_lookup, warnings) where warnings are about duplicate aliases.
    """
    reverse = {}
    warnings = []
    for canonical, aliases in mappings.items():
        for alias in aliases:
            key = alias.strip().lower()
            if key in reverse and reverse[key] != canonical:
                warnings.append(
                    f"Duplicate alias '{alias}' maps to both '{reverse[key]}' and '{canonical}'. "
                    f"Using '{canonical}'."
                )
            reverse[key] = canonical
    return reverse, warnings


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
                   unknown_callback=None,
                   mappings: Dict[str, List[str]] = None) -> Optional[str]:
    """
    Normalize a staff name to its canonical form.
    If the name is not in the lookup, prompt the user if unknown_callback is provided.

    Args:
        name: The raw name to normalize
        reverse_lookup: Mapping from alias lowercase to canonical name
        unknown_callback: Callback for unknown names (receives name, canonical_hint, mappings)
        mappings: Optional staff name mappings for alias suggestions
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
                if mappings:
                    if unknown_callback(name, canonical, mappings=mappings):
                        return canonical
                else:
                    if unknown_callback(name, canonical):
                        return canonical
                # User said no - don't match this alias, try next one
                continue
            else:
                return canonical

    # If nothing matches, ask the user or return as-is
    if unknown_callback:
        if mappings:
            if unknown_callback(name, None, mappings=mappings):
                return name
        else:
            if unknown_callback(name, None):
                return name
        # User said no - skip this unknown staff member
        return None
    # Non-interactive mode: return the raw name (will be flagged later)
    # Also skip obvious non-person entries
    if name.strip().lower() in _NON_PERSON_ENTRIES:
        return None
    return name.strip() if name.strip() else None


def _find_alias_candidates(user_name: str, mappings: Dict[str, List[str]]) -> List[str]:
    """
    Find potential canonical names that a user's name might match.

    Args:
        user_name: The raw name entered by user
        mappings: The staff name lookup mappings (canonical -> aliases)

    Returns:
        List of potential matching canonical names, sorted by relevance
    """
    if not user_name:
        return []

    user_key = user_name.lower().strip()
    candidates = []

    for canonical, aliases in mappings.items():
        canon_key = canonical.lower()
        alias_keys = [a.lower() for a in aliases]

        # Exact match (shouldn't happen here but check anyway)
        if user_key == canon_key or user_key in alias_keys:
            return [canonical]

        # Check if user_name is a partial match to the canonical name
        # e.g., "Chris" matches "Christopher Crispin-Bailey"
        if len(user_name) >= 2:
            # Starts with same first letter and shares significant prefix
            if canon_key.startswith(user_key):
                candidates.append((canonical, 'prefix', len(user_key)))

            # Contains user_name as a component (e.g., "Smith" in "William Smith")
            elif ' ' in canon_key and user_key in canon_key:
                candidates.append((canonical, 'substring', len(user_key)))

        # Check if user_name's first letter matches the canonical's first letter
        # and the remaining length is similar (handles abbreviations like "Chris CB")
        if len(user_name) <= 3:
            if canon_key.startswith(user_key):
                candidates.append((canonical, 'initial', len(user_key)))

        # Check for common patterns:姓 + first name initial
        # e.g., "W Smith" might match "William Smith"
        user_parts = user_key.split()
        canon_parts = canon_key.split()
        if len(user_parts) >= 1 and len(canon_parts) >= 1:
            if user_parts[0] == canon_parts[0][:len(user_parts[0])]:
                # First name partial match
                candidates.append((canonical, 'first_name_partial', len(user_parts[0])))

    # Sort by relevance: exact matches first, then longer prefix matches
    def sort_key(item):
        canonical, match_type, match_len = item
        # Higher score for longer matches and exact/prefix matches
        type_score = {'prefix': 3, 'first_name_partial': 2, 'substring': 1, 'initial': 0}.get(match_type, 0)
        return (-type_score, -match_len, canonical)

    candidates.sort(key=sort_key)
    return [c[0] for c in candidates]


def _prompt_name_match(user_name: str, canonical_name: Optional[str],
                       mappings: Dict[str, List[str]] = None) -> bool:
    """
    Callback for unknown names. Returns True if the user confirms a match.

    Args:
        user_name: The raw name from the data
        canonical_name: If provided, ask if user_name refers to this name
        mappings: Optional mappings dict to suggest candidates

    Returns:
        True if user confirms match or wants to keep as-is, False to skip
    """
    if canonical_name:
        response = input(f"Does '{user_name}' refer to '{canonical_name}'? (y/n): ").strip().lower()
        return response == "y"

    # No suggested canonical name - show candidates and ask user
    print(f"\nUnknown name: '{user_name}'")

    if mappings:
        candidates = _find_alias_candidates(user_name, mappings)
        if candidates:
            print("Possible matches:")
            for i, candidate in enumerate(candidates[:5], 1):  # Show top 5
                print(f"  {i}. {candidate}")
            response = input("Select number to use this match, or 'n' for new/other: ").strip().lower()
            if response.isdigit() and 1 <= int(response) <= len(candidates):
                return True  # User selected a candidate

    response = input("Use this as-is? (y/n): ").strip().lower()
    return response == "y"


def _resolve_category_from_data(canonical_name: str,
                                art_ts_category: Optional[str],
                                pt_info: Optional[Dict],
                                category_overrides: Dict[str, str]) -> str:
    """Resolve a staff member's contract category from the available data
    sources, in priority order: the ART Performance data capture sheet, then
    Part time.csv's Staff Category column, then a previously-saved answer.
    Returns "" if none of them cover this person (the caller decides whether
    to ask the user).
    """
    if art_ts_category:
        return art_ts_category
    if pt_info and pt_info.get("staff_category"):
        return pt_info["staff_category"]
    return category_overrides.get(canonical_name, "")


def _prompt_category_match(canonical_name: str) -> Optional[str]:
    """
    Callback for staff whose contract category (ART / T and S) can't be
    deduced from the ART Performance sheet, Part time.csv, or a previously
    saved answer. Returns the chosen category, or None to skip (leave
    unresolved for this run - will be asked again next time).
    """
    print(f"\nCannot determine contract category for '{canonical_name}' "
          f"(not found in the ART Performance sheet or Part time.csv).")
    response = input("Category? [1] ART  [2] T and S  [Enter to skip]: ").strip()
    if response == "1":
        return "ART"
    if response == "2":
        return "T and S"
    return None


# --- WTW CSV Loading ---

def _detect_year_from_filename(filename: str) -> str:
    """Extract year label from WTW filename, e.g., 'WTW 2026-7.csv' -> '2026-7'."""
    base = os.path.basename(filename)
    # Look for pattern YYYY-X
    match = re.search(r'(\d{4})-(\d)', base)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return base


def _load_module_mapping() -> Dict[str, Any]:
    """Load module mapping JSON to identify new modules for new_content detection."""
    path = PROJECT_ROOT / "data" / "module_mapping.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# The SCSE masters modules are block-taught rather than semesterised, and WTW
# records their stage as "SC" with "-" for the semester. They are MSc-level (every
# code carries the "M" suffix), so they map onto stage 4 under CLAUDE.md's
# "1-3 UG, 4+ MSc" convention.
SCSE_STAGE_MARKER = "SC"
SCSE_STAGE = 4

# People who appear in WTW but are not workload-modelled - research assistants and
# other non-academic contributors who pick up some teaching. Filtered out at parse
# time so they neither join the staff roster nor take a share of a module: the
# module's hours split between the remaining team instead. Compared case-folded
# against the raw WTW cell.
NON_MODELLED_TEACHERS = {
    "kate p",  # RA doing some teaching on HUFS (confirmed 2026-08-18)
}


def _parse_wtw_csv(filepath: str, known_lecturers: Set[str] = None,
                   new_modules: Set[str] = None) -> List[ModuleData]:
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
            codes = tuple(c.strip() for c in codes_str.split(",") if c.strip())
            if not codes:
                # The previous-year layout has no codes column - column 1 is the
                # semester there, which is blank for block-taught SCSE modules. That
                # file exists only to discover who taught what last year, so a named
                # row is enough; requiring a "code" silently dropped every SCSE
                # module from it and made the whole SCSE team look like new
                # lecturers (5x) on modules they have taught for years.
                if year_label.startswith("2026"):
                    continue
                codes = (name,)

            # Stage. "SC" marks the block-taught SCSE masters modules, whose codes
            # all carry the "M" suffix - record them at MSc level (CLAUDE.md's
            # "1-3 UG, 4+ MSc" convention) so project supervision uses the MSc rate.
            stage = 0
            stage_raw = ""
            if len(row) > 2:
                stage_raw = row[2].strip()
                if stage_raw.isdigit():
                    stage = int(stage_raw)
                elif stage_raw.upper() == SCSE_STAGE_MARKER:
                    stage = SCSE_STAGE

            # Semester. Block-taught modules record "-" rather than a semester
            # number; treat anything non-numeric as "no fixed semester" (0). This
            # must not raise - the caller's except clause discards the whole module.
            semester = 0
            if len(row) > 3:
                s = row[3].strip()
                if s.isdigit():
                    semester = int(s)
                elif "-" in s:
                    head = s.split("-")[0].strip()  # e.g., "1-2" -> 1
                    semester = int(head) if head.isdigit() else 0

            # Credits
            credits = int(row[4]) if len(row) > 4 and row[4].strip().isdigit() else 0

            # Cohort
            cohort = row[5].strip() if len(row) > 5 else ""

            # Lead name
            lead_name = row[6].strip() if len(row) > 6 else ""
            if lead_name.lower() in NON_MODELLED_TEACHERS:
                lead_name = ""

            # Teachers - varies by year format
            teachers_list = []
            if year_label.startswith("2026"):
                # 2026-7 format: columns 7, 8 are teachers
                for idx in [7, 8]:
                    if len(row) > idx and row[idx].strip():
                        teachers_list.append(row[idx].strip())
                # Add lead to teachers list (lead is column 6)
                # This ensures leads who are also teaching get included in workload calculation
                if lead_name and lead_name not in teachers_list:
                    teachers_list.insert(0, lead_name)
            else:
                # 2025-6 format: columns 4, 5, 6 are teachers (different layout)
                for idx in [4, 5, 6]:
                    if len(row) > idx and row[idx].strip():
                        teachers_list.append(row[idx].strip())
            teachers = tuple(teachers_list)

            # Extra markers - convert to tuple
            extra_markers_str = ""
            if len(row) > 9 and row[9].strip():
                extra_markers_str = row[9]
            extra_markers = tuple(m.strip() for m in extra_markers_str.split(",") if m.strip())

            # Expert checker (column 11 in WTW 2026-7 format)
            expert_checker = ""
            if len(row) > 11:
                val = row[11].strip()
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

            # Read practicals count from column 13 (new column)
            practicals = 0
            if len(row) > 13 and row[13].strip():
                try:
                    practicals = int(row[13].strip())
                except ValueError:
                    practicals = 0

            # Block-taught SCSE modules carry contact in proportion to credits
            # (about three days per 10 credits), unlike semesterised modules whose
            # lecture contact is a flat 2h/week regardless of credit weighting.
            lecture_contact_hours = 0.0
            if stage == SCSE_STAGE and stage_raw.upper() == SCSE_STAGE_MARKER and credits > 0:
                lecture_contact_hours = (
                    config.SCSE_LECTURE_HOURS_PER_10_CREDITS * credits / 10.0
                )

            module = ModuleData(
                name=name,
                codes=codes,
                stage=stage,
                semester=semester,
                lecture_contact_hours=lecture_contact_hours,
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
                student_count=config.DEFAULT_STUDENT_COUNT,
                assessment_count=1,
                source_year=year_label,
                marking_type="manual",
                new_content=name in (new_modules or set()),
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


def _load_codes_by_acronym(filepath: str = "CS Module Numbers.csv") -> Dict[str, List[str]]:
    """Map module acronym -> real module code(s) from CS Module Numbers.csv.

    Needed because a WTW row may carry a placeholder code (e.g. FOAM's
    "<new for one year>") which hides the real code - and the code's H/M suffix
    is what decides whether marking uses the UG or MSc rate.
    """
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    by_acronym: Dict[str, List[str]] = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = row.get("Module Code", "").strip()
            acronym = row.get("Acronym", "").strip()
            if code and acronym:
                by_acronym.setdefault(acronym, []).append(code)
    return by_acronym


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
    Returns {module_code: {practicals: int, practical_contact_hours: float,
                           practical_groups: int, practical_weeks: List[int]}}.
    practical_contact_hours = Total Duration per practical session (hours).
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
            groups_str = row.get("Number of Practical Groups", "").strip()
            notes_str = row.get("Notes on practicals", "").strip()

            if not n_str or n_str.upper() == "NA":
                continue
            try:
                n_practicals = int(n_str)
            except ValueError:
                continue

            # Parse groups (Number of Practical Groups column)
            groups = 0
            if groups_str and groups_str.upper() != "N/A" and groups_str.strip():
                try:
                    groups = int(groups_str)
                except ValueError:
                    groups = 0

            # Parse weeks from notes (e.g., "Weeks 1,2,3,4,5")
            weeks: List[int] = []
            if notes_str:
                week_match = re.search(r"Weeks?\s+([,\d\s]+)", notes_str, re.IGNORECASE)
                if week_match:
                    week_str = week_match.group(1)
                    for w in week_str.split(","):
                        try:
                            weeks.append(int(w.strip()))
                        except ValueError:
                            pass

            # Parse duration: "X hours" or "Y hours"
            duration_hours = 0.0
            if duration_str:
                dur_match = re.search(r"([\d.]+)\s*hours?", duration_str)
                if dur_match:
                    duration_hours = float(dur_match.group(1))
            # Contact hours per practical session
            # Note: "Total Duration" in CSV represents the duration of each practical session,
            # not a total across all practicals (so we don't divide by n_practicals)
            contact_per = duration_hours if n_practicals > 0 else 0.0

            data[code] = {
                "practicals": n_practicals,
                "practical_contact_hours": contact_per,
                "practical_groups": groups,
                "practical_weeks": weeks
            }
            data[acronym] = {
                "practicals": n_practicals,
                "practical_contact_hours": contact_per,
                "practical_groups": groups,
                "practical_weeks": weeks
            }
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


def _load_project_load(filepath: str = "Project and Pastoral Group Loads - Loadings.csv") -> Dict[str, dict]:
    """Load project/pastoral load data. Returns {canonical_name: data_dict}.

    Source is 'Project and Pastoral Group Loads - Loadings.csv' - the current
    export. It supersedes the older 'project_load.csv', which had identical
    columns but slightly stale computed load values.
    """
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
                # Parse Employment Start - may be N/A, int, or float
                emp_start_val = row.get("Employment Start", 0) or 0
                if str(emp_start_val).strip() == "N/A" or not emp_start_val:
                    emp_start = 0
                else:
                    try:
                        emp_start = int(float(emp_start_val))
                    except ValueError:
                        emp_start = 0

                active_val = row.get("Active", "TRUE").strip().upper() == "TRUE"
                proj_load = float(row.get("Base project load", 0) or 0)
                pastoral_load = float(row.get("Base pastoral load", 0) or 0)
                ecr_year = row.get("ECR Year", "N/A").strip()

                # Parse ECR Value
                ecr_value_raw = row.get("ECR Value", 0) or 0
                if str(ecr_value_raw).strip() == "N/A":
                    ecr_value = 0.0
                else:
                    ecr_value = float(ecr_value_raw)

                # Parse Citizenship Level - may be N/A, int, or float
                citizenship_level_raw = row.get("Citizenship Level", 0)
                if str(citizenship_level_raw).strip() == "N/A" or not citizenship_level_raw:
                    citizenship_level = 0
                else:
                    try:
                        citizenship_level = int(float(citizenship_level_raw))
                    except ValueError:
                        citizenship_level = 0

                research_grant_income = row.get("Research Grant Income", "N/A").strip()
                research_grant_income_value_raw = row.get("Research Grant Income Value", 0) or 0
                if str(research_grant_income_value_raw).strip() == "N/A":
                    research_grant_income_value = 0.0
                else:
                    research_grant_income_value = float(research_grant_income_value_raw)

                citizenship_value_raw = row.get("Citizen value", 0) or 0
                if str(citizenship_value_raw).strip() == "N/A":
                    citizenship_value = 0.0
                else:
                    citizenship_value = float(citizenship_value_raw)

                initial_fractional_project_load_raw = row.get("Initial Fractional Project Load", 0) or 0
                if str(initial_fractional_project_load_raw).strip() == "N/A":
                    initial_fractional_project_load = 0.0
                else:
                    initial_fractional_project_load = float(initial_fractional_project_load_raw)

                initial_fractional_pastoral_load_raw = row.get("Initial Fractional Pastoral Group Load", 0) or 0
                if str(initial_fractional_pastoral_load_raw).strip() == "N/A":
                    initial_fractional_pastoral_load = 0.0
                else:
                    initial_fractional_pastoral_load = float(initial_fractional_pastoral_load_raw)

                adjusted_project_load_raw = row.get("Adjusted Project Load", 0) or 0
                if str(adjusted_project_load_raw).strip() == "N/A":
                    adjusted_project_load = 0.0
                else:
                    adjusted_project_load = float(adjusted_project_load_raw)

                adjusted_pastoral_load_raw = row.get("Adjusted Pastoral Group Load", 0) or 0
                if str(adjusted_pastoral_load_raw).strip() == "N/A":
                    adjusted_pastoral_load = 0.0
                else:
                    adjusted_pastoral_load = float(adjusted_pastoral_load_raw)

                project_load_raw = float(row.get("Project Load", 0) or 0)
                pastoral_load_raw = float(row.get("Pastoral Load", 0) or 0)
                notes = row.get("Notes", "").strip()

                # Ceiling project load to nearest integer
                project_load_ceil = math.ceil(project_load_raw) if project_load_raw > 0 else 0

                data[person] = {
                    "employment_start": emp_start,
                    "active": active_val,
                    "project_load": project_load_ceil,
                    "pastoral_load": math.ceil(pastoral_load_raw) if pastoral_load_raw > 0 else 0,
                    "ecr_year": ecr_year,
                    "ecr_value": ecr_value,
                    "citizenship_level": citizenship_level,
                    "research_grant_income": research_grant_income,
                    "research_grant_income_value": research_grant_income_value,
                    "citizenship_value": citizenship_value,
                    "initial_fractional_project_load": initial_fractional_project_load,
                    "initial_fractional_pastoral_load": initial_fractional_pastoral_load,
                    "adjusted_project_load": adjusted_project_load,
                    "adjusted_pastoral_load": adjusted_pastoral_load,
                    "project_load_raw": project_load_raw,
                    "pastoral_load_raw": pastoral_load_raw,
                    "notes": notes,
                }
            except (ValueError, KeyError) as e:
                # Skip rows with unparseable data
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
                def parse_int_or_na(val) -> int:
                    """Parse int value that may be N/A, empty, or a number."""
                    if str(val).strip() == "N/A" or not val:
                        return 0
                    try:
                        return int(float(val))
                    except ValueError:
                        return 0

                data[staff] = {
                    "total_as_supervisor": parse_int_or_na(row.get("Total as supervisor", 0)),
                    "sole_supervisor": parse_int_or_na(row.get("Sole supervisor", 0)),
                    "co_supervisor": parse_int_or_na(row.get("Co-supervisor", 0)),
                    "tap_member": parse_int_or_na(row.get("TAP member", 0)),
                    "combined": parse_int_or_na(row.get("Total as supervisor (sole or co-supervisor) AND TAP member", 0)),
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


_ADJUSTMENT_ABSOLUTE_RE = re.compile(r'^SET\s+([+-]?\d+(?:\.\d+)?)$', re.IGNORECASE)
_ADJUSTMENT_DELTA_RE = re.compile(r'^([+-]?\d+(?:\.\d+)?)$')


def _parse_adjustment_cell(text: str) -> Tuple[str, float]:
    """Parse a non-blank adjustment cell. Raises ValueError if malformed.

    Grammar: 'SET N' -> absolute; '+N'/'-N'/bare 'N' -> delta. A leading '='
    is deliberately NOT accepted (Excel/Sheets evaluates '=250' as a formula
    and drops the '=' on CSV re-save, which would make absolute overrides
    indistinguishable from deltas after a spreadsheet round-trip).
    """
    stripped = text.strip()
    m = _ADJUSTMENT_ABSOLUTE_RE.match(stripped)
    if m:
        return ("absolute", float(m.group(1)))
    m = _ADJUSTMENT_DELTA_RE.match(stripped)
    if m:
        return ("delta", float(m.group(1)))
    raise ValueError(f"'{text}' is not a valid adjustment (expected +N, -N, N, or SET N)")


def _load_adjustments(filepath: str = "workload_adjustments.csv"):
    """Load manual workload adjustments.

    Returns (adjustments_by_raw_name, warnings_by_raw_name, unattributed_warnings):
        - adjustments_by_raw_name: Dict[str, List[AdjustmentRecord]]
        - warnings_by_raw_name: Dict[str, List[str]]
        - unattributed_warnings: List[str] (rows with adjustment data but no Person)

    Missing file -> ({}, {}, []) (no-op), matching every other optional CSV loader
    in this file.
    """
    path = DATA_DIR / filepath
    if not path.exists():
        return {}, {}, []

    column_map = {
        "teaching": ("Teaching Adjustment", "Teaching Rationale"),
        "research": ("Research Adjustment", "Research Rationale"),
        "admin": ("Admin Adjustment", "Admin Rationale"),
    }
    adjustments: Dict[str, list] = {}
    warnings_by_name: Dict[str, list] = {}
    unattributed: list = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):  # row 1 = header
            person = (row.get("Person") or "").strip()
            row_module = (row.get("Teaching Module") or "").strip()
            any_cell_filled = any((row.get(c) or "").strip()
                                   for cols in column_map.values() for c in cols)
            if not person:
                if any_cell_filled:
                    unattributed.append(f"row {row_num}: adjustment data present but Person is blank - row skipped.")
                continue

            if row_module and not (row.get("Teaching Adjustment") or "").strip():
                warnings_by_name.setdefault(person, []).append(
                    f"row {row_num}: Teaching Module '{row_module}' specified but Teaching Adjustment is blank - ignored.")

            for category, (adj_col, rat_col) in column_map.items():
                cell = (row.get(adj_col) or "").strip()
                if not cell:
                    continue
                rationale = (row.get(rat_col) or "").strip()
                try:
                    mode, value = _parse_adjustment_cell(cell)
                except ValueError as e:
                    warnings_by_name.setdefault(person, []).append(
                        f"row {row_num}, {adj_col} ('{cell}'): {e} - not applied.")
                    continue
                if not rationale:
                    warnings_by_name.setdefault(person, []).append(
                        f"row {row_num}, {adj_col} ('{cell}'): no rationale in {rat_col} - not applied.")
                    continue
                adjustments.setdefault(person, []).append(AdjustmentRecord(
                    category=category, mode=mode, value=value, rationale=rationale,
                    source_row=row_num, raw_person=person,
                    module=row_module if category == "teaching" else "",
                ))
    return adjustments, warnings_by_name, unattributed


_ADJUSTMENTS_HEADER = ["Person", "Teaching Module", "Teaching Adjustment", "Teaching Rationale",
                       "Research Adjustment", "Research Rationale",
                       "Admin Adjustment", "Admin Rationale"]


def sync_adjustment_names(year_data: "YearData", filepath: str = "workload_adjustments.csv") -> Tuple[str, ...]:
    """Ensure every active staff member in year_data has at least one row in
    workload_adjustments.csv, appending a blank row for anyone missing.
    Never modifies, reorders, or removes an existing row - strictly additive.
    Idempotent: a name already present (under any resolvable alias spelling)
    is never re-added. Returns the canonical names that were newly added
    (empty tuple if the file already covered everyone, e.g. on every run
    after the first)."""
    path = DATA_DIR / filepath
    file_exists = path.exists()

    covered: Set[str] = set()
    if file_exists:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                person = (row.get("Person") or "").strip()
                if not person:
                    continue
                resolved = normalize_name(person, year_data.reverse_lookup, unknown_callback=None)
                if resolved:
                    covered.add(resolved)
                else:
                    # Can't resolve this spelling to a canonical name (e.g. a stale
                    # or unmatched entry). Fall back to the raw text itself so we
                    # don't risk appending a second, canonical-named row for what
                    # might be the very same person - best-effort, not a guarantee.
                    covered.add(person.upper())

    missing = sorted(
        s.canonical_name for s in year_data.staff
        if s.active and s.canonical_name not in covered
    )

    if not missing:
        return ()

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(_ADJUSTMENTS_HEADER)
        for name in missing:
            writer.writerow([name, "", "", "", "", "", "", ""])

    return tuple(missing)


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


# One-off spelling correction for a known typo in the ART Performance data
# capture sheet ("Banerjee, Soumua" - should be "Soumya"), so it resolves to
# the correct canonical name instead of silently failing to match.
_ART_TS_NAME_CORRECTIONS = {
    "Soumua": "Soumya",
}


def _load_art_ts_categories(filepath: str = "CS Data Collection on ART Performance 2026 - MASTER Overall Data Capture.csv") -> Dict[str, str]:
    """Load staff contract category (ART / T and S) from the ART Performance
    data capture sheet. Returns {parsed_name: category}, where parsed_name is
    a best-effort "Firstname Lastname" reconstruction of the sheet's
    "Lastname, Firstname" column, intended to be resolved against the normal
    canonical-name system (aliases/normalize_name) by the caller - this
    function does no name normalization itself.
    """
    path = DATA_DIR / filepath
    if not path.exists():
        return {}

    data = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            raw_name = row[0].strip()
            category = row[1].strip()
            if category == "T&S":
                category = "T and S"
            elif category != "ART":
                continue
            if not raw_name:
                continue

            if "," in raw_name:
                lastname, _, firstname = raw_name.partition(",")
            else:
                # A few rows in the source sheet are missing the comma
                # (e.g. "O'Dea Mike", "Wilson Richard") - the last
                # whitespace-separated token is the first name.
                parts = raw_name.rsplit(" ", 1)
                if len(parts) != 2:
                    continue
                lastname, firstname = parts

            firstname = firstname.strip()
            lastname = lastname.strip()
            firstname = _ART_TS_NAME_CORRECTIONS.get(firstname, firstname)
            if not firstname or not lastname:
                continue

            data[f"{firstname} {lastname}"] = category
    return data


def _load_category_overrides(filepath: str = "staff_category_lookup.json") -> Dict[str, str]:
    """Load previously-resolved staff categories (e.g. answered via an
    interactive prompt for a name not covered by any other source).
    Returns {canonical_name: category}.
    """
    path = DATA_DIR / filepath
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_category_overrides(overrides: Dict[str, str], filepath: str = "staff_category_lookup.json") -> None:
    """Persist resolved staff categories so future runs don't need to re-ask."""
    path = DATA_DIR / filepath
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(overrides.items())), f, indent=2)
        f.write("\n")


def load_wtw_files(base_dir: str = None) -> Tuple[List[ModuleData], str]:
    """Load the current year's WTW file and return modules with year label.

    Auto-detects the latest WTW CSV file from the data directory.

    Args:
        base_dir: Directory containing WTW files. Defaults to data folder.

    Returns:
        Tuple of (list of ModuleData, year_label string)

    Raises:
        DataLoadError: If no WTW CSV files are found in the data directory.
    """
    if base_dir is None:
        base_dir = DATA_DIR

    wtw_files = sorted(glob.glob(os.path.join(base_dir, "WTW *.csv")))
    if not wtw_files:
        raise DataLoadError("No WTW CSV files found in the data directory.")

    # Use the latest file (highest year number)
    latest = wtw_files[-1]
    year = _detect_year_from_filename(latest)
    modules = _parse_wtw_csv(latest)
    return modules, year


def load_previous_wtw(base_dir: str = None) -> Optional[List[ModuleData]]:
    """Load the previous year's WTW file for new lecturer detection.

    Used to identify lecturers who were teaching in the previous academic year,
    which affects their multiplier assignment (new lecturers get higher multipliers).

    Args:
        base_dir: Directory containing WTW files. Defaults to data folder.

    Returns:
        List of ModuleData from the previous year, or None if fewer than 2
        WTW files are available.
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
# Note: Duplicates have been de-duplicated; only one entry per unique role name.
_WAW_ROLE_MAPPING = {
    # Director/Leadership roles
    "Director for Students": "Director of Students",
    "Deputy Head of Department (On-campus teaching)": "Deputy Head of Department (On-campus teaching)",
    "Deputy Head of Department (Online teaching)": "Deputy Head of Department (Online teaching)",
    "Deputy Head (Research) and Chair DRC": "Deputy Head (Research)",
    # Committee chairs
    "Chair of Equality, Diversity and Inclusion Committee": "Chair of Equality, Diversity and Inclusion (EDI) Committee",
    "Chair of the Board of Examiners": "CBoE (on-campus)",
    "Chair ECA committee (online)": "Chair ECA committee (online)",
    "Chair of the Department Education Committee": "DEC Chair",
    "StAMP committee members": "StAMP committee",
    "Chair of the Research Progression Panel": "Progression Panel Chair",
    "Chair of the Ethics Committee": "Ethics",
    "Ethics Committee members": "Ethics Committee Member",
    "ECR rep": "ECR representative",
    "ART staff rep": "ART staff representative",
    # Deputy CBoE roles
    "Deputy CBoE (paper checking for on-campus)": "Deputy CBoEs",
    "Deputy CBoE (marking for on-campus) and student prizes": "Deputy CBoEs",
    "Deputy CBoE (academic misconduct for on-campus)": "Deputy CBoEs",
    # EC Officer
    "EC Officer (on-campus)": "EC Officer (on-campus)",
    # Programme Leaders
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
    # Coordinators
    "Taught Project Coordinator": "Taught Project Coordinator",
    "GTA Coordinator": "GTA Coordinator",
    "Internationalisation and Visitors Coordinator": "Internationalisation and Visitors Coordinator",
    "Outreach and Recruitment Coordinator": "Outreach and Extra-Curricular Activities",
    "Academic Ambassador for UG Student Recruitment and Outreach": "Academic Admissions Team",
    # Admissions roles
    "Director of Admissions & Outreach": "Director of Admissions",
    "Undergraduate Admissions Tutor": "Deputy Director of Admissions (UG Admissions)",
    "Graduate School Board (GSB) Chair": "Graduate Chair",
    "Deputy Graduate Chair": "Deputy Graduate Chair",
    "Graduate School Board (PGR Supervisor Representative)": "Graduate School Board (Ordinary member)",
    # Additional roles from WAW
    "Head of Department": "Head of Department",
    "PGR Training Officer": "PhD Training Officer",  # PGR = Postgraduate Research
    "Research Progression Panel member": "Progression Panel",
    "REF lead": "REF Lead",
    "Internally Distributed Funding panel reviewer": "Internally Distributed Funding panel reviewer",
    "Research Impact (including REF impact submission)": "Impact",
    "Deputy Director of Admissions (POVD etc)": "Deputy Director of Admissions (POVD etc)",
    "Deputy Director of Admissions (UG Admissions)": "Deputy Director of Admissions (UG Admissions)",
}


def allocate_supervision(staff_data: Dict[str, StaffData]) -> SupervisionAllocation:
    """Calculate supervision allocation for all staff members.

    This is a pure function that reads from staff data and returns an immutable
    SupervisionAllocation. It should be called once per calculation run before
    teaching workload calculations.

    Args:
        staff_data: Mapping of canonical_name to StaffData

    Returns:
        Immutable SupervisionAllocation containing pastoral counts, project loads,
        and PhD supervision counts for each staff member.
    """
    pastoral = {}
    projects = {}
    phd = {}

    for name, staff in staff_data.items():
        pastoral[name] = staff.pastoral_students
        projects[name] = staff.project_load  # Already ceiling'd in data_loader.py
        phd[name] = staff.phd_supervisions

    return SupervisionAllocation(pastoral, projects, phd)


_UNSET = object()

def load_all_data(data_dir: str = None,
                  unknown_callback=_UNSET,
                  category_callback=_UNSET) -> YearData:
    """Load all data sources and merge into a YearData object.

    This is the main entry point for data loading. It reads WTW files, student
    counts, assessment counts, staff data, and other supplementary files to build
    a complete dataset for workload calculation.

    Args:
        data_dir: Directory containing data files. Defaults to 'data' folder.
        unknown_callback: Callback for unknown names, or _UNSET for auto-detect.
                          Pass None for non-interactive mode (keep names as-is).
                          Pass _UNSET or omit to auto-detect (use interactive prompt).
        category_callback: Callback(canonical_name) -> Optional[str] for staff
                          whose contract category can't be deduced from the ART
                          Performance sheet, Part time.csv, or a previously saved
                          answer. Pass None for non-interactive mode (leave
                          unresolved). Pass _UNSET or omit to auto-detect (use
                          interactive prompt). Answers are persisted to
                          staff_category_lookup.json so future runs don't re-ask.

    Returns:
        YearData containing all loaded and merged data for the academic year.
    """
    if data_dir is None:
        data_dir = DATA_DIR

    # Load name lookup first (needed for callback creation in non-interactive mode)
    mappings = _load_name_lookup()
    reverse_lookup, name_warnings = _build_reverse_lookup(mappings)

    if unknown_callback is _UNSET:
        # Create callback with mappings for alias suggestions
        unknown_callback = functools.partial(_prompt_name_match, mappings=mappings)

    if category_callback is _UNSET:
        category_callback = _prompt_category_match

    category_overrides = _load_category_overrides()
    category_overrides_dirty = False

    # Print any warnings about duplicate aliases
    for warning in name_warnings:
        print(f"Warning: {warning}")

    # Load module mapping to identify new modules for new_content detection
    module_mapping = _load_module_mapping()

    # Get new_modules set from the mapping
    new_modules: Set[str] = set()
    if "new_modules" in module_mapping:
        new_modules = set(module_mapping["new_modules"].keys())

    # Load current year WTW (data_dir is passed to load_wtw_files)
    modules, year_label = load_wtw_files(data_dir)

    # Drop modules explicitly excluded from teaching workload. These are modules
    # whose work is credited elsewhere (e.g. "Projects" is covered by the Taught
    # Project Coordinator admin role), so counting them here would double-count.
    # Configured in module_mapping.json rather than hardcoded.
    excluded_modules = module_mapping.get("excluded_modules", {}) or {}
    if excluded_modules:
        kept = []
        for module in modules:
            if module.name in excluded_modules:
                reason = excluded_modules[module.name].get("reason", "no reason recorded")
                print(f"Excluding module '{module.name}' from teaching workload: {reason}")
            else:
                kept.append(module)
        modules = kept

    # Mark new content on modules that appear in new_modules
    for module in modules:
        if module.name in new_modules:
            module.new_content = True

    # Load previous year WTW for known lecturers (data_dir is passed to load_previous_wtw)
    prev_modules = load_previous_wtw(data_dir)
    known_lecturers = set()
    known_lecturers_per_module: Dict[str, Set[str]] = {}  # module_code -> set of teachers

    if prev_modules:
        for m in prev_modules:
            # Track teachers per module
            module_teachers: Set[str] = set()
            for t in m.teachers:
                name = normalize_name(t, reverse_lookup, unknown_callback, mappings)
                if name:
                    known_lecturers.add(name)
                    module_teachers.add(name)

            # Store the set of teachers for this module (use canonical names from codes)
            # Track by ALL codes AND by module name to handle code changes between years
            all_keys = set(m.codes)
            all_keys.add(m.name)  # Add module name like "SYS3" as key
            if module_teachers:
                for key in all_keys:
                    known_lecturers_per_module[key] = module_teachers.copy()

    # Load student counts, assessment counts, and practical data (DATA_DIR is used internally)
    student_counts = _load_student_counts()
    codes_by_acronym = _load_codes_by_acronym()
    assessment_counts = _load_assessment_counts()
    practical_data = _load_practical_data()

    # Merge student counts for H/M variants (combine numbers for same module)
    # e.g., COM00056H (NETS-H) + COM00188M (NETS-M) should be combined.
    #
    # The pairing is by trailing H/M on an otherwise identical key, which is right
    # for the acronym-suffixed keys ("NETS-H"/"NETS-M") this was written for, but
    # two real codes can share a numeric stem while belonging to entirely different
    # modules - COM00052H is AURO, COM00052M is the SCSE module SSAS. Merging those
    # would credit each with the other's cohort, so a stem pair is only treated as
    # an H/M variant when the two codes are not claimed by different WTW rows.
    code_owner = {}
    for module in modules:
        for module_code in module.codes:
            code_owner.setdefault(module_code, module.name)

    def _is_same_module(code_a: str, code_b: str) -> bool:
        owner_a, owner_b = code_owner.get(code_a), code_owner.get(code_b)
        return owner_a is None or owner_b is None or owner_a == owner_b

    merged_student_counts = {}
    for code, count in student_counts.items():
        # Check if this code is part of an H/M pair
        base_code = code
        if code.endswith("H") and code[:-1] + "M" in student_counts \
                and _is_same_module(code, code[:-1] + "M"):
            # This is the H variant; combine with M
            m_code = code[:-1] + "M"
            merged_student_counts[code] = count + student_counts[m_code]
            merged_student_counts[m_code] = count + student_counts[m_code]
        elif code.endswith("M") and code[:-1] + "H" in student_counts \
                and _is_same_module(code, code[:-1] + "H"):
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
        # Fall back to the module acronym when no code matched. Some WTW rows
        # carry a placeholder code (e.g. FOAM's "<new for one year>") but the
        # module still has real student numbers recorded under its acronym -
        # without this they would silently use DEFAULT_STUDENT_COUNT. Mirrors
        # the acronym fallback already used for assessment counts below.
        matched_by_acronym = False
        if total_students == 0 and module.name in merged_student_counts:
            total_students = merged_student_counts[module.name]
            matched_by_acronym = True
        if total_students > 0:
            module.student_count = total_students

        # Per-code counts (unmerged), so callers can tell H-variant and M-variant
        # cohorts apart for modules that share a WTW row but have separate codes
        # (e.g. AURO: COM00052H + COM00186M)
        module.student_count_by_code = {
            code: student_counts[code] for code in module.codes if code in student_counts
        }
        # When the match came via the acronym, record the real code(s) too. The
        # H/M suffix decides the marking rate, so without this a module whose WTW
        # row has a placeholder code would be marked at the UG rate regardless of
        # its actual level.
        if matched_by_acronym and not module.student_count_by_code:
            module.student_count_by_code = {
                real_code: student_counts[real_code]
                for real_code in codes_by_acronym.get(module.name, [])
                if real_code in student_counts
            }

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
                module.practical_groups = pdata.get("practical_groups", 0)
                module.practical_weeks = pdata.get("practical_weeks", [])
                break
        # If no code match, try by acronym
        if module.practical_contact_hours == 0.0 and module.name in practical_data:
            pdata = practical_data[module.name]
            module.practicals = pdata["practicals"]
            module.practical_contact_hours = pdata["practical_contact_hours"]
            module.practical_groups = pdata.get("practical_groups", 0)
            module.practical_weeks = pdata.get("practical_weeks", [])

    # Load supplementary data (DATA_DIR is used internally for all file loading)
    project_load_data = _load_project_load()
    pastoral_load_data = _load_pastoral_load()
    phd_data = _load_phd_supervision()
    fte_data = _load_fte_data()
    waw_roles = _load_waw_roles()
    part_time_data = _load_part_time()
    art_ts_data = _load_art_ts_categories()
    adjustments_data, adjustment_warnings, unattributed_adjustment_warnings = _load_adjustments()
    for w in unattributed_adjustment_warnings:
        print(f"Warning: workload_adjustments.csv {w}")

    # Build staff roster from all data sources
    staff = {}

    # Collect all names from all sources (as a set to deduplicate)
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

    # Sort names for deterministic processing order
    sorted_names = sorted(all_names)

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

    # Build consolidated data lookup in a single pass per source
    # This avoids multiple loops over all_names and all data sources
    def _find_data(raw_name: str, canonical: str, data_source: Dict) -> Optional[Dict]:
        """Find matching data from a source using raw name or canonical name."""
        # Direct match on raw name (case-insensitive)
        for key, val in data_source.items():
            if key.upper() == raw_name.upper() or key.lower() == raw_name.lower():
                return val
        # Match via canonical name
        for key, val in data_source.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback, mappings)
            if norm_key == canonical:
                return val
        return None

    def _find_all_matches(raw_name: str, canonical: str, data_source: Dict[str, list]) -> list:
        """Find and concatenate matching data from EVERY key that matches raw_name,
        instead of stopping at the first (unlike _find_data). Used for adjustments,
        where a person can legitimately have multiple rows/entries that must all be
        collected rather than only the first key-match found."""
        matches = []
        matched_keys = set()
        for key, val in data_source.items():
            if key.upper() == raw_name.upper() or key.lower() == raw_name.lower():
                if key not in matched_keys:
                    matches.extend(val)
                    matched_keys.add(key)
        for key, val in data_source.items():
            if key in matched_keys:
                continue
            norm_key = normalize_name(key, reverse_lookup, unknown_callback, mappings)
            if norm_key == canonical:
                matches.extend(val)
                matched_keys.add(key)
        return matches

    for raw_name in sorted_names:
        canonical = normalize_name(raw_name, reverse_lookup, unknown_callback, mappings)
        if not canonical:
            continue

        # Single-pass lookup from each data source
        proj_data = _find_data(raw_name, canonical, project_load_data)
        phd_info = _find_data(raw_name, canonical, phd_data)
        fte_info = _find_data(raw_name, canonical, fte_data)
        pt_info = _find_data(raw_name, canonical, part_time_data)
        art_ts_category = _find_data(raw_name, canonical, art_ts_data)
        adj_records = _find_all_matches(raw_name, canonical, adjustments_data)
        adj_warnings = _find_all_matches(raw_name, canonical, adjustment_warnings)

        # Assign roles from WAW (apply name mapping to resolve WAW→YAML differences)
        staff_roles = []
        for role in sorted(waw_roles.keys()):
            members = waw_roles[role]
            yaml_role = _WAW_ROLE_MAPPING.get(role, role)
            if yaml_role is None:
                continue  # Skip non-role entries like "Group Leads"
            for member in members:
                norm_member = normalize_name(member, reverse_lookup, unknown_callback, mappings)
                if norm_member == canonical:
                    staff_roles.append(yaml_role)

        # Check for SAINTS modules
        saint_modules = []
        for saint_name, modules_list in saint_module_map.items():
            if raw_name.upper() == saint_name.upper() or \
               saint_name.lower() in canonical.lower() or \
               saint_name.lower() in raw_name.lower():
                saint_modules.extend(modules_list)

        if canonical not in staff:
            # Extract pastoral students from pastoral_load_data (prioritized) or project_load data
            pastoral_students = 0
            # First try to get from dedicated pastoral_load_data
            if raw_name.upper() in pastoral_load_data:
                pastoral_students = pastoral_load_data[raw_name.upper()]
            elif canonical.upper() in pastoral_load_data:
                pastoral_students = pastoral_load_data[canonical.upper()]
            else:
                # Fallback: try without middle initial (e.g., "DAWN WOOD" instead of "DAWN H WOOD")
                canonical_parts = canonical.upper().split()
                if len(canonical_parts) > 1:
                    simplified_key = " ".join([canonical_parts[0], canonical_parts[-1]])
                    if simplified_key in pastoral_load_data:
                        pastoral_students = pastoral_load_data[simplified_key]

            # Fall back to project_load.csv Pastoral Load column only if not already set from pastoral_load_data
            if proj_data and "pastoral_load" in proj_data and pastoral_students == 0:
                try:
                    pastoral_students = int(float(proj_data.get("pastoral_load", 0)))
                except (ValueError, TypeError):
                    pastoral_students = 0

            # Resolve contract category (ART / T and S) from the available data
            # sources, in priority order. Anything still unresolved here is left
            # blank for now and asked about later (after the roster is filtered
            # down to this year's staff) so we never prompt about someone who
            # won't appear in any report.
            resolved_category = _resolve_category_from_data(
                canonical, art_ts_category, pt_info, category_overrides
            )

            staff[canonical] = StaffData(
                canonical_name=canonical,
                aliases=tuple(mappings.get(canonical, [canonical])),
                fte=pt_info["fte"] if pt_info else 1.0,
                employment_start=proj_data["employment_start"] if proj_data else 0,
                active=proj_data["active"] if proj_data else True,
                category=resolved_category,
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
                roles=tuple(staff_roles),
                phd_supervisions=phd_info["sole_supervisor"] if phd_info else 0,
                phd_co_supervisions=phd_info["co_supervisor"] if phd_info else 0,
                phd_assessor_count=phd_info["tap_member"] if phd_info else 0,
                research_projects=tuple(fte_info) if fte_info else (),
                saint_modules=tuple(sorted(set(saint_modules))),
                pastoral_students=pastoral_students,
                adjustments=tuple(adj_records),
                adjustment_warnings=tuple(adj_warnings),
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

    # Sort staff by canonical name for deterministic processing order
    sorted_staff_items = sorted(staff.items())

    filtered_staff = {}
    for name, data in sorted_staff_items:
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
    # Generalized: look up Head of Department role from WAW instead of hardcoding name
    hod_role = "Head of Department"
    hod_name_from_waw = None
    for role, members in waw_roles.items():
        yaml_role = _WAW_ROLE_MAPPING.get(role, role)
        if yaml_role == hod_role and members:
            # First member is the HoD
            potential_hod = members[0] if isinstance(members, list) else members
            norm_name = normalize_name(potential_hod, reverse_lookup, unknown_callback=None)
            if norm_name:
                hod_name_from_waw = norm_name
                break

    # If HoD not already in staff and found in WAW, add them with proper data
    if hod_name_from_waw and hod_name_from_waw not in staff:
        # Look up PhD info for the HoD (if available)
        phd_info = None
        for key, val in phd_data.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
            if norm_key == hod_name_from_waw:
                phd_info = val
                break

        # Look up FTE/research grant info for the HoD (if available)
        fte_info = None
        for key, val in fte_data.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
            if norm_key == hod_name_from_waw:
                fte_info = val
                break

        # Get project_load data for the HoD (if available)
        proj_data_hod = None
        for key, val in project_load_data.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
            if norm_key == hod_name_from_waw:
                proj_data_hod = val
                break

        # Get part-time info (FTE) for the HoD (if available)
        pt_info_hod = None
        for key, val in part_time_data.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
            if norm_key == hod_name_from_waw:
                pt_info_hod = val
                break

        # Default FTE to 1.0 if no part-time data found
        hod_fte = pt_info_hod["fte"] if pt_info_hod else 1.0

        # Collect ALL roles this person holds in WAW (same logic as normal staff)
        hod_roles = []
        for role, members in waw_roles.items():
            yaml_role = _WAW_ROLE_MAPPING.get(role, role)
            if yaml_role is None:
                continue  # Skip non-role entries like "Group Leads"
            for member in members:
                norm_member = normalize_name(member, reverse_lookup, unknown_callback=None)
                if norm_member == hod_name_from_waw:
                    hod_roles.append(yaml_role)

        # Resolve contract category using the same priority order as regular staff
        art_ts_category_hod = None
        for key, val in art_ts_data.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
            if norm_key == hod_name_from_waw:
                art_ts_category_hod = val
                break

        resolved_category_hod = _resolve_category_from_data(
            hod_name_from_waw, art_ts_category_hod, pt_info_hod, category_overrides
        )

        # Collect adjustment rows/warnings for the HoD (if available). This uses the
        # same every-matching-key-collected logic as _find_all_matches above, kept
        # inline here since this block operates outside that closure's scope.
        adj_records_hod = []
        for key, val in adjustments_data.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
            if key.lower() == hod_name_from_waw.lower() or norm_key == hod_name_from_waw:
                adj_records_hod.extend(val)
        adj_warnings_hod = []
        for key, val in adjustment_warnings.items():
            norm_key = normalize_name(key, reverse_lookup, unknown_callback=None)
            if key.lower() == hod_name_from_waw.lower() or norm_key == hod_name_from_waw:
                adj_warnings_hod.extend(val)

        staff[hod_name_from_waw] = StaffData(
            canonical_name=hod_name_from_waw,
            aliases=tuple(mappings.get(hod_name_from_waw, [hod_name_from_waw])),
            fte=hod_fte,
            employment_start=proj_data_hod["employment_start"] if proj_data_hod else 0,
            active=proj_data_hod["active"] if proj_data_hod else True,
            category=resolved_category_hod,
            project_load=proj_data_hod["project_load"] if proj_data_hod else 0,
            pastoral_load=proj_data_hod["pastoral_load"] if proj_data_hod else 0,
            adjusted_project_load=proj_data_hod["adjusted_project_load"] if proj_data_hod else 0,
            adjusted_pastoral_load=proj_data_hod["adjusted_pastoral_load"] if proj_data_hod else 0,
            ecr_year=proj_data_hod["ecr_year"] if proj_data_hod else "N/A",
            ecr_value=proj_data_hod["ecr_value"] if proj_data_hod else 0,
            citizenship_level=proj_data_hod["citizenship_level"] if proj_data_hod else 0,
            research_grant_income=proj_data_hod["research_grant_income"] if proj_data_hod else "N/A",
            research_grant_income_value=proj_data_hod["research_grant_income_value"] if proj_data_hod else 0,
            citizenship_value=proj_data_hod["citizenship_value"] if proj_data_hod else 0,
            initial_fractional_project_load=proj_data_hod["initial_fractional_project_load"] if proj_data_hod else 0,
            initial_fractional_pastoral_load=proj_data_hod["initial_fractional_pastoral_load"] if proj_data_hod else 0,
            notes="HoD - added for completeness, not in WTW",
            roles=tuple(sorted(hod_roles)),
            phd_supervisions=phd_info["sole_supervisor"] if phd_info else 0,
            phd_co_supervisions=phd_info["co_supervisor"] if phd_info else 0,
            phd_assessor_count=phd_info["tap_member"] if phd_info else 0,
            research_projects=tuple(fte_info) if fte_info else (),
            saint_modules=(),
            adjustments=tuple(adj_records_hod),
            adjustment_warnings=tuple(adj_warnings_hod),
        )

    # Ask about any remaining unresolved contract categories. Deliberately done
    # here - after the roster has been filtered to this year's staff and the HoD
    # added - so the user is only asked about people who actually appear in the
    # reports, rather than every historical name in the data files. Inactive
    # staff are skipped for the same reason.
    if category_callback:
        for name in sorted(staff.keys()):
            data = staff[name]
            if data.category or not data.active:
                continue
            answer = category_callback(name)
            if answer:
                category_overrides[name] = answer
                category_overrides_dirty = True
                staff[name] = replace(data, category=answer)

    # Convert modules to tuple for frozen YearData
    modules_tuple = tuple(modules)

    # Convert per-module teacher sets to frozensets
    frozen_per_module = {code: frozenset(teachers) for code, teachers in known_lecturers_per_module.items()}

    # Sort modules by name for deterministic output
    sorted_modules = sorted(modules, key=lambda m: m.name)
    # Sort staff by canonical name for deterministic output
    sorted_staff = dict(sorted(staff.items()))

    if category_overrides_dirty:
        _save_category_overrides(category_overrides)

    # Orphan detection: warn about any workload_adjustments.csv Person that never
    # resolved to a staff member in this year's final roster. There's no per-person
    # report to attach a flag to for someone not in the roster, so this is
    # console-only - matching the pattern used for unattributed_adjustment_warnings.
    for raw_person, records in adjustments_data.items():
        norm = normalize_name(raw_person, reverse_lookup, unknown_callback=None)
        if not norm or norm not in sorted_staff:
            print(f"Warning: workload_adjustments.csv Person '{raw_person}' does not match "
                  f"any staff member in this year's roster - {len(records)} adjustment row(s) ignored.")

    return YearData(
        year_label=year_label,
        modules=tuple(sorted_modules),
        student_counts=dict(merged_student_counts),
        assessment_counts=dict(assessment_counts),
        staff=tuple(sorted_staff.values()),
        known_lecturers=frozenset(known_lecturers),
        known_lecturers_per_module=frozen_per_module,
        reverse_lookup=reverse_lookup,
        canonical_lookup=mappings,
    )


def _deduplicate_staff(staff: Dict[str, StaffData], mappings: Dict[str, List[str]]) -> Dict[str, StaffData]:
    """Second-pass deduplication: merge staff entries that share the same lookup mapping. E.g., 'Chris Crispin-Bailey' and 'Christopher Crispin-Bailey' should be merged."""
    # Build reverse: alias -> canonical (sort for determinism)
    alias_to_canonical = {}
    for canonical in sorted(mappings.keys()):
        aliases = mappings[canonical]
        for alias in aliases:
            alias_to_canonical[alias.strip().lower()] = canonical

    # Group staff by their resolved canonical name
    groups = {}
    for name, data in sorted(staff.items()):
        # Find which canonical name this maps to
        resolved = alias_to_canonical.get(name.lower(), name)
        groups.setdefault(resolved, []).append((name, data))

    # Merge each group - create new StaffData entries since they are frozen
    merged = {}
    for canonical in sorted(groups.keys()):
        entries = groups[canonical]
        if len(entries) == 1:
            merged[canonical] = entries[0][1]
        else:
            # Collect all values from duplicate entries (sorted for determinism)
            all_aliases = set()
            all_roles = set()
            all_research_projects = []
            all_saint_modules = []
            all_adjustments = []
            all_adjustment_warnings = []

            for _, data in sorted(entries):
                all_aliases.update(data.aliases)
                all_roles.update(data.roles)
                all_research_projects.extend(data.research_projects)
                all_saint_modules.extend(data.saint_modules)
                all_adjustments.extend(data.adjustments)
                all_adjustment_warnings.extend(data.adjustment_warnings)

            # Take the max values for numeric fields
            merged_fte = max((e[1].fte for e in entries if e[1].fte), default=0.0)
            merged_category = next((e[1].category for e in entries if e[1].category), "")
            # Sort notes to ensure deterministic output
            merged_notes = "; ".join(sorted(set(e[1].notes for e in entries if e[1].notes)))
            merged_employment_start = max((e[1].employment_start for e in entries), default=0)
            merged_active = any(e[1].active for e in entries)

            # Merge PhD supervision counts (take max for each type)
            merged_phd_supervisions = max((e[1].phd_supervisions for e in entries), default=0)
            merged_phd_co_supervisions = max((e[1].phd_co_supervisions for e in entries), default=0)
            merged_phd_assessor_count = max((e[1].phd_assessor_count for e in entries), default=0)

            # Get first non-zero values for other fields (sorted entries ensures determinism)
            proj_data = next((e[1] for e in sorted(entries) if e[1].project_load > 0), entries[0][1])

            merged[canonical] = StaffData(
                canonical_name=canonical,
                aliases=tuple(sorted(all_aliases)),
                fte=merged_fte,
                employment_start=merged_employment_start,
                active=merged_active,
                category=merged_category,
                project_load=proj_data.project_load,
                pastoral_load=proj_data.pastoral_load,
                adjusted_project_load=proj_data.adjusted_project_load,
                adjusted_pastoral_load=proj_data.adjusted_pastoral_load,
                ecr_year=proj_data.ecr_year,
                ecr_value=proj_data.ecr_value,
                citizenship_level=proj_data.citizenship_level,
                research_grant_income=proj_data.research_grant_income,
                research_grant_income_value=proj_data.research_grant_income_value,
                citizenship_value=proj_data.citizenship_value,
                initial_fractional_project_load=proj_data.initial_fractional_project_load,
                initial_fractional_pastoral_load=proj_data.initial_fractional_pastoral_load,
                notes=merged_notes,
                roles=tuple(sorted(all_roles)),
                phd_supervisions=merged_phd_supervisions,
                phd_co_supervisions=merged_phd_co_supervisions,
                phd_assessor_count=merged_phd_assessor_count,
                research_projects=tuple(all_research_projects),
                saint_modules=tuple(sorted(set(all_saint_modules))),
                unallocated_students=0,
                pastoral_students=0,
                adjustments=tuple(all_adjustments),
                adjustment_warnings=tuple(all_adjustment_warnings),
            )

    return merged
