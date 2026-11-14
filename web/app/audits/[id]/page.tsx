import Link from "next/link";
import { SeverityLine } from "../../components/severity-line";
import { StatusStamp } from "../../components/status-stamp";
import { type AuditSummary, apiBase, getAudit } from "../../lib/audits";
import { formatDuration, formatMoment, splitSite } from "../../lib/format";

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
  criterion: string | null;
  criterion_title: string | null;
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
  generated_at: string;
  summary: {
    pages_audited: number;
    findings_total: number;
    by_severity: Record<string, number>;
    scores: Record<string, number>;
    duration_ms: number;
    root_causes: number;
    duplicates_removed: number;
    duplicate_rate: number;
  };
  findings: Finding[];
  root_causes: RootCause[];
};

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
  const meta = [
    finding.category,
    finding.severity,
    `priority ${finding.priority}`,
  ];
  if (finding.criterion !== null) {
    meta.push(
      `${finding.criterion}${finding.criterion_title === null ? "" : ` ${finding.criterion_title}`}`,
    );
  }

  return (
    <li className="finding" data-severity={finding.severity}>
      <span className="finding-rail" aria-hidden="true" />
      <div className="finding-body">
        <h4>
          {finding.title} <span className="rule">{finding.rule_id}</span>
        </h4>
        <p className="finding-meta">{meta.join(" · ")}</p>
        <p className="finding-summary">{finding.summary}</p>
        <div className="finding-fix">
          <span className="label">Fix</span>
          <p>{finding.suggested_fix}</p>
        </div>
        <div className="evidence">
          <span className="label">Evidence</span>
          {finding.evidence.map((item) => (
            <div
              className="evidence-item"
              key={`${item.kind}-${item.observation_id}-${item.excerpt ?? ""}`}
            >
              <span className="evidence-kind">{item.kind}</span>
              <pre>{item.excerpt ?? item.observation_id}</pre>
            </div>
          ))}
        </div>
      </div>
    </li>
  );
}

function Unavailable({
  id,
  summary,
}: {
  id: string;
  summary: AuditSummary | null;
}) {
  const { host } = splitSite(summary?.site ?? "");
  const reason =
    summary === null
      ? "No audit with this id exists."
      : summary.status === "running"
        ? "The run is still going; the report appears when it finishes."
        : summary.status === "failed"
          ? "The run failed before a report was written."
          : "The stored report could not be read.";

  return (
    <main>
      <p className="eyebrow">
        <Link href="/">Sites</Link> <span className="sep">/</span>{" "}
        {summary !== null && host !== "" && (
          <>
            <Link href={`/sites/${encodeURIComponent(host)}`}>{host}</Link>{" "}
            <span className="sep">/</span>{" "}
          </>
        )}
        {id.slice(0, 8)}
      </p>
      <h1>{host === "" ? "Report unavailable" : host}</h1>
      {summary !== null && (
        <p className="run-meta">
          <StatusStamp status={summary.status} />
          <span>started {formatMoment(summary.started_at)}</span>
        </p>
      )}
      <p className="lede">{reason}</p>
      {summary?.error != null && (
        <div className="notice">
          <p>{summary.error}</p>
        </div>
      )}
      <p>
        <Link className="button-link" href="/audits">
          Back to runs
        </Link>
      </p>
    </main>
  );
}

export default async function AuditPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [report, summary] = await Promise.all([loadReport(id), getAudit(id)]);

  if (report === null) {
    return <Unavailable id={id} summary={summary} />;
  }

  const { host } = splitSite(report.site);
  const byId = new Map(report.findings.map((finding) => [finding.id, finding]));
  const grouped = new Set(
    report.root_causes.flatMap((cause) => cause.finding_ids),
  );
  const ungrouped = report.findings
    .filter((finding) => !grouped.has(finding.id))
    .sort((left, right) => right.priority - left.priority);

  return (
    <main>
      <p className="eyebrow">
        <Link href="/">Sites</Link> <span className="sep">/</span>{" "}
        <Link href={`/sites/${encodeURIComponent(host)}`}>{host}</Link>{" "}
        <span className="sep">/</span> {report.audit_id.slice(0, 8)}
      </p>

      <header className="report-head">
        <h1>{host}</h1>
        <p className="report-url">{report.site}</p>
        <p className="run-meta">
          <StatusStamp status={report.status} />
          <span>
            {summary === null
              ? formatMoment(report.generated_at)
              : formatMoment(summary.finished_at ?? summary.started_at)}
          </span>
          {summary?.duration_ms != null && (
            <span>took {formatDuration(summary.duration_ms)}</span>
          )}
          <span>
            {report.summary.pages_audited}{" "}
            {report.summary.pages_audited === 1 ? "page" : "pages"}
          </span>
          <span className="agent">agent {report.agent_version}</span>
        </p>
      </header>

      <div className="verdict">
        <div className="verdict-total">
          <strong>{report.summary.findings_total}</strong>
          <span>
            {report.summary.findings_total === 1 ? "finding" : "findings"}
          </span>
        </div>
        <SeverityLine
          counts={report.summary.by_severity}
          total={report.summary.findings_total}
          status={report.status}
        />
        <div className="verdict-fact">
          <strong>{report.summary.root_causes}</strong>
          <span>
            {report.summary.root_causes === 1 ? "root cause" : "root causes"}
          </span>
        </div>
        <div className="verdict-fact">
          <strong>{report.summary.duplicates_removed}</strong>
          <span>duplicates merged</span>
        </div>
      </div>

      {Object.keys(report.summary.scores).length > 0 && (
        <div className="score-line">
          <span className="score-label">Direction scores</span>
          {Object.entries(report.summary.scores).map(([name, score]) => (
            <span key={name} className="score">
              <span>{name}</span>
              <strong>{Math.round(score)}</strong>
            </span>
          ))}
        </div>
      )}

      <section>
        <h2 className="section-label">
          <span>Root causes</span>
          <span className="section-count">{report.root_causes.length}</span>
        </h2>
        {report.root_causes.length === 0 ? (
          <p className="empty">
            No block has symptoms in two categories, so no finding was grouped
            into a root cause.
          </p>
        ) : (
          report.root_causes.map((cause) => (
            <article
              key={cause.id}
              className="cause"
              data-severity={cause.severity}
            >
              <header className="cause-head">
                <div>
                  <p className="cause-anchor">{cause.anchor}</p>
                  <h3>{cause.label === "" ? cause.anchor : cause.label}</h3>
                </div>
                <p className="cause-side">
                  <span className="cause-tags">
                    {cause.categories.map((category) => (
                      <span key={category}>{category}</span>
                    ))}
                  </span>
                  <span>priority {cause.priority}</span>
                </p>
              </header>
              <p className="cause-summary">{cause.summary}</p>
              <p className="cause-rationale">{cause.rationale}</p>
              <ol className="findings">
                {cause.finding_ids.map((findingId) => {
                  const finding = byId.get(findingId);
                  return finding ? (
                    <FindingItem key={findingId} finding={finding} />
                  ) : null;
                })}
              </ol>
            </article>
          ))
        )}
      </section>

      {ungrouped.length > 0 && (
        <section>
          <h2 className="section-label">
            <span>Findings without a shared cause</span>
            <span className="section-count">{ungrouped.length}</span>
          </h2>
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
