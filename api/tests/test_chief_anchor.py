import uuid

from app.agents.models import EvidenceRef
from app.chief.anchor import anchor_for_evidence, anchor_for_selectors, selectors_in
from app.core.report import EvidenceOut, FindingOut, ImpactOut

HEADER_LINK = "html:nth-of-type(1) > body:nth-of-type(1) > header:nth-of-type(1) > a:nth-of-type(2)"
HEADER_BANNER = (
    "html:nth-of-type(1) > body:nth-of-type(1) > header:nth-of-type(1) > div:nth-of-type(1) > img"
)
MAIN_PARAGRAPH = (
    "html:nth-of-type(1) > body:nth-of-type(1) > main:nth-of-type(1) > p:nth-of-type(3)"
)


def test_a_single_path_names_its_block() -> None:
    assert anchor_for_selectors([HEADER_LINK]) == "header"


def test_paths_in_one_block_name_that_block() -> None:
    assert anchor_for_selectors([HEADER_LINK, HEADER_BANNER]) == "header"


def test_paths_in_different_blocks_name_nothing() -> None:
    """A finding that touches two blocks belongs to neither, and a cluster would be invented."""
    assert anchor_for_selectors([HEADER_LINK, MAIN_PARAGRAPH]) is None


def test_a_leaf_under_a_page_wrapper_names_nothing() -> None:
    """`main > p` is a paragraph, not a place: stripping the wrapper leaves one segment."""
    assert anchor_for_selectors([MAIN_PARAGRAPH]) is None


def test_a_bare_element_selector_is_not_a_place() -> None:
    assert anchor_for_selectors([".icon-link", "#cta"]) is None


def test_free_text_is_not_a_selector() -> None:
    """A note that happens to look like a path must not strip the real anchor."""
    payload = {
        "selector": HEADER_LINK,
        "note": "main > pricing",
        "html": '<h2 class="a > b">',
    }
    assert selectors_in(payload) == [HEADER_LINK]
    assert anchor_for_selectors(selectors_in(payload)) == "header"


def test_two_sections_are_two_blocks() -> None:
    """`section:nth-of-type(1)` and `section:nth-of-type(2)` share a tag, not a place."""
    first = "main:nth-of-type(1) > section:nth-of-type(1) > p"
    second = "main:nth-of-type(1) > section:nth-of-type(2) > p"
    assert anchor_for_selectors([first]) == "section"
    assert anchor_for_selectors([first, second]) is None


def test_selectors_are_read_from_payload_values_not_keys() -> None:
    payload = {
        "selector": HEADER_LINK,
        "occluder_selector": HEADER_BANNER,
        "selector_count": 2,
        "note": "not a path",
    }
    assert selectors_in(payload) == [HEADER_LINK, HEADER_BANNER]


def test_the_subject_wins_over_the_rest_of_its_observation() -> None:
    """One occlusion report holds hits from the whole page; a finding is about one of them."""
    header_hit = "html > body > header:nth-of-type(1) > a:nth-of-type(1)"
    footer_hit = "html > body > footer:nth-of-type(1) > a:nth-of-type(1)"
    observations = {
        "obs-occlusion": {
            "hits": [
                {"selector": header_hit, "occluder_selector": "html > body > div:nth-of-type(2)"},
                {"selector": footer_hit, "occluder_selector": "html > body > div:nth-of-type(2)"},
            ]
        }
    }
    # Without a subject the payload disagrees with itself, so the finding has no place.
    assert anchor_for_evidence(["obs-occlusion"], observations) is None
    # The subject names the covered element, so the finding keeps its block.
    assert anchor_for_evidence(["obs-occlusion"], observations, subject=header_hit) == "header"
    assert anchor_for_evidence(["obs-occlusion"], observations, subject=footer_hit) == "footer"


def test_free_text_subject_does_not_override_the_evidence() -> None:
    """The validator only checks the subject text appears in the payload, so a breadcrumb passes."""
    observations = {"obs": {"selector": HEADER_LINK, "note": "Home > Products"}}
    assert anchor_for_evidence(["obs"], observations, subject="Home > Products") == "header"


def test_a_subject_that_is_not_a_path_falls_back_to_the_evidence() -> None:
    observations = {"obs": {"selector": HEADER_LINK}}
    assert anchor_for_evidence(["obs"], observations, subject="header > a") == "header"
    assert anchor_for_evidence(["obs"], observations, subject="Navigation link") == "header"


def test_evidence_refs_and_report_evidence_share_one_shape() -> None:
    """The validator and the chief layer read the same evidence type; this pins the assumption."""
    finding = FindingOut(
        id=str(uuid.uuid4()),
        rule_id="A11Y-LINK-NAME",
        category="a11y",
        severity="major",
        title="Link has no accessible name",
        summary="",
        suggested_fix="",
        impact=ImpactOut(conversion=0, seo=0, ux=0),
        confidence=1.0,
        agent="rules",
        page_url="http://localhost:8081/",
        page_key="localhost",
        evidence=[EvidenceOut(kind="axe_node", observation_id=str(uuid.uuid4()))],
    )
    assert isinstance(finding.evidence[0].observation_id, str)
    assert EvidenceRef(observation_id=finding.evidence[0].observation_id, kind="axe_node")
