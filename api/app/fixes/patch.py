"""Deterministic fixes: five rules can be repaired from the facts, the rest need a human.

A patch is a suggestion with evidence behind it, not a promise: it is computed from the HTML the
audit captured, so it applies cleanly where the served page is the source (a static site) and stays
advisory where the HTML is produced at runtime. The rules chosen here are the ones whose repair does
not require inventing text: a language attribute, a heading level, a title taken from the heading
that already exists, a description taken from the paragraph that already exists, and a darker shade
of the colour that failed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Rules whose repair is mechanical. Everything else gets a recommendation and no diff: an
# automatic patch that invents a name or alt text hides a defect instead of fixing it.
FIXABLE = ("SEO-TITLE", "SEO-META-DESC", "SEO-H1", "A11Y-LANG", "LAYOUT-OCCLUSION")

TAG_RE = re.compile(r"<[^>]+>")


class FixError(ValueError):
    """The page does not offer what the fix needs (no heading to borrow a title from)."""


@dataclass(frozen=True)
class Patch:
    rule_id: str
    page_url: str
    before: str
    after: str
    note: str


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", fragment)).strip()


def first_heading(html: str) -> str | None:
    for level in (1, 2, 3):
        match = re.search(rf"<h{level}[^>]*>(.*?)</h{level}>", html, flags=re.S | re.I)
        if match:
            text = text_of(match.group(1))
            if text:
                return text
    return None


def first_paragraph(html: str) -> str | None:
    match = re.search(r"<p[^>]*>(.*?)</p>", html, flags=re.S | re.I)
    if not match:
        return None
    text = text_of(match.group(1))
    return text or None


def shorten(text: str, limit: int = 155) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def fix_title(html: str) -> tuple[str, str]:
    heading = first_heading(html)
    if heading is None:
        raise FixError("the page has no heading to take a title from")
    title = f"<title>{heading}</title>"
    if re.search(r"<title[^>]*>.*?</title>", html, flags=re.S | re.I):
        fixed = re.sub(r"<title[^>]*>.*?</title>", title, html, count=1, flags=re.S | re.I)
        return fixed, "rewrote the existing <title> from the page heading"
    if "</head>" not in html:
        raise FixError("the page has no </head> to insert a title into")
    inserted = html.replace("</head>", f"    {title}\n  </head>", 1)
    return inserted, "added a <title> from the page heading"


def fix_meta_description(html: str) -> tuple[str, str]:
    paragraph = first_paragraph(html)
    if paragraph is None:
        raise FixError("the page has no paragraph to take a description from")
    description = shorten(paragraph)
    tag = f'<meta name="description" content="{description}">'
    existing = re.search(r'<meta[^>]+name=["\']description["\'][^>]*>', html, flags=re.I)
    if existing:
        fixed = html.replace(existing.group(0), tag, 1)
        return fixed, "rewrote the existing meta description from the first paragraph"
    if "</head>" not in html:
        raise FixError("the page has no </head> to insert a description into")
    inserted = html.replace("</head>", f"    {tag}\n  </head>", 1)
    return inserted, "added a meta description from the first paragraph"


def fix_h1(html: str) -> tuple[str, str]:
    if re.search(r"<h1[^>]*>", html, flags=re.I):
        raise FixError("the page already has an h1")
    for level in (2, 3):
        match = re.search(rf"<h{level}([^>]*)>(.*?)</h{level}>", html, flags=re.S | re.I)
        if match:
            fixed = (
                html[: match.start()]
                + f"<h1{match.group(1)}>{match.group(2)}</h1>"
                + html[match.end() :]
            )
            return fixed, f"promoted the first h{level} to h1"
    raise FixError("the page has no heading to promote")


def fix_lang(html: str, default: str = "en") -> tuple[str, str]:
    if re.search(r"<html[^>]*\blang=", html, flags=re.I):
        raise FixError("the page already declares a language")
    if "<html" not in html:
        raise FixError("the page has no <html> element")
    match = re.search(r"<html([^>]*)>", html, flags=re.I)
    assert match is not None
    fixed = html[: match.start()] + f'<html{match.group(1)} lang="{default}">' + html[match.end() :]
    return fixed, f'declared lang="{default}" on <html>'


def _channel(value: int) -> float:
    return value / 255


def _linear(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    raw = hex_colour.lstrip("#")
    if len(raw) == 3:
        raw = "".join(channel * 2 for channel in raw)
    red, green, blue = (int(raw[index : index + 2], 16) for index in (0, 2, 4))
    return (
        0.2126 * _linear(_channel(red))
        + 0.7152 * _linear(_channel(green))
        + 0.0722 * _linear(_channel(blue))
    )


def contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def darken_until(hex_colour: str, background: str, target: float = 4.5) -> str:
    """Walk the colour towards black until it passes; the hue survives, the lightness does not."""
    raw = hex_colour.lstrip("#")
    if len(raw) == 3:
        raw = "".join(channel * 2 for channel in raw)
    red, green, blue = (int(raw[index : index + 2], 16) for index in (0, 2, 4))
    for step in range(1, 101):
        scale = 1 - step / 100
        candidate = f"#{int(red * scale):02x}{int(green * scale):02x}{int(blue * scale):02x}"
        if contrast_ratio(candidate, background) >= target:
            return candidate
    return "#000000"


def selector_of(path: str) -> str:
    """The last segment of a DOM path, as a CSS selector a stylesheet can use."""
    segment = path.split(">")[-1].strip()
    if not segment:
        raise FixError("the occluder has no selector")
    tag = segment.partition(":")[0]
    classes = re.findall(r"\.([A-Za-z0-9_-]+)", tag)
    if classes:
        return "." + ".".join(classes)
    identifier = re.search(r"#([A-Za-z0-9_-]+)", tag)
    if identifier:
        return "#" + identifier.group(1)
    return tag.lower() if tag else "body"


def fix_occlusion(html: str, *, occluder_selector: str) -> tuple[str, str]:
    """Let the occluding element take part in the flow, so it stops covering its neighbours."""
    selector = selector_of(occluder_selector)
    rule = f"    {selector} {{ position: static !important; }}\n"
    if "</style>" not in html:
        raise FixError("the page has no inline stylesheet to add the override to")
    index = html.rindex("</style>")
    start_of_rule = html.rfind("\n", 0, index)
    fixed = f"{html[:start_of_rule]}\n{rule}{html[start_of_rule:]}"
    return fixed, f"stopped {selector} from being positioned over its neighbours"


def passing_colour(foreground: str, background: str, target: float = 4.5) -> str:
    """The nearest darker shade of a failing colour; reported, not applied."""
    return darken_until(foreground, background, target)


def patch_for(
    rule_id: str, page_url: str, html: str, *, subject: str | None = None
) -> Patch | None:
    """The patch for one finding, or None when this rule is recommendation-only.

    `subject` is the occluder for `LAYOUT-OCCLUSION`; the other four rules read the page alone.
    """
    if rule_id not in FIXABLE:
        return None
    try:
        if rule_id == "SEO-TITLE":
            after, note = fix_title(html)
        elif rule_id == "SEO-META-DESC":
            after, note = fix_meta_description(html)
        elif rule_id == "SEO-H1":
            after, note = fix_h1(html)
        elif rule_id == "A11Y-LANG":
            after, note = fix_lang(html)
        else:
            if subject is None:
                raise FixError("the occlusion finding does not name the covering element")
            after, note = fix_occlusion(html, occluder_selector=subject)
    except FixError:
        return None
    if after == html:
        return None
    return Patch(rule_id=rule_id, page_url=page_url, before=html, after=after, note=note)
