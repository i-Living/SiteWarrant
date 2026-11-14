import Link from "next/link";
import { SeverityLine } from "../../components/severity-line";
import { StatusStamp } from "../../components/status-stamp";
import { getSite, type PageSummary } from "../../lib/audits";
import {
  formatDate,
  formatDuration,
  formatMoment,
  isLocalHost,
} from "../../lib/format";

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

export default async function SitePage({
  params,
}: {
  params: Promise<{ host: string }>;
}) {
  const { host: rawHost } = await params;
  const host = decodeHost(rawHost);
  const site = await getSite(host);

  if (site === null) {
    return (
      <main>
        <p className="eyebrow">Site</p>
        <h1>Site not found</h1>
        <p className="lede">No audit exists for {host}.</p>
        <p>
          <Link className="button-link" href="/">
            Back to sites
          </Link>
        </p>
      </main>
    );
  }

  const { summary } = site;
  const pages = [...site.pages].sort(comparePages);

  return (
    <main>
      <p className="eyebrow">
        <Link href="/">Sites</Link> <span className="sep">/</span>{" "}
        {summary.host}
      </p>

      <header className="report-head">
        <h1>
          {summary.host}
          {isLocalHost(summary.host) && <span className="site-tag">local</span>}
        </h1>
        <p className="run-meta">
          <span>
            {summary.runs} {summary.runs === 1 ? "run" : "runs"}
          </span>
          <span>last {formatMoment(summary.last_activity)}</span>
          {summary.measured_pages < summary.pages && (
            <span>
              {summary.measured_pages} of {summary.pages} measured
            </span>
          )}
          {summary.running > 0 && (
            <span className="flag" data-state="running">
              <span className="status-dot" aria-hidden="true" />
              {summary.running} running
            </span>
          )}
          {summary.failed > 0 && (
            <span className="flag" data-state="failed">
              {summary.failed} failed
            </span>
          )}
        </p>
      </header>

      <div className="verdict">
        <div className="verdict-total">
          <strong>{summary.findings_total ?? "—"}</strong>
          <span>{summary.findings_total === 1 ? "finding" : "findings"}</span>
        </div>
        <SeverityLine
          counts={summary.by_severity}
          total={summary.findings_total}
          status={summary.running > 0 ? "running" : "completed"}
        />
      </div>

      <section>
        <h2 className="section-label">
          <span>Pages</span>
          <span className="section-count">{pages.length}</span>
        </h2>
        <p className="group-note">
          Latest run per page; failed and running first, then worst severity.
        </p>
        <ol className="ledger">
          {pages.map((page) => {
            const body = (
              <>
                <div className="row-main">
                  <span className="page-name">{page.page}</span>
                  <p className="row-meta">
                    {page.runs > 1 && <>{page.runs} runs · </>}
                    {formatDate(page.finished_at ?? page.started_at)}
                    {page.duration_ms !== null && (
                      <> · took {formatDuration(page.duration_ms)}</>
                    )}
                  </p>
                  {!page.has_report && page.error !== null && (
                    <details className="row-error">
                      <summary>Why it failed</summary>
                      <p>{page.error}</p>
                    </details>
                  )}
                </div>
                <SeverityLine
                  counts={page.by_severity}
                  total={page.findings_total}
                  status={page.status}
                />
                <StatusStamp status={page.status} />
              </>
            );

            return (
              <li
                key={page.page}
                className="ledger-row"
                data-status={page.status}
              >
                {page.has_report ? (
                  <Link
                    href={`/audits/${page.audit_id}`}
                    className="row-grid run-grid row-link"
                    title={`Open the report for ${page.page}`}
                  >
                    {body}
                    <span className="row-arrow" aria-hidden="true">
                      →
                    </span>
                  </Link>
                ) : (
                  <div className="row-grid run-grid">
                    {body}
                    <span className="row-open muted">no report</span>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </section>
    </main>
  );
}
