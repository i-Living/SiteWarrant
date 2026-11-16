import { SEVERITY_ORDER, severityStyle } from "../lib/severity";
import { cn } from "../lib/utils";

export function SeverityLine({
  counts,
  total,
  status,
  coverage,
  className,
}: {
  counts: Record<string, number> | null;
  total: number | null;
  status: string;
  coverage?: { measured: number; pages: number };
  className?: string;
}) {
  const base = cn(
    "inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-xs",
    className,
  );

  if (total === null) {
    return (
      <span className={cn(base, "text-muted-foreground")}>
        {status === "running" || status === "queued" ? "pending" : "—"}
      </span>
    );
  }
  if (total === 0) {
    // Zero findings over a partly measured host is not "clean": the unmeasured pages
    // have no verdict at all, so the line has to carry how much of it was audited.
    if (coverage !== undefined && coverage.measured < coverage.pages) {
      return (
        <span className={cn(base, "text-muted-foreground")}>
          0 findings · {coverage.measured}/{coverage.pages} pages measured
        </span>
      );
    }
    return (
      <span className={cn(base, "text-emerald-700")}>
        <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
        clean
      </span>
    );
  }
  if (counts === null) {
    return (
      <span className={cn(base, "text-muted-foreground")}>
        {total} findings
      </span>
    );
  }

  return (
    <span className={base}>
      {SEVERITY_ORDER.filter((severity) => (counts[severity] ?? 0) > 0).map(
        (severity) => (
          <span
            key={severity}
            className={cn(
              "inline-flex items-center gap-1.5",
              severityStyle(severity).text,
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "size-1.5 rounded-full",
                severityStyle(severity).dot,
              )}
            />
            <span className="font-medium text-foreground">
              {counts[severity]}
            </span>
            {severity}
          </span>
        ),
      )}
    </span>
  );
}
