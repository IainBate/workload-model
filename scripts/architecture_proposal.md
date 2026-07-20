# Workload Model - Software Architecture Proposal

**Status**: Partially Implemented (P0-P1 completed)

## Implementation Complete (Priority P0-P1)

### 1. Fixed Supervision Allocation (P0 - Completed)

**Problem**: The `supervision_allocated` set was passed as a mutable default argument and mutated across module calls, causing state to persist between calculation runs.

**Solution**: Implemented a new `SupervisionAllocation` dataclass with supervision allocation moved to a separate phase:

```python
@dataclass(frozen=True)
class SupervisionAllocation:
    """Immutable record of supervision hours allocated to each staff member."""
    pastoral_students: Dict[str, int]      # canonical_name -> count
    project_loads: Dict[str, float]        # canonical_name -> project load (ceiling'd)
    phd_supervisions: Dict[str, int]       # canonical_name -> count

def allocate_supervision(staff_data: Dict[str, StaffData]) -> SupervisionAllocation:
    """
    Calculate supervision allocation for all staff members.
    
    This is a pure function that reads from staff data and returns an immutable
    SupervisionAllocation. It should be called once per calculation run before
    teaching workload calculations.
    """
    pastoral = {}
    projects = {}
    phd = {}
    
    for name, staff in staff_data.items():
        pastoral[name] = staff.pastoral_students
        projects[name] = staff.project_load  # Already ceiling'd in data_loader.py
        phd[name] = staff.phd_supervisions
    
    return SupervisionAllocation(pastoral, projects, phd)
```

**Changes Made**:
- `SupervisionAllocation` added to `data_loader.py` with `frozen=True`
- `allocate_supervision()` function added to `data_loader.py`
- `_calculate_teaching_workload()` signature changed from mutable set to `supervision: SupervisionAllocation`
- `calculate_workload()` now calls `allocate_supervision(year_data.staff)` once at start
- Removed all `supervision_allocated.add(teacher)` tracking logic

### 2. Separated Supervision Allocation from Teaching Calculation (P1 - Completed)

**Problem**: Supervision allocation was embedded within `_calculate_teaching_workload()` with stateful tracking.

**Solution**: Supervision is now allocated once per calculation run and passed as an immutable parameter:

```python
def calculate_workload(year_data: YearData) -> List[WorkloadResult]:
    # Allocate supervision once for all teachers (pure function)
    supervision = allocate_supervision(year_data.staff)
    
    # Process each module with explicit supervision parameter
    for module in year_data.modules:
        module_teaching = _calculate_teaching_workload(
            module, normalized_teachers, year_data.known_lecturers,
            year_data.staff, supervision=supervision  # Immutable allocation
        )
```

---

## Remaining Issues (Priority P2-P4)

### 3. Single Source of Truth for Pastoral Students (P2 - Pending)

**Current State**: Pastoral students are read from `pastoral_load.csv` as the primary source. The old code had a fallback to `project_load.csv`, which has been removed.

**Status**: Now uses only `pastoral_load.csv` as the single source of truth for pastoral student counts.

### 2. Separate Data Loading from Data Merging

**Problem**: `load_all_data()` does both loading AND merging in one function.

```python
# PROPOSED SPLIT:

def load_pastoral_load(filepath: str = "pastoral_load.csv") -> Dict[str, int]:
    """Load pastoral student counts."""
    ...

def load_project_load(filepath: str = "project_load.csv") -> Dict[str, dict]:
    """Load project load data."""
    ...

def merge_staff_data(
    wtw_names: Set[str],
    project_data: Dict[str, dict],
    pastoral_data: Dict[str, int],
    phd_data: Dict[str, dict],
    fte_data: Dict[str, list],
    roles: Dict[str, List[str]],
    name_lookup: Dict[str, str]
) -> Dict[str, StaffData]:
    """
    Merge data from all sources into staff records.
    Each input is processed once, with clear precedence rules.
    """
    staff = {}
    
    for raw_name in wtw_names:
        canonical = normalize_name(raw_name, name_lookup)
        if not canonical:
            continue
        
        # Get data from each source (no overwriting - merge explicitly)
        proj_data = project_data.get(canonical, {})
        past_data = pastoral_data.get(canonical, 0)
        
        staff[canonical] = StaffData(
            pastoral_students=past_data,  # From dedicated pastoral_load.csv
            project_load=proj_data.get("project_load", 0),
            ...
        )
    
    return staff
```

### 3. Immutable WorkloadResult (P3 - Completed)

**Problem**: `WorkloadResult` had optional mutable fields (lists, dicts) that could be modified.

**Solution**: Made `WorkloadResult` a frozen dataclass with immutable tuples for list-like fields:

```python
@dataclass(frozen=True)
class WorkloadResult:
    name: str
    fte: float
    total_hours: float
    teaching_hours: float
    research_hours: float
    admin_hours: float
    assumptions: Tuple[str, ...]  # Immutable tuple (was List[str])
    missing_data: Tuple[str, ...]  # Immutable tuple

    teaching_detail: str = ""
    research_detail: str = ""
    admin_detail: str = ""
    nominal_hours: float = 0.0
    teaching_breakdown: Dict[str, float] = None
    research_breakdown: Dict[str, float] = None
    admin_breakdown: Dict[str, float] = None
    grant_titles: Dict[str, str] = None
    module_details: Tuple[str, ...] = ()  # Immutable tuple (was List[str])
    supervision_details: Tuple[str, ...] = ()  # Immutable tuple (was List[str])
```

**Changes Made**:
- `WorkloadResult` now uses `@dataclass(frozen=True)`
- `assumptions` and `missing_data` changed from `List[str]` to `Tuple[str, ...]`
- `module_details` and `supervision_details` changed from `List[str]` to `Tuple[str, ...]`
- Default values use empty tuples instead of `None`

---

## Architecture Improvements Summary

| Priority | Task | Status |
|----------|------|--------|
| **P0** | Remove `supervision_allocated` mutable default | ✅ Completed - uses immutable SupervisionAllocation |
| **P1** | Separate supervision allocation from teaching calculation | ✅ Completed - pure function, no state mutation |
| **P2** | Deduplicate pastoral_students source (use only pastoral_load.csv) | ✅ Completed - single source of truth |
| **P3** | Make WorkloadResult frozen dataclass | ✅ Completed - prevents accidental mutation |

---

## Remaining Improvements (Future Work)

### 4. Extract Aggregation Logic from calculate_workload() (P4 - Future)

**Current State**: The `calculate_workload()` function still mutates `staff_teaching` dictionary throughout the calculation loop.

**Proposed Improvement**: Extract aggregation into a separate pure function:

```python
@dataclass(frozen=True)
class ModuleWorkload:
    module: ModuleData
    teacher_hours: Dict[str, float]
    teacher_breakdowns: Dict[str, Dict[str, float]]
    details: Dict[str, str]

def _calculate_module_workload(module: ModuleData, ...) -> ModuleWorkload:
    """Pure function - calculates workload for a single module."""
    ...

def _aggregate_staff_totals(staff_data: Dict[str, StaffData], 
                            module_results: List[ModuleWorkload]) -> Dict[str, StaffTotal]:
    """Aggregate per-staff totals from all modules (pure function)."""
    totals = {name: {"hours": 0.0, "details": [], ...} for name in staff_data}
    for result in module_results:
        # Aggregate without mutation - use functional approach
        ...
    return totals

def calculate_workload(year_data: YearData) -> List[WorkloadResult]:
    supervision = allocate_supervision(year_data.staff)
    
    module_results = []
    for module in year_data.modules:
        result = _calculate_module_workload(module, ...)
        module_results.append(result)
    
    staff_totals = _aggregate_staff_totals(year_data.staff, module_results)
    
    return [_build_result(name, staff, totals) 
            for name, staff in staff_totals.items()]
```

This would make the code more testable and easier to reason about since each phase would be a separate pure function.

---

## Testing Strategy

With these changes, each component becomes independently testable:

```python
# Test supervision allocation (pure function)
def test_supervision_allocation():
    staff = {
        "John": StaffData(pastoral_students=10, project_load=5),
        "Jane": StaffData(pastoral_students=8, project_load=3),
    }
    allocation = _allocate_supervision(staff)
    assert allocation.pastoral == {"John": 10, "Jane": 8}
    assert allocation.projects == {"John": 5, "Jane": 3}

# Test module workload (pure function, no state)
def test_module_workload():
    module = ModuleData(teachers=["John", "Jane"], ...)
    known_lecturers = {"Jane"}
    staff = {...}
    supervision = _allocate_supervision(staff)
    
    result = _calculate_teaching_workload(module, teachers, known_lecturers, staff, supervision)
    # Verify calculation without worrying about global state
```
