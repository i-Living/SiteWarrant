"""A sitemap run is a dispatch: bounded page audits queued, nothing of its own to report.

The row the operator submits has no findings and no report — the page rows it queues do. Keeping
those apart is what stops one defect from being counted twice in the site ledger, and it is why the
dispatch answers with `pages_count` and not with a merged report.
"""

import uuid

import pytest
from sqlalchemy import select

from app import lifecycle
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.models import Audit
from app.storage import repo
from app.worker import context_for, run_once
from tests.conftest import Route, Site

pytestmark = pytest.mark.integration

URL = "http://localhost:8081/"


def one_page(origin: str) -> dict[str, Route]:
    """A site with a page and no sitemap at all: the run has nothing to dispatch."""
    body = b'<!doctype html><html lang="en"><body><h1>one page</h1></body></html>'
    return {"/index.html": (200, {"Content-Type": "text/html; charset=utf-8"}, body)}


async def clear_queue() -> None:
    """A dispatch test claims the oldest row, so leftovers from other tests have to go first."""
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Audit).where(Audit.status.in_([lifecycle.QUEUED, lifecycle.RUNNING]))
            )
        ).scalars()
        for row in rows:
            row.status = lifecycle.CANCELLED
            row.error = "left over from another test"
        await session.commit()


async def enqueue_dispatch(url: str, pages_limit: int) -> uuid.UUID:
    async with session_scope() as session:
        return await repo.create_audit(
            session,
            site_url=url,
            agent_version="sha256:test",
            config={
                "agents": [],
                "scope": "sitemap",
                "pages_limit": pages_limit,
                "robots": "enforced",
            },
            status=lifecycle.QUEUED,
        )


async def queued_pages(dispatch_id: uuid.UUID) -> list[Audit]:
    async with session_scope() as session:
        return list(
            (
                await session.execute(
                    select(Audit).where(Audit.id != dispatch_id, Audit.status == lifecycle.QUEUED)
                )
            )
            .scalars()
            .all()
        )


async def cancel(rows: list[Audit]) -> None:
    async with session_scope() as session:
        for row in rows:
            stored = await session.get(Audit, row.id)
            if stored is not None and stored.status == lifecycle.QUEUED:
                stored.status = lifecycle.CANCELLED
                stored.error = "cancelled by the sitemap test"
        await session.commit()


async def test_the_dispatch_queues_a_bounded_page_audit_per_sitemap_entry() -> None:
    await clear_queue()
    dispatch_id = await enqueue_dispatch(URL, 3)

    assert await run_once(context_for(get_settings())) is True

    async with session_scope() as session:
        dispatch = await repo.get_audit(session, dispatch_id)
    children = await queued_pages(dispatch_id)
    try:
        assert dispatch is not None
        assert dispatch.status == lifecycle.COMPLETED
        assert dispatch.report_key is None, "a dispatch has no report of its own"
        assert dispatch.pages_count == 3
        # The submitted URL was included and the sitemap's own order filled the rest; the rows
        # themselves come back from the queue in no particular order.
        assert {row.site_url for row in children} == {
            "http://localhost:8081/",
            "http://localhost:8081/about.html",
            "http://localhost:8081/blog/",
        }
        assert all(row.config["scope"] == "page" for row in children)
        assert all(row.config["pages_limit"] == 1 for row in children)
        # robots.txt disallows /blocked.html and the sitemap names another host: neither is queued.
        queued = {row.site_url for row in children}
        assert "http://localhost:8081/blocked.html" not in queued
        assert not any("elsewhere.example" in url for url in queued)
    finally:
        await cancel(children)


async def test_the_site_root_sitemap_is_used_when_the_page_has_none() -> None:
    """`https://site/pricing` still walks `https://site/sitemap.xml`."""
    await clear_queue()
    dispatch_id = await enqueue_dispatch("http://localhost:8081/about.html", 3)

    assert await run_once(context_for(get_settings())) is True

    async with session_scope() as session:
        dispatch = await repo.get_audit(session, dispatch_id)
    children = await queued_pages(dispatch_id)
    try:
        assert dispatch is not None
        assert dispatch.status == lifecycle.COMPLETED
        assert {row.site_url for row in children} == {
            "http://localhost:8081/about.html",
            "http://localhost:8081/",
            "http://localhost:8081/blog/",
        }
    finally:
        await cancel(children)


@pytest.mark.parametrize("site", [one_page], indirect=True)
async def test_a_site_without_a_sitemap_fails_the_dispatch_instead_of_one_page(
    site: Site,
) -> None:
    """One page audited would present a fallback as the run the operator asked for."""
    await clear_queue()
    dispatch_id = await enqueue_dispatch(site.url("/index.html"), 3)

    assert await run_once(context_for(get_settings())) is True

    async with session_scope() as session:
        dispatch = await repo.get_audit(session, dispatch_id)

    assert dispatch is not None
    assert dispatch.status == lifecycle.FAILED
    assert "sitemap" in (dispatch.error or "")
    assert await queued_pages(dispatch_id) == [], "a failed dispatch queues nothing"
