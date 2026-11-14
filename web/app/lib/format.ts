const STATUS_LABELS: Record<string, string> = {
  running: "running",
  completed: "completed",
  partial: "partial",
  failed: "failed",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function statusNote(status: string): string | undefined {
  if (status === "partial") {
    return "An agent failed; the deterministic findings are in the report.";
  }
  if (status === "running") {
    return "The page is being captured and measured.";
  }
  return undefined;
}

export function formatMoment(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(
    new Date(value),
  );
}

export function formatClock(ms: number): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(ms));
}

export function formatRelative(value: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(value)) / 1000));
  if (seconds < 45) {
    return "just now";
  }
  if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60);
    return `${minutes} min ago`;
  }
  if (seconds < 86_400) {
    const hours = Math.floor(seconds / 3600);
    return `${hours} h ago`;
  }
  const days = Math.floor(seconds / 86_400);
  return `${days} d ago`;
}

export function formatElapsed(startedAt: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(startedAt)) / 1000));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms} ms`;
  }
  const seconds = ms / 1000;
  return `${seconds.toFixed(1).replace(/\.0$/, "")} s`;
}

export function splitSite(site: string): { host: string; path: string } {
  try {
    const url = new URL(site);
    const path = `${url.pathname}${url.search}`;
    return {
      host: url.host,
      path: path === "/" ? "" : path.replace(/\/$/, ""),
    };
  } catch {
    return { host: site, path: "" };
  }
}

export function isLocalHost(host: string): boolean {
  let name = host.toLowerCase();
  if (name.startsWith("[")) {
    const end = name.indexOf("]");
    name = end === -1 ? name : name.slice(1, end);
  } else {
    const colon = name.lastIndexOf(":");
    name = colon === -1 ? name : name.slice(0, colon);
  }
  return (
    name === "localhost" ||
    name === "127.0.0.1" ||
    name === "0.0.0.0" ||
    name === "::1" ||
    name.endsWith(".local") ||
    /^10\./.test(name) ||
    /^192\.168\./.test(name) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(name)
  );
}

export function isLocalSite(site: string): boolean {
  try {
    return isLocalHost(new URL(site).host);
  } catch {
    return false;
  }
}

export function isBenchmarkSite(site: string): boolean {
  // The frozen corpus is generated under /bench/; the fixture site itself is not.
  try {
    return new URL(site).pathname.startsWith("/bench/");
  } catch {
    return false;
  }
}
