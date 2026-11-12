from app.tools.responsive import (
    TOUCH_TARGET_MIN_PX,
    OverflowItem,
    ResponsiveReport,
    TouchTarget,
    has_horizontal_overflow,
    overflow_px,
)


def report(document_width: int, viewport_width: int = 390) -> ResponsiveReport:
    return ResponsiveReport(
        viewport_width=viewport_width,
        document_width=document_width,
        overflowing=[],
        small_targets=[],
    )


def test_a_wider_document_overflows() -> None:
    assert has_horizontal_overflow(report(420)) is True
    assert overflow_px(report(420)) == 30


def test_a_one_pixel_rounding_difference_is_not_overflow() -> None:
    assert has_horizontal_overflow(report(391)) is False
    assert overflow_px(report(391)) == 0


def test_a_narrower_document_does_not_overflow() -> None:
    assert has_horizontal_overflow(report(300)) is False


def test_touch_target_threshold_is_the_wcag_minimum() -> None:
    assert TOUCH_TARGET_MIN_PX == 24.0


def test_items_are_typed() -> None:
    item = OverflowItem(selector="div:nth-of-type(1)", tag="div", right_px=420, width_px=300)
    target = TouchTarget(selector="a:nth-of-type(1)", tag="a", width_px=12.5, height_px=30.0)
    assert item.right_px == 420
    assert target.width_px < TOUCH_TARGET_MIN_PX
