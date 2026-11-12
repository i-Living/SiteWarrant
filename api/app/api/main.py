import json
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.audit import read_artifact, run_audit
from app.core.db import session_scope
from app.storage import repo


class AuditRequest(BaseModel):
    """A URL the caller wants audited.

    Deliberately no "allow private" switch: letting a request body relax the SSRF guard
    would let any caller scan the host's internal network. Private targets are permitted
    by deployment configuration (SITEWARRANT_ALLOW_PRIVATE_HOSTS), never per request.
    """

    url: str


class AuditCreated(BaseModel):
    audit_id: str
    findings_total: int
    by_severity: dict[str, int]


def create_app() -> FastAPI:
    api = FastAPI(title="SiteWarrant", version="0.1.0")

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/audits")
    async def create_audit(request: AuditRequest) -> AuditCreated:
        """Run one audit synchronously.

        The job queue arrives in P3; until then a request holds until the page is done,
        which is acceptable because P0 audits a single page.
        """
        report = await run_audit(request.url)
        return AuditCreated(
            audit_id=report.audit_id,
            findings_total=report.summary.findings_total,
            by_severity=report.summary.by_severity,
        )

    @api.get("/audits/{audit_id}/report")
    async def get_report(audit_id: str) -> JSONResponse:
        try:
            parsed = uuid.UUID(audit_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="audit not found") from error
        async with session_scope() as session:
            audit = await repo.get_audit(session, parsed)
            report_key = audit.report_key if audit is not None else None
        if report_key is None:
            raise HTTPException(status_code=404, detail="report not found")
        try:
            payload: Any = json.loads(read_artifact(report_key))
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return JSONResponse(content=payload)

    return api


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000)
