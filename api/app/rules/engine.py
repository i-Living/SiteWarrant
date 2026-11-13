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
    subject: str | None = None
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


def occlusion_drafts(observation: ObservationView) -> list[FindingDraft]:
    """One draft per covered target: a click that lands on someone else is a measured defect."""
    rule = rule_by_match("occlusion", _OCCLUSION_MATCH)
    if rule is None:
        return []
    drafts: list[FindingDraft] = []
    for hit in observation.payload.get("hits") or []:
        selector = str(hit.get("selector") or "")
        occluder = str(hit.get("occluder_selector") or "")
        if not selector or not occluder:
            continue
        drafts.append(
            _draft(
                rule,
                [
                    EvidenceDraft(
                        observation_id=observation.id,
                        kind="occlusion_hit",
                        excerpt=f"{selector} covered by {occluder}",
                    )
                ],
                f"{rule.summary} Observed: {selector} is covered by {occluder}.",
            )
        )
    return drafts


_OCCLUSION_MATCH = "occluded_target"


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
        elif observation.tool == "occlusion":
            drafts.extend(occlusion_drafts(observation))
    return merge_by_rule(drafts)


def merge_by_rule(drafts: Sequence[FindingDraft]) -> list[FindingDraft]:
    """One draft per rule, with evidence pooled across viewports.

    Evidence is taken round-robin by position within each draft, so a viewport that reports
    ten nodes cannot fill the cap and hide the two later viewports. Items are deduplicated
    by observation and excerpt: the same node twice is one item, two nodes of one observation
    stay two items.
    """
    groups: dict[str, list[FindingDraft]] = {}
    for draft in drafts:
        groups.setdefault(draft.rule_id, []).append(draft)

    merged: list[FindingDraft] = []
    for group in groups.values():
        head = group[0]
        pooled = sorted(
            ((index, item) for draft in group for index, item in enumerate(draft.evidence)),
            key=lambda pair: pair[0],
        )
        seen: set[tuple[str, str, str | None]] = set()
        evidence: list[EvidenceDraft] = []
        for _, item in pooled:
            key = (item.observation_id, item.kind, item.excerpt)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(item)
            if len(evidence) >= MAX_EVIDENCE_ITEMS:
                break
        head.evidence = evidence
        merged.append(head)
    return merged


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
