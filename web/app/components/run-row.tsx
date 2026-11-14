import Link from "next/link";
import type { AuditSummary } from "../lib/audits";
import { formatDuration, formatElapsed, formatRelative } from "../lib/format";
import { SeverityLine } from "./severity-line";
import { SiteName } from "./site-name";
import { StatusStamp } from "./status-stamp";

export function RunRow({
  audit,
  now,
  highlighted,
}: {
  audit: AuditSummary;
  now: number;
  highlighted: boolean;
}) {
  const running = audit.status === "running";

  return (
    <li
      id={audit.audit_id}
      className="ledger-row"
      data-status={audit.status}
      data-highlighted={highlighted ? "true" : undefined}
    >
      <div className="row-grid run-grid">
        <div className="row-main">
          <SiteName site={audit.site} />
          <p className="row-meta">
            {running ? (
              <>
                started {formatRelative(audit.started_at, now)} ·{" "}
                {formatElapsed(audit.started_at, now)} elapsed
              </>
            ) : (
              <>
                {formatRelative(audit.finished_at ?? audit.started_at, now)}
                {audit.duration_ms !== null && (
                  <> · took {formatDuration(audit.duration_ms)}</>
                )}
              </>
            )}
            {highlighted && <span className="row-new">just submitted</span>}
          </p>
          {audit.error !== null && (
            <details className="row-error">
              <summary>Why it failed</summary>
              <p>{audit.error}</p>
            </details>
          )}
        </div>
        <SeverityLine
          counts={audit.by_severity}
          total={audit.findings_total}
          status={audit.status}
        />
        <StatusStamp status={audit.status} />
        {audit.has_report ? (
          <Link className="row-open" href={`/audits/${audit.audit_id}`}>
            Report <span aria-hidden="true">→</span>
          </Link>
        ) : (
          <span className="row-open muted" aria-hidden="true">
            —
          </span>
        )}
      </div>
    </li>
  );
}
