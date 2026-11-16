export const SEVERITY_ORDER = ["blocker", "major", "minor", "info"] as const;

export type Severity = (typeof SEVERITY_ORDER)[number];

/** One place decides what a severity looks like, so a badge, a dot and a bar agree. */
export const SEVERITY_STYLES: Record<
  Severity,
  { dot: string; text: string; badge: string; bar: string }
> = {
  blocker: {
    dot: "bg-severity-blocker",
    text: "text-severity-blocker",
    badge:
      "border-severity-blocker/25 bg-severity-blocker/10 text-severity-blocker",
    bar: "bg-severity-blocker",
  },
  major: {
    dot: "bg-severity-major",
    text: "text-severity-major",
    badge: "border-severity-major/25 bg-severity-major/10 text-severity-major",
    bar: "bg-severity-major",
  },
  minor: {
    dot: "bg-severity-minor",
    text: "text-severity-minor",
    badge: "border-severity-minor/25 bg-severity-minor/10 text-severity-minor",
    bar: "bg-severity-minor",
  },
  info: {
    dot: "bg-severity-info",
    text: "text-severity-info",
    badge: "border-severity-info/25 bg-severity-info/10 text-severity-info",
    bar: "bg-severity-info",
  },
};

export function severityStyle(severity: string) {
  return SEVERITY_STYLES[severity as Severity] ?? SEVERITY_STYLES.info;
}

export const STATUS_STYLES: Record<string, string> = {
  completed: "border-emerald-200 bg-emerald-50 text-emerald-700",
  partial: "border-amber-200 bg-amber-50 text-amber-700",
  running: "border-blue-200 bg-blue-50 text-blue-700",
  queued: "border-zinc-200 bg-zinc-50 text-zinc-600",
  failed: "border-red-200 bg-red-50 text-red-700",
  cancelled: "border-zinc-200 bg-zinc-50 text-zinc-500",
};

export function statusStyle(status: string): string {
  return STATUS_STYLES[status] ?? STATUS_STYLES.queued;
}
