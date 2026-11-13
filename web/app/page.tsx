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
  priority: number;
  root_cause_id: string | null;
  evidence: Evidence[];
};

type RootCause = {
  id: string;
  kind: string;
  anchor: string;
  label: string;
  categories: string[];
  summary: string;
  rationale: string;
  severity: string;
  priority: number;
  finding_ids: string[];
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
    root_causes: number;
    duplicates_removed: number;
    duplicate_rate: number;
  };
  findings: Finding[];
  root_causes: RootCause[];
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

function FindingItem({ finding }: { finding: Finding }) {
  return (
    <li data-severity={finding.severity}>
      <h3>
        {finding.title} <span className="rule">{finding.rule_id}</span>
      </h3>
      <p className="why">
        {finding.category} · {finding.severity} · priority {finding.priority}
      </p>
      <p>{finding.summary}</p>
      <p className="fix">{finding.suggested_fix}</p>
      {finding.evidence.map((item) => (
        <pre key={`${item.kind}-${item.observation_id}-${item.excerpt ?? ""}`}>
          {item.excerpt ?? item.kind}
        </pre>
      ))}
    </li>
  );
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

  const byId = new Map(report.findings.map((finding) => [finding.id, finding]));
  const grouped = new Set(
    report.root_causes.flatMap((cause) => cause.finding_ids),
  );
  const ungrouped = report.findings
    .filter((finding) => !grouped.has(finding.id))
    .sort((left, right) => right.priority - left.priority);

  return (
    <main>
      <h1>{report.site}</h1>
      <p className="meta">
        {report.summary.findings_total} finding(s) ·{" "}
        {report.summary.root_causes} root cause(s) · duplicate rate{" "}
        {report.summary.duplicate_rate} · agent {report.agent_version}
      </p>
      <ul className="severities">
        {Object.entries(report.summary.by_severity).map(([severity, count]) => (
          <li key={severity}>
            {severity}: {count}
          </li>
        ))}
      </ul>

      {report.root_causes.map((cause) => (
        <section
          key={cause.id}
          className="cause"
          data-severity={cause.severity}
        >
          <h2>
            {cause.label} <span className="rule">{cause.anchor}</span>{" "}
            <span className="rule">{cause.categories.join(" + ")}</span>
          </h2>
          <p>{cause.summary}</p>
          <p className="why">
            priority {cause.priority} · {cause.rationale}
          </p>
          <ol className="findings">
            {cause.finding_ids.map((id) => {
              const finding = byId.get(id);
              return finding ? (
                <FindingItem key={id} finding={finding} />
              ) : null;
            })}
          </ol>
        </section>
      ))}

      {ungrouped.length > 0 && (
        <section className="standalone">
          <h2>Findings without a shared cause</h2>
          <ol className="findings">
            {ungrouped.map((finding) => (
              <FindingItem key={finding.id} finding={finding} />
            ))}
          </ol>
        </section>
      )}
    </main>
  );
}
