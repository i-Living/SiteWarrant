"""Screenshot a stored report page, so a reviewer can see it without running the stack.

CI runs this after building the web app and serving one audit: the page is the product's face,
and a contract test on JSX does not show whether the cause headings, the severities and the
evidence lines actually render (docs/PLAN.md, P4 «Осталось из плана»).

    SITEWARRANT_AUTH_LOGIN=… SITEWARRANT_AUTH_PASSWORD=… \
        uv run --project api python scripts/report_screenshot.py \
        --url "http://127.0.0.1:3000/?audit=<audit_id>" --out report-page.png

Every route but `/login` needs a session, so a closed web app redirects the capture to the sign-in
form. The credentials are read from the same environment variables the web app uses, and the capture
signs in like a person: the gate is what the artifact is supposed to exercise, so the job does not
turn it off. A redirect without credentials is reported as such, not as a missing finding count.

`?audit=` is the URL the page has always accepted; a page that redirects it to `/audits/<id>` is
followed, so the capture survives a route rename.

Exits 2 when the page renders nothing recognisable — a screenshot of an error page is worse than
no artifact, because it looks like one.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# The report page must show findings before the capture is worth keeping. A page that says "report
# unavailable" is an error state, and a screenshot of it looks like an artifact while saying the
# opposite of what happened.
ERROR_TEXT = ("report unavailable", "no audit selected")
REPORT_TEXT = re.compile(r"\d+\s+finding", re.IGNORECASE)
LOGIN_PATH = "/login"


def credentials_from_env() -> tuple[str, str] | None:
    """The operator credentials the web app was started with, or None when it is open."""
    login = os.environ.get("SITEWARRANT_AUTH_LOGIN", "")
    password = os.environ.get("SITEWARRANT_AUTH_PASSWORD", "")
    if not login or not password:
        return None
    return login, password


def capture(
    url: str,
    out: Path,
    *,
    width: int,
    height: int,
    timeout_ms: int,
    credentials: tuple[str, str] | None,
) -> str:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            if urlsplit(page.url).path == LOGIN_PATH:
                if credentials is None:
                    return (
                        "the page redirected to /login: set SITEWARRANT_AUTH_LOGIN and "
                        "SITEWARRANT_AUTH_PASSWORD to capture a report behind the session"
                    )
                login, password = credentials
                page.fill("#login", login)
                page.fill("#password", password)
                page.click(".login-submit")
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
                if urlsplit(page.url).path == LOGIN_PATH:
                    return f"sign-in was refused: the page stayed on {page.url}"
                # Stay on the page the login redirected to. A loopback or proxied app answers
                # with the origin the browser reached (`localhost` for a `127.0.0.1` request),
                # and the session cookie is stored for that origin: re-requesting the literal
                # URL we were given would arrive without it and bounce back to /login.
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
            args.url,
            args.out,
            width=args.width,
            height=args.height,
            timeout_ms=args.timeout_ms,
            credentials=credentials_from_env(),
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
