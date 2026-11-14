export const apiBase = process.env.SITEWARRANT_API ?? "http://127.0.0.1:8000";

export type AuditSummary = {
  audit_id: string;
  site: string;
  status: string;
  pages_count: number;
  findings_total: number | null;
  by_severity: Record<string, number> | null;
  duration_ms: number | null;
  has_report: boolean;
  started_at: string;
  finished_at: string | null;
  error: string | null;
};

export type PageSummary = {
  page: string;
  url: string;
  audit_id: string;
  status: string;
  findings_total: number | null;
  by_severity: Record<string, number> | null;
  duration_ms: number | null;
  has_report: boolean;
  runs: number;
  running: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
};

export type SiteSummary = {
  host: string;
  pages: number;
  measured_pages: number;
  findings_total: number | null;
  by_severity: Record<string, number> | null;
  runs: number;
  running: number;
  failed: number;
  last_activity: string;
};

export type SiteDetail = {
  summary: SiteSummary;
  pages: PageSummary[];
};

export async function listSites(): Promise<SiteSummary[]> {
  const response = await fetch(`${apiBase}/sites`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`The audit API answered ${response.status}.`);
  }
  return (await response.json()) as SiteSummary[];
}

export async function getSite(host: string): Promise<SiteDetail | null> {
  const response = await fetch(`${apiBase}/sites/${encodeURIComponent(host)}`, {
    cache: "no-store",
  });
  // Only a 404 means "no such site". A 500 or 503 is an API failure, and a page that
  // calls it "not found" hides the difference.
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`The audit API answered ${response.status}.`);
  }
  return (await response.json()) as SiteDetail;
}

export async function getAudit(auditId: string): Promise<AuditSummary | null> {
  const response = await fetch(`${apiBase}/audits/${auditId}`, {
    cache: "no-store",
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`The audit API answered ${response.status}.`);
  }
  return (await response.json()) as AuditSummary;
}
