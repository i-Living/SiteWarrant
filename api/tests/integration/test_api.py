import httpx
import pytest

from app.api.main import app

pytestmark = pytest.mark.integration

FIXTURE_URL = "http://localhost:8081/"


async def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=120.0,
    )


async def test_health_reports_ok() -> None:
    async with await client() as http:
        response = await http.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_audit_then_fetch_report() -> None:
    async with await client() as http:
        created = await http.post("/audits", json={"url": FIXTURE_URL})
        assert created.status_code == 200, created.text
        body = created.json()
        report = await http.get(f"/audits/{body['audit_id']}/report")
    assert report.status_code == 200
    assert report.json()["audit_id"] == body["audit_id"]
    assert body["findings_total"] == report.json()["summary"]["findings_total"]


async def test_unknown_audit_returns_404() -> None:
    async with await client() as http:
        response = await http.get("/audits/00000000-0000-0000-0000-000000000000/report")
    assert response.status_code == 404


async def test_malformed_audit_id_returns_404() -> None:
    async with await client() as http:
        response = await http.get("/audits/not-a-uuid/report")
    assert response.status_code == 404
