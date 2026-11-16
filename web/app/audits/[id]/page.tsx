import { AlertTriangle, ChevronDown } from "lucide-react";
import Link from "next/link";
import { Kpi } from "../../components/kpi";
import { StatusStamp } from "../../components/status-stamp";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Progress } from "../../components/ui/progress";
import { type AuditSummary, apiBase, getAudit } from "../../lib/audits";
import {
  formatCostEstimate,
  formatDuration,
  formatMoment,
  splitSite,
} from "../../lib/format";
import { SEVERITY_ORDER, severityStyle } from "../../lib/severity";
import { cn } from "../../lib/utils";

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
    tokens_in?: number;
    tokens_out?: number;
    llm_calls?: number;
    cost_estimate_usd?: number | null;
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

function FindingItem({ finding, last }: { finding: Finding; last: boolean }) {
  const style = severityStyle(finding.severity);
  const meta = [
    finding.severity,
    finding.category,
    `priority ${finding.priority}`,
  ];
  if (finding.criterion !== null) {
    meta.push(
      `${finding.criterion}${finding.criterion_title === null ? "" : ` ${finding.criterion_title}`}`,
    );
  }

  return (
    <div className={cn("py-3.5", !last && "border-b border-border/70")}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          aria-hidden="true"
          className={cn("size-1.5 rounded-full", style.dot)}
        />
        <h4 className="text-sm font-medium">{finding.title}</h4>
        <Badge variant="muted" className="font-mono text-[10px]">
          {finding.rule_id}
        </Badge>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {meta.join(" · ")}
      </p>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
        {finding.summary}
      </p>
      <p className="mt-2 flex gap-2 text-sm leading-relaxed">
        <span className="mt-0.5 text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
          Fix
        </span>
        <span className="text-foreground/80">{finding.suggested_fix}</span>
      </p>
      <details className="group mt-2 rounded-md border border-border/70 bg-muted/40">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 font-mono text-[11px] text-muted-foreground">
          <span className="min-w-0 flex-1 truncate">
            {finding.evidence[0]?.excerpt ??
              finding.evidence[0]?.observation_id ??
              "no excerpt"}
          </span>
          <span className="shrink-0 text-[10px]">
            {finding.evidence.length}{" "}
            {finding.evidence.length === 1 ? "item" : "items"}
          </span>
          <ChevronDown className="size-3.5 shrink-0" aria-hidden="true" />
        </summary>
        <ul className="border-t border-border/70 px-2.5 py-2">
          {finding.evidence.map((item) => (
            <li
              key={`${item.kind}-${item.observation_id}-${item.excerpt ?? ""}`}
              className="flex gap-2 py-0.5 font-mono text-[11px] text-muted-foreground"
            >
              <span className="w-16 shrink-0 text-foreground/60">
                {item.kind}
              </span>
              <span className="min-w-0 break-words">
                {item.excerpt ?? item.observation_id}
              </span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function CauseCard({ cause }: { cause: RootCause & { findings: Finding[] } }) {
  const style = severityStyle(cause.severity);

  return (
    <Card className="gap-0 py-0">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 pt-4">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className={cn(
              "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg",
              style.badge,
            )}
          >
            <AlertTriangle className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold">{cause.label}</h3>
              <Badge
                variant="outline"
                className={cn("capitalize", style.badge)}
              >
                {cause.severity}
              </Badge>
            </div>
            <p className="mt-1 font-mono text-[11px] text-muted-foreground">
              {cause.anchor}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {cause.categories.map((category) => (
                <Badge key={category} variant="muted" className="text-[10px]">
                  {category}
                </Badge>
              ))}
            </div>
          </div>
        </div>
        <Badge variant="muted" className="font-mono text-[11px]">
          P{cause.priority}
        </Badge>
      </div>

      <p className="mt-3 px-4 text-sm leading-relaxed text-muted-foreground">
        {cause.summary}
      </p>
      {cause.rationale !== "" && (
        <p className="mt-1.5 px-4 text-xs leading-relaxed text-muted-foreground/80">
          {cause.rationale}
        </p>
      )}

      <div className="mt-3 border-t border-border bg-muted/30 px-4 pt-1 pb-1">
        <p className="mb-1 pt-2 text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
          Findings in this block · {cause.findings.length}
        </p>
      </div>
      <div className="px-4">
        {cause.findings.map((finding, position) => (
          <FindingItem
            key={finding.id}
            finding={finding}
            last={position === cause.findings.length - 1}
          />
        ))}
      </div>
    </Card>
  );
}

function scoreLabel(name: string): string {
  const labels: Record<string, string> = {
    a11y: "Accessibility",
    seo: "SEO",
    ui: "UI",
    ux: "UX",
    i18n: "i18n",
  };
  return labels[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
}

function SeverityBars({ counts }: { counts: Record<string, number> }) {
  const total = SEVERITY_ORDER.reduce(
    (sum, key) => sum + (counts[key] ?? 0),
    0,
  );
  if (total === 0) {
    // Four zero-width bars would read as four measurements of nothing; the report measured
    // and found nothing, which is a sentence, not a proportion.
    return <p className="text-xs text-muted-foreground">no findings</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      {SEVERITY_ORDER.map((key) => {
        const count = counts[key] ?? 0;
        return (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span className="w-16 capitalize text-muted-foreground">{key}</span>
            <Progress
              value={count}
              max={total}
              label={`${key}: ${count} of ${total}`}
              className="flex-1"
              indicatorClassName={severityStyle(key).bar}
            />
            <span className="w-5 text-right font-medium tabular-nums">
              {count}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Panel({
  report,
  summary,
  counts,
  categories,
  selected,
}: {
  report: Report;
  summary: AuditSummary | null;
  counts: Record<string, number>;
  categories: string[];
  selected: string | null;
}) {
  const scores = Object.entries(report.summary.scores);
  const startedAt = summary?.started_at ?? report.generated_at;
  const finishedAt = summary?.finished_at ?? null;
  const duration = summary?.duration_ms ?? report.summary.duration_ms;
  const tokensIn = report.summary.tokens_in;
  const tokensOut = report.summary.tokens_out;
  const calls = report.summary.llm_calls;
  const cost = report.summary.cost_estimate_usd ?? null;

  return (
    <div className="flex flex-col gap-4 lg:sticky lg:top-20">
      <Card className="gap-3">
        <CardContent className="flex flex-col gap-4 px-4">
          <section>
            <h3 className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
              Severity
            </h3>
            <div className="mt-2.5">
              <SeverityBars counts={counts} />
            </div>
          </section>

          {scores.length > 0 && (
            <section className="border-t border-border pt-3">
              <h3 className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
                Direction scores
              </h3>
              <div className="mt-2.5 flex flex-col gap-2">
                {scores.map(([name, score]) => (
                  <div key={name} className="flex items-center gap-2 text-xs">
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">
                      {scoreLabel(name)}
                    </span>
                    <span className="w-20 shrink-0">
                      <Progress
                        value={score}
                        max={100}
                        label={`${scoreLabel(name)} score: ${score} of 100`}
                        indicatorClassName="bg-foreground/70"
                      />
                    </span>
                    <span className="w-7 text-right font-medium tabular-nums">
                      {Math.round(score)}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="border-t border-border pt-3">
            <h3 className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
              Run
            </h3>
            <dl className="mt-2.5 flex flex-col gap-1.5 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Started</dt>
                <dd className="text-right">{formatMoment(startedAt)}</dd>
              </div>
              {finishedAt !== null && (
                <div className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">Finished</dt>
                  <dd className="text-right">{formatMoment(finishedAt)}</dd>
                </div>
              )}
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Duration</dt>
                <dd className="text-right tabular-nums">
                  {formatDuration(duration)}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Pages</dt>
                <dd className="text-right tabular-nums">
                  {report.summary.pages_audited}
                </dd>
              </div>
              {tokensIn !== undefined && tokensOut !== undefined && (
                <div className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">Tokens</dt>
                  <dd className="text-right tabular-nums">
                    {tokensIn.toLocaleString("en-GB")} in ·{" "}
                    {tokensOut.toLocaleString("en-GB")} out
                  </dd>
                </div>
              )}
              {calls !== undefined && (
                <div className="flex justify-between gap-3">
                  <dt className="text-muted-foreground">Model calls</dt>
                  <dd className="text-right tabular-nums">{calls}</dd>
                </div>
              )}
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Cost estimate</dt>
                <dd className="text-right tabular-nums">
                  {formatCostEstimate(cost)}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Agent</dt>
                <dd
                  className="max-w-[11rem] truncate text-right font-mono text-[11px]"
                  title={report.agent_version}
                >
                  {report.agent_version.replace("sha256:", "")}
                </dd>
              </div>
            </dl>
          </section>

          <section className="border-t border-border pt-3">
            <h3 className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
              Categories
            </h3>
            <ul className="mt-2.5 flex flex-col gap-1">
              <li>
                <Link
                  href={`/audits/${report.audit_id}`}
                  aria-current={selected === null ? "true" : undefined}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-1.5 py-1 text-xs hover:bg-accent",
                    selected === null
                      ? "font-medium text-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  <span
                    className={cn(
                      "flex size-3.5 items-center justify-center rounded-[4px] border",
                      selected === null
                        ? "border-foreground bg-foreground text-background"
                        : "border-border",
                    )}
                  >
                    {selected === null && (
                      <svg
                        viewBox="0 0 24 24"
                        className="size-2.5"
                        aria-hidden="true"
                      >
                        <path
                          d="M20 6 9 17l-5-5"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="3"
                        />
                      </svg>
                    )}
                  </span>
                  All findings
                  <span className="ml-auto tabular-nums text-muted-foreground">
                    {report.findings.length}
                  </span>
                </Link>
              </li>
              {categories.map((name) => {
                const isSelected = selected === name;
                const count = report.findings.filter(
                  (finding) => finding.category === name,
                ).length;
                return (
                  <li key={name}>
                    <Link
                      href={`/audits/${report.audit_id}?category=${encodeURIComponent(name)}`}
                      aria-current={isSelected ? "true" : undefined}
                      className={cn(
                        "flex items-center gap-2 rounded-md px-1.5 py-1 text-xs hover:bg-accent",
                        isSelected
                          ? "font-medium text-foreground"
                          : "text-muted-foreground",
                      )}
                    >
                      <span
                        className={cn(
                          "flex size-3.5 items-center justify-center rounded-[4px] border",
                          isSelected
                            ? "border-foreground bg-foreground text-background"
                            : "border-border",
                        )}
                      >
                        {isSelected && (
                          <svg
                            viewBox="0 0 24 24"
                            className="size-2.5"
                            aria-hidden="true"
                          >
                            <path
                              d="M20 6 9 17l-5-5"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="3"
                            />
                          </svg>
                        )}
                      </span>
                      {name}
                      <span className="ml-auto tabular-nums text-muted-foreground">
                        {count}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        </CardContent>
      </Card>

      <p className="px-1 text-[11px] leading-relaxed text-muted-foreground">
        Counts come from the stored report. Tokens and call counts are measured;
        the dollar figure is an estimate from the pinned price table. A run
        without a report keeps no numbers here.
      </p>
    </div>
  );
}

function Unavailable({ summary }: { summary: AuditSummary | null }) {
  const { host } = splitSite(summary?.site ?? "");
  const reason =
    summary === null
      ? "No audit with this id exists."
      : summary.status === "queued"
        ? "The run is queued; the report appears when a worker finishes it."
        : summary.status === "running"
          ? "The run is still going; the report appears when it finishes."
          : summary.status === "failed"
            ? "The run failed before a report was written."
            : summary.status === "cancelled"
              ? "The run was cancelled; no report was written."
              : "The stored report could not be read.";

  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">
        {host === "" ? "Report unavailable" : host}
      </h1>
      {summary !== null && (
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <StatusStamp status={summary.status} />
          <span>started {formatMoment(summary.started_at)}</span>
        </div>
      )}
      <p className="mt-3 max-w-2xl text-sm text-muted-foreground">{reason}</p>
      {summary?.error != null && (
        <Card className="mt-4 border-red-200 bg-red-50/60">
          <CardContent className="py-1 font-mono text-xs text-red-800">
            {summary.error}
          </CardContent>
        </Card>
      )}
      <Button asChild variant="outline" className="mt-4">
        <Link href="/audits">Back to runs</Link>
      </Button>
    </>
  );
}

export default async function AuditPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ category?: string }>;
}) {
  const { id } = await params;
  const { category } = await searchParams;
  const [report, summary] = await Promise.all([loadReport(id), getAudit(id)]);

  if (report === null) {
    return <Unavailable summary={summary} />;
  }

  const { host } = splitSite(report.site);
  const categories = [
    ...new Set(report.findings.map((item) => item.category)),
  ].sort();
  // An unknown category is the unfiltered report, not an empty one: a stale link should not
  // read as "this page is clean now".
  const selected =
    category !== undefined && categories.includes(category) ? category : null;
  const shown =
    selected === null
      ? report.findings
      : report.findings.filter((item) => item.category === selected);
  const byId = new Map(shown.map((finding) => [finding.id, finding]));
  const causes = report.root_causes
    .map((cause) => ({
      ...cause,
      findings: cause.finding_ids
        .map((findingId) => byId.get(findingId))
        .filter((finding): finding is Finding => finding !== undefined),
    }))
    .filter((cause) => cause.findings.length > 0);
  const grouped = new Set(causes.flatMap((cause) => cause.finding_ids));
  const ungrouped = shown
    .filter((finding) => !grouped.has(finding.id))
    .sort((left, right) => right.priority - left.priority);
  // The verdict counts what is on screen, so a filtered report does not show the
  // unfiltered severity split above a shorter list.
  const shownBySeverity = shown.reduce<Record<string, number>>(
    (counts, item) => {
      counts[item.severity] = (counts[item.severity] ?? 0) + 1;
      return counts;
    },
    {},
  );
  const verdictSeverity =
    selected === null ? report.summary.by_severity : shownBySeverity;
  const verdictTotal =
    selected === null ? report.summary.findings_total : shown.length;
  const severityChips = SEVERITY_ORDER.filter(
    (key) => (verdictSeverity[key] ?? 0) > 0,
  );

  return (
    <>
      <header className="mb-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="truncate text-2xl font-semibold tracking-tight">
                {host}
              </h1>
              <StatusStamp status={report.status} />
              {selected !== null && (
                <Badge variant="outline">filtered: {selected}</Badge>
              )}
            </div>
            <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
              {report.site}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span>
                {formatMoment(
                  summary?.finished_at ??
                    summary?.started_at ??
                    report.generated_at,
                )}
              </span>
              <span aria-hidden="true">·</span>
              <span>
                {report.summary.pages_audited}{" "}
                {report.summary.pages_audited === 1 ? "page" : "pages"}
              </span>
              <span aria-hidden="true">·</span>
              <span>
                {verdictTotal} {verdictTotal === 1 ? "finding" : "findings"}
              </span>
              <span aria-hidden="true">·</span>
              <span>run {report.audit_id.slice(0, 8)}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href={`/sites/${encodeURIComponent(host)}`}>Open site</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <a
                href={`/api/audits/${report.audit_id}/report`}
                target="_blank"
                rel="noreferrer"
              >
                Report JSON
              </a>
            </Button>
          </div>
        </div>
      </header>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          label="Findings"
          value={verdictTotal}
          hint={
            selected === null
              ? "after dedupe"
              : `of ${report.summary.findings_total}`
          }
        >
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
            {severityChips.length === 0 ? (
              <span className="text-muted-foreground">no findings</span>
            ) : (
              severityChips.map((key) => (
                <span
                  key={key}
                  className={cn(
                    "inline-flex items-center gap-1.5",
                    severityStyle(key).text,
                  )}
                >
                  <span
                    className={cn(
                      "size-1.5 rounded-full",
                      severityStyle(key).dot,
                    )}
                  />
                  {verdictSeverity[key]} {key}
                </span>
              ))
            )}
          </div>
        </Kpi>
        <Kpi
          label="Root causes"
          value={causes.length}
          hint={
            causes.length === 1
              ? "block that repeats across categories"
              : "blocks that repeat across categories"
          }
        />
        <Kpi
          label="Duplicates merged"
          value={report.summary.duplicates_removed}
          hint={`${Math.round(report.summary.duplicate_rate * 100)}% of candidates`}
        />
        <Kpi
          label="Cost estimate"
          value={formatCostEstimate(report.summary.cost_estimate_usd ?? null)}
          hint={
            report.summary.llm_calls === undefined
              ? "from the pinned price table"
              : `${report.summary.llm_calls} model calls`
          }
        />
      </div>

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_20.5rem]">
        <div className="flex min-w-0 flex-col gap-4">
          {causes.length === 0 ? (
            <Card>
              <CardContent className="py-5 text-sm text-muted-foreground">
                {selected === null
                  ? "No block has symptoms in two categories, so no finding was grouped into a root cause."
                  : `No root cause has a finding in ${selected} on this page.`}
              </CardContent>
            </Card>
          ) : (
            causes.map((cause) => <CauseCard key={cause.id} cause={cause} />)
          )}

          {ungrouped.length > 0 && (
            <Card className="gap-0 py-0">
              <div className="flex items-center justify-between px-4 py-2.5">
                <h3 className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
                  Findings without a shared cause
                </h3>
                <Badge variant="muted">{ungrouped.length}</Badge>
              </div>
              <div className="border-t border-border px-4">
                {ungrouped.map((finding, position) => (
                  <FindingItem
                    key={finding.id}
                    finding={finding}
                    last={position === ungrouped.length - 1}
                  />
                ))}
              </div>
            </Card>
          )}
        </div>

        <Panel
          report={report}
          summary={summary}
          counts={verdictSeverity}
          categories={categories}
          selected={selected}
        />
      </div>
    </>
  );
}
