"""Screenshot a stored report page, so a reviewer can see it without running the stack.

CI runs this after building the web app and serving one audit: the page is the product's face,
and a contract test on JSX does not show whether the cause headings, the severities and the
evidence lines actually render (docs/PLAN.md, P4 «Осталось из плана»).

    uv run --project api python scripts/report_screenshot.py \
        --url "http://127.0.0.1:3000/?audit=<audit_id>" --out report-page.png

`?audit=` is the URL the page has always accepted; a page that redirects it to `/audits/<id>` is
followed, so the capture survives a route rename.

Exits 2 when the page renders nothing recognisable — a screenshot of an error page is worse than
no artifact, because it looks like one.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# The report page must show findings before the capture is worth keeping. A page that says "report
# unavailable" is an error state, and a screenshot of it looks like an artifact while saying the
# opposite of what happened.
ERROR_TEXT = ("report unavailable", "no audit selected")
REPORT_TEXT = re.compile(r"\d+\s+finding", re.IGNORECASE)


def capture(url: str, out: Path, *, width: int, height: int, timeout_ms: int) -> str:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_selector("main", timeout=timeout_ms)
            text = page.inner_text("main") or ""
            lowered = text.lower()
            if any(marker in lowered for marker in ERROR_TEXT):
                return f"the page rendered an error state: {text[:200]!r}"
            if not REPORT_TEXT.search(text):
                return f"the page shows no finding count: {text[:200]!r}"
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out), full_page=True)
            return ""
        finally:
            browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    args = parser.parse_args(argv)

    try:
        problem = capture(
            args.url, args.out, width=args.width, height=args.height, timeout_ms=args.timeout_ms
        )
    except (PlaywrightTimeout, PlaywrightError) as error:
        print(f"screenshot failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    if problem:
        print(f"screenshot rejected: {problem}", file=sys.stderr)
        return 2
    print(f"report page captured to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
