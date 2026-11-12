type Evidence = {
  kind: string;
  observation_id: string;
  excerpt: string | null;
};

type Finding = {
  id: string;
  rule_id: string;
  category: string;
  severity: string;
  title: string;
  summary: string;
  suggested_fix: string;
  evidence: Evidence[];
};

type Report = {
  audit_id: string;
  site: string;
  agent_version: string;
  status: string;
  summary: {
    findings_total: number;
    by_severity: Record<string, number>;
    scores: Record<string, number>;
  };
  findings: Finding[];
};

const apiBase = process.env.SITEWARRANT_API ?? "http://127.0.0.1:8000";

async function loadReport(auditId: string): Promise<Report | null> {
  const response = await fetch(`${apiBase}/audits/${auditId}/report`, {
    cache: "no-store",
  });
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as Report;
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ audit?: string }>;
}) {
  const { audit } = await searchParams;

  if (!audit) {
    return (
      <main>
        <h1>SiteWarrant</h1>
        <p>
          No audit selected. Run <code>sitewarrant audit &lt;url&gt;</code> and
          open <code>/?audit=&lt;audit id&gt;</code>.
        </p>
      </main>
    );
  }

  const report = await loadReport(audit);
  if (report === null) {
    return (
      <main>
        <h1>Report unavailable</h1>
        <p>
          Audit <code>{audit}</code> has no stored report.
        </p>
      </main>
    );
  }

  return (
    <main>
      <h1>{report.site}</h1>
      <p className="meta">
        {report.summary.findings_total} finding(s) · agent{" "}
        {report.agent_version}
      </p>
      <ul className="severities">
        {Object.entries(report.summary.by_severity).map(([severity, count]) => (
          <li key={severity}>
            {severity}: {count}
          </li>
        ))}
      </ul>
      <ol className="findings">
        {report.findings.map((finding) => (
          <li key={finding.id} data-severity={finding.severity}>
            <h2>
              {finding.title} <span className="rule">{finding.rule_id}</span>
            </h2>
            <p>{finding.summary}</p>
            <p className="fix">{finding.suggested_fix}</p>
            {finding.evidence.map((item) => (
              <pre
                key={`${item.kind}-${item.observation_id}-${item.excerpt ?? ""}`}
              >
                {item.excerpt ?? item.kind}
              </pre>
            ))}
          </li>
        ))}
      </ol>
    </main>
  );
}
