import asyncio
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from app.agents.orchestrator import observation_index, run_agents
from app.agents.specs import spec_for
from app.agents.validator import validate
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.report import (
    AgentSummaryOut,
    EvidenceOut,
    FindingOut,
    ImpactOut,
    Report,
    build_report,
)
from app.core.urls import page_key
from app.core.version import AUDIT_TOOLS, compute_agent_version
from app.rules import corpus
from app.rules.catalog import RULES
from app.rules.engine import FindingDraft, NewObservation, draft_findings
from app.storage import repo
from app.tools import http_probe
from app.tools.fetch import PageCapture, ViewportCapture, capture_page
from app.tools.http_probe import SECURITY_HEADERS, HttpFacts
from app.tools.robots import ensure_allowed, robots_hop_check

MEASURED_TOOLS = {"axe", "dom"}


class CaptureFailed(RuntimeError):
    """The page answered with an error status, so there is nothing to audit."""


class ProbeTimeout(RuntimeError):
    """The HTTP probe did not finish inside its budget.

    httpx applies its timeout to each read, not to the request: a server that drips a byte
    before every read timeout keeps a stream open indefinitely. The aggregate deadline is
    what bounds the probe.
    """


def http_observations(facts: HttpFacts) -> list[NewObservation]:
    """Header and redirect facts. Independent of the viewport, so viewport stays None."""
    observations = [
        NewObservation(
            id=uuid.uuid4(),
            tool="http",
            kind="http_status",
            payload={
                "url": facts.url,
                "status": facts.status_code,
                "content_type": facts.content_type,
            },
        ),
        NewObservation(
            id=uuid.uuid4(),
            tool="http",
            kind="redirect_chain",
            payload={"redirects": facts.redirects, "hops": len(facts.redirects)},
        ),
    ]
    for name in SECURITY_HEADERS:
        value = facts.header(name)
        observations.append(
            NewObservation(
                id=uuid.uuid4(),
                tool="http",
                kind="security_header",
                rule_ref=name,
                payload={"name": name, "present": value is not None, "value": value},
            )
        )
    return observations


def viewport_observations(
    capture: ViewportCapture, *, html_key: str, dom_key: str, screenshot_key: str
) -> list[NewObservation]:
    """Every channel reports that it ran, even when it found nothing.

    A channel with no observation is indistinguishable from a channel that never executed,
    and the report scores only the categories whose tools produced facts.
    """
    viewport = capture.viewport
    observations = [
        NewObservation(
            id=uuid.uuid4(),
            tool="dom",
            kind="dom_snapshot",
            viewport=viewport,
            payload=capture.dom.model_dump(),
        ),
        NewObservation(
            id=uuid.uuid4(),
            tool="axe",
            kind="axe_run",
            viewport=viewport,
            payload={"violations": len(capture.axe)},
        ),
        NewObservation(
            id=uuid.uuid4(),
            tool="contrast",
            kind="contrast_run",
            viewport=viewport,
            payload={
                "checked": capture.contrast.checked,
                "violations": len(capture.contrast.violations),
            },
        ),
        NewObservation(
            id=uuid.uuid4(),
            tool="responsive",
            kind="responsive_report",
            viewport=viewport,
            payload=capture.responsive.model_dump(),
        ),
        NewObservation(
            id=uuid.uuid4(),
            tool="occlusion",
            kind="occlusion_hits",
            viewport=viewport,
            payload={
                "count": len(capture.occlusion),
                "hits": [hit.model_dump() for hit in capture.occlusion],
            },
        ),
        NewObservation(
            id=uuid.uuid4(),
            tool="performance",
            kind="performance_facts",
            viewport=viewport,
            payload=capture.performance.model_dump(),
        ),
        NewObservation(
            id=uuid.uuid4(),
            tool="screenshot",
            kind="screenshot",
            viewport=viewport,
            payload={
                "key": screenshot_key,
                "html_key": html_key,
                "dom_key": dom_key,
                "width": capture.screenshot.width,
                "height": capture.screenshot.height,
                "clipped": capture.screenshot.clipped,
            },
        ),
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
    for contrast_violation in capture.contrast.violations:
        observations.append(
            NewObservation(
                id=uuid.uuid4(),
                tool="contrast",
                kind="contrast_violation",
                rule_ref="contrast",
                viewport=viewport,
                payload=contrast_violation.model_dump(),
            )
        )
    return observations


def measured_categories(tools_ran: set[str]) -> set[str]:
    """Only categories whose facts were actually collected may be scored."""
    return {rule.category for rule in RULES if rule.source in tools_ran}


def to_finding_out(
    finding_id: uuid.UUID, draft: FindingDraft, page_url: str, key: str
) -> FindingOut:
    criterion = corpus.claim_by_id(draft.rule_id)
    criterion_entry = (
        corpus.criterion_by_id(criterion.wcag) if criterion and criterion.wcag else None
    )
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
        criterion=criterion_entry.id if criterion_entry else None,
        criterion_title=criterion_entry.title if criterion_entry else None,
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


def write_binary_artifact(audit_id: uuid.UUID, name: str, data: bytes) -> str:
    key = f"audits/{audit_id}/{name}"
    target = artifact_path(key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return key


def read_artifact(key: str) -> str:
    return artifact_path(key).read_text(encoding="utf-8")


def store_artifacts(
    capture: PageCapture, audit_id: uuid.UUID
) -> tuple[str, list[tuple[str, str, str, ViewportCapture]]]:
    """Write the page's artifacts and return its key plus per-viewport keys."""
    key = page_key(capture.url)
    stored: list[tuple[str, str, str, ViewportCapture]] = []
    for viewport_capture in capture.viewports:
        prefix = f"{key}/{viewport_capture.viewport}"
        html_key = write_artifact(audit_id, f"{prefix}.html", viewport_capture.html)
        dom_key = write_artifact(
            audit_id,
            f"{prefix}.dom.json",
            viewport_capture.dom.model_dump_json(indent=2),
        )
        screenshot_key = write_binary_artifact(
            audit_id, f"{prefix}.png", viewport_capture.screenshot.png
        )
        stored.append((html_key, dom_key, screenshot_key, viewport_capture))
    return key, stored


async def run_audit(
    url: str,
    *,
    allow_private: bool = False,
    ignore_robots: bool = False,
    agents: Sequence[str] = (),
) -> Report:
    """Audit one page at every configured viewport: facts first, findings from facts.

    Agents and root causes arrive in later phases; this is the deterministic fact layer.
    """
    settings = get_settings()
    started = time.monotonic()
    allowed_private_hosts = settings.allowed_private_host_set
    if allow_private:
        audited_host = urlsplit(url).hostname
        if audited_host:
            allowed_private_hosts = allowed_private_hosts | {audited_host.lower()}
    viewports = settings.viewport_list
    agent_version = compute_agent_version(
        viewports=viewports,
        page_timeout_ms=settings.page_timeout_ms,
        capture_timeout_ms=settings.capture_timeout_ms,
        user_agent=settings.user_agent,
        llm_model=settings.llm_model,
    )
    async with session_scope() as session:
        audit_id = await repo.create_audit(
            session,
            site_url=url,
            agent_version=agent_version,
            config={
                "viewports": list(viewports),
                "tools": list(AUDIT_TOOLS),
                "pages_limit": 1,
                "robots": "ignored" if ignore_robots else "enforced",
                "agents": list(agents),
            },
        )
        try:
            if not ignore_robots:
                await ensure_allowed(
                    url,
                    settings.user_agent,
                    allowed_private_hosts=allowed_private_hosts,
                )
            hop_check = (
                None
                if ignore_robots
                else robots_hop_check(
                    settings.user_agent, allowed_private_hosts=allowed_private_hosts
                )
            )
            try:
                async with asyncio.timeout(settings.page_timeout_ms / 1000):
                    facts = await http_probe.probe(
                        url,
                        user_agent=settings.user_agent,
                        allowed_private_hosts=allowed_private_hosts,
                        timeout_s=settings.page_timeout_ms / 1000,
                        hop_check=hop_check,
                    )
            except TimeoutError as error:
                raise ProbeTimeout(
                    f"HTTP probe of {url} exceeded {settings.page_timeout_ms} ms"
                ) from error
            capture = await capture_page(
                url,
                settings,
                allowed_private_hosts=allowed_private_hosts,
            )
            if capture.status_code >= 400:
                raise CaptureFailed(f"{capture.url} answered with HTTP {capture.status_code}")
            key, stored = store_artifacts(capture, audit_id)
            page_id = await repo.save_page(
                session,
                audit_id=audit_id,
                url=capture.url,
                key=key,
                status_code=capture.status_code,
                render_mode="browser",
            )
            observations = http_observations(facts)
            for html_key, dom_key, screenshot_key, viewport_capture in stored:
                await repo.save_snapshot(
                    session,
                    page_id=page_id,
                    viewport=viewport_capture.viewport,
                    html_key=html_key,
                    dom_key=dom_key,
                    screenshot_key=screenshot_key,
                )
                observations.extend(
                    viewport_observations(
                        viewport_capture,
                        html_key=html_key,
                        dom_key=dom_key,
                        screenshot_key=screenshot_key,
                    )
                )
            await repo.save_observations(session, page_id=page_id, observations=observations)
            drafts = draft_findings([observation.view() for observation in observations])
            stored_findings = await repo.save_findings(
                session, audit_id=audit_id, page_id=page_id, drafts=drafts
            )
            findings = [
                to_finding_out(finding_id, draft, capture.url, key)
                for finding_id, draft in stored_findings
            ]
            observations_by_tool: dict[str, int] = {}
            for observation in observations:
                observations_by_tool[observation.tool] = (
                    observations_by_tool.get(observation.tool, 0) + 1
                )
            measured = measured_categories(MEASURED_TOOLS)
            agent_summaries: list[AgentSummaryOut] = []
            status = "completed"
            if agents:
                # The agents read the facts through a separate process, so the facts have to
                # be committed before the MCP server can serve them.
                await session.commit()
                orchestration = await run_agents(audit_id, names=agents, settings=settings)
                index = await observation_index(audit_id)
                agent_drafts: list[FindingDraft] = []
                for run in orchestration.runs:
                    for candidate in run.accepted:
                        draft, _ = validate(candidate, observations=index, agent=run.name)
                        if draft is not None:
                            agent_drafts.append(draft)
                    if run.status == "ok":
                        measured.add(spec_for(run.name).category)
                    agent_summaries.append(
                        AgentSummaryOut(
                            name=run.name,
                            status=run.status,
                            findings=len(run.accepted),
                            rejected=len(run.rejected),
                            tool_calls=run.tool_calls,
                            llm_calls=run.llm_calls,
                            tokens_in=run.tokens_in,
                            tokens_out=run.tokens_out,
                            latency_ms=run.latency_ms,
                            error=run.error,
                        )
                    )
                if agent_drafts:
                    stored_agents = await repo.save_findings(
                        session, audit_id=audit_id, page_id=page_id, drafts=agent_drafts
                    )
                    findings.extend(
                        to_finding_out(finding_id, draft, capture.url, key)
                        for finding_id, draft in stored_agents
                    )
                status = orchestration.status
            report = build_report(
                audit_id=str(audit_id),
                site=url,
                agent_version=agent_version,
                status=status,
                findings=findings,
                pages_audited=1,
                duration_ms=int((time.monotonic() - started) * 1000),
                measured_categories=measured,
                observations_by_tool=observations_by_tool,
                agents=agent_summaries,
            )
            report_key = write_artifact(audit_id, "report.json", report.model_dump_json(indent=2))
            await repo.finish_audit(
                session,
                audit_id=audit_id,
                status=report.status,
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
