const ORDER = ["blocker", "major", "minor", "info"] as const;

export function SeverityLine({
  counts,
  total,
  status,
}: {
  counts: Record<string, number> | null;
  total: number | null;
  status: string;
}) {
  if (total === null) {
    return (
      <span className="severity-line muted">
        {status === "running" ? "pending" : "—"}
      </span>
    );
  }
  if (total === 0) {
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
