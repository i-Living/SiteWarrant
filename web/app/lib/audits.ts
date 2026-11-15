export const apiBase = process.env.SITEWARRANT_API ?? "http://127.0.0.1:8000";

export type AuditSummary = {
  audit_id: string;
  site: string;
  status: string;
  scope: string;
  stage: string | null;
  cancel_requested: boolean;
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

export type HistoryRun = {
  audit_id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  agent_version: string;
  error: string | null;
  has_report: boolean;
  pages_audited: number | null;
  findings_total: number | null;
  by_severity: Record<string, number> | null;
  by_category: Record<string, number> | null;
  scores: Record<string, number> | null;
  duration_ms: number | null;
  tokens_in: number;
  tokens_out: number;
  llm_calls: number;
  cost_estimate_usd: number | null;
  compared_to: string | null;
  comparable: boolean | null;
  comparison_notes: string[];
  new: number | null;
  closed: number | null;
  remaining: number | null;
};

export type SiteHistory = {
  host: string;
  runs: HistoryRun[];
  notes: string[];
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

export async function getSiteHistory(
  host: string,
  limit = 30,
): Promise<SiteHistory | null> {
  const response = await fetch(
    `${apiBase}/sites/${encodeURIComponent(host)}/history?limit=${limit}`,
    { cache: "no-store" },
  );
  // Only a 404 means "this host has no page audit". A 500 is the API failing, and
  // showing an empty dashboard would read as "nothing was ever measured".
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`The audit API answered ${response.status}.`);
  }
  return (await response.json()) as SiteHistory;
}
