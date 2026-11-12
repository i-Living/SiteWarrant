from playwright.async_api import Page
from pydantic import BaseModel

# Largest Contentful Paint and Layout Shift are only observable through an observer, and the
# observer has to exist before the page starts painting. This script is installed before
# navigation; without it getEntriesByType('largest-contentful-paint') is always empty.
INIT_SCRIPT = """(() => {
  window.__sitewarrant = { lcp: null, cls: 0, tbt: 0 };
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) window.__sitewarrant.lcp = entry.startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (error) { /* not every browser build exposes LCP */ }
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) window.__sitewarrant.cls += entry.value;
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (error) { /* layout-shift is Chromium-only */ }
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__sitewarrant.tbt += Math.max(0, entry.duration - 50);
      }
    }).observe({ type: 'longtask', buffered: true });
  } catch (error) { /* longtask is Chromium-only */ }
})()"""

PROBE_SCRIPT = """() => {
  const navigation = performance.getEntriesByType('navigation')[0];
  const paints = performance.getEntriesByType('paint');
  const firstContentful = paints.find((entry) => entry.name === 'first-contentful-paint');
  const observed = window.__sitewarrant || { lcp: null, cls: 0, tbt: 0 };
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
    cumulative_layout_shift: Math.round((observed.cls || 0) * 1000) / 1000,
    total_blocking_time_ms: round(observed.tbt),
    resource_count: resources.length,
    transfer_bytes: transfer,
  };
}"""


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
    resource_count: int = 0
    transfer_bytes: int = 0


async def probe(page: Page) -> PerformanceFacts:
    raw = await page.evaluate(PROBE_SCRIPT)
    return PerformanceFacts.model_validate(raw)
