from collections.abc import Sequence

from playwright.async_api import Page
from pydantic import BaseModel

# Largest Contentful Paint and Layout Shift are only observable through an observer, and the
# observer has to exist before the page starts painting. This script is installed before
# navigation; without it getEntriesByType('largest-contentful-paint') is always empty.
# Raw entries are collected here and turned into metrics in Python, where they are testable.
INIT_SCRIPT = """(() => {
  window.__sitewarrant = { lcp: null, shifts: [], tasks: [], end: null };
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) window.__sitewarrant.lcp = entry.startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (error) { /* not every browser build exposes LCP */ }
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) {
          window.__sitewarrant.shifts.push([entry.startTime, entry.value]);
        }
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (error) { /* layout-shift is Chromium-only */ }
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__sitewarrant.tasks.push([entry.startTime, entry.duration]);
      }
    }).observe({ type: 'longtask', buffered: true });
  } catch (error) { /* longtask is Chromium-only */ }
})()"""

# The measurement interval ends before the geometry probes run: axe, contrast and the
# occlusion hit test execute script, and their long tasks are the auditor's work, not the
# page's.
END_SCRIPT = """() => {
  window.__sitewarrant = window.__sitewarrant || {};
  window.__sitewarrant.end = performance.now();
}"""

PROBE_SCRIPT = """() => {
  const navigation = performance.getEntriesByType('navigation')[0];
  const paints = performance.getEntriesByType('paint');
  const firstContentful = paints.find((entry) => entry.name === 'first-contentful-paint');
  const observed = window.__sitewarrant || { lcp: null, shifts: [], tasks: [], end: null };
  const resources = performance.getEntriesByType('resource');
  let transfer = 0;
  for (const entry of resources) transfer += entry.transferSize || 0;
  const round = (value) => (typeof value === 'number' && Number.isFinite(value)
    ? Math.round(value * 10) / 10
    : null);
  return {
    ttfb_ms: navigation ? round(navigation.responseStart - navigation.startTime) : null,
    dom_content_loaded_ms: navigation ? round(navigation.domContentLoadedEventEnd) : null,
    load_ms: navigation ? round(navigation.loadEventEnd) : null,
    first_contentful_paint_ms: firstContentful ? round(firstContentful.startTime) : null,
    largest_contentful_paint_ms: round(observed.lcp),
    measurement_end_ms: round(observed.end),
    shifts: observed.shifts || [],
    tasks: observed.tasks || [],
    resource_count: resources.length,
    transfer_bytes: transfer,
  };
}"""

# CLS is the largest session window, not the sum of every shift: two shifts a minute apart
# are two windows, and the metric reports the worse one.
CLS_WINDOW_GAP_MS = 1_000.0
CLS_WINDOW_MAX_MS = 5_000.0
LONG_TASK_MS = 50.0


class PerformanceFacts(BaseModel):
    """Lab measurements for one viewport.

    These are not field numbers and not stable between runs: the report says so, and the
    determinism check excludes them. TBT is a proxy for INP, never labelled INP.
    """

    ttfb_ms: float | None = None
    dom_content_loaded_ms: float | None = None
    load_ms: float | None = None
    first_contentful_paint_ms: float | None = None
    largest_contentful_paint_ms: float | None = None
    cumulative_layout_shift: float | None = None
    total_blocking_time_ms: float | None = None
    measurement_end_ms: float | None = None
    layout_shift_count: int = 0
    long_task_count: int = 0
    resource_count: int = 0
    transfer_bytes: int = 0


def cls_session_window(shifts: Sequence[tuple[float, float]]) -> float:
    """Largest session-window score, per the CLS definition.

    A window closes when a shift starts at least one second after the previous one, or when
    the window already spans five seconds.
    """
    best = 0.0
    score = 0.0
    first: float | None = None
    previous: float | None = None
    for start, value in sorted(shifts):
        if (
            first is None
            or previous is None
            or start - previous >= CLS_WINDOW_GAP_MS
            or start - first >= CLS_WINDOW_MAX_MS
        ):
            first = start
            score = 0.0
        score += value
        previous = start
        best = max(best, score)
    return round(best, 4)


def total_blocking_time(
    tasks: Sequence[tuple[float, float]], *, first_paint_ms: float | None, end_ms: float | None
) -> float:
    """Sum of the over-50 ms part of every long task inside [FCP, end of measurement].

    A task that finished before the first paint delayed nothing the user could see, so it
    does not belong in the number.
    """
    if first_paint_ms is None or end_ms is None:
        return 0.0
    total = 0.0
    for start, duration in tasks:
        if start < first_paint_ms or start > end_ms:
            continue
        total += max(0.0, duration - LONG_TASK_MS)
    return round(total, 1)


async def mark_measurement_end(page: Page) -> None:
    await page.evaluate(END_SCRIPT)


async def probe(page: Page) -> PerformanceFacts:
    raw = await page.evaluate(PROBE_SCRIPT)
    shifts = [(float(start), float(value)) for start, value in raw.pop("shifts") or []]
    tasks = [(float(start), float(duration)) for start, duration in raw.pop("tasks") or []]
    return PerformanceFacts.model_validate(
        {
            **raw,
            "cumulative_layout_shift": cls_session_window(shifts),
            "total_blocking_time_ms": total_blocking_time(
                tasks,
                first_paint_ms=raw.get("first_contentful_paint_ms"),
                end_ms=raw.get("measurement_end_ms"),
            ),
            "layout_shift_count": len(shifts),
            "long_task_count": len(tasks),
        }
    )
