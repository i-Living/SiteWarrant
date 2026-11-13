"""Fixes: a recommendation for every finding, a patch for the five mechanical ones."""

from app.fixes.patch import FIXABLE, FixError, Patch, patch_for
from app.fixes.reaudit import Delta, ReauditError, ReauditResult, diff_findings, reaudit
from app.fixes.recommend import (
    FixBuildError,
    FixReport,
    Recommendation,
    build_fixes,
    unified_diff,
    write_fix_files,
)

__all__ = [
    "FIXABLE",
    "Delta",
    "FixBuildError",
    "FixError",
    "FixReport",
    "Patch",
    "ReauditError",
    "ReauditResult",
    "Recommendation",
    "build_fixes",
    "diff_findings",
    "patch_for",
    "reaudit",
    "unified_diff",
    "write_fix_files",
]
