"""Turn operator feedback into a labelled corpus.

A benchmark of real sites needs labels a human stands behind. The cheapest honest source is the
feedback a reader already gave on findings: a confirmed finding is a defect on that page, a false
positive is a page with no such defect. This module exports exactly that and refuses to invent the
rest — a page is included only when *every* finding on it was reviewed, because an unreviewed
finding would otherwise be counted as a false positive.

The manifest it writes has no page bytes: it names live URLs and the date they were measured
(`source: "live"`), so the repository does not grow by a copy of somebody's site.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.db import session_scope
from app.eval.dataset import LIVE, DatasetError, Label, SiteLabels, dataset_digest
from app.storage import repo

# A defect the reader saw: confirmed in place, or confirmed by having been fixed afterwards.
POSITIVE_VERDICTS = frozenset({"confirmed", "fixed"})


def host_of(url: str) -> str:
    parts = urlsplit(url)
    port = f":{parts.port}" if parts.port else ""
    return f"{(parts.hostname or '').lower()}{port}"


def base_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def path_of(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def write_manifest(manifest: dict[str, Any], out: Path) -> None:
    """Write the file: a sync helper, because an async function must not block on the disk."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


async def export_labels(host: str, *, out: Path) -> dict[str, Any]:
    """Write a live-corpus manifest from the feedback recorded for one host.

    Raises `DatasetError` when no page is fully reviewed: an empty manifest would look like a
    measured zero, and it is not one.
    """
    labels: set[Label] = set()
    pages: list[str] = []
    async with session_scope() as session:
        audits = [
            audit
            for audit in await repo.latest_audit_per_url(session)
            if host_of(audit.site_url) == host.lower()
        ]
        if not audits:
            raise DatasetError(f"no audit of {host!r} is stored, so there is nothing to label")

        for audit in audits:
            findings = await repo.findings_for_audit(session, audit.id)
            if not findings:
                # Nothing was reported, so nothing was reviewed: a page with no findings is not
                # a clean control until a human says so, and this export has no way to ask.
                continue
            verdicts = {
                str(finding.id): {
                    row.verdict for row in await repo.list_feedback(session, finding.id)
                }
                for finding in findings
            }
            if any(not seen for seen in verdicts.values()):
                continue
            page = path_of(audit.site_url)
            pages.append(page)
            for finding in findings:
                if verdicts[str(finding.id)] & POSITIVE_VERDICTS:
                    # One label per (rule, page): the layer reports one finding per rule per page
                    # however many nodes it names, so five covered links are one labelled defect.
                    labels.add(Label(page=page, rule_id=finding.rule_id))

    if not pages:
        raise DatasetError(
            f"no page of {host!r} has a verdict on every finding; review the findings first "
            "(POST /findings/{id}/feedback)"
        )

    site = SiteLabels(
        slug=host.lower().replace(":", "-").replace(".", "-"),
        base_url=base_of(audits[0].site_url),
        pages=tuple(sorted(pages)),
        # Sorted: a set has no order, and the digest is over this tuple.
        labels=tuple(sorted(labels, key=lambda label: (label.page, label.rule_id))),
    )
    captured_at = datetime.now(UTC).date().isoformat()
    manifest: dict[str, Any] = {
        "version": 1,
        "generator": "sitewarrant labels",
        "notes": (
            "Labels come from operator feedback; each listed page has a verdict on every "
            "finding the audit reported. Pages with no review are absent, not clean."
        ),
        "source": LIVE,
        "captured_at": captured_at,
        "minimums": {"sites": 1, "pages": 1},
        "sites": [
            {
                "slug": site.slug,
                "base_url": site.base_url,
                "pages": list(site.pages),
                "labels": [{"page": label.page, "rule_id": label.rule_id} for label in site.labels],
                "page_digests": {},
            }
        ],
        "totals": {"sites": 1, "pages": len(site.pages), "labels": len(site.labels)},
    }
    manifest["digest"] = dataset_digest((site,), source=LIVE, captured_at=captured_at)
    write_manifest(manifest, out)
    return manifest
