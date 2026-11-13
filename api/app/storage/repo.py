import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import (
    Audit,
    Finding,
    FindingEvidence,
    LlmCall,
    Observation,
    Page,
    Snapshot,
)
from app.core.models import RootCause as RootCauseRow
from app.core.report import RootCauseOut
from app.rules.engine import FindingDraft, NewObservation


async def create_audit(
    session: AsyncSession,
    *,
    site_url: str,
    agent_version: str,
    config: dict[str, Any],
) -> uuid.UUID:
    audit = Audit(
        site_url=site_url,
        status="running",
        agent_version=agent_version,
        config=config,
    )
    session.add(audit)
    await session.commit()
    return audit.id


async def save_page(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    url: str,
    key: str,
    status_code: int,
    render_mode: str,
) -> uuid.UUID:
    page = Page(
        audit_id=audit_id,
        url=url,
        page_key=key,
        status_code=status_code,
        render_mode=render_mode,
    )
    session.add(page)
    await session.flush()
    return page.id


async def save_snapshot(
    session: AsyncSession,
    *,
    page_id: uuid.UUID,
    viewport: str,
    html_key: str,
    dom_key: str | None = None,
    screenshot_key: str | None = None,
) -> None:
    session.add(
        Snapshot(
            page_id=page_id,
            viewport=viewport,
            html_key=html_key,
            dom_key=dom_key,
            screenshot_key=screenshot_key,
        )
    )


async def save_observations(
    session: AsyncSession,
    *,
    page_id: uuid.UUID,
    observations: Sequence[NewObservation],
) -> None:
    for item in observations:
        session.add(
            Observation(
                id=item.id,
                page_id=page_id,
                viewport=item.viewport,
                tool=item.tool,
                rule_ref=item.rule_ref,
                kind=item.kind,
                payload=item.payload,
            )
        )


async def save_findings(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    page_id: uuid.UUID,
    drafts: Sequence[FindingDraft],
) -> list[tuple[uuid.UUID, FindingDraft]]:
    stored: list[tuple[uuid.UUID, FindingDraft]] = []
    for draft in drafts:
        finding = Finding(
            audit_id=audit_id,
            page_id=page_id,
            rule_id=draft.rule_id,
            category=draft.category,
            severity=draft.severity,
            title=draft.title,
            summary=draft.summary,
            suggested_fix=draft.suggested_fix,
            impact_conversion=draft.impact_conversion,
            impact_seo=draft.impact_seo,
            impact_ux=draft.impact_ux,
            confidence=draft.confidence,
            agent=draft.agent,
            subject=draft.subject,
        )
        session.add(finding)
        await session.flush()
        for evidence in draft.evidence:
            session.add(
                FindingEvidence(
                    finding_id=finding.id,
                    observation_id=uuid.UUID(evidence.observation_id),
                    kind=evidence.kind,
                    excerpt=evidence.excerpt,
                )
            )
        stored.append((finding.id, draft))
    return stored


async def finish_audit(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    status: str,
    pages_count: int,
    report_key: str | None,
    error: str | None = None,
) -> None:
    audit = await session.get(Audit, audit_id)
    if audit is None:
        return
    audit.status = status
    audit.pages_count = pages_count
    audit.report_key = report_key
    audit.error = error
    audit.finished_at = datetime.now(UTC)


async def get_audit(session: AsyncSession, audit_id: uuid.UUID) -> Audit | None:
    result = await session.execute(select(Audit).where(Audit.id == audit_id))
    return result.scalar_one_or_none()


async def save_llm_calls(
    session: AsyncSession, *, audit_id: uuid.UUID, run: Any, model: str
) -> None:
    """One row per model call, from the per-call stats the runner kept."""
    for stat in run.calls:
        session.add(
            LlmCall(
                audit_id=audit_id,
                agent=run.name,
                model=model,
                tokens_in=stat.tokens_in,
                tokens_out=stat.tokens_out,
                latency_ms=stat.latency_ms,
            )
        )


async def add_audit_usage(
    session: AsyncSession, *, audit_id: uuid.UUID, tokens_in: int, tokens_out: int, llm_calls: int
) -> None:
    audit = await session.get(Audit, audit_id)
    if audit is None:
        return
    audit.tokens_in += tokens_in
    audit.tokens_out += tokens_out
    audit.llm_calls += llm_calls


async def save_root_causes(
    session: AsyncSession,
    *,
    audit_id: uuid.UUID,
    page_id: uuid.UUID,
    causes: Sequence[RootCauseOut],
) -> dict[str, uuid.UUID]:
    """Store the deterministic clusters and return report id -> row id."""
    stored: dict[str, uuid.UUID] = {}
    for cause in causes:
        row = RootCauseRow(
            audit_id=audit_id,
            page_id=page_id,
            cause_kind=cause.kind,
            anchor=cause.anchor,
            summary=cause.summary,
            rationale=cause.rationale,
            severity=cause.severity,
            priority=cause.priority,
            categories=list(cause.categories),
        )
        session.add(row)
        await session.flush()
        stored[cause.id] = row.id
    return stored


async def assign_root_causes(session: AsyncSession, *, mapping: dict[str, uuid.UUID]) -> None:
    """Point stored findings at their cluster. Unknown ids are ignored, not invented."""
    for finding_id, cause_id in mapping.items():
        finding = await session.get(Finding, uuid.UUID(finding_id))
        if finding is not None:
            finding.root_cause_id = cause_id
