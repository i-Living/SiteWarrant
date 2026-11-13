"""Audit every page of the corpus and compare what came back with what was planted."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from app.audit import run_audit
from app.core.config import get_settings
from app.core.version import compute_agent_version
from app.eval.dataset import Dataset, DatasetError, SiteLabels, load_dataset
from app.eval.metrics import Metrics, measure
from app.eval.models import EvalRun, Mismatch, RunContext


def predictions_from(findings: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """`(rule_id, page)` pairs: the granularity a label is stated at."""
    return {(rule_id, page) for rule_id, page in findings}


async def run_eval(
    dataset_path: Path,
    *,
    sites: list[str] | None = None,
    agents: list[str] | None = None,
    store_artifacts: bool = False,
) -> EvalRun:
    """One measured pass. Deterministic by construction: the same corpus, the same numbers."""
    dataset = load_dataset(dataset_path)
    selected = _select_sites(dataset, sites)
    settings = get_settings()
    started_at = datetime.now(UTC)
    clock = time.monotonic()

    labels: set[tuple[str, str]] = set()
    predicted: set[tuple[str, str]] = set()
    findings_raw = 0
    duplicates_removed = 0
    pages = 0
    pages_with_false_positives = 0
    durations: list[int] = []
    per_site: dict[str, dict[str, object]] = {}

    for site in selected:
        site_labels: set[tuple[str, str]] = set()
        site_predicted: set[tuple[str, str]] = set()
        site_pages_with_false = 0
        site_findings_raw = 0
        site_duplicates = 0
        for page in site.pages:
            url = dataset.page_url(site, page)
            report = await run_audit(
                str(url),
                allow_private=True,
                agents=agents or (),
                store_artifacts=store_artifacts,
            )
            page_rules = {finding.rule_id for finding in report.findings}
            site_labels |= {(rule_id, page) for rule_id in site.labels_for(page)}
            site_predicted |= {(rule_id, page) for rule_id in page_rules}
            planted = site.labels_for(page)
            if page_rules - planted:
                site_pages_with_false += 1
            # Raw means before dedupe: a finding the chief layer removed was still reported.
            findings_raw += len(report.findings) + report.summary.duplicates_removed
            duplicates_removed += report.summary.duplicates_removed
            site_findings_raw += len(report.findings) + report.summary.duplicates_removed
            site_duplicates += report.summary.duplicates_removed
            durations.append(report.summary.duration_ms)
            pages += 1

        labels |= site_labels
        predicted |= site_predicted
        pages_with_false_positives += site_pages_with_false
        per_site[site.slug] = measure(
            site_labels,
            site_predicted,
            pages=len(site.pages),
            pages_with_false_positives=site_pages_with_false,
            findings_raw=site_findings_raw,
            duplicates_removed=site_duplicates,
        ).as_dict()

    metrics: Metrics = measure(
        labels,
        predicted,
        pages=pages,
        pages_with_false_positives=pages_with_false_positives,
        findings_raw=findings_raw,
        duplicates_removed=duplicates_removed,
        all_rules=dataset.rules(),
    )
    return EvalRun(
        context=RunContext(
            dataset_digest=dataset.digest,
            dataset_version=dataset.version,
            # The same inputs run_audit feeds the digest: a version that ignores the model would
            # label two different agents as one.
            agent_version=compute_agent_version(
                viewports=settings.viewport_list,
                page_timeout_ms=settings.page_timeout_ms,
                capture_timeout_ms=settings.capture_timeout_ms,
                user_agent=settings.user_agent,
                llm_model=settings.llm_model,
            ),
            viewports=list(settings.viewport_list),
            agents=list(agents or ()),
            model=settings.llm_model if agents else None,
            store_artifacts=store_artifacts,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            duration_s=round(time.monotonic() - clock, 1),
        ),
        metrics=metrics.as_dict(),
        per_site=per_site,
        missing=_mismatches(labels - predicted, selected),
        extra=_mismatches(predicted - labels, selected),
        page_durations_ms=durations,
    )


def _mismatches(pairs: set[tuple[str, str]], sites: list[SiteLabels]) -> list[Mismatch]:
    order = {site.slug: index for index, site in enumerate(sites)}
    by_page = {(site.slug, page): site for site in sites for page in site.pages}
    found: list[Mismatch] = []
    for rule_id, page in sorted(pairs, key=lambda item: (item[1], item[0])):
        site = next(
            (
                candidate
                for (slug, candidate_page), candidate in by_page.items()
                if candidate_page == page
            ),
            None,
        )
        if site is None:
            continue
        found.append(Mismatch(site=site.slug, page=page, rule_id=rule_id))
    found.sort(key=lambda item: (order.get(item.site, 0), item.page, item.rule_id))
    return found


def _select_sites(dataset: Dataset, sites: list[str] | None) -> list[SiteLabels]:
    if not sites:
        return list(dataset.sites)
    selected: list[SiteLabels] = []
    for slug in sites:
        try:
            selected.append(dataset.site(slug))
        except DatasetError as error:
            raise DatasetError(
                f"{error}; available: {', '.join(s.slug for s in dataset.sites)}"
            ) from error
    return selected
