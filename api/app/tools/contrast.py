import re
from collections.abc import Sequence

from playwright.async_api import Page
from pydantic import BaseModel

# WCAG 2.2 SC 1.4.3 Contrast (Minimum): 4.5:1 for normal text, 3:1 for large text.
# Large text is 18 pt (24 CSS px) or 14 pt bold (18.66 CSS px).
NORMAL_TEXT_MIN = 4.5
LARGE_TEXT_MIN = 3.0
LARGE_TEXT_PX = 24.0
LARGE_BOLD_PX = 18.66
MAX_SAMPLES = 400

COLLECT_SCRIPT = """() => {
  const MAX = 400;
  const path = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      const parent = node.parentElement;
      let index = 1;
      if (parent) {
        for (const sibling of parent.children) {
          if (sibling === node) break;
          if (sibling.tagName === node.tagName) index += 1;
        }
      }
      parts.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + index + ')');
      node = parent;
    }
    return parts.join(' > ');
  };
  // Only rgba() carries alpha: the fourth number of rgb() is the blue channel. Splitting on
  // non-numeric characters avoids a regex whose escaping is easy to get wrong.
  const alphaOf = (value) => {
    const numbers = value.replace(/[^0-9.%]/g, ' ').trim().split(/ +/);
    if (numbers.length < 4) return 1;
    const last = numbers[numbers.length - 1];
    return last.endsWith('%') ? Number(last.slice(0, -1)) / 100 : Number(last);
  };
  const background = (el) => {
    let node = el;
    while (node && node.nodeType === 1) {
      const value = getComputedStyle(node).backgroundColor;
      if (value && value !== 'transparent' && alphaOf(value) > 0) {
        return value;
      }
      node = node.parentElement;
    }
    return 'rgb(255, 255, 255)';
  };
  const samples = [];
  for (const element of document.body ? document.body.querySelectorAll('*') : []) {
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) {
      continue;
    }
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    let text = '';
    for (const child of element.childNodes) {
      if (child.nodeType === 3) text += child.nodeValue || '';
    }
    text = text.trim().replace(/\\s+/g, ' ');
    if (!text) continue;
    samples.push({
      selector: path(element),
      text: text.slice(0, 80),
      color: style.color,
      background: background(element),
      font_size: parseFloat(style.fontSize),
      bold: Number(style.fontWeight) >= 700,
    });
    if (samples.length >= MAX) break;
  }
  return samples;
}"""

RGB = tuple[int, int, int]
# Red, green, blue and alpha: the alpha has to survive parsing, because a translucent
# colour renders as a different colour than the same channels at full opacity.
RGBA = tuple[int, int, int, float]
WHITE: RGB = (255, 255, 255)
COLOR = re.compile(
    r"rgba?\(\s*(\d+)\s*[,\s]\s*(\d+)\s*[,\s]\s*(\d+)\s*(?:[,/]\s*([\d.]+)(%?)\s*)?\)"
)


class ColorSample(BaseModel):
    selector: str
    text: str
    color: str
    background: str
    font_size: float
    bold: bool


class ContrastReport(BaseModel):
    """The channel's own record: how many pairs were measured, how many failed."""

    checked: int
    violations: list["ContrastViolation"]


class ContrastViolation(BaseModel):
    """A measured pair below the WCAG threshold, with the threshold that applies.

    `ratio` keeps full precision: WCAG forbids rounding before the comparison, and a stored
    4.5 for a pair that measured 4.496 would claim a pass the page does not have.
    """

    selector: str
    text: str
    ratio: float
    required: float
    font_size: float
    bold: bool
    color: str
    background: str


def parse_color(value: str) -> RGBA | None:
    """Parse a computed colour, keeping its alpha.

    `rgb()` has three channels and is opaque; only `rgba()` and the slash syntax carry alpha.
    """
    match = COLOR.search(value)
    if match is None:
        return None
    red, green, blue = (int(part) for part in match.groups()[:3])
    alpha_text = match.group(4)
    alpha = 1.0
    if alpha_text is not None:
        alpha = float(alpha_text)
        if match.group(5) == "%":
            alpha /= 100
        alpha = min(max(alpha, 0.0), 1.0)
    return (red, green, blue, alpha)


def composite(color: RGBA, backdrop: RGB) -> RGB:
    """Flatten a translucent colour onto its backdrop, as the screen does."""
    red, green, blue, alpha = color
    if alpha >= 1.0:
        return (red, green, blue)
    return (
        round(red * alpha + backdrop[0] * (1 - alpha)),
        round(green * alpha + backdrop[1] * (1 - alpha)),
        round(blue * alpha + backdrop[2] * (1 - alpha)),
    )


def channel_luminance(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: RGB) -> float:
    red, green, blue = (channel_luminance(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: RGBA, background: RGBA) -> float:
    """WCAG 2.2 relative contrast ratio of the rendered pair, unrounded.

    Both colours are composited before measuring: the page shows the composited pair, so
    dropping alpha would measure a colour the user never sees.
    """
    base = composite(background, WHITE)
    shown = composite(foreground, base)
    light, dark = sorted((relative_luminance(shown), relative_luminance(base)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def required_ratio(font_size_px: float, bold: bool) -> float:
    """The threshold for this text, from the criterion rather than from the tool."""
    large = font_size_px >= LARGE_TEXT_PX or (bold and font_size_px >= LARGE_BOLD_PX)
    return LARGE_TEXT_MIN if large else NORMAL_TEXT_MIN


def violations(samples: Sequence[ColorSample]) -> list[ContrastViolation]:
    found: list[ContrastViolation] = []
    for sample in samples:
        foreground = parse_color(sample.color)
        background = parse_color(sample.background)
        if foreground is None or background is None:
            continue
        ratio = contrast_ratio(foreground, background)
        needed = required_ratio(sample.font_size, sample.bold)
        if ratio >= needed:
            continue
        found.append(
            ContrastViolation(
                selector=sample.selector,
                text=sample.text,
                ratio=ratio,
                required=needed,
                font_size=sample.font_size,
                bold=sample.bold,
                color=sample.color,
                background=sample.background,
            )
        )
    return found


async def probe(page: Page) -> ContrastReport:
    raw = await page.evaluate(COLLECT_SCRIPT)
    samples = [ColorSample.model_validate(item) for item in raw[:MAX_SAMPLES]]
    return ContrastReport(checked=len(samples), violations=violations(samples))
