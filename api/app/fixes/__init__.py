"""Fixes: a recommendation for every finding, a patch for the five mechanical ones."""

from app.fixes.measure import Counts, FixRun, NotApplied, measure_fixes, rate, with_rates
from app.fixes.patch import FIXABLE, FixError, Patch, patch_for
from app.fixes.reaudit import Delta, ReauditError, ReauditResult, diff_findings, reaudit
from app.fixes.recommend import (
    FixBuildError,
    FixReport,
    Recommendation,
    build_fixes,
    plan_repairs,
    unified_diff,
    write_fix_files,
)

__all__ = [
    "FIXABLE",
    "Counts",
    "Delta",
    "FixBuildError",
    "FixError",
    "FixReport",
    "FixRun",
    "NotApplied",
    "Patch",
    "ReauditError",
    "ReauditResult",
    "Recommendation",
    "build_fixes",
    "diff_findings",
    "measure_fixes",
    "patch_for",
    "plan_repairs",
    "rate",
    "reaudit",
    "unified_diff",
    "with_rates",
    "write_fix_files",
]
