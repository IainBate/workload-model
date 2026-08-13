"""
Shared reporting helpers (plan item E2).

Both report surfaces - the department dashboard (`output_generator.py`) and the
per-staff reports (`new_individual_reports.py`) - answer the same questions:
"how far is this person from their contract-type target?" and "is that far
enough to flag?". Those were previously two independent implementations with
their own thresholds, free to drift apart.

This module owns those definitions so both reports agree. It contains no
calculation of workload hours - it only compares and classifies numbers the
calculator has already produced.
"""

from typing import Any, Dict, List, Optional

import config

# Deviation thresholds, in percentage points, shared by both reports.
DEVIATION_ON_TARGET_PP = 5      # within this -> "On target"
DEVIATION_MODERATE_PP = 10      # within this -> "Moderate", beyond -> "High"

# Over/under nominal-hours threshold used to decide whether someone needs
# attention on the department report.
NOMINAL_VARIANCE_THRESHOLD = 0.10   # 10%

CATEGORIES = ("teaching", "research", "admin")


def deviation_band(deviation_pp: float) -> str:
    """Classify a percentage-point deviation as 'ok' | 'moderate' | 'high'."""
    magnitude = abs(deviation_pp)
    if magnitude <= DEVIATION_ON_TARGET_PP:
        return "ok"
    if magnitude <= DEVIATION_MODERATE_PP:
        return "moderate"
    return "high"


def category_deviations(result: Any) -> Optional[Dict[str, Dict[str, float]]]:
    """Per-category actual vs target split for one staff member.

    Returns {category: {actual_pct, target_pct, deviation_pct}} or None when the
    person's contract category has no normative split - callers must render
    "no comparison available" rather than inventing a target.
    """
    normative_split = config.get_normative_split(getattr(result, "category", ""))
    if not normative_split or not getattr(result, "total_hours", 0):
        return None

    deviations = {}
    for category in CATEGORIES:
        actual_hours = getattr(result, f"{category}_hours", 0.0)
        actual_pct = (actual_hours / result.total_hours) * 100
        target_pct = normative_split.get(f"{category}_hours", 0) * 100
        deviations[category] = {
            "actual_pct": actual_pct,
            "target_pct": target_pct,
            "deviation_pct": actual_pct - target_pct,
        }
    return deviations


def worst_deviation_band(result: Any) -> Optional[str]:
    """The most severe band across all categories, or None if not comparable."""
    deviations = category_deviations(result)
    if not deviations:
        return None
    worst = max(abs(d["deviation_pct"]) for d in deviations.values())
    return deviation_band(worst)


def nominal_variance(result: Any) -> Optional[float]:
    """Fractional over/under nominal hours (+0.125 == 12.5% over), or None."""
    nominal = getattr(result, "nominal_hours", 0)
    if not nominal:
        return None
    return (result.total_hours - nominal) / nominal


def is_over_or_under_nominal(result: Any) -> bool:
    """True if total hours deviate from nominal by more than the shared threshold."""
    variance = nominal_variance(result)
    return variance is not None and abs(variance) > NOMINAL_VARIANCE_THRESHOLD


def data_quality_issue_label(result: Any) -> str:
    """Human-readable summary of assumption/missing-data flags ('' if none)."""
    parts = []
    if getattr(result, "assumptions", None):
        parts.append("Assumptions")
    if getattr(result, "missing_data", None):
        parts.append("Missing Data")
    return ", ".join(parts)


def needs_attention(results: List[Any]) -> List[Dict[str, Any]]:
    """Staff a manager should look at first.

    Flags anyone materially over/under nominal hours, or carrying data-quality
    flags. Sorted by deviation magnitude, largest first.
    """
    flagged = []
    for r in results:
        issues = data_quality_issue_label(r)
        if not is_over_or_under_nominal(r) and not issues:
            continue
        target = getattr(r, "nominal_hours", 0) or 0
        variance = nominal_variance(r)
        flagged.append({
            "name": r.name,
            "category": getattr(r, "category", "") or "Unknown",
            "fte": r.fte,
            "total": r.total_hours,
            "target": target,
            "deviation_pct": (variance * 100) if variance is not None else 0.0,
            "issues": issues,
        })
    return sorted(flagged, key=lambda x: abs(x["deviation_pct"]), reverse=True)


def department_summary(results: List[Any]) -> Dict[str, Any]:
    """Headline department-wide figures."""
    total_fte = sum(r.fte for r in results)
    total_hours = sum(r.total_hours for r in results)
    return {
        "headcount": len(results),
        "total_fte": total_fte,
        "total_hours": total_hours,
        "average_hours": (total_hours / len(results)) if results else 0.0,
        "nominal_total": total_fte * config.NOMINAL_WORKING_HOURS_PER_YEAR,
    }


def category_statistics(results: List[Any]) -> Dict[str, Dict[str, Any]]:
    """Per-contract-category aggregates, including the average actual split
    and the normative target it should be compared against."""
    stats: Dict[str, Dict[str, Any]] = {}
    for r in results:
        category = getattr(r, "category", "") or "Unknown"
        entry = stats.setdefault(category, {
            "count": 0, "fte_sum": 0.0, "hours_sum": 0.0,
            "teaching_sum": 0.0, "research_sum": 0.0, "admin_sum": 0.0,
        })
        entry["count"] += 1
        entry["fte_sum"] += r.fte
        entry["hours_sum"] += r.total_hours
        for c in CATEGORIES:
            entry[f"{c}_sum"] += getattr(r, f"{c}_hours", 0.0)

    for category, entry in stats.items():
        count = entry["count"] or 1
        averages = {c: entry[f"{c}_sum"] / count for c in CATEGORIES}
        entry["averages"] = averages
        total_avg = sum(averages.values())
        entry["actual_split_pct"] = {
            c: (averages[c] / total_avg * 100) if total_avg else 0.0 for c in CATEGORIES
        }
        split = config.get_normative_split(category)
        entry["normative_split_pct"] = (
            {c: split.get(f"{c}_hours", 0) * 100 for c in CATEGORIES} if split else None
        )
    return stats
