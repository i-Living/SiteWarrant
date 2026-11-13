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
    priority: float = 0.0
    subject: str | None = None
    root_cause_id: str | None = None
    evidence: list[EvidenceOut]


class RootCauseOut(BaseModel):
    """Several findings that one fix is likely to close (docs/PLAN.md section 6).

    The grouping is deterministic; `summary` and `rationale` explain it, they do not decide it.
    """

    id: str
    kind: str
    anchor: str
    label: str = ""
    categories: list[str]
    summary: str
    rationale: str
    severity: Severity
    priority: float
    finding_ids: list[str]


class SummaryOut(BaseModel):
    pages_audited: int
    findings_total: int
    by_severity: dict[str, int]
    scores: dict[str, float]
    duration_ms: int
    observations_by_tool: dict[str, int]
    agents: list[AgentSummaryOut] = []
    root_causes: int = 0
    duplicates_removed: int = 0
    duplicate_rate: float = 0.0


class Report(BaseModel):
    audit_id: str
    site: str
    agent_version: str
    status: str
    generated_at: datetime
    summary: SummaryOut
    findings: list[FindingOut]
    root_causes: list[RootCauseOut] = []


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
    root_causes: Sequence[RootCauseOut] = (),
    duplicates_removed: int = 0,
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
            root_causes=len(root_causes),
            duplicates_removed=duplicates_removed,
            duplicate_rate=_duplicate_rate(findings, duplicates_removed),
        ),
        findings=list(findings),
        root_causes=list(root_causes),
    )


def _duplicate_rate(findings: Sequence[FindingOut], duplicates_removed: int) -> float:
    total = len(findings) + duplicates_removed
    return round(duplicates_removed / total, 4) if total else 0.0


def has_blocker(report: Report) -> bool:
    return any(finding.severity == "blocker" for finding in report.findings)


def exit_code_for(report: Report) -> int:
    """0 when the page is free of blockers, 1 when a blocker was proven."""
    return 1 if has_blocker(report) else 0
