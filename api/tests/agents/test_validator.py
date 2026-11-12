import uuid

from app.agents.models import CandidateFinding, EvidenceRef, ObservationFacts
from app.agents.validator import claimed_numbers, number_is_corroborated, validate, validate_all
from app.rules.catalog import Impact

DOM_ID = str(uuid.uuid4())
RESPONSIVE_ID = str(uuid.uuid4())
CONTRAST_ID = str(uuid.uuid4())
HTTP_ID = str(uuid.uuid4())


def observations() -> dict[str, ObservationFacts]:
    return {
        DOM_ID: ObservationFacts(
            tool="dom",
            kind="dom_snapshot",
            viewport="390x844",
            payload={
                "title": "SiteWarrant fixture",
                "meta_description": "short",
                "h1_count": 1,
                "canonical": None,
                "images_total": 12,
                "images_missing_alt": 3,
                "headings": [{"level": 1, "text": "Home"}, {"level": 3, "text": "Prices"}],
            },
        ),
        CONTRAST_ID: ObservationFacts(
            tool="contrast",
            kind="contrast_violation",
            viewport="390x844",
            payload={
                "selector": "p:nth-of-type(1)",
                "text": "Prices start at 40 EUR",
                "ratio": 3.1957,
                "required": 4.5,
                "color": "rgba(0, 0, 0, 0.45)",
                "background": "rgb(255, 255, 255)",
            },
        ),
        RESPONSIVE_ID: ObservationFacts(
            tool="responsive",
            kind="responsive_report",
            viewport="390x844",
            payload={
                "viewport_width": 390,
                "document_width": 390,
                "overflowing": [],
                "small_targets": [
                    {
                        "selector": "header:nth-of-type(1) > a:nth-of-type(1)",
                        "tag": "a",
                        "width_px": 16.0,
                        "height_px": 20.0,
                    }
                ],
            },
        ),
        HTTP_ID: ObservationFacts(
            tool="http",
            kind="security_header",
            rule_ref="content-security-policy",
            payload={"name": "content-security-policy", "present": False, "value": None},
        ),
    }


def candidate(**overrides: object) -> CandidateFinding:
    base: dict[str, object] = {
        "rule_id": "SEO-CANONICAL",
        "category": "seo",
        "severity": "minor",
        "title": "Page declares no canonical URL",
        "summary": "The DOM snapshot has no canonical link, so duplicates compete in search.",
        "suggested_fix": "Add a canonical link pointing at the preferred URL.",
        "impact": Impact(seo=2),
        "confidence": 0.9,
        "evidence": [EvidenceRef(observation_id=DOM_ID, kind="dom", excerpt="canonical: null")],
    }
    base.update(overrides)
    return CandidateFinding.model_validate(base)


def test_a_valid_candidate_becomes_a_draft() -> None:
    draft, rejection = validate(candidate(), observations=observations(), agent="seo")
    assert rejection is None
    assert draft is not None
    assert draft.rule_id == "SEO-CANONICAL"
    assert draft.agent == "seo"
    assert draft.evidence[0].observation_id == DOM_ID


def test_a_fabricated_observation_is_rejected() -> None:
    """The acceptance test for P3: no evidence, no finding."""
    invented = str(uuid.uuid4())
    draft, rejection = validate(
        candidate(evidence=[EvidenceRef(observation_id=invented, kind="dom")]),
        observations=observations(),
        agent="seo",
    )
    assert draft is None
    assert rejection is not None
    assert "does not exist" in rejection.reasons[0]


def test_a_fabricated_number_is_rejected() -> None:
    draft, rejection = validate(
        candidate(summary="Nine of twelve images have no alt text, so search loses context."),
        observations=observations(),
        agent="seo",
    )
    assert draft is None
    assert rejection is not None
    assert any("number 9" in reason for reason in rejection.reasons)


def test_a_number_that_matches_the_measurement_is_accepted() -> None:
    draft, rejection = validate(
        candidate(summary="Three of twelve images carry no alt text."),
        observations=observations(),
        agent="seo",
    )
    assert rejection is None, rejection.reasons if rejection else None
    assert draft is not None


def test_a_measurement_is_compared_at_the_precision_that_was_claimed() -> None:
    assert number_is_corroborated("3.2", [3.1957])
    assert not number_is_corroborated("3.3", [3.1957])
    assert number_is_corroborated("3.1957", [3.1957])


def test_rule_and_criterion_ids_are_not_measurements() -> None:
    assert claimed_numbers("Fails WCAG 1.4.3 and rule A11Y-CONTRAST at 3.2 to 1") == ["3.2", "1"]


def test_a_claim_outside_the_corpus_is_rejected() -> None:
    draft, rejection = validate(
        candidate(rule_id="SEO-MADE-UP"), observations=observations(), agent="seo"
    )
    assert draft is None
    assert rejection is not None
    assert "not a claim" in rejection.reasons[0]


def test_a_category_mismatch_is_rejected() -> None:
    draft, rejection = validate(candidate(category="ux"), observations=observations(), agent="seo")
    assert draft is None
    assert rejection is not None
    assert any("belongs to seo" in reason for reason in rejection.reasons)


def test_an_agent_may_not_soften_the_corpus_severity() -> None:
    draft, rejection = validate(
        candidate(rule_id="CONV-CTA-UNREACHABLE", category="conversion", severity="minor"),
        observations=observations(),
        agent="conversion",
    )
    assert draft is None
    assert rejection is not None
    assert any("would soften" in reason for reason in rejection.reasons)


def test_an_agent_may_escalate_the_corpus_severity() -> None:
    draft, rejection = validate(
        candidate(
            rule_id="SEC-CSP-MISSING",
            category="security",
            severity="blocker",
            evidence=[EvidenceRef(observation_id=HTTP_ID, kind="http")],
            summary="The response carries no Content-Security-Policy header.",
        ),
        observations=observations(),
        agent="security",
    )
    assert rejection is None, rejection.reasons if rejection else None
    assert draft is not None and draft.severity == "blocker"


def test_a_claim_cannot_cite_an_unrelated_channel() -> None:
    draft, rejection = validate(
        candidate(
            rule_id="A11Y-TARGET-SIZE",
            category="a11y",
            severity="major",
            evidence=[EvidenceRef(observation_id=DOM_ID, kind="dom")],
            criterion="WCAG-2.5.8",
        ),
        observations=observations(),
        agent="a11y",
    )
    assert draft is None
    assert rejection is not None
    assert any("may only cite responsive" in reason for reason in rejection.reasons)


def test_an_accessibility_finding_must_cite_its_criterion() -> None:
    base = {
        "rule_id": "A11Y-TEXT-CONTRAST-ALPHA",
        "category": "a11y",
        "severity": "major",
        "title": "Translucent text falls below the contrast minimum",
        "summary": "The composited pair measures 3.2 to 1.",
        "suggested_fix": "Raise the text opacity.",
        "evidence": [EvidenceRef(observation_id=CONTRAST_ID, kind="contrast")],
    }
    draft, rejection = validate(candidate(**base), observations=observations(), agent="a11y")
    assert draft is None
    assert rejection is not None
    assert any("must cite a WCAG criterion" in reason for reason in rejection.reasons)

    draft, rejection = validate(
        candidate(**base, criterion="WCAG-1.4.3"), observations=observations(), agent="a11y"
    )
    assert rejection is None, rejection.reasons if rejection else None
    assert draft is not None
    assert draft.summary.startswith("The composited pair")


def test_a_criterion_that_does_not_match_the_claim_is_rejected() -> None:
    draft, rejection = validate(
        candidate(
            rule_id="A11Y-TEXT-CONTRAST-ALPHA",
            category="a11y",
            severity="major",
            summary="The composited pair measures 3.2 to 1.",
            evidence=[EvidenceRef(observation_id=CONTRAST_ID, kind="contrast")],
            criterion="WCAG-2.5.8",
        ),
        observations=observations(),
        agent="a11y",
    )
    assert draft is None
    assert rejection is not None
    assert any("rests on WCAG-1.4.3" in reason for reason in rejection.reasons)


def test_two_findings_on_one_observation_both_survive() -> None:
    """One responsive observation can list two targets; both are findings.

    Suppressing by (rule, observation) would silently drop the second one. Deduplication
    across agents is the chief auditor's job, not the validator's.
    """
    first = candidate(
        rule_id="A11Y-TARGET-SIZE",
        category="a11y",
        severity="major",
        title="Header link is smaller than the minimum target",
        summary="The header link measures 16 by 20 pixels at this viewport.",
        suggested_fix="Increase the target to at least 24 by 24 CSS pixels.",
        criterion="WCAG-2.5.8",
        evidence=[EvidenceRef(observation_id=RESPONSIVE_ID, kind="responsive")],
    )
    second = first.model_copy(
        update={
            "title": "Footer link is smaller than the minimum target",
            "subject": "footer:nth-of-type(1) > a:nth-of-type(1)",
        }
    )
    first = first.model_copy(update={"subject": "header:nth-of-type(1) > a:nth-of-type(1)"})
    result = validate_all([first, second], observations=observations(), agent="a11y")
    assert len(result.accepted) == 2
    assert result.rejected == []


def test_the_same_claim_about_the_same_subject_is_one_finding() -> None:
    """Filing one claim twice would double the score, so the second copy is dropped."""
    result = validate_all(
        [candidate(subject="canonical: null"), candidate(subject="Canonical: Null ")],
        observations=observations(),
        agent="seo",
    )
    assert len(result.accepted) == 1


def test_an_invented_subject_does_not_split_a_finding() -> None:
    """A subject the evidence does not contain distinguishes nothing, so the claim is one."""
    result = validate_all(
        [
            candidate(subject="the meta description tag"),
            candidate(subject="the description meta tag"),
        ],
        observations=observations(),
        agent="seo",
    )
    assert len(result.accepted) == 1


def test_without_a_subject_the_cited_evidence_is_the_identity() -> None:
    result = validate_all([candidate(), candidate()], observations=observations(), agent="seo")
    assert len(result.accepted) == 1


def test_a_grouped_thousands_separator_is_not_a_decimal() -> None:
    """'1,000 pages' is a thousand; reading it as 1.0 would let h1_count=1 corroborate it."""
    draft, rejection = validate(
        candidate(
            title="The site has 1,000 pages without a canonical URL",
            summary="The DOM snapshot declares no canonical URL.",
            suggested_fix="Add a canonical link pointing at the preferred URL.",
        ),
        observations=observations(),
        agent="seo",
    )
    assert draft is None
    assert rejection is not None
    assert any("number 1,000" in reason for reason in rejection.reasons)
    assert number_is_corroborated("1,000", [1000.0])
    assert not number_is_corroborated("1,000", [1.0])


def test_an_excerpt_number_must_come_from_its_own_observation() -> None:
    """An excerpt is copied into the report as the observation's words, so it is checked."""
    draft, rejection = validate(
        candidate(
            title="Page declares no canonical URL",
            summary="The DOM snapshot has no canonical link.",
            suggested_fix="Add a canonical link pointing at the preferred URL.",
            evidence=[
                EvidenceRef(
                    observation_id=DOM_ID,
                    kind="dom",
                    excerpt="images_total: 47, images_missing_alt: 3",
                )
            ],
        ),
        observations=observations(),
        agent="seo",
    )
    assert draft is None
    assert rejection is not None
    assert any("excerpt number 47" in reason for reason in rejection.reasons)


def test_an_excerpt_with_real_numbers_passes() -> None:
    draft, rejection = validate(
        candidate(
            title="Page declares no canonical URL",
            summary="The DOM snapshot has no canonical link.",
            suggested_fix="Add a canonical link pointing at the preferred URL.",
            evidence=[
                EvidenceRef(
                    observation_id=DOM_ID,
                    kind="dom",
                    excerpt="images_total: 12, images_missing_alt: 3",
                )
            ],
        ),
        observations=observations(),
        agent="seo",
    )
    assert rejection is None, rejection.reasons if rejection else None
    assert draft is not None


def test_a_standard_constant_in_the_summary_is_not_a_measurement() -> None:
    """'24 by 24 CSS pixels' is the rule the claim rests on, not a measured value."""
    draft, rejection = validate(
        candidate(
            rule_id="A11Y-TARGET-SIZE",
            category="a11y",
            severity="major",
            title="Interactive target is smaller than 24 by 24 CSS pixels",
            summary="The target is below the 24 by 24 CSS pixel minimum at this viewport.",
            suggested_fix="Increase the target to at least 24 by 24 CSS pixels.",
            criterion="WCAG-2.5.8",
            evidence=[EvidenceRef(observation_id=RESPONSIVE_ID, kind="responsive")],
        ),
        observations=observations(),
        agent="a11y",
    )
    assert rejection is None, rejection.reasons if rejection else None
    assert draft is not None


def test_the_viewport_of_a_citation_is_a_fact() -> None:
    """'390x844' names where the measurement happened, so both numbers are supported."""
    draft, rejection = validate(
        candidate(
            rule_id="A11Y-TARGET-SIZE",
            category="a11y",
            severity="major",
            title="Interactive target is below the minimum",
            summary="Measured at 390x844, the header link is 16 by 20 pixels.",
            suggested_fix="Increase the target to at least 24 by 24 CSS pixels.",
            criterion="WCAG-2.5.8",
            evidence=[EvidenceRef(observation_id=RESPONSIVE_ID, kind="responsive")],
        ),
        observations=observations(),
        agent="a11y",
    )
    assert rejection is None, rejection.reasons if rejection else None
    assert draft is not None


def test_a_number_that_is_neither_measured_nor_in_the_claim_is_rejected() -> None:
    draft, rejection = validate(
        candidate(
            rule_id="A11Y-TARGET-SIZE",
            category="a11y",
            severity="major",
            summary="Measured at 390x844, the link is 17 by 20 pixels.",
            suggested_fix="Increase the target to at least 24 by 24 CSS pixels.",
            criterion="WCAG-2.5.8",
            evidence=[EvidenceRef(observation_id=RESPONSIVE_ID, kind="responsive")],
        ),
        observations=observations(),
        agent="a11y",
    )
    assert draft is None
    assert rejection is not None
    assert any("number 17" in reason for reason in rejection.reasons)


def test_the_stored_observation_kind_is_also_accepted() -> None:
    draft, rejection = validate(
        candidate(evidence=[EvidenceRef(observation_id=DOM_ID, kind="dom_snapshot")]),
        observations=observations(),
        agent="seo",
    )
    assert rejection is None, rejection.reasons if rejection else None
    assert draft is not None


def test_evidence_kind_must_match_the_cited_observation() -> None:
    """A DOM observation cited as 'axe' would put a false channel in the report."""
    draft, rejection = validate(
        candidate(evidence=[EvidenceRef(observation_id=DOM_ID, kind="axe")]),
        observations=observations(),
        agent="seo",
    )
    assert draft is None
    assert rejection is not None
    assert any("evidence kind axe does not match" in reason for reason in rejection.reasons)
