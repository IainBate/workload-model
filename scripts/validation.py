"""
Input validation layer for workload calculations.

Provides ValidationResult class and validation functions to ensure
data integrity before calculation.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class ValidationLevel(Enum):
    """Severity level for validation issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ValidationResult:
    """
    Result of a validation check.

    Args:
        valid: Whether the overall validation passed
        issues: List of validation issues found
        data: Optional original data that was validated
    """
    valid: bool
    issues: List['ValidationIssue'] = field(default_factory=list)
    data: Any = None

    def add_issue(self, level: ValidationLevel, message: str,
                  field_name: str = None, value: Any = None) -> 'ValidationResult':
        """Add an issue to this result and return updated result."""
        new_issues = self.issues + [ValidationIssue(level, message, field_name, value)]
        return ValidationResult(
            valid=self.valid and level == ValidationLevel.INFO,
            issues=new_issues,
            data=self.data
        )

    def merge(self, other: 'ValidationResult') -> 'ValidationResult':
        """Merge another validation result into this one."""
        return ValidationResult(
            valid=self.valid and other.valid,
            issues=self.issues + other.issues,
            data=self.data
        )

    @property
    def has_errors(self) -> bool:
        """Check if there are any errors in the issues."""
        return any(i.level == ValidationLevel.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings in the issues."""
        return any(i.level == ValidationLevel.WARNING for i in self.issues)

    @property
    def summary(self) -> str:
        """Return a summary of validation issues."""
        if not self.issues:
            return "No issues"
        error_count = sum(1 for i in self.issues if i.level == ValidationLevel.ERROR)
        warning_count = sum(1 for i in self.issues if i.level == ValidationLevel.WARNING)
        info_count = sum(1 for i in self.issues if i.level == ValidationLevel.INFO)
        return f"{error_count} error(s), {warning_count} warning(s), {info_count} info(s)"


@dataclass(frozen=True)
class ValidationIssue:
    """
    A single validation issue found during validation.

    Args:
        level: Severity level (INFO, WARNING, ERROR)
        message: Human-readable description of the issue
        field_name: Optional name of the field with the issue
        value: Optional value that caused the issue
    """
    level: ValidationLevel
    message: str
    field_name: str = None
    value: Any = None

    def __str__(self) -> str:
        field_info = f"[{self.field_name}] " if self.field_name else ""
        return f"{field_info}{self.message}"


# --- Validation Functions ---

def validatefte(fte: float, allow_zero: bool = False) -> ValidationResult:
    """
    Validate FTE (Full-Time Equivalent) value.

    Args:
        fte: The FTE value to validate
        allow_zero: Whether zero FTE is acceptable

    Returns:
        ValidationResult with any issues found
    """
    issues = []

    if fte < 0:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(ValidationLevel.ERROR, "FTE cannot be negative", "fte", fte)]
        )

    if fte > 1.0:
        return ValidationResult(
            valid=True,  # Not an error, but worth noting
            issues=[ValidationIssue(ValidationLevel.WARNING, "FTE exceeds 1.0 (full-time)", "fte", fte)]
        )

    if not allow_zero and fte == 0:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(ValidationLevel.ERROR, "FTE cannot be zero", "fte", fte)]
        )

    if fte < 0.1:
        return ValidationResult(
            valid=True,
            issues=[ValidationIssue(ValidationLevel.WARNING, "Very low FTE (< 0.1)", "fte", fte)]
        )

    return ValidationResult(valid=True)


def validatestudentcount(student_count: int) -> ValidationResult:
    """
    Validate student count value.

    Args:
        student_count: The student count to validate

    Returns:
        ValidationResult with any issues found
    """
    if student_count < 0:
        return ValidationResult(
            valid=False,
            issues=[ValidationIssue(ValidationLevel.ERROR, "Student count cannot be negative", "student_count", student_count)]
        )

    if student_count == 0:
        return ValidationResult(
            valid=True,
            issues=[ValidationIssue(ValidationLevel.INFO, "No students enrolled", "student_count", student_count)]
        )

    if student_count > 500:
        return ValidationResult(
            valid=True,
            issues=[ValidationIssue(ValidationLevel.WARNING, "Very high student count (> 500)", "student_count", student_count)]
        )

    return ValidationResult(valid=True)


def validate_module_data(module) -> ValidationResult:
    """
    Validate a ModuleData object.

    Args:
        module: The ModuleData instance to validate

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult(valid=True, data=module)

    # Validate required fields exist
    if not hasattr(module, 'name'):
        return result.add_issue(ValidationLevel.ERROR, "Module missing 'name' field")

    if not hasattr(module, 'credits'):
        return result.add_issue(ValidationLevel.ERROR, "Module missing 'credits' field", "credits", None)

    # Validate credits (should be positive)
    credits = getattr(module, 'credits', 0)
    if credits <= 0:
        result = result.add_issue(ValidationLevel.ERROR, "Credits must be positive", "credits", credits)

    # Validate module codes. Codes are the join key for student numbers,
    # assessment counts, practical data and previous-year lecturer lookups, so a
    # missing or placeholder code means the module silently falls back to
    # defaults (e.g. DEFAULT_STUDENT_COUNT) instead of using real data.
    codes = getattr(module, 'codes', ()) or ()
    placeholder_codes = [
        c for c in codes
        if not c or '<' in c or '>' in c or c.strip().lower() in ('n/a', 'na', 'tbd', 'none')
    ]
    if not codes:
        result = result.add_issue(
            ValidationLevel.WARNING, "Module has no codes - student/assessment data cannot be matched",
            "codes", codes)
    elif placeholder_codes:
        result = result.add_issue(
            ValidationLevel.WARNING,
            f"Module has placeholder code(s) {placeholder_codes} - student/assessment "
            f"data cannot be matched and defaults will be used",
            "codes", codes)

    # Validate student count
    student_count = getattr(module, 'student_count', 0)
    result = result.merge(validatestudentcount(student_count))

    # Validate practicals if present
    practicals = getattr(module, 'practicals', 0)
    if practicals < 0:
        result = result.add_issue(ValidationLevel.ERROR, "Practicals cannot be negative", "practicals", practicals)

    # Validate assessment count if present
    assessment_count = getattr(module, 'assessment_count', 0)
    if assessment_count < 0:
        result = result.add_issue(ValidationLevel.ERROR, "Assessment count cannot be negative", "assessment_count", assessment_count)

    return result


def validatestaffdata(staff) -> ValidationResult:
    """
    Validate a StaffData object.

    Args:
        staff: The StaffData instance to validate

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult(valid=True, data=staff)

    # Validate FTE
    fte = getattr(staff, 'fte', None)
    if fte is None:
        return result.add_issue(ValidationLevel.ERROR, "Staff missing 'fte' field", "fte", None)

    result = result.merge(validatefte(fte))

    # Validate canonical_name exists
    if not hasattr(staff, 'canonical_name') or not staff.canonical_name:
        result = result.add_issue(ValidationLevel.ERROR, "Staff missing 'canonical_name' field")

    # Validate active status if present
    active = getattr(staff, 'active', True)
    if not isinstance(active, bool):
        result = result.add_issue(ValidationLevel.WARNING, "Active field should be boolean", "active", active)

    # Validate PhD supervision counts
    phd_supervisions = getattr(staff, 'phd_supervisions', 0)
    if phd_supervisions < 0:
        result = result.add_issue(ValidationLevel.ERROR, "PhD supervisions cannot be negative", "phd_supervisions", phd_supervisions)

    phd_co_supervisions = getattr(staff, 'phd_co_supervisions', 0)
    if phd_co_supervisions < 0:
        result = result.add_issue(ValidationLevel.ERROR, "PhD co-supervisions cannot be negative", "phd_co_supervisions", phd_co_supervisions)

    # Validate roles if present
    roles = getattr(staff, 'roles', [])
    if not isinstance(roles, (list, tuple)):
        result = result.add_issue(ValidationLevel.WARNING, "Roles should be a list or tuple", "roles", roles)

    return result


def validateresultsforreasonableness(results: List[Any]) -> ValidationResult:
    """
    Validate that workload results are within reasonable ranges.

    Args:
        results: List of WorkloadResult objects to validate

    Returns:
        ValidationResult with any issues found
    """
    result = ValidationResult(valid=True, data=results)
    nominal_hours = 1642  # Standard full-time hours per year

    for wr in results:
        total = getattr(wr, 'total_hours', 0)

        if total < 0:
            result = result.add_issue(ValidationLevel.ERROR, "Total workload is negative", "total_hours", total)
        elif total > nominal_hours * 2:  # More than double full-time
            result = result.add_issue(
                ValidationLevel.WARNING,
                f"Very high workload ({total:.1f}h exceeds {nominal_hours * 2}h)",
                "total_hours",
                total
            )

        # Check teaching percentage is reasonable (typically 30-70%)
        teaching = getattr(wr, 'teaching_hours', 0)
        if total > 0 and teaching / total > 0.8:
            result = result.add_issue(
                ValidationLevel.WARNING,
                "Teaching workload is very high (> 80% of total)",
                "teaching_hours",
                teaching
            )

    return result


# --- Validation Pipeline ---

def validate_year_data(year_data) -> ValidationResult:
    """
    Run full validation pipeline on YearData.

    Args:
        year_data: The YearData instance to validate

    Returns:
        ValidationResult with all issues found
    """
    result = ValidationResult(valid=True, data=year_data)

    # Validate modules
    for i, module in enumerate(getattr(year_data, 'modules', [])):
        module_result = validate_module_data(module)
        if not module_result.valid:
            result = result.add_issue(
                ValidationLevel.ERROR,
                f"Module {i} ({getattr(module, 'name', 'unknown')}): {module_result.summary}",
                f"modules[{i}]"
            )
        result = result.merge(module_result)

    # Validate staff
    for i, staff in enumerate(getattr(year_data, 'staff', [])):
        staff_result = validatestaffdata(staff)
        if not staff_result.valid:
            result = result.add_issue(
                ValidationLevel.ERROR,
                f"Staff {i} ({getattr(staff, 'canonical_name', 'unknown')}): {staff_result.summary}",
                f"staff[{i}]"
            )
        result = result.merge(staff_result)

    return result


def run_validation_pipeline_input(year_data):
    """Run validation on YearData (input data validation).

    Args:
        year_data: The YearData instance to validate

    Returns:
        Dictionary with validation results including valid, has_warnings, issues
    """
    result = validate_year_data(year_data)

    # Categorize issues by type
    module_issues = [i for i in result.issues if 'modules[' in str(i.field_name)]
    staff_issues = [i for i in result.issues if 'staff[' in str(i.field_name)]

    return {
        "valid": result.valid and not result.has_errors,
        "has_warnings": result.has_warnings,
        "issues": result.issues,
        "module_issues": module_issues,
        "staff_issues": staff_issues,
        "summary": result.summary
    }


# --- Post-Calculation Validation (WorkloadResult) ---

def validate_workload_result(result, tolerance: float = 0.1) -> List[ValidationIssue]:
    """Validate a workload result after calculation.

    Checks:
    - Total = Teaching + Research + Admin (within tolerance)
    - No negative hours
    - Breakdowns sum to category totals

    Args:
        result: The WorkloadResult to validate
        tolerance: Maximum allowed difference for sums

    Returns:
        List of validation issues (empty if valid)
    """
    issues = []

    # Check total split
    expected_total = (
        result.teaching_hours +
        result.research_hours +
        result.admin_hours
    )

    diff = abs(expected_total - result.total_hours)
    if diff > tolerance:
        issues.append(ValidationIssue(
            level=ValidationLevel.ERROR,
            message=f"Total mismatch: {result.total_hours:.1f} != {expected_total:.1f}",
            field_name="total_hours"
        ))

    # Check for negative hours
    if result.teaching_hours < 0:
        issues.append(ValidationIssue(
            level=ValidationLevel.ERROR,
            message=f"Negative teaching hours: {result.teaching_hours:.1f}",
            field_name="teaching_hours"
        ))

    if result.research_hours < 0:
        issues.append(ValidationIssue(
            level=ValidationLevel.ERROR,
            message=f"Negative research hours: {result.research_hours:.1f}",
            field_name="research_hours"
        ))

    if result.admin_hours < 0:
        issues.append(ValidationIssue(
            level=ValidationLevel.ERROR,
            message=f"Negative admin hours: {result.admin_hours:.1f}",
            field_name="admin_hours"
        ))

    # Helper to get numeric values from breakdown dict
    # For teaching/admin: only direct numeric values at top level (no nesting)
    # For research: includes protected_research_baseline plus numeric leaves in nested dicts
    def get_numeric_values(d, is_research=False):
        """Extract numeric values from a breakdown dict.

        Args:
            d: The breakdown dictionary
            is_research: If True, recursively extract from grants/phd_students dicts

        For teaching/admin breakdowns, only direct numeric values are summed.
        For research breakdowns, we also include nested grant and phd_students values.
        """
        if not isinstance(d, dict):
            return [d] if isinstance(d, (int, float)) else []

        result = []
        for k, v in d.items():
            if isinstance(v, (int, float)):
                # Direct numeric value
                result.append(v)
            elif isinstance(v, dict) and is_research:
                # For research: grants and phd_students are nested but contain actual hours
                # Recursively extract from these structure keys
                result.extend(get_numeric_values(v, is_research=True))
            elif isinstance(v, dict) and not is_research:
                # For teaching/admin: skip nested dicts (they're metadata like pastoral_breakdown)
                pass
        return result

    # Check teaching breakdown sum
    teaching_values = get_numeric_values(result.teaching_breakdown)
    teaching_sum = sum(teaching_values) if teaching_values else 0.0
    if abs(teaching_sum - result.teaching_hours) > tolerance:
        issues.append(ValidationIssue(
            level=ValidationLevel.ERROR,
            message=f"Teaching breakdown sum mismatch: {teaching_sum:.1f} != {result.teaching_hours:.1f}",
            field_name="teaching_breakdown"
        ))

    # Check research breakdown sum (pass is_research=True to handle nested grants/phd_students)
    research_values = get_numeric_values(result.research_breakdown, is_research=True)
    research_sum = sum(research_values) if research_values else 0.0
    if abs(research_sum - result.research_hours) > tolerance:
        issues.append(ValidationIssue(
            level=ValidationLevel.ERROR,
            message=f"Research breakdown sum mismatch: {research_sum:.1f} != {result.research_hours:.1f}",
            field_name="research_breakdown"
        ))

    # Check admin breakdown sum
    admin_values = get_numeric_values(result.admin_breakdown)
    admin_sum = sum(admin_values) if admin_values else 0.0
    if abs(admin_sum - result.admin_hours) > tolerance:
        issues.append(ValidationIssue(
            level=ValidationLevel.ERROR,
            message=f"Admin breakdown sum mismatch: {admin_sum:.1f} != {result.admin_hours:.1f}",
            field_name="admin_breakdown"
        ))

    return issues


def validate_all_results(results: List[Any], tolerance: float = 0.1) -> Dict[str, List[ValidationIssue]]:
    """Validate all workload results and group by staff member.

    Args:
        results: List of WorkloadResult objects to validate
        tolerance: Maximum allowed difference for sums

    Returns:
        Dict mapping staff name to list of validation issues
    """
    return {
        result.name: validate_workload_result(result, tolerance)
        for result in results
    }


def run_validation_pipeline(results: List[Any]) -> bool:
    """Run post-calculation validation and print results.

    Args:
        results: List of WorkloadResult objects to validate

    Returns:
        True if all validations passed, False otherwise
    """
    issues_by_staff = validate_all_results(results)

    has_errors = False

    for staff_name, issues in sorted(issues_by_staff.items()):
        if not issues:
            continue

        print(f"\n{staff_name}:")
        for issue in issues:
            level_str = {
                ValidationLevel.ERROR: "[ERROR]",
                ValidationLevel.WARNING: "[WARN ]",
                ValidationLevel.INFO: "[INFO ]"
            }.get(issue.level, "[     ]")

            print(f"  {level_str} {issue.field_name or 'unknown'}: {issue.message}")

            if issue.level == ValidationLevel.ERROR:
                has_errors = True

    return not has_errors
