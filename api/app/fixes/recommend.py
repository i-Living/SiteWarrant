"""Recommendations for every finding, patches for the rules that can be repaired mechanically."""

from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.core.db import session_scope
from app.core.models import Finding, Observation, Page, Snapshot
from app.fixes.patch import FIXABLE, Patch, passing_colour, patch_for


class FixBuildError(ValueError):
    """The audit cannot be turned into fixes: no page, no captured HTML."""


@dataclass(frozen=True)
class Recommendation:
    rule_id: str
    page_url: str
    severity: str
    text: str
    patched: bool
    note: str | None = None


@dataclass
class FixReport:
    audit_id: str
    recommendations: list[Recommendation] = field(default_factory=list)
    patches: list[Patch] = field(default_factory=list)
    diff: str = ""

    @property
    def patchable(self) -> int:
        return sum(1 for item in self.recommendations if item.patched)


def unified_diff(patch: Patch, *, path: str | None = None) -> str:
    target = path or patch.page_url
    lines = difflib.unified_diff(
        patch.before.splitlines(keepends=True),
        patch.after.splitlines(keepends=True),
        fromfile=f"a/{target}",
        tofile=f"b/{target}",
        n=2,
    )
    return "".join(lines)


async def build_fixes(audit_id: str, site_dir: Path | None = None) -> FixReport:
    """Read the audit's findings and the page source, and say how each one gets repaired.

    Patches are computed against the source file when `site_dir` names the site, because a browser
    serialises its DOM: a diff made from the captured HTML reorders attributes and fails to apply.
    Without a source directory the diff is advisory and says so.
    """
    identifier = uuid.UUID(audit_id)
    async with session_scope() as session:
        findings = (
            (await session.execute(select(Finding).where(Finding.audit_id == identifier)))
            .scalars()
            .all()
        )
        pages = {
            page.id: page
            for page in (
                await session.execute(select(Page).where(Page.audit_id == identifier))
            ).scalars()
        }
        # Which element covered which: keyed by the covered selector, because that is what a
        # finding's `subject` names. An empty hit list is a page with nothing covered.
        occluders: dict[uuid.UUID, dict[str, str]] = {}
        observation_rows = (
            await session.execute(select(Observation).where(Observation.page_id.in_(list(pages))))
        ).scalars()
        for row in observation_rows:
            if row.tool != "occlusion":
                continue
            for hit in row.payload.get("hits") or []:
                if not isinstance(hit, dict):
                    continue
                covered = str(hit.get("selector") or "")
                covering = str(hit.get("occluder_selector") or "")
                if covered and covering:
                    occluders.setdefault(row.page_id, {})[covered] = covering
        snapshots = {
            snapshot.page_id: snapshot
            for snapshot in (
                await session.execute(select(Snapshot).where(Snapshot.page_id.in_(list(pages))))
            ).scalars()
        }
        rows = [
            (
                finding.rule_id,
                finding.severity,
                finding.suggested_fix,
                finding.subject,
                pages[finding.page_id].url if finding.page_id in pages else "",
                _html_key(snapshots.get(finding.page_id)),
                _occluder_for(occluders.get(finding.page_id, {}), finding.subject),
            )
            for finding in findings
        ]

    if not rows:
        raise FixBuildError(f"audit {audit_id} has no findings")
    report = FixReport(audit_id=audit_id)
    working: dict[str, str] = {}
    notes: dict[str, list[str]] = {}
    originals: dict[str, str] = {}
    for rule_id, severity, suggestion, subject, page_url, html_key, occluder in rows:
        patch: Patch | None = None
        if rule_id in FIXABLE and html_key and page_url and site_dir is not None:
            html = working.get(page_url) or _source_of(page_url, html_key, site_dir)
            if html is not None:
                originals.setdefault(page_url, html)
                # For an occlusion the fix moves the covering element, never the covered one:
                # `subject` names the target a click failed to reach.
                patch = patch_for(
                    rule_id,
                    page_url,
                    html,
                    subject=occluder if rule_id == "LAYOUT-OCCLUSION" else subject,
                )
                if patch is not None:
                    working[page_url] = patch.after
                    notes.setdefault(page_url, []).append(patch.note)
        note: str | None = None
        if rule_id not in FIXABLE:
            note = "recommendation only: repairing this means writing text a machine cannot invent"
        elif site_dir is None:
            # Browsers serialise the DOM they were given: a diff of that snapshot reorders
            # attributes and does not apply to the file a human edits.
            note = "no patch: pass --site-dir so the diff is computed against the served source"
        elif patch is None:
            note = "no patch: the source does not offer what this fix would need"
        report.recommendations.append(
            Recommendation(
                rule_id=rule_id,
                page_url=page_url,
                severity=severity,
                text=suggestion,
                patched=patch is not None,
                note=note,
            )
        )

    # One diff per page, composed in order: two patches computed against the same bytes would
    # overlap, and the second would not apply to the result of the first.
    for page_url, final in working.items():
        before = originals[page_url]
        if before == final:
            continue
        report.patches.append(
            Patch(
                rule_id=",".join(
                    sorted(
                        {
                            item.rule_id
                            for item in report.recommendations
                            if item.page_url == page_url and item.patched
                        }
                    )
                ),
                page_url=page_url,
                before=before,
                after=final,
                note="; ".join(notes.get(page_url, [])),
            )
        )
    report.diff = "".join(
        unified_diff(patch, path=_relative(patch.page_url)) for patch in report.patches
    )
    return report


def _source_of(page_url: str, html_key: str, site_dir: Path | None) -> str | None:
    if site_dir is not None:
        candidate = site_dir / _relative(page_url)
        if candidate.is_file():
            return _with_final_newline(candidate.read_text(encoding="utf-8"))
    return _read(html_key)


def _occluder_for(occluders: dict[str, str], subject: str | None) -> str:
    if subject and subject in occluders:
        return occluders[subject]
    return next(iter(occluders.values()), "")


def _html_key(snapshot: Snapshot | None) -> str | None:
    return snapshot.html_key if snapshot is not None else None


def _read(key: str) -> str | None:
    from app.audit import artifact_path

    target = artifact_path(key)
    if not target.exists():
        return None
    return _with_final_newline(target.read_text(encoding="utf-8"))


def _with_final_newline(text: str) -> str:
    """A diff of a file whose last line has no newline applies with a warning at best."""
    return text if text.endswith("\n") or not text else text + "\n"


def _relative(url: str) -> str:
    """The file a URL is served from: `/` and `/products/` are index files, not directories."""
    from urllib.parse import urlsplit

    path = urlsplit(url).path.lstrip("/")
    if not path or path.endswith("/"):
        return f"{path}index.html"
    return path


def contrast_hint(foreground: str, background: str) -> str:
    """What a human needs when the recommendation is 'use a darker colour'."""
    passing = passing_colour(foreground, background)
    return f"{foreground} on {background} fails; {passing} passes at 4.5:1 or better"


def write_fix_files(report: FixReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# Fixes for audit {report.audit_id}", ""]
    lines.append(f"{len(report.recommendations)} findings, {report.patchable} with a patch.")
    lines.append("")
    for item in report.recommendations:
        lines.append(f"## {item.rule_id} ({item.severity}) — {item.page_url}")
        lines.append("")
        lines.append(item.text)
        if item.note:
            lines.append("")
            lines.append(f"_{item.note}_")
        lines.append("")
    (out_dir / "recommendations.md").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "fixes.patch").write_text(report.diff, encoding="utf-8")
    return out_dir
