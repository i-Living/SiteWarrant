import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.report import EvidenceOut, FindingOut, ImpactOut, Report, build_report
from app.core.urls import page_key
from app.core.version import compute_agent_version
from app.rules.catalog import RULES
from app.rules.engine import FindingDraft, NewObservation, draft_findings
from app.storage import repo
from app.tools.fetch import Capture, capture_page
from app.tools.robots import ensure_allowed


class CaptureFailed(RuntimeError):
    """The page answered with an error status, so there is nothing to audit."""


def build_observations(capture: Capture, viewport: str) -> list[NewObservation]:
    observations = [
        NewObservation(
            id=uuid.uuid4(),
            tool="dom",
            kind="dom_snapshot",
            viewport=viewport,
            payload=capture.dom.model_dump(),
        )
    ]
    for violation in capture.axe:
        observations.append(
            NewObservation(
                id=uuid.uuid4(),
                tool="axe",
                kind="axe_violation",
                rule_ref=violation.id,
                viewport=viewport,
                payload=violation.model_dump(),
            )
        )
    return observations


def measured_categories(tools_ran: set[str]) -> set[str]:
    """Only categories whose facts were actually collected may be scored."""
    return {rule.category for rule in RULES if rule.source in tools_ran}


def to_finding_out(
    finding_id: uuid.UUID, draft: FindingDraft, page_url: str, key: str
) -> FindingOut:
    return FindingOut(
        id=str(finding_id),
        rule_id=draft.rule_id,
        category=draft.category,
        severity=draft.severity,
        title=draft.title,
        summary=draft.summary,
        suggested_fix=draft.suggested_fix,
        impact=ImpactOut(
            conversion=draft.impact_conversion,
            seo=draft.impact_seo,
            ux=draft.impact_ux,
        ),
        confidence=draft.confidence,
        agent=draft.agent,
        page_url=page_url,
        page_key=key,
        evidence=[
            EvidenceOut(kind=item.kind, observation_id=item.observation_id, excerpt=item.excerpt)
            for item in draft.evidence
        ],
    )


def artifact_path(key: str) -> Path:
    root = get_settings().artifacts_dir.resolve()
    candidate = (root / key).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("artifact key escapes the artifacts directory")
    return candidate


def write_artifact(audit_id: uuid.UUID, name: str, text: str) -> str:
    key = f"audits/{audit_id}/{name}"
    target = artifact_path(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return key


def read_artifact(key: str) -> str:
    return artifact_path(key).read_text(encoding="utf-8")


async def run_audit(
    url: str, *, allow_private: bool = False, ignore_robots: bool = False
) -> Report:
    """Audit one page end to end: capture, facts, findings, stored report.

    Crawling, agents and root causes arrive in later phases; this is the P0 slice.
    """
    settings = get_settings()
    started = time.monotonic()
    allowed_private_hosts = settings.allowed_private_host_set
    if allow_private:
        audited_host = urlsplit(url).hostname
        if audited_host:
            allowed_private_hosts = allowed_private_hosts | {audited_host.lower()}
    agent_version = compute_agent_version(
        viewport=settings.viewport,
        page_timeout_ms=settings.page_timeout_ms,
        capture_timeout_ms=settings.capture_timeout_ms,
        user_agent=settings.user_agent,
    )
    async with session_scope() as session:
        audit_id = await repo.create_audit(
            session,
            site_url=url,
            agent_version=agent_version,
            config={
                "viewport": settings.viewport,
                "tools": ["axe", "dom_probe"],
                "pages_limit": 1,
                "robots": "ignored" if ignore_robots else "enforced",
            },
        )
        try:
            if not ignore_robots:
                await ensure_allowed(
                    url,
                    settings.user_agent,
                    allowed_private_hosts=allowed_private_hosts,
                )
            capture = await capture_page(
                url,
                settings,
                allowed_private_hosts=allowed_private_hosts,
            )
            if capture.status_code >= 400:
                raise CaptureFailed(f"{capture.url} answered with HTTP {capture.status_code}")
            key = page_key(capture.url)
            page_id = await repo.save_page(
                session,
                audit_id=audit_id,
                url=capture.url,
                key=key,
                status_code=capture.status_code,
                render_mode="browser",
            )
            html_key = write_artifact(audit_id, "page.html", capture.html)
            await repo.save_snapshot(
                session, page_id=page_id, viewport=settings.viewport, html_key=html_key
            )
            observations = build_observations(capture, settings.viewport)
            await repo.save_observations(session, page_id=page_id, observations=observations)
            drafts = draft_findings([observation.view() for observation in observations])
            stored = await repo.save_findings(
                session, audit_id=audit_id, page_id=page_id, drafts=drafts
            )
            findings = [
                to_finding_out(finding_id, draft, capture.url, key) for finding_id, draft in stored
            ]
            report = build_report(
                audit_id=str(audit_id),
                site=url,
                agent_version=agent_version,
                status="completed",
                findings=findings,
                pages_audited=1,
                duration_ms=int((time.monotonic() - started) * 1000),
                measured_categories=measured_categories({"axe", "dom"}),
            )
            report_key = write_artifact(audit_id, "report.json", report.model_dump_json(indent=2))
            await repo.finish_audit(
                session,
                audit_id=audit_id,
                status="completed",
                pages_count=1,
                report_key=report_key,
            )
            await session.commit()
            return report
        except Exception as error:
            await session.rollback()
            await repo.finish_audit(
                session,
                audit_id=audit_id,
                status="failed",
                pages_count=0,
                report_key=None,
                error=str(error)[:2000],
            )
            await session.commit()
            raise
