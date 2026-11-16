import Link from "next/link";
import type { AuditSummary } from "../lib/audits";
import { formatDuration, formatElapsed, formatRelative } from "../lib/format";
import { cn } from "../lib/utils";
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
  const queued = audit.status === "queued";
  // A sitemap run is a dispatch row: it has no report of its own, and the page audits it queued
  // carry the findings. Saying so is the difference between "nothing found" and "ten pages queued".
  const sitemapNote =
    audit.scope !== "sitemap"
      ? null
      : queued || running
        ? "sitemap dispatch"
        : `sitemap · ${audit.pages_count} ${audit.pages_count === 1 ? "page" : "pages"} queued`;

  return (
    <div
      id={audit.audit_id}
      className={cn(
        "grid gap-x-4 gap-y-2 px-4 py-3 transition-colors md:grid-cols-[minmax(0,1fr)_11rem_6.5rem_5.5rem] md:items-center",
        highlighted && "bg-brand/5",
      )}
    >
      <div className="min-w-0">
        <SiteName site={audit.site} />
        <p className="mt-1 text-xs text-muted-foreground">
          {queued ? (
            <>
              queued {formatRelative(audit.started_at, now)} · waiting for a
              worker
            </>
          ) : running ? (
            <>
              started {formatRelative(audit.started_at, now)} ·{" "}
              {formatElapsed(audit.started_at, now)} elapsed
              {audit.stage != null && <> · stage {audit.stage}</>}
              {audit.cancel_requested && <> · stopping after this stage</>}
            </>
          ) : (
            <>
              {formatRelative(audit.finished_at ?? audit.started_at, now)}
              {audit.duration_ms !== null && (
                <> · took {formatDuration(audit.duration_ms)}</>
              )}
            </>
          )}
          {sitemapNote !== null && <> · {sitemapNote}</>}
          {highlighted && (
            <span className="ml-2 rounded-full bg-brand/10 px-1.5 py-0.5 text-[10px] font-medium text-brand">
              just submitted
            </span>
          )}
        </p>
        {audit.error !== null && (
          <details className="mt-1 text-xs text-muted-foreground">
            <summary className="cursor-pointer">Why it failed</summary>
            <p className="mt-1 font-mono text-[11px] break-words">
              {audit.error}
            </p>
          </details>
        )}
      </div>
      <SeverityLine
        counts={audit.by_severity}
        total={audit.findings_total}
        status={audit.status}
      />
      <StatusStamp status={audit.status} />
      <div className="md:text-right">
        {audit.has_report ? (
          <Link
            href={`/audits/${audit.audit_id}`}
            className="text-xs font-medium text-brand hover:underline"
          >
            Report →
          </Link>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </div>
    </div>
  );
}
