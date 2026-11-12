import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from app.rules.catalog import Rule, Severity, rule_by_match

MAX_EVIDENCE_ITEMS = 10
DETERMINISTIC_CONFIDENCE = 1.0
RULES_AGENT = "rules"


class NewObservation(BaseModel):
    """A fact about to be stored. The id is generated up front so findings can cite it."""

    id: uuid.UUID
    tool: str
    kind: str
    payload: dict[str, Any]
    rule_ref: str | None = None
    viewport: str | None = None

    def view(self) -> "ObservationView":
        return ObservationView(
            id=str(self.id),
            tool=self.tool,
            kind=self.kind,
            rule_ref=self.rule_ref,
            payload=self.payload,
        )


class ObservationView(BaseModel):
    """A stored fact, as an auditor reads it."""

    id: str
    tool: str
    kind: str
    rule_ref: str | None = None
    payload: dict[str, Any]


class EvidenceDraft(BaseModel):
    observation_id: str
    kind: str
    excerpt: str | None = None


class FindingDraft(BaseModel):
    rule_id: str
    category: str
    severity: Severity
    title: str
    summary: str
    suggested_fix: str
    impact_conversion: int
    impact_seo: int
    impact_ux: int
    confidence: float
    agent: str
    evidence: list[EvidenceDraft]


def dom_violations(payload: dict[str, Any]) -> dict[str, str]:
    """Turn a DOM snapshot into the DOM checks that failed."""
    found: dict[str, str] = {}
    if not str(payload.get("title") or "").strip():
        found["title"] = "document.title is empty"
    if not str(payload.get("meta_description") or "").strip():
        found["meta_description"] = "meta[name=description] is missing or empty"
    if int(payload.get("h1_count") or 0) == 0:
        found["h1"] = "the page has no h1 element"
    return found


def axe_draft(observation: ObservationView) -> FindingDraft | None:
    """Map one axe violation to a catalogued rule, if this project claims that rule."""
    rule = rule_by_match("axe", observation.rule_ref or "")
    if rule is None:
        return None
    nodes = observation.payload.get("nodes") or []
    evidence = [
        EvidenceDraft(
            observation_id=observation.id,
            kind="axe_node",
            excerpt=_node_excerpt(node),
        )
        for node in nodes[:MAX_EVIDENCE_ITEMS]
    ]
    if not evidence:
        return None
    summary = f"{rule.summary} Reported on {len(nodes)} element(s)."
    return _draft(rule, evidence, summary)


def dom_drafts(observation: ObservationView) -> list[FindingDraft]:
    drafts: list[FindingDraft] = []
    for match, message in dom_violations(observation.payload).items():
        rule = rule_by_match("dom", match)
        if rule is None:
            continue
        evidence = [EvidenceDraft(observation_id=observation.id, kind="dom", excerpt=message)]
        drafts.append(_draft(rule, evidence, f"{rule.summary} Observed: {message}."))
    return drafts


def draft_findings(observations: Sequence[ObservationView]) -> list[FindingDraft]:
    """Rules only claim what the catalog covers; every other fact stays an observation.

    One rule, one finding: the same defect seen at three viewports is one claim with three
    evidence items, not three findings. Grouping happens here rather than per node, because
    a per-node finding is noise a reader has to re-collapse by hand.
    """
    drafts: list[FindingDraft] = []
    for observation in observations:
        if observation.tool == "axe":
            draft = axe_draft(observation)
            if draft is not None:
                drafts.append(draft)
        elif observation.tool == "dom":
            drafts.extend(dom_drafts(observation))
    return merge_by_rule(drafts)


def merge_by_rule(drafts: Sequence[FindingDraft]) -> list[FindingDraft]:
    merged: dict[str, FindingDraft] = {}
    for draft in drafts:
        existing = merged.get(draft.rule_id)
        if existing is None:
            merged[draft.rule_id] = draft
            continue
        seen = {item.observation_id for item in existing.evidence}
        for item in draft.evidence:
            if len(existing.evidence) >= MAX_EVIDENCE_ITEMS:
                break
            if item.observation_id in seen:
                continue
            existing.evidence.append(item)
            seen.add(item.observation_id)
    return list(merged.values())


def _draft(rule: Rule, evidence: list[EvidenceDraft], summary: str) -> FindingDraft:
    return FindingDraft(
        rule_id=rule.id,
        category=rule.category,
        severity=rule.severity,
        title=rule.title,
        summary=summary,
        suggested_fix=rule.suggested_fix,
        impact_conversion=rule.impact.conversion,
        impact_seo=rule.impact.seo,
        impact_ux=rule.impact.ux,
        confidence=DETERMINISTIC_CONFIDENCE,
        agent=RULES_AGENT,
        evidence=evidence,
    )


def _node_excerpt(node: dict[str, Any]) -> str:
    target = " ".join(str(part) for part in node.get("target") or [])
    html = str(node.get("html") or "")
    return f"{target} :: {html}"[:EXCERPT_LIMIT_NODE]


EXCERPT_LIMIT_NODE = 400
