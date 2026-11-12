import uuid
from typing import Any

from app.rules.engine import (
    NewObservation,
    ObservationView,
    axe_draft,
    dom_drafts,
    dom_violations,
    draft_findings,
)


def dom_observation(**payload: Any) -> ObservationView:
    return ObservationView(
        id=str(uuid.uuid4()),
        tool="dom",
        kind="dom_snapshot",
        payload=payload,
    )


def axe_observation(rule_ref: str, nodes: list[dict[str, Any]]) -> ObservationView:
    return ObservationView(
        id=str(uuid.uuid4()),
        tool="axe",
        kind="axe_violation",
        rule_ref=rule_ref,
        payload={"nodes": nodes},
    )


def test_dom_violations_detects_all_three() -> None:
    found = dom_violations({"title": "", "meta_description": None, "h1_count": 0})
    assert set(found) == {"title", "meta_description", "h1"}


def test_dom_violations_pass_a_clean_page() -> None:
    assert dom_violations({"title": "Northwind", "meta_description": "Prints", "h1_count": 1}) == {}


def test_dom_drafts_cite_the_observation() -> None:
    observation = dom_observation(title="", meta_description="Prints", h1_count=1)
    drafts = dom_drafts(observation)
    assert [draft.rule_id for draft in drafts] == ["SEO-TITLE"]
    assert drafts[0].evidence[0].observation_id == observation.id
    assert drafts[0].severity == "major"


def test_unknown_axe_rule_produces_no_finding() -> None:
    assert axe_draft(axe_observation("region", [{"html": "<div>", "target": ["div"]}])) is None


def test_axe_rule_uses_catalog_severity_not_axe_impact() -> None:
    draft = axe_draft(axe_observation("label", [{"html": "<input>", "target": ["#email"]}]))
    assert draft is not None
    assert draft.rule_id == "A11Y-LABEL"
    assert draft.severity == "blocker"
    assert draft.confidence == 1.0


def test_every_node_becomes_evidence() -> None:
    nodes = [
        {"html": f"<img src={index}>", "target": [f"img:nth-child({index})"]} for index in range(3)
    ]
    draft = axe_draft(axe_observation("image-alt", nodes))
    assert draft is not None
    assert len(draft.evidence) == 3
    assert "Reported on 3 element(s)" in draft.summary


def test_violation_without_nodes_is_dropped() -> None:
    assert axe_draft(axe_observation("image-alt", [])) is None


def test_draft_findings_ignores_tools_without_rules() -> None:
    observation = ObservationView(
        id=str(uuid.uuid4()), tool="lighthouse", kind="metrics", payload={"lcp": 1200}
    )
    assert draft_findings([observation]) == []


def test_new_observation_view_keeps_its_id() -> None:
    observation = NewObservation(id=uuid.uuid4(), tool="dom", kind="dom_snapshot", payload={})
    assert observation.view().id == str(observation.id)
