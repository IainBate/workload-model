"""
Configuration and constants for workload calculations.
Loads parameters from workload_parameters.yaml (extracted from Work Allocation Model.docx).

This is the runtime source of truth for all workload parameters.
"""

import yaml
from pathlib import Path
from typing import Any, Dict, Optional

# Get project root directory (parent of scripts folder)
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent


def _load_yaml(filepath: str) -> dict:
    """Load a YAML file from params folder and return its contents as a dict."""
    path = PROJECT_ROOT / "params" / filepath
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Load parameters from YAML
_params = _load_yaml("workload_parameters.yaml")

# Global parameters
NOMINAL_WORKING_HOURS_PER_YEAR: int = _params["global_parameters"]["nominal_working_hours_per_year"]  # 1642
WEEKS_PER_YEAR: int = _params["global_parameters"]["weeks_per_year"]  # 44
HOURS_PER_WEEK: int = _params["global_parameters"]["hours_per_week"]  # 37

# Baseline workloads (fixed hours)
BASELOADS: dict[str, float] = _params["baselines_hours"]

# Protected research time baseline (10% of nominal hours = 164.2h)
PROTECTED_RESEARCH_BASELINE: float = _params.get("protected_research_baseline", 164.2)

# ART staff expected workload split (as percentage of nominal hours)
ART_STAFF_SPLIT: dict[str, float] = _params.get("art_staff_split", {"teaching": 0.40, "research": 0.40})
ART_TEACHING_PERCENTAGE: float = ART_STAFF_SPLIT.get("teaching", 0.40)
ART_RESEARCH_PERCENTAGE: float = ART_STAFF_SPLIT.get("research", 0.40)

# Minimum teaching load for administrative staff who don't teach modules
MIN_ADMIN_TEACHING_HOURS: float = BASELOADS.get("min_admin_teaching", 30.0)

# Teaching weeks per semester (for practical schedule calculations)
TEACHING_WEEKS_PER_SEMESTER: int = BASELOADS.get("teaching_weeks_per_semester", 11)

# Research allowances
RESEARCH_ALLOWANCES: dict[str, float] = _params.get("research_allowances", {})

# Contract normative divisions (percentage of nominal hours)
CONTRACT_NORMATIVE_DIVISIONS: dict[str, dict[str, float]] = _params["contract_normative_divisions"]

# --- Assessment Setting (hours per paper) ---
ASSESSMENT_SETTING = _params["task_multipliers"]["assessment_setting_hours_per_paper"]
# Convenience access
ASSESSMENT_AUTO_STANDARD = ASSESSMENT_SETTING["automated_marked"]["standard"]  # 25
ASSESSMENT_AUTO_NEW_SETTER = ASSESSMENT_SETTING["automated_marked"]["new_setter_same_format"]  # 35
ASSESSMENT_AUTO_NEW_ASSESSMENT = ASSESSMENT_SETTING["automated_marked"]["new_assessment_or_format"]  # 60
ASSESSMENT_AUTO_CHECKING = ASSESSMENT_SETTING["automated_marked"]["checking_paper_base"]  # 4
ASSESSMENT_MANUAL_STANDARD = ASSESSMENT_SETTING["manually_marked"]["standard"]  # 15
ASSESSMENT_MANUAL_NEW_SETTER = ASSESSMENT_SETTING["manually_marked"]["new_setter_same_format"]  # 22.5
ASSESSMENT_MANUAL_NEW_ASSESSMENT = ASSESSMENT_SETTING["manually_marked"]["new_assessment_or_format"]  # 37.5
ASSESSMENT_MANUAL_CHECKING = ASSESSMENT_SETTING["manually_marked"]["checking_paper_base"]  # 2

# --- Marking (hours per script) ---
MARKING = _params["task_multipliers"]["marking_hours_per_script"]
MARKING_AUTO_MSC = MARKING["automated"]["msc"]  # 0.25
MARKING_AUTO_UG = MARKING["automated"]["ug"]  # 0.166
MARKING_AUTO_CHECKING = MARKING["automated"]["checking"]  # 0.1
MARKING_AUTO_ADMIN = MARKING["automated"]["admin_flat_rate_per_assessment"]  # 3
MARKING_MANUAL_MSC = MARKING["manual"]["msc"]  # 0.5
MARKING_MANUAL_UG = MARKING["manual"]["ug"]  # 1/3 (20 min/script)
MARKING_MANUAL_CHECKING = MARKING["manual"]["checking"]  # 0.1
MARKING_MANUAL_ADMIN = MARKING["manual"]["admin_flat_rate_per_assessment"]  # 3

# --- Teaching (hours per contact hour) ---
TEACHING_MULTIPLIERS: dict[str, float] = _params["task_multipliers"]["teaching_on_campus_hours_per_contact_hour"]
TEACHING_STANDARD = TEACHING_MULTIPLIERS["lecture_standard"]  # 2.5
TEACHING_NEW_CONTENT = TEACHING_MULTIPLIERS["lecture_new_content_or_lecturer"]  # 5
TEACHING_NEW_BOTH = TEACHING_MULTIPLIERS["lecture_new_content_and_lecturer"]  # 7.5
TEACHING_NEW_VIDEO = TEACHING_MULTIPLIERS["lecture_new_video"]  # 10
TEACHING_PROBLEM_CLASS = TEACHING_MULTIPLIERS["problem_class_seminar_practical"]  # 2.5
TEACHING_NEW_PROBLEM_CLASS = TEACHING_MULTIPLIERS["new_problem_class_seminar_practical"]  # 5
TEACHING_HW_LAB = TEACHING_MULTIPLIERS["hw_lab"]  # 4

# Repetition multiplier for additional practical sessions
REPETITION_MULTIPLIER: float = TEACHING_MULTIPLIERS["repetition_multiplier"]  # 1.5
TEACHING_NEW_HW_LAB = TEACHING_MULTIPLIERS["new_hw_lab"]  # 8
TEACHING_DROP_IN = TEACHING_MULTIPLIERS["drop_in_session"]  # 1.5

# --- Supervision (hours per student) ---
SUPERVISION_MULTIPLIERS: dict[str, float] = _params["task_multipliers"]["supervision_hours_per_student"]
SUPERVISION_PASTORAL = SUPERVISION_MULTIPLIERS["pastoral"]  # 3
SUPERVISION_UG_PROJECT = SUPERVISION_MULTIPLIERS["ug_project"]  # 16
SUPERVISION_MSC_PROJECT = SUPERVISION_MULTIPLIERS["msc_project"]  # 24
SUPERVISION_PROJECT_MARKING = SUPERVISION_MULTIPLIERS["project_marking_first_or_second"]  # 2
SUPERVISION_PGR_PRIMARY = SUPERVISION_MULTIPLIERS["pgr_primary_supervisor_per_fte"]  # 80
SUPERVISION_PGR_CO_SUPERVISOR = SUPERVISION_MULTIPLIERS["pgr_co_supervisor_per_fte"]  # 48 (60% of primary)
SUPERVISION_PGR_ASSESSOR = SUPERVISION_MULTIPLIERS["pgr_assessor"]  # 8

# --- Online Programmes ---
ONLINE_PROGRAMS: dict[str, float] = _params["task_multipliers"]["teaching_online_programmes"]

# --- Roles (percentage of nominal hours) ---
ROLES_PERCENTAGE: dict[str, float] = _params["roles_percentage_of_nominal_hours"]

# Defaults
DEFAULT_STUDENT_COUNT: int = 100  # Default when student count is unknown
DEFAULT_CONTACT_HOURS_PER_CREDIT: float = 1.0  # Standard contact hours per credit point

# Default lecture contact hours per week (standard modules without specified contact time)
DEFAULT_LECURE_HOURS_PER_WEEK: float = _params.get("lecture_contact_hours", {}).get("default_hours_per_week", 2.0)

# Project setting allowance - given once per year to each supervisor with non-zero project load
PROJECT_SETTING_ALLOWANCE: float = 6.0  # Teaching-related, for setting projects for students

# Stage codes (for module level detection)
STAGE_UG_LEVEL_1: int = 1  # Year 1 undergraduate
STAGE_UG_LEVEL_2: int = 2  # Year 2 undergraduate
STAGE_UG_LEVEL_3: int = 3  # Year 3 undergraduate
# TODO(human): confirm STAGE_MSC_LEVEL against real WTW stage codes - does 4 mean
# integrated-masters-year, and is there a separate encoding (e.g., 10+) for standalone MSc modules?
STAGE_MSC_LEVEL: int = 4   # Master's level threshold (currently unconfirmed against real data)
STAGE_PGR_LEVEL: int = 7   # Postgraduate research level

# Helper function to determine module level from stage code
def is_ug_level(module_stage: int) -> bool:
    """Check if module stage is undergraduate level (1-3)."""
    return STAGE_UG_LEVEL_1 <= module_stage < STAGE_MSC_LEVEL

def is_msc_level(module_stage: int) -> bool:
    """Check if module stage is Master's level (stage >= 4)."""
    return module_stage >= STAGE_MSC_LEVEL


# --- Category mapping for normative split comparison ---

def normative_key_for_category(category: str) -> Optional[str]:
    """
    Translate a real-world category string to a CONTRACT_NORMATIVE_DIVISIONS key.

    Args:
        category: The staff member's contract category (e.g., "T and S", "ART")

    Returns:
        The corresponding key for CONTRACT_NORMATIVE_DIVISIONS, or None if no mapping
        exists. Callers should treat None as "no normative comparison available".
    """
    # Map real-world category strings to the keys in CONTRACT_NORMATIVE_DIVISIONS
    # Based on data analysis: categories seen are "T and S" and "ART"
    category_map = {
        "ART": "TR_staff",           # ART staff use TR_staff split (40/40/20)
        "T and S": "TS_staff_lecturer_and_above",  # T and S staff use TS_lecturer_and_above split
    }

    return category_map.get(category)


def get_normative_split(category: str) -> Optional[Dict[str, float]]:
    """
    Get the expected workload split for a given category.

    Args:
        category: The staff member's contract category

    Returns:
        A dict with teaching_hours, research_hours, admin_hours (as percentages of
        nominal hours), or None if no mapping exists for this category.
    """
    key = normative_key_for_category(category)
    if key is None:
        return None

    division = CONTRACT_NORMATIVE_DIVISIONS.get(key)
    if division is None:
        return None

    # Return a dict with the expected hours (as percentages of nominal hours)
    # Note: The keys in CONTRACT_NORMATIVE_DIVISIONS may vary (e.g., "citizenship"
    # vs "admin"), so we normalize them here
    split = {}

    # Map various key names to standard categories
    if "teaching" in division:
        split["teaching_hours"] = division["teaching"]

    # Research-related keys
    for research_key in ["research_and_scholarship", "scholarship"]:
        if research_key in division:
            split["research_hours"] = division[research_key]
            break

    # Admin/citizenship-related keys
    for admin_key in ["citizenship"]:
        if admin_key in division:
            split["admin_hours"] = division[admin_key]
            break

    return split
