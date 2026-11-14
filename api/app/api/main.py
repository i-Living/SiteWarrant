import asyncio
import logging
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel

from app.audit import read_artifact, run_audit
from app.core.db import session_scope
from app.core.models import Audit
from app.core.report import SEVERITIES, Report
from app.storage import repo

logger = logging.getLogger(__name__)


class AuditRequest(BaseModel):
    """A URL the caller wants audited.

    Deliberately no "allow private" switch: letting a request body relax the SSRF guard
    would let any caller scan the host's internal network. Private targets are permitted
    by deployment configuration (SITEWARRANT_ALLOW_PRIVATE_HOSTS), never per request.
    """

    url: str


class AuditAccepted(BaseModel):
    """The audit exists as soon as the row is written; the run continues without the caller."""

    audit_id: str
    status: str


class AuditSummary(BaseModel):
    """One row of the audit list: enough for the progress page and the main page.

    `by_severity` comes from the stored report, so the list shows the same counts the
    report does. A missing or unreadable artifact leaves them None instead of zero.
    """

    audit_id: str
    site: str
    status: str
    pages_count: int
    findings_total: int | None
    by_severity: dict[str, int] | None
    duration_ms: int | None
    has_report: bool
    started_at: datetime
    finished_at: datetime | None
    error: str | None


def stored_report_summary(
    report_key: str | None,
) -> tuple[int, dict[str, int], int] | None:
    """The stored report's (finding count, severity counts, duration), or None.

    The row does not carry the summary, and counting `findings` rows would count the
    duplicates the chief layer removed. The artifact is the number the report shows.
    """
    if report_key is None:
        return None
    try:
        report = Report.model_validate_json(read_artifact(report_key))
    except (OSError, ValueError):
        return None
    summary = report.summary
    return summary.findings_total, summary.by_severity, summary.duration_ms


def audit_summary(audit: Audit) -> AuditSummary:
    stored = stored_report_summary(audit.report_key)
    return AuditSummary(
        audit_id=str(audit.id),
        site=audit.site_url,
        status=audit.status,
        pages_count=audit.pages_count,
        findings_total=None if stored is None else stored[0],
        by_severity=None if stored is None else stored[1],
        duration_ms=None if stored is None else stored[2],
        has_report=audit.report_key is not None,
        started_at=audit.started_at,
        finished_at=audit.finished_at,
        error=audit.error,
    )


class PageSummary(BaseModel):
    """One page of a site: the newest audit of that path and how many runs it has."""

    page: str
    url: str
    audit_id: str
    status: str
    findings_total: int | None
    by_severity: dict[str, int] | None
    duration_ms: int | None
    has_report: bool
    runs: int
    running: int
    started_at: datetime
    finished_at: datetime | None
    error: str | None


class SiteSummary(BaseModel):
    """A host rolled up from its pages: the row the main page shows."""

    host: str
    pages: int
    measured_pages: int
    findings_total: int | None
    by_severity: dict[str, int] | None
    runs: int
    running: int
    failed: int
    last_activity: datetime


class SiteDetail(BaseModel):
    summary: SiteSummary
    pages: list[PageSummary]


def site_host(url: str) -> str:
    """The site a URL belongs to: host plus a non-default port, lowercased.

    An explicit `:443` on https (or `:80` on http) is the same site as the bare host; a
    non-default port stays because two local servers are two sites. `www.` is not stripped:
    `docs.example.com` and `www.example.com` are separate hosts with separate reports, and
    merging them would invent a site nobody audited.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    default_port = {"http": 80, "https": 443}.get(parts.scheme.lower())
    if port and port != default_port:
        return f"{host}:{port}"
    return host or url


def site_path(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "/"
    if not parts.hostname:
        return "/"
    path = parts.path.rstrip("/")
    return path or "/"


def url_rows(
    latest: Sequence[Audit], counts: Sequence[tuple[str, int]]
) -> list[tuple[Audit, int, int]]:
    """Pair each URL's newest audit with its run count and whether it is in flight.

    In-flight comes from the newest row, not from a count of older rows: a page that was
    re-audited successfully is not running just because an older process left a row behind.
    """
    totals = {url: runs for url, runs in counts}
    rows: list[tuple[Audit, int, int]] = []
    for audit in latest:
        rows.append(
            (
                audit,
                totals.get(audit.site_url, 1),
                1 if audit.status == "running" else 0,
            )
        )
    return rows


def page_summaries(rows: Sequence[tuple[Audit, int, int]]) -> list[PageSummary]:
    """One row per page, merging the URL variants of one path.

    The repository returns the newest audit per exact URL; `/path` and `/path/` (or a
    query-string variant) are one page here, so their runs add up and the newest audit is
    the result shown.
    """
    newest: dict[tuple[str, str], Audit] = {}
    runs: Counter[tuple[str, str]] = Counter()
    running: Counter[tuple[str, str]] = Counter()
    for audit, total, in_flight in rows:
        key = (site_host(audit.site_url), site_path(audit.site_url))
        runs[key] += total
        running[key] += in_flight
        current = newest.get(key)
        if current is None or audit.started_at > current.started_at:
            newest[key] = audit

    pages: list[PageSummary] = []
    for key, audit in newest.items():
        stored = stored_report_summary(audit.report_key)
        pages.append(
            PageSummary(
                page=key[1],
                url=audit.site_url,
                audit_id=str(audit.id),
                status=audit.status,
                findings_total=None if stored is None else stored[0],
                by_severity=None if stored is None else stored[1],
                duration_ms=None if stored is None else stored[2],
                has_report=audit.report_key is not None,
                runs=runs[key],
                running=running[key],
                started_at=audit.started_at,
                finished_at=audit.finished_at,
                error=audit.error,
            )
        )
    return pages


def site_rollup(
    host: str, rows: Sequence[tuple[Audit, int, int]]
) -> tuple[SiteSummary, list[PageSummary]]:
    """Aggregate one host's page rows into a site row.

    A page whose stored report cannot be read, or a site with no readable report at all,
    makes the site total None rather than a smaller number: an undercount would look like
    a cleaner site, and zero with nothing measured is not zero findings.
    """
    pages = page_summaries(rows)
    measured = sum(1 for page in pages if page.has_report)
    by_severity: dict[str, int] = {severity: 0 for severity in SEVERITIES}
    findings = 0
    unreadable = False
    for page in pages:
        if page.findings_total is None:
            unreadable = unreadable or page.has_report
            continue
        findings += page.findings_total
        for severity, count in (page.by_severity or {}).items():
            by_severity[severity] = by_severity.get(severity, 0) + count

    # A site with no readable report has no measured finding count: zero would read as a
    # clean site, and nothing was measured there.
    has_measurement = measured > 0 and not unreadable
    summary = SiteSummary(
        host=host,
        pages=len(pages),
        measured_pages=measured,
        findings_total=findings if has_measurement else None,
        by_severity=by_severity if has_measurement else None,
        runs=sum(page.runs for page in pages),
        running=sum(page.running for page in pages),
        failed=sum(1 for page in pages if page.status == "failed"),
        last_activity=max(page.started_at for page in pages),
    )
    return summary, pages


async def load_site_rows() -> list[tuple[Audit, int, int]]:
    """The newest audit per URL and its run counts, for the site views.

    The API transfers one row per URL (pages, not runs) and the database does the grouping;
    the report artifacts are still read one per page, which is the price of the numbers
    matching the stored report.
    """
    async with session_scope() as session:
        latest = await repo.latest_audit_per_url(session)
        counts = await repo.audit_counts_per_url(session)
    return url_rows(latest, counts)


def create_app() -> FastAPI:
    api = FastAPI(title="SiteWarrant", version="0.1.0")
    # A task that nobody holds a reference to may be collected mid-run; the set is the
    # reference, and the done callback keeps it from growing.
    tasks: set[asyncio.Task[None]] = set()

    async def audit_in_background(audit_id: uuid.UUID, url: str) -> None:
        try:
            await run_audit(url, audit_id=audit_id)
        except Exception:
            # finish_audit already stored the message on the row; logging here keeps the
            # exception from disappearing as "Task exception was never retrieved".
            logger.exception("audit %s failed", audit_id)

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/audits", response_model=AuditAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def create_audit(request: AuditRequest) -> AuditAccepted:
        """Start one audit and answer before it runs.

        An audit takes tens of seconds; holding the request for it left the browser with
        nothing to show, so the run happens in this process instead. A restart loses the
        task and leaves the row `running` — the residual a real worker would close.
        """
        audit_id = uuid.uuid4()
        task = asyncio.create_task(audit_in_background(audit_id, request.url))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return AuditAccepted(audit_id=str(audit_id), status="running")

    @api.get("/audits", response_model=list[AuditSummary])
    async def list_audits(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[AuditSummary]:
        """Recent audits, newest first, for the progress page and the main page."""
        async with session_scope() as session:
            audits = await repo.list_audits(session, limit=limit)
        return [audit_summary(audit) for audit in audits]

    @api.get("/audits/{audit_id}", response_model=AuditSummary)
    async def get_audit(audit_id: str) -> AuditSummary:
        """One audit's state, so a progress page can follow a submission by id."""
        try:
            parsed = uuid.UUID(audit_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="audit not found") from error
        async with session_scope() as session:
            audit = await repo.get_audit(session, parsed)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        return audit_summary(audit)

    @api.get("/sites", response_model=list[SiteSummary])
    async def list_sites() -> list[SiteSummary]:
        """Every host, rolled up from its pages; newest activity first."""
        rows = await load_site_rows()
        grouped: dict[str, list[tuple[Audit, int, int]]] = defaultdict(list)
        for row in rows:
            grouped[site_host(row[0].site_url)].append(row)
        summaries = [site_rollup(host, site_rows)[0] for host, site_rows in grouped.items()]
        return sorted(summaries, key=lambda item: item.last_activity, reverse=True)

    @api.get("/sites/{host}", response_model=SiteDetail)
    async def get_site(host: str) -> SiteDetail:
        """One host's pages, each showing its latest result."""
        requested = host.lower()
        rows = [row for row in await load_site_rows() if site_host(row[0].site_url) == requested]
        if not rows:
            raise HTTPException(status_code=404, detail="site not found")
        summary, pages = site_rollup(requested, rows)
        return SiteDetail(summary=summary, pages=pages)

    @api.get("/audits/{audit_id}/report", response_model=Report)
    async def get_report(audit_id: str) -> Report:
        """Return the stored report, validated against the report contract.

        The artifact on disk is the source of truth; parsing it through the model means a
        corrupted or outdated artifact fails loudly here instead of reaching a client.
        """
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
            return Report.model_validate_json(read_artifact(report_key))
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    return api


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("app.api.main:app", host="127.0.0.1", port=8000)
