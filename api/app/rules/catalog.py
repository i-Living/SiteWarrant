from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "seo",
    "ux",
    "ui",
    "a11y",
    "performance",
    "security",
    "responsive",
    "conversion",
]
Severity = Literal["blocker", "major", "minor", "info"]
RuleSource = Literal["axe", "dom", "occlusion"]

CATEGORIES: tuple[Category, ...] = (
    "seo",
    "ux",
    "ui",
    "a11y",
    "performance",
    "security",
    "responsive",
    "conversion",
)

SEVERITY_WEIGHTS: dict[Severity, float] = {
    "blocker": 8.0,
    "major": 3.0,
    "minor": 1.0,
    "info": 0.25,
}


class Impact(BaseModel):
    """Estimated effect of a finding, 0 to 3 on each axis (docs/PLAN.md section 3)."""

    conversion: int = Field(default=0, ge=0, le=3)
    seo: int = Field(default=0, ge=0, le=3)
    ux: int = Field(default=0, ge=0, le=3)


class Rule(BaseModel):
    """A claim this project is willing to make about a page.

    Severity is set per rule, not derived from the source tool: axe reports its own
    impact scale, which does not match the definitions in docs/PLAN.md section 3.
    """

    id: str
    category: Category
    severity: Severity
    title: str
    summary: str
    suggested_fix: str
    impact: Impact
    source: RuleSource
    match: str
    wcag: str | None = None


RULES: tuple[Rule, ...] = (
    Rule(
        id="A11Y-LABEL",
        category="a11y",
        severity="blocker",
        title="Form field has no accessible name",
        summary=(
            "A field in the page form has no label, aria-label or title. A screen reader "
            "announces nothing, so the primary action cannot be completed without sight."
        ),
        suggested_fix="Associate a visible <label for> with the field, or add aria-label.",
        impact=Impact(conversion=2, ux=3),
        source="axe",
        match="label",
        wcag="3.3.2",
    ),
    Rule(
        id="A11Y-BUTTON-NAME",
        category="a11y",
        severity="blocker",
        title="Button has no accessible name",
        summary=(
            "A button exposes no text alternative. Voice control and screen readers cannot "
            "address it, so the action behind it is unreachable."
        ),
        suggested_fix="Add visible text, aria-label, or an <svg> with <title> inside the button.",
        impact=Impact(conversion=3, ux=3),
        source="axe",
        match="button-name",
        wcag="4.1.2",
    ),
    Rule(
        id="A11Y-IMG-ALT",
        category="a11y",
        severity="major",
        title="Image has no text alternative",
        summary=(
            "An image carries no alt attribute, so its content is lost for screen reader users "
            "and for search engines."
        ),
        suggested_fix="Add alt text describing the content, or an empty alt if it is decorative.",
        impact=Impact(seo=1, ux=2),
        source="axe",
        match="image-alt",
        wcag="1.1.1",
    ),
    Rule(
        id="A11Y-CONTRAST",
        category="a11y",
        severity="major",
        title="Text contrast below WCAG AA",
        summary=(
            "Text and background do not reach the 4.5:1 ratio required for normal text, which "
            "makes content hard to read in daylight and for low-vision users."
        ),
        suggested_fix="Darken the text or lighten the background until the ratio reaches 4.5:1.",
        impact=Impact(conversion=2, ux=3),
        source="axe",
        match="color-contrast",
        wcag="1.4.3",
    ),
    Rule(
        id="A11Y-LANG",
        category="a11y",
        severity="major",
        title="Page language is not declared",
        summary=(
            "The html element has no lang attribute, so screen readers may read the page with the "
            "wrong pronunciation rules."
        ),
        suggested_fix='Set lang on the html element, for example <html lang="en">.',
        impact=Impact(ux=1),
        source="axe",
        match="html-has-lang",
        wcag="3.1.1",
    ),
    Rule(
        id="A11Y-LINK-NAME",
        category="a11y",
        severity="major",
        title="Link has no accessible name",
        summary=(
            "A link contains no text and no aria-label. Screen reader users hear the raw URL or "
            "nothing at all, and cannot tell where the link leads."
        ),
        suggested_fix="Add link text or aria-label; for icon links describe the destination.",
        impact=Impact(seo=1, ux=2),
        source="axe",
        match="link-name",
        wcag="2.4.4",
    ),
    Rule(
        id="SEO-TITLE",
        category="seo",
        severity="major",
        title="Document title is missing or empty",
        summary=(
            "The page has no usable <title>. Search results show a generated name instead of the "
            "intended one, which costs clicks."
        ),
        suggested_fix="Add a unique 30 to 60 character title that names the page and the brand.",
        impact=Impact(seo=3),
        source="dom",
        match="title",
    ),
    Rule(
        id="SEO-H1",
        category="seo",
        severity="major",
        title="Page has no h1 heading",
        summary=(
            "No first-level heading exists, so the page has no declared main topic for assistive "
            "technology or for search engines."
        ),
        suggested_fix="Promote the page headline to a single <h1>.",
        impact=Impact(seo=2, ux=1),
        source="dom",
        match="h1",
        wcag="1.3.1",
    ),
    Rule(
        id="SEO-META-DESC",
        category="seo",
        severity="minor",
        title="Meta description is missing",
        summary=(
            "Without a meta description, search engines assemble the snippet themselves, which "
            "usually reads worse than a written one."
        ),
        suggested_fix="Add a 120 to 160 character meta description that states the page offer.",
        impact=Impact(seo=2),
        source="dom",
        match="meta_description",
    ),
    Rule(
        id="LAYOUT-OCCLUSION",
        category="responsive",
        severity="major",
        title="An interactive element is covered by another element",
        summary=(
            "A hit test at the centre of an interactive element lands on a different element, "
            "so a pointer user cannot activate it where it appears to be."
        ),
        suggested_fix=(
            "Move the covering element out of the target's box, or let the block reflow so the "
            "target is not covered at this viewport."
        ),
        impact=Impact(conversion=2, ux=2),
        source="occlusion",
        match="occluded_target",
    ),
)


def rule_by_id(rule_id: str) -> Rule | None:
    return next((rule for rule in RULES if rule.id == rule_id), None)


def rule_by_match(source: RuleSource, match: str) -> Rule | None:
    return next((rule for rule in RULES if rule.source == source and rule.match == match), None)
