"""Re-audit a page after a patch and say what closed, what stayed and what broke."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from app.audit import run_audit
from app.core.report import FindingOut, Report


class ReauditError(ValueError):
    """The patch cannot be applied, so there is nothing to re-audit."""


@dataclass(frozen=True)
class Delta:
    rule_id: str
    page_url: str
    severity: str


@dataclass
class ReauditResult:
    closed: list[Delta] = field(default_factory=list)
    remaining: list[Delta] = field(default_factory=list)
    new: list[Delta] = field(default_factory=list)
    regressions: list[Delta] = field(default_factory=list)
    pages: int = 0

    @property
    def regression_count(self) -> int:
        return len(self.regressions)


def key_of(finding: FindingOut) -> tuple[str, str, str]:
    """A finding is the same defect when the rule, the page and the subject match."""
    return (finding.rule_id, path_of(finding.page_url), (finding.subject or "").strip())


def path_of(url: str) -> str:
    return urlsplit(url).path or "/"


def diff_findings(before: list[FindingOut], after: list[FindingOut]) -> ReauditResult:
    """Closed, remaining and new; every new finding is a regression until a human says otherwise."""
    previous = {key_of(finding): finding for finding in before}
    current = {key_of(finding): finding for finding in after}
    result = ReauditResult()
    for key, finding in previous.items():
        delta = Delta(rule_id=finding.rule_id, page_url=finding.page_url, severity=finding.severity)
        (result.remaining if key in current else result.closed).append(delta)
    for key, finding in current.items():
        if key in previous:
            continue
        delta = Delta(rule_id=finding.rule_id, page_url=finding.page_url, severity=finding.severity)
        result.new.append(delta)
        result.regressions.append(delta)
    return result


def apply_patch(site_dir: Path, patch_file: Path) -> Path:
    """Copy the site, apply the patch to the copy, and return the copy.

    The patch is computed from the HTML the audit captured, so it applies where the served page is
    the source. A client-rendered page is captured after its scripts ran: the diff there is advice,
    not a commit, and this refuses rather than pretending otherwise.
    """
    if not site_dir.is_dir():
        raise ReauditError(f"{site_dir} is not a directory")
    if not patch_file.is_file():
        raise ReauditError(f"{patch_file} is not a file")
    copy = Path(tempfile.mkdtemp(prefix="sitewarrant-reaudit-")) / "site"
    shutil.copytree(site_dir, copy)
    result = subprocess.run(
        ["patch", "-p1", "--forward", "--batch", "-i", str(patch_file.resolve())],
        cwd=copy,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReauditError(f"patch failed: {result.stdout}{result.stderr}".strip())
    return copy


class PatchedSite:
    """Serve the patched copy on loopback so the audit re-reads it under its own guard."""

    def __init__(self, root: Path) -> None:
        handler = partial(SimpleHTTPRequestHandler, directory=str(root))
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}"

    def __enter__(self) -> PatchedSite:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


async def reaudit(
    before: Report,
    *,
    site_dir: Path | None = None,
    patch_file: Path | None = None,
) -> ReauditResult:
    """Re-audit every page of a previous report, from the site or from its patched copy."""
    targets = sorted({finding.page_url for finding in before.findings})
    if not targets:
        raise ReauditError("the previous report has no findings to re-audit")
    if patch_file is not None and site_dir is None:
        raise ReauditError("--patch needs --site-dir: the copy has to come from somewhere")

    after: list[FindingOut] = []
    if patch_file is not None:
        assert site_dir is not None
        copy = apply_patch(site_dir, patch_file)
        with PatchedSite(copy) as server:
            for url in targets:
                report = await run_audit(
                    server.base_url + path_of(url), allow_private=True, agents=()
                )
                after.extend(_rebase(report.findings, server.base_url))
    else:
        for url in targets:
            report = await run_audit(url, allow_private=True, agents=())
            after.extend(report.findings)

    result = diff_findings(before.findings, after)
    result.pages = len(targets)
    return result


def _rebase(findings: list[FindingOut], base_url: str) -> list[FindingOut]:
    """Report the patched copy's findings under the original URL, so keys line up."""
    rebased: list[FindingOut] = []
    for finding in findings:
        rebased.append(
            finding.model_copy(update={"page_url": base_url + path_of(finding.page_url)})
        )
    return rebased
