"""Cross-source deduplication, root-cause clustering and priority for one audit.

Everything here is deterministic: the same findings produce the same duplicates, clusters and
order. The Chief Auditor's narration, when it exists, explains these groups; it never decides
them (docs/PLAN.md, section 6 invariants 3 and 4).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.chief.anchor import anchor_for_evidence
from app.core.report import FindingOut, RootCauseOut
from app.rules.catalog import SEVERITY_WEIGHTS, Severity

MAX_EVIDENCE_ITEMS = 10
ROOT_CAUSE_MIN_FINDINGS = 2
ROOT_CAUSE_MIN_CATEGORIES = 2


@dataclass
class ChiefResult:
    findings: list[FindingOut]
    root_causes: list[RootCauseOut]
    duplicates_removed: int

    @property
    def duplicate_rate(self) -> float:
        """Share of the reported findings that were duplicates of another one."""
        total = len(self.findings) + self.duplicates_removed
        return round(self.duplicates_removed / total, 4) if total else 0.0


def severity_weight(severity: Severity) -> float:
    return SEVERITY_WEIGHTS[severity]


def finding_priority(finding: FindingOut) -> float:
    """Severity times the largest impact axis, tempered by how sure the agent was.

    A blocker on a page nobody converts from should not outrank a major defect that blocks the
    primary action, and an unsure agent's claim should not outrank a measured one.
    """
    impact = max(finding.impact.conversion, finding.impact.seo, finding.impact.ux)
    return round(severity_weight(finding.severity) * (1 + impact) * finding.confidence, 3)


def _place(finding: FindingOut, anchor: str | None) -> str:
    if anchor is not None:
        return f"anchor:{anchor}"
    return "evidence:" + "|".join(sorted(item.observation_id for item in finding.evidence))


def _evidence_ids(finding: FindingOut) -> set[str]:
    return {item.observation_id for item in finding.evidence}


def _merge(first: FindingOut, second: FindingOut) -> FindingOut:
    """Keep the harsher claim and pool the evidence: two agents saw the same defect."""
    primary, other = (
        (first, second)
        if (severity_weight(first.severity), first.confidence)
        >= (severity_weight(second.severity), second.confidence)
        else (second, first)
    )
    seen: set[tuple[str, str, str | None]] = set()
    evidence = []
    for item in [*primary.evidence, *other.evidence]:
        key = (item.observation_id, item.kind, item.excerpt)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(item)
        if len(evidence) >= MAX_EVIDENCE_ITEMS:
            break
    return primary.model_copy(update={"evidence": evidence})


def dedupe(
    findings: Sequence[FindingOut], observations: dict[str, dict[str, Any]]
) -> tuple[list[FindingOut], int]:
    """Collapse the same claim about the same place, keeping one finding with all its evidence."""
    kept: dict[tuple[str, str, str], FindingOut] = {}
    order: list[tuple[str, str, str]] = []
    duplicates = 0
    for finding in findings:
        anchor = anchor_for_evidence(
            (item.observation_id for item in finding.evidence), observations
        )
        place = _place(finding, anchor)
        subject = (finding.subject or "").strip().lower()
        key = (finding.rule_id, place, subject)
        existing = kept.get(key)
        mergeable = existing is not None and (
            bool(subject) or bool(_evidence_ids(existing) & _evidence_ids(finding))
        )
        if not mergeable:
            # Two findings with one rule in one block are still two targets unless they talk
            # about the same subject or cite the same fact.
            suffix = "" if existing is None else f"#{len(order)}"
            key = (finding.rule_id, place + suffix, subject)
            kept[key] = finding
            order.append(key)
            continue
        assert existing is not None  # mergeable is only true when it exists
        kept[key] = _merge(existing, finding)
        duplicates += 1
    return [kept[key] for key in order], duplicates


def root_cause_id(page_key: str, anchor: str) -> str:
    digest = hashlib.sha1(f"{page_key}|{anchor}".encode()).hexdigest()[:10]
    return f"rc-{digest}"


def cluster(
    findings: Sequence[FindingOut], observations: dict[str, dict[str, Any]]
) -> list[RootCauseOut]:
    """Group findings that share a place and promote only the cross-category groups.

    A group with one category is one finding plus its siblings, not a cause: the invariant says
    a root cause has to explain symptoms from at least two directions, or it is just a defect.
    """
    groups: dict[str, list[FindingOut]] = {}
    for finding in findings:
        anchor = anchor_for_evidence(
            (item.observation_id for item in finding.evidence), observations
        )
        if anchor is None:
            continue
        groups.setdefault(anchor, []).append(finding)

    causes: list[RootCauseOut] = []
    for anchor, members in groups.items():
        categories = sorted({finding.category for finding in members})
        if len(members) < ROOT_CAUSE_MIN_FINDINGS or len(categories) < ROOT_CAUSE_MIN_CATEGORIES:
            continue
        severity = max(members, key=lambda item: severity_weight(item.severity)).severity
        causes.append(
            RootCauseOut(
                id=root_cause_id(members[0].page_key, anchor),
                kind="dom_anchor",
                anchor=anchor,
                categories=categories,
                summary=(
                    f"{len(members)} findings in {len(categories)} categories share "
                    f"{anchor}; fixing the block is likely to close them together."
                ),
                rationale=", ".join(sorted({finding.rule_id for finding in members})),
                severity=severity,
                priority=max(finding.priority for finding in members),
                finding_ids=[finding.id for finding in members],
            )
        )
    causes.sort(key=lambda cause: (-cause.priority, cause.id))
    return causes


def run_chief(
    findings: Sequence[FindingOut], observations: dict[str, dict[str, Any]]
) -> ChiefResult:
    """Dedupe, prioritise, then cluster. Clustering runs last so a merged finding counts once."""
    kept, duplicates = dedupe(findings, observations)
    prioritised = [
        finding.model_copy(update={"priority": finding_priority(finding)}) for finding in kept
    ]
    causes = cluster(prioritised, observations)
    caused = {finding_id: cause.id for cause in causes for finding_id in cause.finding_ids}
    return ChiefResult(
        findings=[
            finding.model_copy(update={"root_cause_id": caused.get(finding.id)})
            for finding in prioritised
        ],
        root_causes=causes,
        duplicates_removed=duplicates,
    )


@dataclass
class ChiefState:
    """Kept for callers that build a report incrementally."""

    findings: list[FindingOut] = field(default_factory=list)
    root_causes: list[RootCauseOut] = field(default_factory=list)
