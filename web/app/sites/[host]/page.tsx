import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { PageHeader } from "../../components/page-header";
import { SeverityLine } from "../../components/severity-line";
import { StatusStamp } from "../../components/status-stamp";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { getSite, type PageSummary, type SiteDetail } from "../../lib/audits";
import {
  formatDate,
  formatDuration,
  formatMoment,
  isLocalHost,
} from "../../lib/format";
import { cn } from "../../lib/utils";

const SEVERITIES = ["blocker", "major", "minor", "info"] as const;

function comparePages(left: PageSummary, right: PageSummary): number {
  // A failed page has no numbers to compare; it belongs at the top, not at the bottom
  // where a missing severity would sort it.
  const failed =
    Number(right.status === "failed") - Number(left.status === "failed");
  if (failed !== 0) {
    return failed;
  }
  const running =
    Number(right.status === "running") - Number(left.status === "running");
  if (running !== 0) {
    return running;
  }
  for (const severity of SEVERITIES) {
    const diff =
      (right.by_severity?.[severity] ?? 0) -
      (left.by_severity?.[severity] ?? 0);
    if (diff !== 0) {
      return diff;
    }
  }
  return left.page.localeCompare(right.page);
}

function decodeHost(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function PageRow({ page }: { page: PageSummary }) {
  const body = (
    <>
      <div className="min-w-0">
        <p className="truncate font-mono text-sm">{page.page}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          {page.runs > 1 && <>{page.runs} runs · </>}
          {formatDate(page.finished_at ?? page.started_at)}
          {page.duration_ms !== null && (
            <> · took {formatDuration(page.duration_ms)}</>
          )}
        </p>
        {!page.has_report && page.error !== null && (
          <details className="mt-1 text-xs text-muted-foreground">
            <summary className="cursor-pointer">Why it failed</summary>
            <p className="mt-1 font-mono text-[11px] break-words">
              {page.error}
            </p>
          </details>
        )}
      </div>
      <SeverityLine
        counts={page.by_severity}
        total={page.findings_total}
        status={page.status}
      />
      <div className="flex items-center gap-2 md:justify-end">
        <StatusStamp status={page.status} />
        {page.has_report ? (
          <ChevronRight
            className="size-4 text-muted-foreground"
            aria-hidden="true"
          />
        ) : (
          <span className="text-xs text-muted-foreground">no report</span>
        )}
      </div>
    </>
  );

  return (
    <li className="border-t border-border first:border-t-0">
      {page.has_report ? (
        <Link
          href={`/audits/${page.audit_id}`}
          title={`Open the report for ${page.page}`}
          className="grid gap-x-4 gap-y-2 px-4 py-3 transition-colors hover:bg-muted/50 md:grid-cols-[minmax(0,1fr)_12rem_auto] md:items-center"
        >
          {body}
        </Link>
      ) : (
        <div className="grid gap-x-4 gap-y-2 px-4 py-3 md:grid-cols-[minmax(0,1fr)_12rem_auto] md:items-center">
          {body}
        </div>
      )}
    </li>
  );
}

export default async function SitePage({
  params,
}: {
  params: Promise<{ host: string }>;
}) {
  const { host: rawHost } = await params;
  const host = decodeHost(rawHost);
  let site: SiteDetail | null = null;
  let error: string | null = null;
  try {
    site = await getSite(host);
  } catch (cause) {
    // A 500 is not "no such site": say the API failed, or the page reads as an empty host.
    error =
      cause instanceof Error
        ? cause.message
        : "The audit API could not be reached.";
  }

  if (error !== null) {
    return (
      <>
        <h1 className="text-2xl font-semibold tracking-tight">{host}</h1>
        <Card className="mt-4 border-red-200 bg-red-50/60">
          <CardContent className="py-1 text-sm text-red-800">
            <p className="font-medium">{error}</p>
            <p className="mt-1 text-red-700/80">
              The ledger could not be read; retry in a moment.
            </p>
          </CardContent>
        </Card>
        <Button asChild variant="outline" className="mt-4">
          <Link href="/">Back to sites</Link>
        </Button>
      </>
    );
  }

  if (site === null) {
    return (
      <>
        <h1 className="text-2xl font-semibold tracking-tight">
          Site not found
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          No audit exists for {host}.
        </p>
        <Button asChild variant="outline" className="mt-4">
          <Link href="/">Back to sites</Link>
        </Button>
      </>
    );
  }

  const { summary } = site;
  const pages = [...site.pages].sort(comparePages);

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2.5">
            {summary.host}
            {isLocalHost(summary.host) && (
              <Badge variant="outline" className="text-[10px]">
                local
              </Badge>
            )}
          </span>
        }
        meta={
          <>
            <span>
              {summary.runs} {summary.runs === 1 ? "run" : "runs"}
            </span>
            <span aria-hidden="true">·</span>
            <span>last {formatMoment(summary.last_activity)}</span>
            {summary.measured_pages < summary.pages && (
              <>
                <span aria-hidden="true">·</span>
                <span>
                  {summary.measured_pages} of {summary.pages} measured
                </span>
              </>
            )}
            {summary.running > 0 && (
              <Badge
                variant="outline"
                className="gap-1.5 border-blue-200 bg-blue-50 text-blue-700"
              >
                <span className="size-1.5 animate-pulse rounded-full bg-current" />
                {summary.running} running
              </Badge>
            )}
            {summary.failed > 0 && (
              <Badge
                variant="outline"
                className="border-red-200 bg-red-50 text-red-700"
              >
                {summary.failed} failed
              </Badge>
            )}
          </>
        }
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href={`/sites/${encodeURIComponent(summary.host)}/dashboard`}>
              Quality over time
            </Link>
          </Button>
        }
      />

      <Card className="mb-5">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-1">
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-semibold tabular-nums">
              {summary.findings_total ?? "—"}
            </span>
            <span className="text-xs text-muted-foreground">
              {summary.findings_total === 1 ? "finding" : "findings"}
            </span>
          </div>
          <SeverityLine
            counts={summary.by_severity}
            total={summary.findings_total}
            status={summary.running > 0 ? "running" : "completed"}
            coverage={{
              measured: summary.measured_pages,
              pages: summary.pages,
            }}
          />
        </CardContent>
      </Card>

      <Card className="gap-0 overflow-hidden py-0">
        <div className="flex items-center justify-between px-4 py-2.5">
          <h2 className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
            Pages
          </h2>
          <Badge variant="muted">{pages.length}</Badge>
        </div>
        <p className="px-4 pb-2 text-xs text-muted-foreground">
          Latest run per page; failed and running first, then worst severity.
        </p>
        <div className="hidden grid-cols-[minmax(0,1fr)_12rem_auto] gap-x-4 border-t border-border px-4 py-1.5 text-[10px] font-medium tracking-wider text-muted-foreground uppercase md:grid">
          <span>Page</span>
          <span>Findings</span>
          <span className="text-right">Status</span>
        </div>
        <ul className="border-t border-border md:border-t-0">
          {pages.map((page) => (
            <PageRow key={page.page} page={page} />
          ))}
        </ul>
      </Card>

      {pages.some((page) => !page.has_report) && (
        <p className={cn("mt-3 px-1 text-xs text-muted-foreground")}>
          A page without a report was not measured; its row keeps the failure
          reason instead of a zero.
        </p>
      )}
    </>
  );
}
