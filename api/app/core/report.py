from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel

from app.rules.catalog import CATEGORIES, SEVERITY_WEIGHTS, Severity

SCORE_CAP = 40.0
SEVERITIES: tuple[Severity, ...] = ("blocker", "major", "minor", "info")


class EvidenceOut(BaseModel):
    kind: str
    observation_id: str
    excerpt: str | None = None


class ImpactOut(BaseModel):
    conversion: int
    seo: int
    ux: int


class AgentSummaryOut(BaseModel):
    """What one agent did. `status` other than ok is why the report says partial."""

    name: str
    status: str
    findings: int = 0
    rejected: int = 0
    tool_calls: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    error: str | None = None


class FindingOut(BaseModel):
    id: str
    rule_id: str
    category: str
    severity: Severity
    title: str
    summary: str
    suggested_fix: str
    impact: ImpactOut
    confidence: float
    agent: str
    page_url: str
    page_key: str
    criterion: str | None = None
    criterion_title: str | None = None
    evidence: list[EvidenceOut]


class SummaryOut(BaseModel):
    pages_audited: int
    findings_total: int
    by_severity: dict[str, int]
    scores: dict[str, float]
    duration_ms: int
    observations_by_tool: dict[str, int]
    agents: list[AgentSummaryOut] = []


class Report(BaseModel):
    audit_id: str
    site: str
    agent_version: str
    status: str
    generated_at: datetime
    summary: SummaryOut
    findings: list[FindingOut]


def direction_score(penalty: float, pages_audited: int) -> float:
    """Product-facing score from docs/PLAN.md section 4. Not a quality metric."""
    if pages_audited <= 0:
        return 0.0
    share = penalty / pages_audited
    return round(max(0.0, 100.0 * (1.0 - share / SCORE_CAP)), 1)


def build_report(
    *,
    audit_id: str,
    site: str,
    agent_version: str,
    status: str,
    findings: Sequence[FindingOut],
    pages_audited: int,
    duration_ms: int,
    measured_categories: set[str],
    observations_by_tool: dict[str, int],
    agents: Sequence[AgentSummaryOut] = (),
) -> Report:
    counts = Counter(finding.severity for finding in findings)
    by_severity = {severity: counts.get(severity, 0) for severity in SEVERITIES}
    scores: dict[str, float] = {}
    for category in CATEGORIES:
        if category not in measured_categories:
            continue
        penalty = sum(
            SEVERITY_WEIGHTS[finding.severity]
            for finding in findings
            if finding.category == category
        )
        scores[category] = direction_score(penalty, pages_audited)
    return Report(
        audit_id=audit_id,
        site=site,
        agent_version=agent_version,
        status=status,
        generated_at=datetime.now(UTC),
        summary=SummaryOut(
            pages_audited=pages_audited,
            findings_total=len(findings),
            by_severity=by_severity,
            scores=scores,
            duration_ms=duration_ms,
            observations_by_tool=observations_by_tool,
            agents=list(agents),
        ),
        findings=list(findings),
    )


def has_blocker(report: Report) -> bool:
    return any(finding.severity == "blocker" for finding in report.findings)


def exit_code_for(report: Report) -> int:
    """0 when the page is free of blockers, 1 when a blocker was proven."""
    return 1 if has_blocker(report) else 0
