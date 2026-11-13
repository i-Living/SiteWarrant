"""The shape of a stored eval run."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunContext(BaseModel):
    """Everything that makes two runs comparable or not."""

    dataset_digest: str
    dataset_version: int
    agent_version: str
    viewports: list[str]
    agents: list[str] = []
    model: str | None = None
    store_artifacts: bool = False
    started_at: datetime
    finished_at: datetime
    duration_s: float


class Mismatch(BaseModel):
    site: str
    page: str
    rule_id: str


class EvalRun(BaseModel):
    """One measured pass over the corpus: counts, ratios, and the exact lists behind them."""

    context: RunContext
    metrics: dict[str, Any]
    per_site: dict[str, dict[str, Any]]
    missing: list[Mismatch] = Field(default_factory=list, description="labelled but not reported")
    extra: list[Mismatch] = Field(default_factory=list, description="reported but not labelled")
    page_durations_ms: list[int] = Field(default_factory=list)
