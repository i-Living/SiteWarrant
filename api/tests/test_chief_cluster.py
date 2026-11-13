import uuid

from app.chief.cluster import dedupe, finding_priority, root_cause_id, run_chief
from app.core.report import EvidenceOut, FindingOut, ImpactOut

HEADER_PATH = "html > body > header:nth-of-type(1) > a:nth-of-type(2)"
HEADER_BANNER = "html > body > header:nth-of-type(1) > div:nth-of-type(1) > span"
MAIN_PATH = "html > body > main:nth-of-type(1) > section:nth-of-type(2) > button"


def observations() -> dict[str, dict]:
    return {
        "obs-header": {"selector": HEADER_PATH},
        "obs-banner": {"selector": HEADER_BANNER},
        "obs-main": {"selector": MAIN_PATH},
        "obs-title": {"title": "", "h1_count": 0},
    }


def finding(
    *,
    rule_id: str = "A11Y-LINK-NAME",
    category: str = "a11y",
    severity: str = "major",
    observation: str = "obs-header",
    kind: str = "axe_node",
    confidence: float = 1.0,
    agent: str = "rules",
    impact: dict | None = None,
    subject: str | None = None,
) -> FindingOut:
    return FindingOut(
        id=str(uuid.uuid4()),
        rule_id=rule_id,
        category=category,
        severity=severity,  # type: ignore[arg-type]
        title="t",
        summary="s",
        suggested_fix="f",
        impact=ImpactOut(**(impact or {"conversion": 0, "seo": 0, "ux": 2})),
        confidence=confidence,
        agent=agent,
        subject=subject,
        page_url="http://localhost:8081/",
        page_key="localhost",
        evidence=[EvidenceOut(kind=kind, observation_id=observation)],
    )


def test_the_same_claim_about_the_same_place_is_one_finding() -> None:
    kept, duplicates = dedupe(
        [finding(agent="rules"), finding(agent="a11y", confidence=0.8)], observations()
    )
    assert len(kept) == 1
    assert duplicates == 1
    assert kept[0].agent == "rules", "the confident claim wins"


def test_merged_duplicates_pool_their_evidence() -> None:
    """Two sources describing the same subject are one finding with both citations."""
    first = finding(observation="obs-header", subject="header > a")
    second = finding(observation="obs-banner", subject="header > a")
    kept, duplicates = dedupe([first, second], observations())
    assert duplicates == 1
    assert [item.observation_id for item in kept[0].evidence] == ["obs-header", "obs-banner"]


def test_subjects_keep_their_case() -> None:
    """`#CTA` and `#cta` are different elements, so their findings must not merge."""
    kept, duplicates = dedupe(
        [finding(subject="header > a#CTA"), finding(subject="header > a#cta")], observations()
    )
    assert duplicates == 0
    assert len(kept) == 2


def test_every_retained_candidate_is_searched_for_a_duplicate() -> None:
    """Three findings citing A, B, B: the third matches the retained B, not only the first."""
    kept, duplicates = dedupe(
        [
            finding(observation="obs-banner"),
            finding(observation="obs-header"),
            finding(observation="obs-header"),
        ],
        observations(),
    )
    assert duplicates == 1
    assert len(kept) == 2


def test_one_rule_in_one_block_without_a_subject_stays_two_targets() -> None:
    """A header can hold two small targets; only a shared citation or subject makes them one."""
    first = finding(observation="obs-header")
    second = finding(observation="obs-banner")
    kept, duplicates = dedupe([first, second], observations())
    assert duplicates == 0
    assert len(kept) == 2


def test_the_same_claim_in_different_places_is_two_findings() -> None:
    kept, duplicates = dedupe([finding(), finding(observation="obs-main")], observations())
    assert len(kept) == 2
    assert duplicates == 0


def test_page_level_findings_have_no_place_and_dedupe_by_evidence() -> None:
    """A page-level fact (an empty title) has no anchor, so the citation set is its identity."""
    kept, duplicates = dedupe(
        [finding(observation="obs-title"), finding(observation="obs-title")], observations()
    )
    assert duplicates == 1
    assert len(kept) == 1


def test_two_hits_from_one_observation_keep_their_own_blocks() -> None:
    """A mixed occlusion report must not make its findings place-less."""
    header_hit = "html > body > header:nth-of-type(1) > a:nth-of-type(1)"
    footer_hit = "html > body > footer:nth-of-type(1) > a:nth-of-type(1)"
    mixed = {
        "hits": [
            {
                "selector": header_hit,
                "occluder_selector": "html > body > header:nth-of-type(1) > div",
            },
            {
                "selector": footer_hit,
                "occluder_selector": "html > body > header:nth-of-type(1) > div",
            },
        ]
    }
    kept, duplicates = dedupe(
        [
            finding(
                rule_id="LAYOUT-OCCLUSION",
                category="responsive",
                observation="obs-mixed",
                subject=header_hit,
            ),
            finding(
                rule_id="LAYOUT-OCCLUSION",
                category="responsive",
                observation="obs-mixed",
                subject=footer_hit,
            ),
        ],
        {"obs-mixed": mixed},
    )
    assert duplicates == 0
    assert len(kept) == 2


def test_a_cross_category_cluster_becomes_a_root_cause() -> None:
    result = run_chief(
        [
            finding(rule_id="A11Y-LINK-NAME", category="a11y"),
            finding(rule_id="LAYOUT-OCCLUSION", category="responsive", observation="obs-banner"),
        ],
        observations(),
    )
    assert len(result.root_causes) == 1
    cause = result.root_causes[0]
    assert cause.anchor == "header"
    assert cause.categories == ["a11y", "responsive"]
    assert len(cause.finding_ids) == 2
    assert {f.root_cause_id for f in result.findings} == {cause.id}
    assert result.duplicate_rate == 0.0


def test_one_category_is_a_group_of_findings_not_a_cause() -> None:
    result = run_chief(
        [
            finding(rule_id="A11Y-LINK-NAME"),
            finding(rule_id="A11Y-TARGET-SIZE", observation="obs-banner", severity="minor"),
        ],
        observations(),
    )
    assert result.root_causes == []
    assert all(item.root_cause_id is None for item in result.findings)


def test_a_single_finding_is_not_a_cause() -> None:
    result = run_chief([finding()], observations())
    assert result.root_causes == []


def test_priority_weighs_severity_impact_and_confidence() -> None:
    blocker = finding(severity="blocker", impact={"conversion": 3, "seo": 0, "ux": 0})
    minor = finding(severity="minor", impact={"conversion": 0, "seo": 0, "ux": 0})
    unsure = finding(severity="major", confidence=0.5)
    assert finding_priority(blocker) > finding_priority(finding(severity="major"))
    assert finding_priority(minor) < finding_priority(unsure)


def test_root_causes_are_ordered_by_priority() -> None:
    result = run_chief(
        [
            finding(rule_id="A11Y-LINK-NAME", category="a11y", severity="info"),
            finding(rule_id="LAYOUT-OCCLUSION", category="responsive", observation="obs-banner"),
            finding(
                rule_id="A11Y-BUTTON-NAME",
                category="a11y",
                observation="obs-main",
                severity="blocker",
            ),
            finding(
                rule_id="LAYOUT-OCCLUSION",
                category="responsive",
                observation="obs-main",
                impact={"conversion": 2, "seo": 0, "ux": 0},
            ),
        ],
        observations(),
    )
    assert [cause.anchor for cause in result.root_causes] == ["section", "header"]


def test_the_root_cause_id_is_stable() -> None:
    assert root_cause_id("localhost", "header") == root_cause_id("localhost", "header")
    assert root_cause_id("localhost", "header") != root_cause_id("localhost", "main")
