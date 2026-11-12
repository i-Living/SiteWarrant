from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SkipReason = Literal[
    "robots",
    "fetch_failed",
    "blocked",
    "not_html",
    "body_too_large",
    "template_limit",
    "page_limit",
]

PageSource = Literal["start", "link", "sitemap"]


class CrawlLimits(BaseModel):
    """Bounds on discovery and selection. Recorded in the report, so a run is reproducible."""

    max_pages: int = Field(default=50, ge=1, le=2000)
    max_depth: int = Field(default=3, ge=0, le=10)
    pages_per_template: int = Field(default=2, ge=1, le=50)
    max_discovered: int = Field(default=200, ge=1, le=10000)
    include_sitemap: bool = True


class DiscoveredPage(BaseModel):
    url: str
    page_key: str
    template: str
    depth: int
    source: PageSource
    status_code: int | None = None
    rendered: bool = False
    selected: bool = False
    skip_reason: SkipReason | str | None = None


class TemplateCoverage(BaseModel):
    """One page template and how much of it the crawl covers."""

    template: str
    discovered: int
    selected: int


class CrawlReport(BaseModel):
    site: str
    start_url: str
    agent_version: str
    generated_at: datetime
    limits: CrawlLimits
    pages_discovered: int
    pages_selected: int
    skipped: dict[str, int]
    templates: list[TemplateCoverage]
    pages: list[DiscoveredPage]
