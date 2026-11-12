import pytest

from app.tools.contrast import (
    LARGE_TEXT_MIN,
    NORMAL_TEXT_MIN,
    ColorSample,
    contrast_ratio,
    parse_color,
    required_ratio,
    violations,
)

OPAQUE_BLACK = (0, 0, 0, 1.0)
OPAQUE_WHITE = (255, 255, 255, 1.0)


def test_black_on_white_is_the_maximum_ratio() -> None:
    assert contrast_ratio(OPAQUE_BLACK, OPAQUE_WHITE) == pytest.approx(21.0)


def test_identical_colours_have_no_contrast() -> None:
    assert contrast_ratio((120, 120, 120, 1.0), (120, 120, 120, 1.0)) == pytest.approx(1.0)


def test_ratio_is_symmetric() -> None:
    assert contrast_ratio(OPAQUE_BLACK, OPAQUE_WHITE) == pytest.approx(
        contrast_ratio(OPAQUE_WHITE, OPAQUE_BLACK)
    )


def test_fixture_grey_on_white_is_below_the_threshold() -> None:
    """#9aa0a6 on white is the fixture's planted contrast defect."""
    grey = parse_color("rgb(154, 160, 166)")
    assert grey is not None
    ratio = contrast_ratio(grey, OPAQUE_WHITE)
    assert ratio < NORMAL_TEXT_MIN
    assert 2.5 <= ratio <= 2.7


def test_parse_color_keeps_the_alpha_and_never_reads_blue_as_alpha() -> None:
    """rgb(0, 0, 0) is opaque black; only rgba() has a fourth component."""
    assert parse_color("rgb(0, 0, 0)") == (0, 0, 0, 1.0)
    assert parse_color("rgb(1, 2, 3)") == (1, 2, 3, 1.0)
    assert parse_color("rgba(1, 2, 3, 0.5)") == (1, 2, 3, 0.5)
    assert parse_color("rgb(0 0 0 / 50%)") == (0, 0, 0, 0.5)
    assert parse_color("transparent") is None


def test_translucent_text_is_measured_as_rendered() -> None:
    """rgba(0,0,0,0.2) on white renders near #cccccc, not black."""
    faint = parse_color("rgba(0, 0, 0, 0.2)")
    assert faint is not None
    ratio = contrast_ratio(faint, OPAQUE_WHITE)
    assert ratio == pytest.approx(1.61, abs=0.05)
    assert ratio < NORMAL_TEXT_MIN


def test_a_translucent_background_is_composited_over_white() -> None:
    """Half-opacity white over white is still white."""
    half_white = parse_color("rgba(255, 255, 255, 0.5)")
    assert half_white is not None
    assert contrast_ratio(OPAQUE_BLACK, half_white) == pytest.approx(21.0, abs=0.2)


def test_contrast_ratio_is_not_rounded_before_the_comparison() -> None:
    """4.496 must not become 4.5 and pass: WCAG forbids rounding here."""
    grey = parse_color("rgb(117, 119, 121)")
    assert grey is not None
    ratio = contrast_ratio(grey, OPAQUE_WHITE)
    assert ratio < NORMAL_TEXT_MIN
    assert ratio > 4.49


@pytest.mark.parametrize(
    ("size", "bold", "expected"),
    [
        (16.0, False, NORMAL_TEXT_MIN),
        (23.9, False, NORMAL_TEXT_MIN),
        (24.0, False, LARGE_TEXT_MIN),
        (18.66, True, LARGE_TEXT_MIN),
        (18.0, True, NORMAL_TEXT_MIN),
        (14.0, True, NORMAL_TEXT_MIN),
    ],
)
def test_threshold_follows_the_criterion(size: float, bold: bool, expected: float) -> None:
    assert required_ratio(size, bold) == expected


def sample(color: str, background: str, size: float = 16.0, bold: bool = False) -> ColorSample:
    return ColorSample(
        selector="p:nth-of-type(1)",
        text="Prices start at 40 EUR",
        color=color,
        background=background,
        font_size=size,
        bold=bold,
    )


def test_low_contrast_body_text_is_reported_with_its_threshold() -> None:
    found = violations([sample("rgb(154, 160, 166)", "rgb(255, 255, 255)")])
    assert len(found) == 1
    assert found[0].required == NORMAL_TEXT_MIN
    assert found[0].ratio < found[0].required


def test_large_text_may_pass_at_the_lower_threshold() -> None:
    """3.4:1 fails for body text and passes for 24 px text — the same pair, two verdicts."""
    pair = "rgb(120, 120, 120)"
    assert violations([sample(pair, "rgb(255, 255, 255)")])
    assert not violations([sample(pair, "rgb(255, 255, 255)", size=24.0)])


def test_a_borderline_pair_is_reported_not_rounded_away() -> None:
    found = violations([sample("rgb(117, 119, 121)", "rgb(255, 255, 255)")])
    assert len(found) == 1
    assert found[0].ratio < NORMAL_TEXT_MIN


def test_unparseable_colour_is_not_a_finding() -> None:
    assert violations([sample("currentcolor", "rgb(255, 255, 255)")]) == []
