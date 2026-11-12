import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.agents.models import (
    CandidateFinding,
    ObservationFacts,
    Rejection,
    ValidationResult,
)
from app.rules import corpus
from app.rules.catalog import SEVERITY_WEIGHTS, Severity
from app.rules.engine import EvidenceDraft, FindingDraft

# A claim id or a criterion id contains digits, and those digits are not measurements.
IDENTIFIER = re.compile(r"\b(?:WCAG|SC)\s*\d+(?:\.\d+)+\b|\b[A-Z][A-Z0-9]*(?:-[A-Z0-9.]+)+\b")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
DECIMALS = re.compile(r"[.,](\d+)")
# An agent that writes "nine images" is making the same claim as one that writes "9".
NUMBER_WORDS: dict[str, int] = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "hundred": 100,
}
WORD_NUMBER = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)

ObservationIndex = Mapping[str, ObservationFacts]


def claimed_numbers(text: str) -> list[str]:
    """Numbers a reader would take as measurements, with rule and criterion ids removed.

    Spelled-out numbers count too: "nine images" asserts the same thing as "9 images", and a
    validator that only reads digits would let a fabricated count through.
    """
    stripped = IDENTIFIER.sub(" ", text)
    found = [match.group(0) for match in NUMBER.finditer(stripped)]
    found.extend(
        str(NUMBER_WORDS[match.group(1).lower()]) for match in WORD_NUMBER.finditer(stripped)
    )
    return found


def payload_numbers(payload: dict[str, Any]) -> list[float]:
    return [
        float(match.group(0).replace(",", ".")) for match in NUMBER.finditer(json.dumps(payload))
    ]


def number_is_corroborated(claimed: str, observed: Sequence[float]) -> bool:
    """A claimed number is corroborated when an observed value rounds to it.

    The comparison uses the precision the agent wrote: a claim of 4.5 is supported by a
    measured 4.4959, and a claim of 4.50 needs the same measurement, because both round to
    what the agent asserted. Rounding the other way — making the observation fit the claim —
    is exactly the move the validator exists to stop.
    """
    value = float(claimed.replace(",", "."))
    decimals = DECIMALS.search(claimed)
    places = len(decimals.group(1)) if decimals else 0
    return any(round(observed_value, places) == round(value, places) for observed_value in observed)


def severity_is_allowed(claimed: Severity, floor: Severity) -> bool:
    """An agent may escalate a claim, never soften it: severity is the corpus's decision."""
    return SEVERITY_WEIGHTS[claimed] >= SEVERITY_WEIGHTS[floor]


def validate(
    candidate: CandidateFinding, *, observations: ObservationIndex, agent: str
) -> tuple[FindingDraft | None, Rejection | None]:
    reasons: list[str] = []
    claim = corpus.claim_by_id(candidate.rule_id)
    if claim is None:
        return None, Rejection(
            rule_id=candidate.rule_id,
            reasons=[f"rule_id {candidate.rule_id} is not a claim in the rule corpus"],
        )
    assert claim.category is not None and claim.severity is not None
    if claim.category != candidate.category:
        reasons.append(
            f"claim {claim.id} belongs to {claim.category}, the finding says {candidate.category}"
        )
    if not severity_is_allowed(candidate.severity, claim.severity):
        reasons.append(
            f"claim {claim.id} carries severity {claim.severity}; "
            f"{candidate.severity} would soften it"
        )

    cited: list[ObservationFacts] = []
    for evidence in candidate.evidence:
        facts = observations.get(evidence.observation_id)
        if facts is None:
            reasons.append(f"observation {evidence.observation_id} does not exist in this audit")
            continue
        if claim.observation_tools and facts.tool not in claim.observation_tools:
            reasons.append(
                f"claim {claim.id} may only cite {'/'.join(claim.observation_tools)}, "
                f"observation {evidence.observation_id} comes from {facts.tool}"
            )
            continue
        cited.append(facts)

    if not cited and not reasons:
        reasons.append("no citable observation survived the checks")

    # The numbers a citation can support: the payload, and the viewport the observation was
    # taken at ("390x844" is where the measurement happened, so 390 and 844 are facts too).
    observed = [number for facts in cited for number in payload_numbers(facts.payload)]
    for facts in cited:
        if facts.viewport:
            observed.extend(payload_numbers({"viewport": facts.viewport}))

    # A claim's own text carries the standard's constants ("24 by 24 CSS pixels", "4.5:1").
    # Repeating a rule is not asserting a measurement, so those are allowed anywhere in the
    # finding; a number that is neither measured nor part of the claim is still rejected.
    constants = [
        float(value.replace(",", "."))
        for value in claimed_numbers(" ".join([claim.title, claim.body, claim.suggested_fix or ""]))
    ]
    supported = observed + constants
    for text in (candidate.title, candidate.summary, candidate.suggested_fix):
        for claimed in claimed_numbers(text):
            if not number_is_corroborated(claimed, supported):
                reasons.append(f"number {claimed} is not in the cited observations")

    if candidate.category == "a11y":
        if candidate.criterion is None:
            reasons.append("accessibility findings must cite a WCAG criterion id")
        else:
            criterion = corpus.criterion_by_id(candidate.criterion)
            if criterion is None:
                reasons.append(f"criterion {candidate.criterion} is not in the corpus")
            elif claim.wcag is not None and claim.wcag != criterion.id:
                reasons.append(
                    f"claim {claim.id} rests on {claim.wcag}, the finding cites {criterion.id}"
                )

    if reasons:
        return None, Rejection(rule_id=candidate.rule_id, reasons=reasons)

    draft = FindingDraft(
        rule_id=claim.id,
        category=claim.category,
        severity=candidate.severity,
        title=candidate.title,
        summary=candidate.summary,
        suggested_fix=candidate.suggested_fix,
        impact_conversion=candidate.impact.conversion,
        impact_seo=candidate.impact.seo,
        impact_ux=candidate.impact.ux,
        confidence=candidate.confidence,
        agent=agent,
        evidence=[
            EvidenceDraft(
                observation_id=evidence.observation_id,
                kind=evidence.kind,
                excerpt=evidence.excerpt,
            )
            for evidence in candidate.evidence
        ],
    )
    return draft, None


def validate_all(
    candidates: Sequence[CandidateFinding], *, observations: ObservationIndex, agent: str
) -> ValidationResult:
    accepted: list[CandidateFinding] = []
    rejected: list[Rejection] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for candidate in candidates:
        _draft, rejection = validate(candidate, observations=observations, agent=agent)
        if rejection is not None:
            rejected.append(rejection)
            continue
        key = (candidate.rule_id, tuple(sorted(item.observation_id for item in candidate.evidence)))
        if key in seen:
            continue
        seen.add(key)
        accepted.append(candidate)
    return ValidationResult(accepted=accepted, rejected=rejected)


def drafts_for(
    result: ValidationResult, *, observations: ObservationIndex, agent: str
) -> list[FindingDraft]:
    drafts: list[FindingDraft] = []
    for candidate in result.accepted:
        draft, _ = validate(candidate, observations=observations, agent=agent)
        if draft is not None:
            drafts.append(draft)
    return drafts
