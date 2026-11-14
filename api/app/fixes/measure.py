"""Measure the fix layer over the benchmark corpus: does a repair apply, and does it break anything?

`docs/PLAN.md` section 4 states two product metrics and nothing computed them:

- `fix_acceptance_rate` — repairs that applied to the served source, over repairs proposed;
- `regression_free_fix_rate` — re-audits that found nothing new, over repairs applied.

The unit is one repair: the fix for one finding, as its own diff against the page as it is served.
`fix` composes a page's repairs into one patch, which is the right packaging for a human and the
wrong one for this count — a composed diff cannot say which repair failed to apply.

A floor, not a promise: the corpus is static, so a patch computed from the source it is later
applied to usually applies. What the measurement buys is the second half — the re-audit, where a
repair that moves a layout or changes contrast shows up as a new finding, which the invariant calls
a regression.
"""

from __future__ import annotations

import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.audit import run_audit
from app.core.config import get_settings
from app.core.report import Report
from app.core.version import compute_agent_version
from app.eval.dataset import DatasetError, SiteLabels, load_dataset, page_digest
from app.eval.models import RunContext
from app.eval.runner import select_sites
from app.fixes.patch import FIXABLE, Patch
from app.fixes.reaudit import Delta, PatchedSite, ReauditError, ReauditResult, reaudit
from app.fixes.recommend import plan_repairs, unified_diff


class Counts(BaseModel):
    """Counts first: a rate without its denominator is a claim without evidence."""

    # Findings of a mechanically fixable rule: the population a repair could be proposed for.
    findings: int = 0
    proposed: int = 0
    applied: int = 0
    closed: int = 0
    regression_free: int = 0
    fix_acceptance_rate: float | None = None
    regression_free_fix_rate: float | None = None


class NotApplied(BaseModel):
    """A repair the page refused: the diff did not land, and why."""

    rule_id: str
    page_url: str
    reason: str


class FixRun(BaseModel):
    """One measured pass over the corpus: what was proposed, what applied, what it broke."""

    context: RunContext
    totals: Counts
    per_site: dict[str, Counts]
    per_rule: dict[str, Counts]
    not_applied: list[NotApplied] = Field(default_factory=list)


def rate(part: int, whole: int) -> float | None:
    """A zero denominator yields null, never 0: an unmeasured rate is not a perfect one."""
    if whole <= 0:
        return None
    return round(part / whole, 4)


def with_rates(counts: Counts) -> Counts:
    return counts.model_copy(
        update={
            "fix_acceptance_rate": rate(counts.applied, counts.proposed),
            "regression_free_fix_rate": rate(counts.regression_free, counts.applied),
        }
    )


def verify_sources(site: SiteLabels, site_dir: Path) -> None:
    """The files this run serves must be the pages the manifest digests.

    `load_dataset` checks the manifest against itself; it cannot see the files, so a page edited
    behind it would be measured under the old identity and the artifact would name a corpus it did
    not audit. `page_digest` is the generator's own contract, so a mismatch here is a corpus that
    `benchmark/generate.py --check` would refuse as well.
    """
    for page in site.pages:
        source = site_dir / page
        if not source.is_file():
            # Without the served source there is nothing to measure, and skipping the page would
            # quietly shrink the denominator.
            raise DatasetError(f"{site.slug}/{page}: no source file at {source}")
        digest = page_digest(source.read_text(encoding="utf-8"))
        expected = site.page_digests[page]
        if digest != expected:
            raise DatasetError(
                f"{site.slug}/{page} is not the page the manifest digests ({digest} != {expected})"
                "; regenerate the corpus instead of editing it"
            )


def closed_by(closed: list[Delta], repair: Patch) -> bool:
    """Whether a repair closed the finding it was computed for.

    A rule can fire twice on one page — the corpus banner covers two links — and moving it closes
    both findings. Counting by rule alone would credit each repair with the other's finding, so the
    subject has to match: `reaudit.key_of` identifies a finding by rule, page and subject, and the
    subject is what is left once the other two are fixed.
    """
    subject = (repair.subject or "").strip()
    return any(item.rule_id == repair.rule_id and item.subject == subject for item in closed)


async def measure_fixes(dataset_path: Path, *, sites: list[str] | None = None) -> FixRun:
    """Audit every page, repair every mechanically fixable finding on its own, and re-audit it."""
    dataset = load_dataset(dataset_path)
    selected = select_sites(dataset, sites)
    settings = get_settings()
    started_at = datetime.now(UTC)
    clock = time.monotonic()

    totals = Counts()
    per_site: dict[str, Counts] = {}
    per_rule: dict[str, Counts] = {}
    not_applied: list[NotApplied] = []

    root = dataset_path.parent
    for site in selected:
        site_dir = root / "sites" / site.slug
        verify_sources(site, site_dir)
        site_counts = per_site.setdefault(site.slug, Counts())
        # Serve the site's own directory, not the corpus host: a repair is a diff against these
        # files, and a URL path that only the web server knows (a `/bench/<slug>/` prefix) would
        # point `reaudit` at a file the copy does not have.
        with PatchedSite(site_dir) as server:
            for page in site.pages:
                source = site_dir / page
                url = f"{server.base_url}/{page}"
                report = await run_audit(url, allow_private=True, agents=(), store_artifacts=False)
                fixable = [finding for finding in report.findings if finding.rule_id in FIXABLE]
                if not fixable:
                    continue
                totals.findings += len(fixable)
                site_counts.findings += len(fixable)
                for finding in fixable:
                    per_rule.setdefault(finding.rule_id, Counts()).findings += 1
                repairs = await plan_repairs(
                    report.audit_id, {url: source.read_text(encoding="utf-8")}
                )
                for repair in repairs:
                    rule_counts = per_rule.setdefault(repair.rule_id, Counts())
                    totals.proposed += 1
                    site_counts.proposed += 1
                    rule_counts.proposed += 1

                    result = await _apply_and_reaudit(report, site_dir, page, repair)
                    if isinstance(result, NotApplied):
                        not_applied.append(result)
                        continue

                    totals.applied += 1
                    site_counts.applied += 1
                    rule_counts.applied += 1
                    if closed_by(result.closed, repair):
                        totals.closed += 1
                        site_counts.closed += 1
                        rule_counts.closed += 1
                    # Every new finding is a regression, and this layer does not grade them.
                    if not result.new:
                        totals.regression_free += 1
                        site_counts.regression_free += 1
                        rule_counts.regression_free += 1

    return FixRun(
        context=RunContext(
            dataset_digest=dataset.digest,
            dataset_version=dataset.version,
            agent_version=compute_agent_version(
                viewports=settings.viewport_list,
                page_timeout_ms=settings.page_timeout_ms,
                capture_timeout_ms=settings.capture_timeout_ms,
                user_agent=settings.user_agent,
                llm_model=settings.llm_model,
            ),
            viewports=list(settings.viewport_list),
            agents=[],
            model=None,
            store_artifacts=False,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            duration_s=round(time.monotonic() - clock, 1),
        ),
        totals=with_rates(totals),
        per_site={slug: with_rates(counts) for slug, counts in per_site.items()},
        per_rule={rule_id: with_rates(counts) for rule_id, counts in sorted(per_rule.items())},
        not_applied=not_applied,
    )


async def _apply_and_reaudit(
    report: Report, site_dir: Path, path: str, repair: Patch
) -> ReauditResult | NotApplied:
    """Apply this one repair to a copy of the site and re-audit the page it belongs to."""
    with tempfile.TemporaryDirectory(prefix="sitewarrant-fix-") as raw:
        patch_file = Path(raw) / "repair.patch"
        patch_file.write_text(unified_diff(repair, path=path), encoding="utf-8")
        try:
            return await reaudit(report, site_dir=site_dir, patch_file=patch_file)
        except ReauditError as error:
            return NotApplied(rule_id=repair.rule_id, page_url=repair.page_url, reason=str(error))
