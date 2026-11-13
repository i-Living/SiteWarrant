import re

import pytest

from app.fixes.patch import (
    FixError,
    contrast_ratio,
    darken_until,
    fix_h1,
    fix_lang,
    fix_meta_description,
    fix_occlusion,
    fix_title,
    patch_for,
    selector_of,
)

PAGE = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <style>
    .muted { color: #555555; }
    </style>
  </head>
  <body>
    <h2>Field notes from the coast</h2>
    <p>Prints and notebooks from a small studio.</p>
    <a class="icon" href="/x"><svg aria-hidden="true"></svg></a>
  </body>
</html>
"""


def test_title_comes_from_the_heading_that_exists() -> None:
    fixed, note = fix_title(PAGE)
    assert "<title>Field notes from the coast</title>" in fixed
    assert "heading" in note


def test_title_replaces_an_empty_one() -> None:
    fixed, _ = fix_title(PAGE.replace('<meta charset="utf-8">', "<title></title>"))
    assert fixed.count("<title>") == 1
    assert "<title>Field notes from the coast</title>" in fixed


def test_description_comes_from_the_first_paragraph() -> None:
    fixed, _ = fix_meta_description(PAGE)
    assert '<meta name="description" content="Prints and notebooks from a small studio.">' in fixed


def test_a_long_paragraph_is_shortened_without_cutting_a_word() -> None:
    long_page = PAGE.replace("Prints and notebooks from a small studio.", "word " * 60)
    fixed, _ = fix_meta_description(long_page)
    match = re.search(r'<meta name="description" content="(.*?)">', fixed)
    assert match is not None
    description = match.group(1)
    assert description.endswith("…")
    assert len(description) <= 155
    assert not description.endswith(" …")
    # The page text itself is left alone: the description quotes it, it does not replace it.
    assert "word word word" in fixed


def test_h1_is_promoted_when_the_page_has_none() -> None:
    fixed, note = fix_h1(PAGE)
    assert "<h1>Field notes from the coast</h1>" in fixed
    assert "<h2>" not in fixed
    assert "h2" in note


def test_a_page_that_already_has_an_h1_is_left_alone() -> None:
    with pytest.raises(FixError):
        fix_h1(PAGE.replace("<h2>", "<h1>").replace("</h2>", "</h1>"))


def test_lang_is_declared_on_the_html_element() -> None:
    fixed, note = fix_lang(PAGE)
    assert '<html lang="en">' in fixed
    assert 'lang="en"' in note


def test_a_page_that_declares_a_language_is_not_touched() -> None:
    with pytest.raises(FixError):
        fix_lang(PAGE.replace("<html>", '<html lang="de">'))


def test_occlusion_is_fixed_by_taking_the_occluder_out_of_the_flow() -> None:
    fixed, note = fix_occlusion(PAGE, occluder_selector="header > div.promo")
    assert ".promo { position: static !important; }" in fixed
    assert fixed.index(".promo { position: static") > fixed.index(".muted")
    assert "promo" in note


def test_a_selector_is_the_last_segment_of_a_path() -> None:
    assert selector_of("html > body > header > div.promo") == ".promo"
    assert selector_of("html > body > header > a#cta") == "#cta"
    assert selector_of("html > body > header > nav") == "nav"


def test_a_failing_colour_is_darkened_until_it_passes() -> None:
    assert contrast_ratio("#9aa0a6", "#ffffff") < 4.5
    passing = darken_until("#9aa0a6", "#ffffff")
    assert contrast_ratio(passing, "#ffffff") >= 4.5
    assert passing != "#9aa0a6"


def test_only_the_five_mechanical_rules_get_a_patch() -> None:
    assert patch_for("SEO-TITLE", "http://x/", PAGE) is not None
    assert patch_for("SEO-META-DESC", "http://x/", PAGE) is not None
    assert patch_for("SEO-H1", "http://x/", PAGE) is not None
    assert patch_for("A11Y-LANG", "http://x/", PAGE) is not None
    assert (
        patch_for("LAYOUT-OCCLUSION", "http://x/", PAGE, subject="header > div.promo") is not None
    )
    # An accessibility defect whose repair needs a human sentence is never patched.
    assert patch_for("A11Y-IMG-ALT", "http://x/", PAGE) is None
    assert patch_for("A11Y-LINK-NAME", "http://x/", PAGE) is None


def test_a_patch_that_would_change_nothing_is_not_a_patch() -> None:
    page_with_h1 = PAGE.replace("<h2>", "<h1>").replace("</h2>", "</h1>")
    assert patch_for("SEO-H1", "http://x/", page_with_h1) is None


def test_the_occlusion_patch_needs_the_occluder() -> None:
    assert patch_for("LAYOUT-OCCLUSION", "http://x/", PAGE) is None
