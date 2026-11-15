import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from app import lifecycle
from app.api.main import app
from app.core.config import get_settings
from app.core.db import session_scope
from app.storage import repo
from app.worker import context_for, run_forever

pytestmark = pytest.mark.integration

FIXTURE_URL = "http://localhost:8081/"
FINISHED = {"completed", "partial", "failed", "cancelled"}


async def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=120.0,
    )


@pytest.fixture
async def worker() -> AsyncIterator[None]:
    """The real worker loop on this test's event loop: the API only ever writes the row."""
    settings = get_settings()
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_forever(context_for(settings), settings=settings, stop=stop),
        name="test-worker",
    )
    try:
        yield None
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=120)


async def wait_for_audit(http: httpx.AsyncClient, audit_id: str) -> dict[str, object]:
    """Poll the status endpoint until the worker reaches a terminal state."""
    deadline = asyncio.get_running_loop().time() + 180
    while True:
        response = await http.get(f"/audits/{audit_id}")
        if response.status_code == 200:
            body = response.json()
            if body["status"] in FINISHED:
                return body
        assert asyncio.get_running_loop().time() < deadline, f"audit {audit_id} never finished"
        await asyncio.sleep(0.2)


async def test_an_audit_is_queued_then_run_by_the_worker(worker: object) -> None:
    async with await client() as http:
        created = await http.post("/audits", json={"url": FIXTURE_URL, "force": True})
        assert created.status_code == 202, created.text
        body = created.json()
        # The row exists before the run: the caller gets an id it can poll at once.
        assert body["status"] == "queued"
        assert body["deduplicated"] is False
        queued = await http.get(f"/audits/{body['audit_id']}")
        assert queued.status_code == 200
        assert queued.json()["status"] in {"queued", "running"}
        summary = await wait_for_audit(http, body["audit_id"])
        listed = await http.get("/audits", params={"limit": 50})
        report = await http.get(f"/audits/{body['audit_id']}/report")
        sites = await http.get("/sites")
        site = await http.get("/sites/localhost:8081")
        missing_site = await http.get("/sites/unknown.invalid")
    assert summary["status"] in {"completed", "partial"}
    assert summary["has_report"] is True
    assert summary["stage"] is None, "a finished audit is not still on a stage"
    assert listed.status_code == 200
    rows = {row["audit_id"]: row for row in listed.json()}
    assert rows[body["audit_id"]]["site"] == FIXTURE_URL
    assert rows[body["audit_id"]]["has_report"] is True
    assert rows[body["audit_id"]]["findings_total"] == summary["findings_total"]
    assert report.status_code == 200
    assert report.json()["audit_id"] == body["audit_id"]
    assert body["audit_id"] == str(uuid.UUID(body["audit_id"]))
    assert summary["findings_total"] == report.json()["summary"]["findings_total"]
    by_severity = summary["by_severity"]
    assert isinstance(by_severity, dict)
    assert sum(by_severity.values()) == summary["findings_total"]
    assert by_severity["blocker"] >= 1
    assert isinstance(summary["duration_ms"], int)
    assert sites.status_code == 200
    assert "localhost:8081" in {row["host"] for row in sites.json()}
    assert site.status_code == 200
    site_body = site.json()
    assert site_body["summary"]["host"] == "localhost:8081"
    assert site_body["summary"]["pages"] >= 1
    assert any(page["page"] == "/" for page in site_body["pages"])
    assert missing_site.status_code == 404


async def test_a_repeated_submission_reuses_the_audit_in_the_window() -> None:
    """No worker runs here, so the row stays queued and the second answer names it."""
    async with await client() as http:
        first = await http.post("/audits", json={"url": FIXTURE_URL, "force": True})
        second = await http.post("/audits", json={"url": FIXTURE_URL})
        forced = await http.post("/audits", json={"url": FIXTURE_URL, "force": True})
        cancelled = await http.post(f"/audits/{second.json()['audit_id']}/cancel")
        after = await http.get(f"/audits/{second.json()['audit_id']}")
    assert second.json()["audit_id"] == first.json()["audit_id"]
    assert second.json()["deduplicated"] is True
    assert forced.json()["audit_id"] != first.json()["audit_id"]
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert after.json()["status"] == "cancelled"


async def test_feedback_is_recorded_against_a_stored_finding(worker: object) -> None:
    async with await client() as http:
        created = await http.post("/audits", json={"url": FIXTURE_URL, "force": True})
        summary = await wait_for_audit(http, created.json()["audit_id"])
        report = (await http.get(f"/audits/{created.json()['audit_id']}/report")).json()
        finding_id = report["findings"][0]["id"]
        posted = await http.post(
            f"/findings/{finding_id}/feedback",
            json={"verdict": "confirmed", "note": "seen on a phone"},
        )
        listed = await http.get(f"/findings/{finding_id}/feedback")
        unknown = await http.post(
            f"/findings/{uuid.uuid4()}/feedback", json={"verdict": "confirmed"}
        )
        bad = await http.post(f"/findings/{finding_id}/feedback", json={"verdict": "maybe"})
    assert summary["has_report"] is True
    assert posted.status_code == 201, posted.text
    assert posted.json()["verdict"] == "confirmed"
    assert posted.json()["source"] == "operator"
    assert [row["id"] for row in listed.json()] == [posted.json()["id"]]
    # The finding is stored once; the verdict is a separate record.
    assert report["findings"][0]["summary"]
    assert unknown.status_code == 404
    assert bad.status_code == 422


async def test_two_stored_audits_compare(worker: object) -> None:
    async with await client() as http:
        first = (await http.post("/audits", json={"url": FIXTURE_URL, "force": True})).json()
        await wait_for_audit(http, first["audit_id"])
        second = (await http.post("/audits", json={"url": FIXTURE_URL, "force": True})).json()
        await wait_for_audit(http, second["audit_id"])
        compared = await http.get(
            f"/audits/{second['audit_id']}/compare", params={"against": first["audit_id"]}
        )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    assert body["comparable"] is True
    assert body["reasons"] == []
    # The same page audited twice with the same instrument: nothing closed, nothing new.
    assert body["closed"] == []
    assert body["new"] == []
    assert body["remaining"], "the fixture's findings are still there on the second run"
    assert body["causes"], "the fixture's banner is a root cause and groups its symptoms"


async def test_a_failed_audit_does_not_swallow_the_retry() -> None:
    """Dedupe answers with work in flight, not with yesterday's failure."""
    url = f"http://retry-{uuid.uuid4().hex[:8]}.invalid/"
    async with session_scope() as session:
        failed = await repo.create_audit(
            session,
            site_url=url,
            agent_version="sha256:test",
            config={"agents": []},
            status=lifecycle.RUNNING,
        )
    async with session_scope() as session:
        await repo.finish_audit(
            session,
            audit_id=failed,
            status=lifecycle.FAILED,
            pages_count=0,
            report_key=None,
            error="boom",
        )
        await session.commit()
    async with await client() as http:
        created = await http.post("/audits", json={"url": url})
    assert created.status_code == 202
    assert created.json()["audit_id"] != str(failed)
    assert created.json()["deduplicated"] is False


async def test_schedules_are_created_edited_and_disabled() -> None:
    url = f"http://schedule-api-{uuid.uuid4().hex[:8]}.invalid/"
    async with await client() as http:
        created = await http.post(
            "/schedules", json={"url": url, "every_minutes": 60, "agents": ["a11y"]}
        )
        edited = await http.post("/schedules", json={"url": url, "every_minutes": 120})
        listed = await http.get("/schedules")
        schedule_id = created.json()["id"]
        off = await http.patch(f"/schedules/{schedule_id}", json={"enabled": False})
        too_often = await http.post("/schedules", json={"url": url, "every_minutes": 1})
        unknown = await http.patch(f"/schedules/{uuid.uuid4()}", json={"enabled": True})
    assert created.status_code == 201, created.text
    assert created.json()["agents"] == ["a11y"]
    # One schedule per URL: the second POST edits rather than duplicates.
    assert edited.status_code == 200
    assert edited.json()["id"] == schedule_id
    assert edited.json()["every_minutes"] == 120
    assert schedule_id in {row["id"] for row in listed.json()}
    assert off.status_code == 200
    assert off.json()["enabled"] is False
    assert too_often.status_code == 422
    assert unknown.status_code == 404


async def test_unknown_audit_returns_404() -> None:
    async with await client() as http:
        status = await http.get("/audits/00000000-0000-0000-0000-000000000000")
        report = await http.get("/audits/00000000-0000-0000-0000-000000000000/report")
        compare = await http.get(
            "/audits/00000000-0000-0000-0000-000000000000/compare",
            params={"against": str(uuid.uuid4())},
        )
    assert status.status_code == 404
    assert report.status_code == 404
    assert compare.status_code == 404


async def test_malformed_audit_id_returns_404() -> None:
    async with await client() as http:
        report = await http.get("/audits/not-a-uuid/report")
    assert report.status_code == 404
