import Link from "next/link";
import { HistoryCharts } from "../../../components/history-charts";
import { StatusStamp } from "../../../components/status-stamp";
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
      <main>
        <p className="eyebrow">Dashboard</p>
        <h1>{host}</h1>
        <div className="notice">
          <p>{error}</p>
          <p className="note">
            The history could not be read; retry in a moment.
          </p>
        </div>
        <p>
          <Link
            className="button-link"
            href={`/sites/${encodeURIComponent(host)}`}
          >
            Back to the site
          </Link>
        </p>
      </main>
    );
  }

  if (history === null) {
    return (
      <main>
        <p className="eyebrow">Dashboard</p>
        <h1>Site not found</h1>
        <p className="lede">No page audit exists for {host}.</p>
        <p>
          <Link className="button-link" href="/">
            Back to sites
          </Link>
        </p>
      </main>
    );
  }

  const runs = history.runs;
  const latestMeasured = lastWhere(runs, (run) => run.findings_total !== null);
  const lastCompared = lastWhere(runs, (run) => run.comparable === true);
  const latestCost = lastWhere(runs, (run) => run.cost_estimate_usd !== null);
  const latestDuration = lastWhere(runs, (run) => run.duration_ms !== null);

  return (
    <main>
      <p className="eyebrow">
        <Link href="/">Sites</Link> <span className="sep">/</span>{" "}
        <Link href={`/sites/${encodeURIComponent(history.host)}`}>
          {history.host}
        </Link>{" "}
        <span className="sep">/</span> dashboard
      </p>

      <header className="report-head">
        <h1>
          {history.host}
          {isLocalHost(history.host) && <span className="site-tag">local</span>}
        </h1>
        <p className="run-meta">
          <span>
            {runs.length} {runs.length === 1 ? "run" : "runs"} in the window
          </span>
          <span>
            last{" "}
            {formatMoment(
              (latestMeasured ?? runs[runs.length - 1])?.started_at ?? "",
            )}
          </span>
        </p>
      </header>

      <div className="dash-stats">
        <div className="dash-stat">
          <strong>{value(latestMeasured?.findings_total ?? null)}</strong>
          <span>latest findings</span>
        </div>
        <div className="dash-stat">
          <strong>
            {lastCompared === null
              ? "—"
              : `${value(lastCompared.new)} / ${value(lastCompared.closed)}`}
          </strong>
          <span>opened / closed, last comparison</span>
        </div>
        <div className="dash-stat">
          <strong>
            {formatCostEstimate(latestCost?.cost_estimate_usd ?? null)}
          </strong>
          <span>latest cost, estimate</span>
        </div>
        <div className="dash-stat">
          <strong>
            {latestDuration?.duration_ms == null
              ? "—"
              : formatDuration(latestDuration.duration_ms)}
          </strong>
          <span>latest duration</span>
        </div>
      </div>

      {history.notes.length > 0 && (
        <div className="notice">
          {history.notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      )}

      <HistoryCharts runs={runs} />

      <section>
        <h2 className="section-label">
          <span>Runs</span>
          <span className="section-count">{runs.length}</span>
        </h2>
        <p className="group-note">
          Oldest first. A run without a report keeps its row and shows no
          numbers.
        </p>
        <div className="table-scroll">
          <table className="dash-table">
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">
                  Findings
                </th>
                <th scope="col" className="num">
                  Opened
                </th>
                <th scope="col" className="num">
                  Closed
                </th>
                <th scope="col" className="num">
                  Cost
                </th>
                <th scope="col" className="num">
                  Duration
                </th>
                <th scope="col">Agent</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.audit_id}>
                  <td>
                    <time dateTime={run.started_at}>
                      {formatMoment(run.started_at)}
                    </time>
                  </td>
                  <td>
                    <StatusStamp status={run.status} />
                    {run.error !== null && run.findings_total === null && (
                      <details className="row-error">
                        <summary>Why</summary>
                        <p>{run.error}</p>
                      </details>
                    )}
                  </td>
                  <td className="num">{value(run.findings_total)}</td>
                  <td className="num">{value(run.new)}</td>
                  <td className="num">{value(run.closed)}</td>
                  <td className="num">
                    {formatCostEstimate(run.cost_estimate_usd)}
                  </td>
                  <td className="num">
                    {run.duration_ms === null
                      ? "—"
                      : formatDuration(run.duration_ms)}
                  </td>
                  <td className="muted">
                    {run.agent_version.replace("sha256:", "")}
                  </td>
                  <td>
                    {run.has_report ? (
                      <Link href={`/audits/${run.audit_id}`}>
                        {run.findings_total === null
                          ? "unreadable →"
                          : "report →"}
                      </Link>
                    ) : (
                      <span className="muted">no report</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p className="note dash-footnote">
        Counts come from the stored report; tokens and call counts are measured,
        the dollar figure is an estimate from the pinned price table. A pair of
        runs with no shared page is not a comparison, and its delta is left
        empty rather than guessed.
      </p>
    </main>
  );
}
