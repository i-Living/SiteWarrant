import Link from "next/link";
import { HistoryCharts } from "../../../components/history-charts";
import { Kpi } from "../../../components/kpi";
import { PageHeader } from "../../../components/page-header";
import { StatusStamp } from "../../../components/status-stamp";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import {
  getSiteHistory,
  type HistoryRun,
  type SiteHistory,
} from "../../../lib/audits";
import {
  formatCostEstimate,
  formatDuration,
  formatMoment,
  isLocalHost,
} from "../../../lib/format";

function decodeHost(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function lastWhere(
  runs: HistoryRun[],
  predicate: (run: HistoryRun) => boolean,
): HistoryRun | null {
  for (let index = runs.length - 1; index >= 0; index -= 1) {
    if (predicate(runs[index])) {
      return runs[index];
    }
  }
  return null;
}

function value(text: string | number | null): string {
  return text === null ? "—" : String(text);
}

export default async function SiteDashboardPage({
  params,
}: {
  params: Promise<{ host: string }>;
}) {
  const { host: rawHost } = await params;
  const host = decodeHost(rawHost);
  let history: SiteHistory | null = null;
  let error: string | null = null;
  try {
    history = await getSiteHistory(host);
  } catch (cause) {
    // A 500 is not "no such site": say the API failed, or the page reads as an idle host.
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
              The history could not be read; retry in a moment.
            </p>
          </CardContent>
        </Card>
        <Button asChild variant="outline" className="mt-4">
          <Link href={`/sites/${encodeURIComponent(host)}`}>
            Back to the site
          </Link>
        </Button>
      </>
    );
  }

  if (history === null) {
    return (
      <>
        <h1 className="text-2xl font-semibold tracking-tight">
          Site not found
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          No page audit exists for {host}.
        </p>
        <Button asChild variant="outline" className="mt-4">
          <Link href="/">Back to sites</Link>
        </Button>
      </>
    );
  }

  const runs = history.runs;
  const latestMeasured = lastWhere(runs, (run) => run.findings_total !== null);
  const lastCompared = lastWhere(runs, (run) => run.comparable === true);
  // The price belongs to the run that measured: an unpriced model leaves it unknown, and an
  // older run's estimate must not stand in for the newest one's absence.
  const latestCost = latestMeasured?.cost_estimate_usd ?? null;
  const latestDuration = lastWhere(runs, (run) => run.duration_ms !== null);

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2.5">
            {history.host}
            {isLocalHost(history.host) && (
              <Badge variant="outline" className="text-[10px]">
                local
              </Badge>
            )}
          </span>
        }
        meta={
          <>
            <span>
              {runs.length} {runs.length === 1 ? "run" : "runs"} in the window
            </span>
            <span aria-hidden="true">·</span>
            <span>
              last{" "}
              {formatMoment(
                (latestMeasured ?? runs[runs.length - 1])?.started_at ?? "",
              )}
            </span>
          </>
        }
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href={`/sites/${encodeURIComponent(history.host)}`}>
              Back to the site
            </Link>
          </Button>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label="Latest findings"
          value={value(latestMeasured?.findings_total ?? null)}
          hint="from the stored report"
        />
        <Kpi
          label="Opened / closed"
          value={
            lastCompared === null
              ? "—"
              : `${value(lastCompared.new)} / ${value(lastCompared.closed)}`
          }
          hint="last comparable pair"
        />
        <Kpi
          label="Cost estimate"
          value={formatCostEstimate(latestCost)}
          hint="from the pinned price table"
        />
        <Kpi
          label="Duration"
          value={
            latestDuration?.duration_ms == null
              ? "—"
              : formatDuration(latestDuration.duration_ms)
          }
          hint="latest measured run"
        />
      </div>

      {history.notes.length > 0 && (
        <Card className="mb-5 border-amber-200 bg-amber-50/60">
          <CardContent className="py-1 text-xs text-amber-900">
            {history.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
          </CardContent>
        </Card>
      )}

      <HistoryCharts runs={runs} />

      <Card className="mt-5 gap-0 overflow-hidden py-0">
        <div className="flex items-center justify-between px-4 py-2.5">
          <h2 className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
            Runs
          </h2>
          <Badge variant="muted">{runs.length}</Badge>
        </div>
        <p className="px-4 pb-2 text-xs text-muted-foreground">
          Oldest first. A run without a report keeps its row and shows no
          numbers.
        </p>
        <div className="overflow-x-auto border-t border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-[11px] text-muted-foreground">
                <th className="px-4 py-2 font-medium">Run</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 text-right font-medium">Findings</th>
                <th className="px-2 py-2 text-right font-medium">Opened</th>
                <th className="px-2 py-2 text-right font-medium">Closed</th>
                <th className="px-2 py-2 text-right font-medium">Cost</th>
                <th className="px-2 py-2 text-right font-medium">Duration</th>
                <th className="px-2 py-2 font-medium">Agent</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.audit_id}
                  className="border-b border-border/70 last:border-b-0"
                >
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    <time dateTime={run.started_at}>
                      {formatMoment(run.started_at)}
                    </time>
                  </td>
                  <td className="px-2 py-2.5">
                    <StatusStamp status={run.status} />
                    {run.error !== null && run.findings_total === null && (
                      <details className="mt-1 text-xs text-muted-foreground">
                        <summary className="cursor-pointer">Why</summary>
                        <p className="mt-1 max-w-56 font-mono text-[11px] break-words">
                          {run.error}
                        </p>
                      </details>
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-right tabular-nums">
                    {value(run.findings_total)}
                  </td>
                  <td className="px-2 py-2.5 text-right tabular-nums">
                    {value(run.new)}
                  </td>
                  <td className="px-2 py-2.5 text-right tabular-nums">
                    {value(run.closed)}
                  </td>
                  <td className="px-2 py-2.5 text-right tabular-nums">
                    {formatCostEstimate(run.cost_estimate_usd)}
                  </td>
                  <td className="px-2 py-2.5 text-right tabular-nums">
                    {run.duration_ms === null
                      ? "—"
                      : formatDuration(run.duration_ms)}
                  </td>
                  <td className="px-2 py-2.5 font-mono text-[11px] text-muted-foreground">
                    {run.agent_version.replace("sha256:", "")}
                  </td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    {run.has_report ? (
                      <Link
                        href={`/audits/${run.audit_id}`}
                        className="text-xs font-medium text-brand hover:underline"
                      >
                        {run.findings_total === null
                          ? "unreadable →"
                          : "report →"}
                      </Link>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        no report
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="mt-3 px-1 text-[11px] leading-relaxed text-muted-foreground">
        Counts come from the stored report; tokens and call counts are measured,
        the dollar figure is an estimate from the pinned price table. A pair of
        runs with no shared page is not a comparison, and its delta is left
        empty rather than guessed.
      </p>
    </>
  );
}
