"""Loading and validating the frozen benchmark corpus."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MIN_SITES = 8
MIN_PAGES = 100


class DatasetError(ValueError):
    """The corpus is not usable: a label points nowhere, or a page has no labels entry."""


@dataclass(frozen=True)
class Label:
    page: str
    rule_id: str

    def key(self) -> tuple[str, str]:
        return (self.rule_id, self.page)


@dataclass(frozen=True)
class SiteLabels:
    slug: str
    base_url: str
    pages: tuple[str, ...]
    labels: tuple[Label, ...]

    def labels_for(self, page: str) -> frozenset[str]:
        return frozenset(label.rule_id for label in self.labels if label.page == page)


@dataclass(frozen=True)
class Dataset:
    version: int
    digest: str
    sites: tuple[SiteLabels, ...]

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
        return site.base_url + page

    def rules(self) -> set[str]:
        return {label.rule_id for site in self.sites for label in site.labels}


def load_dataset(path: Path) -> Dataset:
    """Read the manifest and refuse anything the metrics could not trust."""
    payload = json.loads(path.read_text(encoding="utf-8"))
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
        sites.append(
            SiteLabels(
                slug=str(raw["slug"]),
                base_url=str(raw["base_url"]),
                pages=pages,
                labels=labels,
            )
        )
    site_tuple = tuple(sites)
    computed = dataset_digest(site_tuple)
    declared = payload.get("digest")
    if declared is not None and str(declared) != computed:
        # A comparison trusts the digest; a digest that does not describe the labels means two
        # different corpora could be compared as one.
        raise DatasetError(f"manifest digest {declared} does not match the corpus ({computed})")
    dataset = Dataset(version=int(payload.get("version") or 1), digest=computed, sites=site_tuple)
    if len(dataset.sites) < MIN_SITES:
        raise DatasetError(
            f"a benchmark needs at least {MIN_SITES} sites, found {len(dataset.sites)}"
        )
    if dataset.pages < MIN_PAGES:
        raise DatasetError(f"a benchmark needs at least {MIN_PAGES} pages, found {dataset.pages}")
    return dataset


def dataset_digest(sites: tuple[SiteLabels, ...]) -> str:
    """Digest of the labels alone: two runs may only be compared on the same corpus."""
    payload = json.dumps(
        [
            {
                "slug": site.slug,
                "pages": list(site.pages),
                "labels": sorted(
                    ({"page": label.page, "rule_id": label.rule_id} for label in site.labels),
                    key=lambda item: (item["page"], item["rule_id"]),
                ),
            }
            for site in sites
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    import hashlib

    return f"sha256:{hashlib.sha256(payload).hexdigest()[:16]}"
