import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import typer

from app.audit import run_audit
from app.core.config import get_settings
from app.core.report import exit_code_for
from app.core.version import compute_agent_version
from app.crawl.crawler import crawl as crawl_site
from app.crawl.models import CrawlLimits
from app.rules.catalog import RULES
from app.tools.axe import AXE_VERSION

cli = typer.Typer(add_completion=False, no_args_is_help=True, help="SiteWarrant command line.")


@cli.command()
def version() -> None:
    """Print the agent version and the size of the rule catalog."""
    settings = get_settings()
    agent_version = compute_agent_version(
        viewports=settings.viewport_list,
        page_timeout_ms=settings.page_timeout_ms,
        capture_timeout_ms=settings.capture_timeout_ms,
        user_agent=settings.user_agent,
    )
    typer.echo(f"sitewarrant 0.1.0 agent={agent_version} rules={len(RULES)} axe={AXE_VERSION}")


@cli.command()
def audit(
    url: str = typer.Argument(..., help="Page URL to audit."),
    out: Path = typer.Option(
        Path("report.json"), "--out", "-o", help="Where to write the JSON report."
    ),
    allow_private: bool = typer.Option(
        False,
        "--allow-private",
        help=(
            "Permit the audited host even when it resolves to a private address. "
            "Only that host is exempt, not every private address."
        ),
    ),
    ignore_robots: bool = typer.Option(
        False,
        "--ignore-robots",
        help="Audit even when robots.txt disallows this user agent. Use only on sites you own.",
    ),
) -> None:
    """Audit a single page and write a JSON report.

    Exit codes: 0 clean, 1 a blocker was proven, 2 the audit itself failed.
    """
    try:
        report = asyncio.run(
            run_audit(url, allow_private=allow_private, ignore_robots=ignore_robots)
        )
    except Exception as error:
        typer.echo(f"audit failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary = report.summary
    severities = " ".join(f"{name}={count}" for name, count in summary.by_severity.items())
    typer.echo(f"{summary.findings_total} finding(s) on {summary.pages_audited} page(s)")
    typer.echo(f"severities: {severities}")
    typer.echo(f"report written to {out}")
    raise typer.Exit(code=exit_code_for(report))


@cli.command()
def crawl(
    url: str = typer.Argument(..., help="Start URL of the site to crawl."),
    out: Path = typer.Option(
        Path("pages.json"), "--out", "-o", help="Where to write the crawl report."
    ),
    max_pages: int = typer.Option(50, "--max-pages", min=1, max=2000),
    max_depth: int = typer.Option(3, "--max-depth", min=0, max=10),
    pages_per_template: int = typer.Option(2, "--pages-per-template", min=1, max=50),
    sitemap: bool = typer.Option(True, "--sitemap/--no-sitemap", help="Seed from sitemap.xml."),
    render: bool = typer.Option(
        True, "--render/--no-render", help="Re-read app shells through the browser."
    ),
    allow_private: bool = typer.Option(
        False,
        "--allow-private",
        help="Permit the crawled host even when it resolves to a private address.",
    ),
    ignore_robots: bool = typer.Option(
        False,
        "--ignore-robots",
        help="Crawl even where robots.txt disallows this user agent. Use only on sites you own.",
    ),
) -> None:
    """Discover the pages of a site and pick the ones worth auditing.

    Exit codes: 0 crawl finished, 2 the crawl itself failed.
    """
    settings = get_settings()
    allowed_private_hosts = settings.allowed_private_host_set
    if allow_private:
        crawled_host = urlsplit(url).hostname
        if crawled_host:
            allowed_private_hosts = allowed_private_hosts | {crawled_host.lower()}
    limits = CrawlLimits(
        max_pages=max_pages,
        max_depth=max_depth,
        pages_per_template=pages_per_template,
        include_sitemap=sitemap,
    )
    try:
        report = asyncio.run(
            crawl_site(
                url,
                limits=limits,
                settings=settings,
                allowed_private_hosts=allowed_private_hosts,
                ignore_robots=ignore_robots,
                render_empty_bodies=render,
            )
        )
    except Exception as error:
        typer.echo(f"crawl failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    typer.echo(f"{report.pages_discovered} page(s) discovered, {report.pages_selected} selected")
    for coverage in report.templates:
        typer.echo(
            f"  {coverage.template} {coverage.discovered} discovered / {coverage.selected} selected"
        )
    if report.skipped:
        typer.echo(
            "skipped: " + " ".join(f"{name}={count}" for name, count in report.skipped.items())
        )
    typer.echo(f"crawl report written to {out}")
    raise typer.Exit(code=0)


def main() -> None:
    cli()
