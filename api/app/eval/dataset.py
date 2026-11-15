"""Loading and validating the frozen benchmark corpus."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

MIN_SITES = 8
MIN_PAGES = 100
# A corpus is either a frozen snapshot served locally, or a live set of URLs with labels taken
# from operator feedback. Live corpora are identified by when they were captured, because the
# pages themselves change; they are never the CI corpus.
SNAPSHOT = "snapshot"
LIVE = "live"


class DatasetError(ValueError):
    """The corpus is not usable: a label points nowhere, or a page has no labels entry."""


@dataclass(frozen=True)
class Label:
    page: str
    rule_id: str

    def key(self) -> tuple[str, str]:
        return (self.rule_id, self.page)


def page_digest(text: str) -> str:
    """One page's bytes, in the form both the generator and this loader write.

    `benchmark/generate.py` hashes the same text it writes, so the two digests agree without the
    loader having to guess how the file was produced.
    """
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()[:16]}"


@dataclass(frozen=True)
class SiteLabels:
    slug: str
    base_url: str
    pages: tuple[str, ...]
    labels: tuple[Label, ...]
    # Page → digest of that page's rendered text. Two corpora with identical labels but different
    # markup would otherwise share a digest and be compared as one measurement.
    page_digests: Mapping[str, str] = field(default_factory=dict)

    def labels_for(self, page: str) -> frozenset[str]:
        return frozenset(label.rule_id for label in self.labels if label.page == page)


@dataclass(frozen=True)
class Dataset:
    version: int
    digest: str
    sites: tuple[SiteLabels, ...]
    source: str = SNAPSHOT
    captured_at: str | None = None

    @property
    def allow_private(self) -> bool:
        """A snapshot is served from loopback; a live corpus is fetched from the internet."""
        return self.source == SNAPSHOT

    @property
    def pages(self) -> int:
        return sum(len(site.pages) for site in self.sites)

    @property
    def labels(self) -> int:
        return sum(len(site.labels) for site in self.sites)

    def site(self, slug: str) -> SiteLabels:
        for site in self.sites:
            if site.slug == slug:
                return site
        raise DatasetError(f"unknown site {slug!r}")

    def page_url(self, site: SiteLabels, page: str) -> str:
        """A page may be a path inside `base_url` (a snapshot) or a full audited URL (live).

        The prefix is parsed, not searched: `product?next=https://other.example/` is a relative
        reference that happens to contain a URL in its query, and matching `://` anywhere would
        leave it relative and fetch it from the wrong origin.
        """
        parsed = urlsplit(page)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return page
        return site.base_url + page

    def rules(self) -> set[str]:
        return {label.rule_id for site in self.sites for label in site.labels}


def load_dataset(path: Path) -> Dataset:
    """Read the manifest and refuse anything the metrics could not trust."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = str(payload.get("source") or SNAPSHOT)
    if source not in (SNAPSHOT, LIVE):
        raise DatasetError(f"unknown corpus source {source!r}; expected {SNAPSHOT} or {LIVE}")
    captured_at = payload.get("captured_at")
    if source == LIVE and not captured_at:
        # A live corpus is a measurement of pages on a date; without the date the labels describe
        # a site nobody can identify afterwards.
        raise DatasetError("a live corpus must name the date it was captured (`captured_at`)")
    sites: list[SiteLabels] = []
    for raw in payload.get("sites") or []:
        pages = tuple(str(page) for page in raw.get("pages") or [])
        labels = tuple(
            Label(page=str(item["page"]), rule_id=str(item["rule_id"]))
            for item in raw.get("labels") or []
        )
        for label in labels:
            if label.page not in pages:
                raise DatasetError(f"{raw['slug']}: label for unknown page {label.page!r}")
        page_digests = {
            str(page): str(digest) for page, digest in (raw.get("page_digests") or {}).items()
        }
        if source == SNAPSHOT:
            missing = [page for page in pages if page not in page_digests]
            if missing:
                raise DatasetError(
                    f"{raw['slug']}: no content digest for {missing[0]!r}, so the corpus cannot "
                    "be identified; re-run python benchmark/generate.py"
                )
        sites.append(
            SiteLabels(
                slug=str(raw["slug"]),
                base_url=str(raw["base_url"]),
                pages=pages,
                labels=labels,
                page_digests=page_digests,
            )
        )
    site_tuple = tuple(sites)
    computed = dataset_digest(site_tuple, source=source, captured_at=captured_at)
    declared = payload.get("digest")
    if declared is not None and str(declared) != computed:
        # A comparison trusts the digest; a digest that does not describe the labels means two
        # different corpora could be compared as one.
        raise DatasetError(f"manifest digest {declared} does not match the corpus ({computed})")
    dataset = Dataset(
        version=int(payload.get("version") or 1),
        digest=computed,
        sites=site_tuple,
        source=source,
        captured_at=None if captured_at is None else str(captured_at),
    )
    minimums: dict[str, Any] = payload.get("minimums") or {}
    min_sites = int(minimums.get("sites", MIN_SITES))
    min_pages = int(minimums.get("pages", MIN_PAGES))
    if len(dataset.sites) < min_sites:
        raise DatasetError(
            f"a benchmark needs at least {min_sites} sites, found {len(dataset.sites)}"
        )
    if dataset.pages < min_pages:
        raise DatasetError(f"a benchmark needs at least {min_pages} pages, found {dataset.pages}")
    return dataset


def dataset_digest(
    sites: tuple[SiteLabels, ...], *, source: str = SNAPSHOT, captured_at: str | None = None
) -> str:
    """Digest of the corpus: its labels and the bytes they were planted in.

    Labels alone would let two different corpora compare as one measurement; the page digests keep
    the digest tied to the markup a run actually saw. A live corpus has no bytes to hash, so its
    identity is the URL set, the labels and the capture date.
    """
    site_payload: list[dict[str, Any]] = []
    for site in sites:
        labels_payload: list[dict[str, str]] = [
            {"page": label.page, "rule_id": label.rule_id} for label in site.labels
        ]
        labels_payload.sort(key=lambda item: (item["page"], item["rule_id"]))
        entry: dict[str, Any] = {
            "slug": site.slug,
            "pages": list(site.pages),
            "labels": labels_payload,
            "page_digests": dict(site.page_digests),
        }
        if source == LIVE:
            # A live corpus has no bytes to hash; its identity is where the pages live, which
            # pages, which labels and when. `base_url` moves the audit target, so it is part of
            # the measurement. The snapshot payload keeps its old shape so frozen digests hold.
            entry["base_url"] = site.base_url
        site_payload.append(entry)
    payload = json.dumps(
        site_payload
        if source == SNAPSHOT and captured_at is None
        else {
            "source": source,
            "captured_at": captured_at,
            "sites": site_payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()[:16]}"
