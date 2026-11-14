import asyncio
import uuid

import httpx
import pytest

from app.api.main import app

pytestmark = pytest.mark.integration

FIXTURE_URL = "http://localhost:8081/"
FINISHED = {"completed", "partial", "failed"}


async def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=120.0,
    )


async def wait_for_audit(http: httpx.AsyncClient, audit_id: str) -> dict[str, object]:
    """Poll the status endpoint until the background run reaches a terminal state."""
    deadline = asyncio.get_running_loop().time() + 180
    while True:
        response = await http.get(f"/audits/{audit_id}")
        if response.status_code == 200:
            body = response.json()
            if body["status"] in FINISHED:
                return body
        assert asyncio.get_running_loop().time() < deadline, f"audit {audit_id} never finished"
        await asyncio.sleep(0.2)


async def test_audit_runs_in_background_and_appears_in_the_list() -> None:
    async with await client() as http:
        created = await http.post("/audits", json={"url": FIXTURE_URL})
        assert created.status_code == 202, created.text
        body = created.json()
        assert body["status"] == "running"
        # The row may not exist in the first instant after the answer; the poll absorbs the
        # window instead of pretending the audit is born already.
        summary = await wait_for_audit(http, body["audit_id"])
        listed = await http.get("/audits", params={"limit": 50})
        report = await http.get(f"/audits/{body['audit_id']}/report")
        sites = await http.get("/sites")
        site = await http.get("/sites/localhost:8081")
        missing_site = await http.get("/sites/unknown.invalid")
    assert summary["status"] in {"completed", "partial"}
    assert summary["has_report"] is True
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


async def test_unknown_audit_returns_404() -> None:
    async with await client() as http:
        status = await http.get("/audits/00000000-0000-0000-0000-000000000000")
        report = await http.get("/audits/00000000-0000-0000-0000-000000000000/report")
    assert status.status_code == 404
    assert report.status_code == 404


async def test_malformed_audit_id_returns_404() -> None:
    async with await client() as http:
        report = await http.get("/audits/not-a-uuid/report")
    assert report.status_code == 404
