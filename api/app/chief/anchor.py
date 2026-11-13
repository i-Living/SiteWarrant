"""Deterministic reading of where a finding lives.

A root cause is a place on the page, not a rule family: one banner can produce an occlusion
finding, a contrast finding and a broken accessible name. The place is read from the selectors
the cited observations already contain, so clustering never asks a model what belongs together
(docs/PLAN.md, invariant 3).
"""

from collections.abc import Iterable
from typing import Any

SELECTOR_KEYS = {"selector", "occluder_selector", "target", "targets", "path", "dom_path"}
# Containers that hold most of the page carry no information about a cause.
GENERIC_ANCHORS = {"body", "html", "#document", "main", "app", "root"}
SEPARATOR = " > "


def selectors_in(value: Any, *, under_selector_key: bool = False) -> list[str]:
    """Every selector-shaped string in a payload, keys excluded."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(selectors_in(item, under_selector_key=key in SELECTOR_KEYS))
        return found
    if isinstance(value, (list, tuple)):
        for item in value:
            found.extend(selectors_in(item, under_selector_key=under_selector_key))
        return found
    if isinstance(value, str) and under_selector_key and SEPARATOR in value:
        text = value.strip()
        if text:
            # Only paths under a selector key count. Free text ("main > pricing" in a note, a
            # heading in an attribute) names no element, and axe also emits single-segment
            # selectors (".icon-link"), which name no place at all.
            found.append(text)
    return found


def segments(selector: str) -> list[str]:
    return [part.strip() for part in selector.split(">") if part.strip()]


def common_prefix(paths: Iterable[list[str]]) -> list[str]:
    sequences = [path for path in paths if path]
    if not sequences:
        return []
    prefix = sequences[0]
    for path in sequences[1:]:
        limit = 0
        while limit < min(len(prefix), len(path)) and prefix[limit] == path[limit]:
            limit += 1
        prefix = prefix[:limit]
    return prefix


def without_generic_heads(path: list[str]) -> list[str]:
    """Drop the page-wide wrappers so the anchor names the block, not the document."""
    trimmed = list(path)
    while trimmed and trimmed[0].split(":")[0].strip().lower() in GENERIC_ANCHORS:
        trimmed.pop(0)
    return trimmed


def _normalize(segment: str) -> str:
    return segment.split(":nth-of-type")[0].strip().lower()


def anchor_for_selectors(selectors: Iterable[str]) -> str | None:
    """The block every cited element sits in, or None when they do not agree.

    One selector names its own block (the first segment that is not a page wrapper). A finding
    that cites elements from different blocks belongs to no single block, and clustering it
    would invent a cause.
    """
    paths = [without_generic_heads(segments(selector)) for selector in selectors]
    if not paths:
        return None
    heads: list[str] = []
    for path in paths:
        if len(path) < 2:
            return None
        heads.append(path[0])
    if len(set(heads)) != 1:
        return None
    # Agreement is decided on the raw segment: section:nth-of-type(1) and section:nth-of-type(2)
    # are different blocks even though both are called "section". Only the label is normalized.
    return _normalize(heads[0])


def anchor_for_evidence(
    observation_ids: Iterable[str],
    observations: dict[str, dict[str, Any]],
    *,
    subject: str | None = None,
) -> str | None:
    """Where the finding lives, resolved from its own target when it names one.

    An observation can cover many elements: an occlusion report holds up to twenty hits from
    across the page, and one finding per hit cites that same report. Reading every selector in
    the payload would collect the footer's hits too, so the heads disagree and the finding would
    lose its place. The subject names the element the finding is about, so it wins when the cited
    payload actually holds it as a selector; otherwise the cited payloads decide.
    """
    selectors: list[str] = []
    for observation_id in observation_ids:
        payload = observations.get(observation_id)
        if payload is None:
            continue
        selectors.extend(selectors_in(payload))
    if subject is not None:
        own = subject.strip()
        # The validator only proves the subject appears somewhere in the payload, so a breadcrumb
        # ("Home > Products") would otherwise pass for a path. The override stands only when the
        # cited observation itself holds this selector.
        if own and own in selectors:
            anchor = anchor_for_selectors([own])
            if anchor is not None:
                return anchor
    return anchor_for_selectors(selectors)
