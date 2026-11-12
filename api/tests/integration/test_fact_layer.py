import json
import uuid

import pytest
from sqlalchemy import select

from app.audit import artifact_path, run_audit
from app.core.db import session_scope
from app.core.models import Observation, Page, Snapshot

pytestmark = pytest.mark.integration

URL = "http://localhost:8081/"
VIEWPORTS = ("390x844", "768x1024", "1440x900")
CHANNELS = (
    "http",
    "dom",
    "axe",
    "contrast",
    "responsive",
    "occlusion",
    "performance",
    "screenshot",
)
# Timings and artifact keys differ between runs by definition; the rest must not.
NON_DETERMINISTIC = frozenset({"performance", "screenshot"})


async def stored_observations(audit_id: str) -> list[Observation]:
    async with session_scope() as session:
        rows = await session.execute(
            select(Observation)
            .join(Page, Observation.page_id == Page.id)
            .where(Page.audit_id == uuid.UUID(audit_id))
        )
        return list(rows.scalars())


async def stored_snapshots(audit_id: str) -> list[Snapshot]:
    async with session_scope() as session:
        rows = await session.execute(
            select(Snapshot)
            .join(Page, Snapshot.page_id == Page.id)
            .where(Page.audit_id == uuid.UUID(audit_id))
        )
        return list(rows.scalars())


def signature(rows: list[Observation]) -> set[tuple[str, str, str | None, str | None, str]]:
    return {
        (
            row.tool,
            row.kind,
            row.rule_ref,
            row.viewport,
            json.dumps(row.payload, sort_keys=True),
        )
        for row in rows
        if row.tool not in NON_DETERMINISTIC
    }


async def test_every_channel_reports_on_every_viewport() -> None:
    """Acceptance for P2: eight channels, each with at least one observation per viewport."""
    report = await run_audit(URL, allow_private=True)
    rows = await stored_observations(report.audit_id)

    assert set(CHANNELS) <= {row.tool for row in rows}
    for viewport in VIEWPORTS:
        per_viewport = {row.tool for row in rows if row.viewport == viewport}
        # The http channel is a property of the response, not of a viewport.
        assert set(CHANNELS) - {"http"} <= per_viewport, viewport
    assert report.summary.observations_by_tool.keys() == set(CHANNELS)


async def test_each_viewport_gets_a_snapshot_and_artifacts() -> None:
    report = await run_audit(URL, allow_private=True)
    snapshots = await stored_snapshots(report.audit_id)

    assert sorted(snapshot.viewport for snapshot in snapshots) == sorted(VIEWPORTS)
    for snapshot in snapshots:
        assert snapshot.html_key and snapshot.dom_key and snapshot.screenshot_key
        assert artifact_path(snapshot.html_key).exists()
        assert artifact_path(snapshot.dom_key).exists()
        assert artifact_path(snapshot.screenshot_key).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


async def test_two_runs_report_identical_facts() -> None:
    """Acceptance for P2: two runs in a row agree, except for measured timings."""
    first = await run_audit(URL, allow_private=True)
    second = await run_audit(URL, allow_private=True)

    assert signature(await stored_observations(first.audit_id)) == signature(
        await stored_observations(second.audit_id)
    )


async def test_viewport_facts_name_their_viewport() -> None:
    """A fact without its viewport cannot be acted on: 420 px wide only matters at 390."""
    report = await run_audit(URL, allow_private=True)
    rows = await stored_observations(report.audit_id)

    for row in rows:
        if row.tool in {"responsive", "occlusion", "contrast", "axe", "dom", "screenshot"}:
            assert row.viewport in VIEWPORTS, row.tool
        if row.tool == "http":
            assert row.viewport is None
