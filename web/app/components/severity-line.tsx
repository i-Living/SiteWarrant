const ORDER = ["blocker", "major", "minor", "info"] as const;

export function SeverityLine({
  counts,
  total,
  status,
  coverage,
}: {
  counts: Record<string, number> | null;
  total: number | null;
  status: string;
  coverage?: { measured: number; pages: number };
}) {
  if (total === null) {
    return (
      <span className="severity-line muted">
        {status === "running" ? "pending" : "—"}
      </span>
    );
  }
  if (total === 0) {
    // Zero findings over a partly measured host is not "clean": the unmeasured pages
    // have no verdict at all, so the row has to carry how much of it was audited.
    if (coverage !== undefined && coverage.measured < coverage.pages) {
      return (
        <span className="severity-line">
          0 findings · {coverage.measured}/{coverage.pages} pages measured
        </span>
      );
    }
    return <span className="severity-line clean">clean</span>;
  }
  if (counts === null) {
    return <span className="severity-line">{total} findings</span>;
  }

  return (
    <span className="severity-line">
      {ORDER.filter((severity) => (counts[severity] ?? 0) > 0).map(
        (severity) => (
          <span key={severity} className="sev" data-severity={severity}>
            <span className="sev-dot" aria-hidden="true" />
            <span className="sev-count">{counts[severity]}</span>
            {severity}
          </span>
        ),
      )}
    </span>
  );
}
