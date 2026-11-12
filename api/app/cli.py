import asyncio
import json
from pathlib import Path

import typer

from app.audit import run_audit
from app.core.config import get_settings
from app.core.report import exit_code_for
from app.core.version import compute_agent_version
from app.rules.catalog import RULES
from app.tools.axe import AXE_VERSION

cli = typer.Typer(add_completion=False, no_args_is_help=True, help="SiteWarrant command line.")


@cli.command()
def version() -> None:
    """Print the agent version and the size of the rule catalog."""
    settings = get_settings()
    agent_version = compute_agent_version(settings.viewport, settings.page_timeout_ms)
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
        help="Permit loopback and private addresses. Required for the local fixture site.",
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


def main() -> None:
    cli()
