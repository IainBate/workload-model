# Memory Index

This file indexes key facts and guidance for this project.

## Project Reference

- [Workload Model Specification](workload-model-specification.md) — Core rules for workload calculation, including teaching multipliers, research time allocation, admin percentages, and supervision defaults.

## Developer Guidance

- [Shell Command Warning Configuration](shell-command-warning-configuration.md) — Guidance on Claude Code's "Newline followed by #" warning. These are false positives in this codebase (no subprocess calls). Docstrings have been converted to single-line format to eliminate the pattern.

## Completed Tasks

- [Stage Code Constants Migration](stage-code-constants-migration.md) — Replaced magic number stage comparisons (`module.stage >= 3`) with named constants from config.py. Added `STAGE_UG_LEVEL_*`, `STAGE_MSC_LEVEL`, and `STAGE_PGR_LEVEL` constants with helper functions `is_ug_level()` and `is_msc_level()`.
