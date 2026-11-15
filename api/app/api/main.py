import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app import lifecycle
from app.agents.specs import parse_agent_names
from app.audit import audit_config, current_agent_version, read_artifact
from app.compare import CauseDelta, Comparison, compare_reports
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.models import Audit, AuditSchedule, FindingFeedback
from app.core.report import SEVERITIES, Report
from app.storage import repo


class AuditRequest(BaseModel):
    """A URL the caller wants audited.

    Deliberately no "allow private" switch: letting a request body relax the SSRF guard
    would let any caller scan the host's internal network. Private targets are permitted
    by deployment configuration (SITEWARRANT_ALLOW_PRIVATE_HOSTS), never per request.

    `force` asks for a new run even when the same URL was submitted moments ago; without it a
    repeated submission inside the dedupe window answers with the audit already in flight.
    """

    url: str
    force: bool = False


class AuditAccepted(BaseModel):
    """The audit exists as soon as the row is written; the run continues without the caller."""

    audit_id: str
    status: str
    deduplicated: bool = False


class AuditSummary(BaseModel):
    """One row of the audit list: enough for the progress page and the main page.

    `by_severity` comes from the stored report, so the list shows the same counts the
    report does. A missing or unreadable artifact leaves them None instead of zero.
    """

    audit_id: str
    site: str
    status: str
    # The stage inside `running`, written by the worker; None for anything else.
    stage: str | None = None
    cancel_requested: bool = False
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
        stage=audit.stage,
        cancel_requested=audit.cancel_requested,
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


class DeltaOut(BaseModel):
    """One finding in a comparison: a rule, a page and the subject that tells two apart."""

    rule_id: str
    page_url: str
    severity: str
    subject: str = ""


class CauseDeltaOut(BaseModel):
    anchor: str
    page: str
    label: str
    closed: int
    new: int
    remaining: int


class ComparisonOut(BaseModel):
    before: str
    after: str
    before_version: str
    after_version: str
    comparable: bool
    reasons: list[str] = []
    notes: list[str] = []
    closed: list[DeltaOut] = []
    remaining: list[DeltaOut] = []
    new: list[DeltaOut] = []
    causes: list[CauseDeltaOut] = []

    @classmethod
    def from_comparison(cls, comparison: Comparison) -> "ComparisonOut":
        def delta(item: Any) -> DeltaOut:
            return DeltaOut(
                rule_id=item.rule_id,
                page_url=item.page_url,
                severity=item.severity,
                subject=item.subject,
            )

        def cause(item: CauseDelta) -> CauseDeltaOut:
            return CauseDeltaOut(
                anchor=item.anchor,
                page=item.page,
                label=item.label,
                closed=item.closed,
                new=item.new,
                remaining=item.remaining,
            )

        return cls(
            before=comparison.before,
            after=comparison.after,
            before_version=comparison.before_version,
            after_version=comparison.after_version,
            comparable=comparison.comparable,
            reasons=comparison.reasons,
            notes=comparison.notes,
            closed=[delta(item) for item in comparison.closed],
            remaining=[delta(item) for item in comparison.remaining],
            new=[delta(item) for item in comparison.new],
            causes=[cause(item) for item in comparison.causes],
        )


class FeedbackRequest(BaseModel):
    verdict: Literal["confirmed", "false_positive", "fixed", "irrelevant"]
    note: str | None = None
    source: str = "operator"


class FeedbackOut(BaseModel):
    id: str
    finding_id: str
    verdict: str
    source: str
    note: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: FindingFeedback) -> "FeedbackOut":
        return cls(
            id=str(row.id),
            finding_id=str(row.finding_id),
            verdict=row.verdict,
            source=row.source,
            note=row.note,
            created_at=row.created_at,
        )


MIN_SCHEDULE_MINUTES = 15


class ScheduleRequest(BaseModel):
    """A page the worker should audit on a rhythm."""

    url: str
    every_minutes: int = Field(default=1440, ge=MIN_SCHEDULE_MINUTES, le=10_080)
    agents: list[str] = []


class SchedulePatch(BaseModel):
    enabled: bool


class ScheduleOut(BaseModel):
    id: str
    site_url: str
    every_minutes: int
    agents: list[str]
    enabled: bool
    next_run_at: datetime
    last_audit_id: str | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: AuditSchedule) -> "ScheduleOut":
        return cls(
            id=str(row.id),
            site_url=row.site_url,
            every_minutes=row.every_minutes,
            agents=list(row.agents),
            enabled=row.enabled,
            next_run_at=row.next_run_at,
            last_audit_id=None if row.last_audit_id is None else str(row.last_audit_id),
            created_at=row.created_at,
        )


def parse_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=f"{what} not found") from error


async def load_report(audit_id: str) -> Report:
    """The stored report of one audit, or the HTTP answer that says why there is none."""
    parsed = parse_uuid(audit_id, "audit")
    async with session_scope() as session:
        audit = await repo.get_audit(session, parsed)
        report_key = audit.report_key if audit is not None else None
    if report_key is None:
        raise HTTPException(status_code=404, detail="report not found")
    try:
        return Report.model_validate_json(read_artifact(report_key))
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


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
                1 if audit.status in lifecycle.IN_FLIGHT else 0,
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

    @api.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.post("/audits", response_model=AuditAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def create_audit(request: AuditRequest) -> AuditAccepted:
        """Queue one audit and answer before it runs.

        The row is written here, not by the worker: the caller gets an id it can poll at once,
        and a restart of either process loses the run, not the task. Nothing executes in this
        process — `sitewarrant-worker` claims the row under a lease.

        The duplicate check is a courtesy, not a lock: two requests that arrive in the same
        instant can both find nothing and write two rows. A window is not an index.
        """
        settings = get_settings()
        async with session_scope() as session:
            if not request.force:
                existing = await repo.find_recent_duplicate(
                    session,
                    site_url=request.url,
                    agents=(),
                    window_s=settings.audit_dedupe_window_s,
                )
                if existing is not None:
                    return AuditAccepted(
                        audit_id=str(existing.id),
                        status=existing.status,
                        deduplicated=True,
                    )
            audit_id = await repo.create_audit(
                session,
                site_url=request.url,
                agent_version=current_agent_version(settings),
                config=audit_config(settings, agents=(), ignore_robots=False),
                status=lifecycle.QUEUED,
                owner_id=settings.owner_id,
            )
        return AuditAccepted(audit_id=str(audit_id), status=lifecycle.QUEUED)

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

    @api.post("/audits/{audit_id}/cancel", response_model=AuditSummary)
    async def cancel_audit(audit_id: str) -> AuditSummary:
        """Stop a queued audit now, or ask a running one to stop at its next stage boundary."""
        try:
            parsed = uuid.UUID(audit_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="audit not found") from error
        async with session_scope() as session:
            audit = await repo.request_cancel(session, parsed)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        return audit_summary(audit)

    @api.get("/audits/{audit_id}/compare", response_model=ComparisonOut)
    async def compare_audit(audit_id: str, against: str = Query(...)) -> ComparisonOut:
        """Two stored reports of one site: closed, remaining, new, and the causes behind them.

        A pair that is not a comparison (another site, no shared page) still answers, with
        `comparable: false` and the reason — hiding the rows would look like an empty diff.
        """
        before = await load_report(against)
        after = await load_report(audit_id)
        return ComparisonOut.from_comparison(compare_reports(before, after))

    @api.get("/findings/{finding_id}/feedback", response_model=list[FeedbackOut])
    async def list_finding_feedback(finding_id: str) -> list[FeedbackOut]:
        parsed = parse_uuid(finding_id, "finding")
        async with session_scope() as session:
            if not await repo.finding_exists(session, parsed):
                raise HTTPException(status_code=404, detail="finding not found")
            rows = await repo.list_feedback(session, parsed)
        return [FeedbackOut.from_row(row) for row in rows]

    @api.post(
        "/findings/{finding_id}/feedback",
        response_model=FeedbackOut,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_finding_feedback(finding_id: str, request: FeedbackRequest) -> FeedbackOut:
        """Record a reader's verdict. The finding itself is never edited."""
        parsed = parse_uuid(finding_id, "finding")
        async with session_scope() as session:
            if not await repo.finding_exists(session, parsed):
                raise HTTPException(status_code=404, detail="finding not found")
            row = await repo.add_feedback(
                session,
                finding_id=parsed,
                verdict=request.verdict,
                source=request.source,
                note=request.note,
            )
        return FeedbackOut.from_row(row)

    @api.get("/schedules", response_model=list[ScheduleOut])
    async def list_schedules() -> list[ScheduleOut]:
        """Every schedule, enabled or not: a disabled one is history, not a deletion."""
        async with session_scope() as session:
            rows = await repo.list_schedules(session)
        return [ScheduleOut.from_row(row) for row in rows]

    @api.post("/schedules", response_model=ScheduleOut)
    async def create_schedule(request: ScheduleRequest, response: Response) -> ScheduleOut:
        """Create or edit the one schedule for a URL; the first run is one interval out."""
        settings = get_settings()
        try:
            agents = parse_agent_names(",".join(request.agents)) if request.agents else []
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        async with session_scope() as session:
            row, created = await repo.upsert_schedule(
                session,
                site_url=request.url,
                every_minutes=request.every_minutes,
                agents=agents,
                owner_id=settings.owner_id,
            )
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return ScheduleOut.from_row(row)

    @api.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
    async def patch_schedule(schedule_id: str, request: SchedulePatch) -> ScheduleOut:
        """Turn a schedule off or back on. Re-enabling waits one interval, never a backlog."""
        parsed = parse_uuid(schedule_id, "schedule")
        async with session_scope() as session:
            row = await repo.set_schedule_enabled(session, parsed, request.enabled)
        if row is None:
            raise HTTPException(status_code=404, detail="schedule not found")
        return ScheduleOut.from_row(row)

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
