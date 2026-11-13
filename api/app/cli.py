import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

import typer

from app.agents.specs import parse_agent_names
from app.audit import run_audit
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.report import Report, exit_code_for
from app.core.version import compute_agent_version
from app.crawl.crawler import crawl as crawl_site
from app.crawl.models import CrawlLimits
from app.eval.compare import compare_runs
from app.eval.dataset import DatasetError
from app.eval.gate import decide
from app.eval.models import EvalRun
from app.eval.runner import run_eval
from app.fixes.reaudit import ReauditError, reaudit
from app.fixes.recommend import FixBuildError, build_fixes, write_fix_files
from app.rules import store
from app.rules.catalog import RULES
from app.survey import run_survey
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
        llm_model=settings.llm_model,
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
    agents: str = typer.Option(
        "",
        "--agents",
        help="Comma-separated auditor agents (seo,a11y,...) or 'all'. Empty runs only the "
        "deterministic layer.",
    ),
) -> None:
    """Audit a single page and write a JSON report.

    Exit codes: 0 clean, 1 a blocker was proven, 2 the audit itself failed.
    """
    try:
        names = parse_agent_names(agents) if agents.strip() else []
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    try:
        report = asyncio.run(
            run_audit(
                url,
                allow_private=allow_private,
                ignore_robots=ignore_robots,
                agents=names,
            )
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
    if summary.agents:
        typer.echo(
            "agents: "
            + " ".join(f"{run.name}={run.status}({run.findings})" for run in summary.agents)
        )
        if report.status != "completed":
            typer.echo(f"status: {report.status}")
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


@cli.command()
def survey(
    url: str = typer.Argument(..., help="Start URL of the site to survey."),
    out: Path = typer.Option(
        Path("survey.json"), "--out", "-o", help="Where to write the merged report."
    ),
    max_pages: int = typer.Option(50, "--max-pages", min=1, max=2000),
    max_depth: int = typer.Option(3, "--max-depth", min=0, max=10),
    pages_per_template: int = typer.Option(
        2,
        "--pages-per-template",
        min=1,
        max=50,
        help=(
            "How many pages of one template to audit. A documentation site is a handful of "
            "templates, so this cap and --max-pages decide the coverage together."
        ),
    ),
    allow_private: bool = typer.Option(
        False,
        "--allow-private",
        help="Permit the surveyed host even when it resolves to a private address.",
    ),
    ignore_robots: bool = typer.Option(
        False,
        "--ignore-robots",
        help="Survey even where robots.txt disallows this user agent. Use only on sites you own.",
    ),
    agents: str = typer.Option(
        "", "--agents", help="Comma-separated auditor agents, or 'all'. Empty is deterministic."
    ),
) -> None:
    """Audit every page a crawl selects and write one report for the site.

    Exit codes: 0 no blocker found, 1 a blocker was proven, 2 the survey itself failed.
    """
    settings = get_settings()
    allowed_private_hosts = settings.allowed_private_host_set
    if allow_private:
        surveyed_host = urlsplit(url).hostname
        if surveyed_host:
            allowed_private_hosts = allowed_private_hosts | {surveyed_host.lower()}
    try:
        names = parse_agent_names(agents) if agents.strip() else []
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    limits = CrawlLimits(
        max_pages=max_pages, max_depth=max_depth, pages_per_template=pages_per_template
    )
    try:
        result = asyncio.run(
            run_survey(
                url,
                limits=limits,
                settings=settings,
                allowed_private_hosts=allowed_private_hosts,
                allow_private=allow_private,
                ignore_robots=ignore_robots,
                agents=names,
            )
        )
    except Exception as error:
        typer.echo(f"survey failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    report = result.report
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(
        f"{result.crawl.pages_discovered} page(s) discovered, "
        f"{report.summary.pages_audited} audited, {len(result.failures)} failed"
    )
    typer.echo(
        f"{len(report.findings)} finding(s) in {len(report.root_causes)} root cause(s) "
        f"over {report.summary.pages_audited} page(s)"
    )
    severities = " ".join(f"{name}={count}" for name, count in report.summary.by_severity.items())
    typer.echo(f"severities: {severities}")
    for page, reason in result.failures:
        typer.echo(f"  failed {page}: {reason}", err=True)
    typer.echo(f"report written to {out}")
    raise typer.Exit(code=exit_code_for(report))


@cli.command("eval")
def evaluate(
    dataset: Path = typer.Option(
        Path("benchmark/dataset.json"),
        "--dataset",
        help="Dataset manifest, or a directory holding dataset.json.",
    ),
    out: Path = typer.Option(
        Path("evals/runs/latest.json"), "--out", help="Where to write the run."
    ),
    sites: str = typer.Option("", "--sites", help="Comma separated site slugs; default is all."),
    agents: str = typer.Option("", "--agents", help="Comma separated agent names, or 'all'."),
    compare: Path | None = typer.Option(
        None, "--compare", help="Baseline run to diff this one against."
    ),
) -> None:
    """Audit the frozen corpus and report precision, recall and false-positive rate."""
    manifest = dataset / "dataset.json" if dataset.is_dir() else dataset
    try:
        run = asyncio.run(
            run_eval(
                manifest,
                sites=[item.strip() for item in sites.split(",") if item.strip()] or None,
                agents=[item.strip() for item in agents.split(",") if item.strip()] or None,
            )
        )
    except DatasetError as error:
        typer.echo(f"dataset: {error}", err=True)
        raise typer.Exit(code=2) from error

    # Read the baseline first: writing the candidate over a mistyped path is not recoverable.
    baseline = (
        None
        if compare is None
        else EvalRun.model_validate_json(compare.read_text(encoding="utf-8"))
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
    _print_eval(run)
    typer.echo(f"run written to {out}")

    if baseline is None:
        return
    comparison = compare_runs(baseline, run, baseline_label=str(compare), candidate_label=str(out))
    typer.echo("")
    typer.echo(f"compare {comparison.baseline} -> {comparison.candidate}: {comparison.note}")
    if not comparison.compatible:
        raise typer.Exit(code=2)
    for metric, delta in comparison.deltas.items():
        typer.echo(f"  {metric:<24} {delta:+.4f}")
    for rule_id, rule_delta in comparison.per_rule.items():
        typer.echo(
            f"  {rule_id:<22} precision {rule_delta['precision']:+.4f}  "
            f"recall {rule_delta['recall']:+.4f}"
        )
    typer.echo(f"  regressions: {', '.join(comparison.regressions) or 'none'}")
    if comparison.regressions:
        raise typer.Exit(code=1)


def _print_eval(run: EvalRun) -> None:
    metrics = run.metrics
    typer.echo(
        f"sites {len(run.per_site)}, pages {metrics['pages']}, labels {metrics['labels']}, "
        f"agent {run.context.agent_version}"
    )
    typer.echo(
        f"predicted {metrics['predicted']}: tp {metrics['true_positives']}, "
        f"fp {metrics['false_positives']}, fn {metrics['false_negatives']}"
    )
    typer.echo(
        f"precision {metrics['precision']} ({metrics['true_positives']}/{metrics['predicted']}), "
        f"recall {metrics['recall']} ({metrics['true_positives']}/{metrics['labels']}), "
        f"fp-rate {metrics['false_positive_rate']} "
        f"({metrics['false_positives']}/{metrics['predicted']})"
    )
    typer.echo(
        f"pages with false positives {metrics['pages_with_false_positives']}/{metrics['pages']}, "
        f"duplicate rate {metrics['duplicate_rate']} "
        f"({metrics['duplicates_removed']}/{metrics['findings_raw']})"
    )
    typer.echo(f"runtime {run.context.duration_s} s")
    for rule_id, rule in metrics["per_rule"].items():
        typer.echo(
            f"  {rule_id:<20} p={rule['precision']:<7} r={rule['recall']:<7} "
            f"labels {rule['labels']} predicted {rule['predicted']}"
        )


@cli.command("prompt-check")
def prompt_check_command(
    baseline: Path = typer.Option(
        ..., "--baseline", help="The run the change is measured against."
    ),
    candidate: Path = typer.Option(
        ..., "--candidate", help="The run measured with the new prompts."
    ),
    tolerance: float = typer.Option(
        0.0, "--tolerance", help="Measurement noise allowed on precision."
    ),
) -> None:
    """Accept a prompt change only when precision did not regress."""
    before = EvalRun.model_validate_json(baseline.read_text(encoding="utf-8"))
    after = EvalRun.model_validate_json(candidate.read_text(encoding="utf-8"))
    decision = decide(before, after, tolerance=tolerance)

    typer.echo(f"corpus {decision.corpus}")
    for reason in decision.reasons:
        typer.echo(f"  {reason}")
    typer.echo(f"{decision.verdict}")
    if not decision.accepted:
        raise typer.Exit(code=1)


@cli.command("fix")
def fix_command(
    audit_id: str = typer.Argument(..., help="Audit id to turn into recommendations."),
    out: Path | None = typer.Option(None, "--out", help="Directory for the fix files."),
    site_dir: Path | None = typer.Option(
        None, "--site-dir", help="Static site directory the patch is computed against."
    ),
) -> None:
    """Recommendations for every finding, unified diff for the mechanically fixable rules."""
    try:
        report = asyncio.run(build_fixes(audit_id, site_dir=site_dir))
    except (FixBuildError, ValueError) as error:
        typer.echo(f"fix: {error}", err=True)
        raise typer.Exit(code=2) from error

    target = out or Path("fixes") / audit_id
    write_fix_files(report, target)
    typer.echo(
        f"{len(report.recommendations)} recommendation(s), {report.patchable} with a patch, "
        f"{len(report.patches)} hunk(s)"
    )
    for item in report.recommendations:
        marker = "patch" if item.patched else ("advisory" if item.note else "text")
        typer.echo(f"  {item.rule_id:<20} {item.severity:<8} {marker:<8} {item.page_url}")
    typer.echo(f"written to {target}")


@cli.command("reaudit")
def reaudit_command(
    audit_id: str = typer.Argument(..., help="Audit id whose pages are re-audited."),
    against: Path = typer.Option(
        ..., "--against-report", help="The earlier report.json to compare with."
    ),
    site_dir: Path | None = typer.Option(
        None, "--site-dir", help="Static site directory the patch applies to."
    ),
    patch_file: Path | None = typer.Option(
        None, "--patch", help="Unified diff to apply to a copy of --site-dir first."
    ),
) -> None:
    """Re-audit a page and report what closed, what stayed and what broke."""
    before = Report.model_validate_json(against.read_text(encoding="utf-8"))
    if audit_id and audit_id != before.audit_id:
        typer.echo(
            f"reaudit: {against} is the report of audit {before.audit_id}, not {audit_id}",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        result = asyncio.run(reaudit(before, site_dir=site_dir, patch_file=patch_file))
    except ReauditError as error:
        typer.echo(f"reaudit: {error}", err=True)
        raise typer.Exit(code=2) from error

    typer.echo(
        f"pages {result.pages}: closed {len(result.closed)}, "
        f"remaining {len(result.remaining)}, new {len(result.new)}"
    )
    for label, items in (
        ("closed", result.closed),
        ("remaining", result.remaining),
        ("new", result.new),
    ):
        for item in items:
            typer.echo(f"  {label:<9} {item.rule_id:<20} {item.severity:<8} {item.page_url}")
    if result.regressions:
        typer.echo(f"regressions: {len(result.regressions)}")
        raise typer.Exit(code=1)


@cli.command("index-rules")
def index_rules() -> None:
    """Load the rule corpus into Postgres with its embeddings.

    Idempotent: the corpus digest decides whether anything is rewritten.
    """

    async def run() -> int:
        async with session_scope() as session:
            return await store.ensure_indexed(session)

    count = asyncio.run(run())
    typer.echo(f"indexed {count} corpus chunk(s)")
    raise typer.Exit(code=0)


def main() -> None:
    cli()
