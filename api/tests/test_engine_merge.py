import uuid

from app.rules.engine import (
    MAX_EVIDENCE_ITEMS,
    EvidenceDraft,
    FindingDraft,
    ObservationView,
    draft_findings,
    merge_by_rule,
)


def observation(
    *,
    tool: str,
    kind: str,
    payload: dict[str, object],
    rule_ref: str | None = None,
) -> ObservationView:
    return ObservationView(
        id=str(uuid.uuid4()), tool=tool, kind=kind, rule_ref=rule_ref, payload=payload
    )


def axe_observation(nodes: int, rule_ref: str = "image-alt") -> ObservationView:
    return observation(
        tool="axe",
        kind="axe_violation",
        rule_ref=rule_ref,
        payload={
            "id": rule_ref,
            "help": "Images must have alternate text",
            "help_url": "https://dequeuniversity.com/rules/axe/4.14/image-alt",
            "tags": ["wcag2a"],
            "nodes": [{"html": f"<img {index}>", "target": ["img"]} for index in range(nodes)],
        },
    )


def draft(rule_id: str, evidence: list[EvidenceDraft]) -> FindingDraft:
    return FindingDraft(
        rule_id=rule_id,
        category="a11y",
        severity="major",
        title="t",
        summary="s",
        suggested_fix="f",
        impact_conversion=0,
        impact_seo=0,
        impact_ux=1,
        confidence=1.0,
        agent="rules",
        evidence=evidence,
    )


def test_the_same_rule_at_three_viewports_is_one_finding() -> None:
    """A defect visible at every viewport is one claim, not three."""
    observations = [axe_observation(1) for _ in range(3)]
    drafts = draft_findings(observations)
    assert len(drafts) == 1
    assert len(drafts[0].evidence) == 3
    assert len({item.observation_id for item in drafts[0].evidence}) == 3


def test_the_same_node_twice_is_one_item() -> None:
    one = axe_observation(2)
    drafts = draft_findings([one, one])
    assert len(drafts) == 1
    assert len(drafts[0].evidence) == 2


def test_the_first_viewport_cannot_fill_the_cap_alone() -> None:
    """Ten nodes at 390 px must not hide the one node found at 768 and 1440 px."""
    observations = [axe_observation(MAX_EVIDENCE_ITEMS)]
    observations.append(axe_observation(1))
    observations.append(axe_observation(1))

    drafts = draft_findings(observations)

    assert len(drafts) == 1
    assert len(drafts[0].evidence) == MAX_EVIDENCE_ITEMS
    observation_ids = {item.observation_id for item in drafts[0].evidence}
    assert len(observation_ids) == 3, "every viewport must appear in the evidence"


def test_evidence_is_capped() -> None:
    observations = [axe_observation(1) for _ in range(MAX_EVIDENCE_ITEMS + 5)]
    drafts = draft_findings(observations)
    assert len(drafts[0].evidence) == MAX_EVIDENCE_ITEMS


def test_different_rules_stay_separate() -> None:
    drafts = merge_by_rule(
        [
            draft("A11Y-IMG-ALT", [EvidenceDraft(observation_id="1", kind="axe_node")]),
            draft("A11Y-LABEL", [EvidenceDraft(observation_id="2", kind="axe_node")]),
        ]
    )
    assert sorted(item.rule_id for item in drafts) == ["A11Y-IMG-ALT", "A11Y-LABEL"]


def test_a_rule_outside_the_catalog_is_not_a_claim() -> None:
    """Unknown axe rules stay observations; the catalog decides what is claimed."""
    assert draft_findings([axe_observation(2, rule_ref="color-contrast-enhanced")]) == []


def test_an_observation_from_another_tool_is_ignored() -> None:
    responsive = observation(tool="responsive", kind="responsive_report", payload={})
    assert draft_findings([responsive]) == []
