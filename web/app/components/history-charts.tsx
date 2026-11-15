"use client";

import Link from "next/link";
import { type ReactNode, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HistoryRun } from "../lib/audits";
import { formatDate, formatDuration } from "../lib/format";
import { cn } from "../lib/utils";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Select } from "./ui/select";

const SEVERITIES = ["blocker", "major", "minor", "info"] as const;

// The same palette as the badges: the charts are part of the report's typography, not a
// second visual language. Explicit hex because SVG fills resolve `var()` per browser.
const SEVERITY_COLORS: Record<(typeof SEVERITIES)[number], string> = {
  blocker: "#b91c1c",
  major: "#c2410c",
  minor: "#a16207",
  info: "#1d4ed8",
};

const CATEGORY_COLORS = [
  "#1d4d3b",
  "#b91c1c",
  "#2563eb",
  "#c2410c",
  "#7c3aed",
  "#0f766e",
  "#a16207",
  "#52525b",
];

const TOOLTIP_STYLE = {
  background: "#ffffff",
  border: "1px solid #e4e4e7",
  borderRadius: 8,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 11,
  color: "#18181b",
};

const AXIS_TICK = { fontSize: 11, fill: "#71717a" };
const GRID_STROKE = "#e4e4e7";

function runLabel(value: string, withDate: boolean): string {
  // A dashboard window is often one afternoon; repeat the date on every tick and the axis
  // says the same string thirty times. The date appears when the window spans more than a
  // day, the time always does.
  return new Intl.DateTimeFormat(
    "en-GB",
    withDate
      ? {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }
      : { hour: "2-digit", minute: "2-digit", hour12: false },
  ).format(new Date(value));
}

function categoryKeys(runs: HistoryRun[]): string[] {
  const seen = new Set<string>();
  for (const run of runs) {
    for (const category of Object.keys(run.by_category ?? {})) {
      seen.add(category);
    }
  }
  return [...seen].sort();
}

function ChartCard({
  title,
  note,
  wide,
  children,
}: {
  title: string;
  note: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <Card className={cn("gap-2", wide === true && "lg:col-span-2")}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{note}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function HistoryCharts({ runs }: { runs: HistoryRun[] }) {
  const [category, setCategory] = useState("all");
  const categories = categoryKeys(runs);
  const latest = [...runs].reverse().find((run) => run.by_category !== null);
  const spansDays =
    new Set(runs.map((run) => new Date(run.started_at).toDateString())).size >
    1;

  const points = runs.map((run, index) => {
    const point: Record<string, string | number | null> = {
      key: `${run.audit_id}-${index}`,
      i: index,
      label: runLabel(run.started_at, spansDays),
      findings: run.findings_total,
      opened: run.new,
      closed: run.closed,
      cost: run.cost_estimate_usd,
    };
    for (const severity of SEVERITIES) {
      point[severity] = run.by_severity?.[severity] ?? null;
    }
    for (const name of categories) {
      // A report that can be read but has no finding of this category measured zero of it;
      // only a run without a readable report leaves the point empty.
      point[`cat_${name}`] =
        run.by_category === null ? null : (run.by_category[name] ?? 0);
    }
    return point;
  });

  const incomparable = runs.filter(
    (run) => run.compared_to !== null && run.comparable === false,
  );

  const selected = category === "all" ? categories : [category];
  const hasComparison = runs.some(
    (run) => run.new !== null || run.closed !== null,
  );
  const hasReports = runs.some((run) => run.findings_total !== null);
  const hasCost = runs.some((run) => run.cost_estimate_usd !== null);
  // A zero is a measurement: when every plotted value is zero the plot is empty on purpose,
  // and saying so keeps it from reading as missing data.
  const comparisonIsZero =
    hasComparison &&
    runs.every(
      (run) => run.new === null || (run.new === 0 && (run.closed ?? 0) === 0),
    );
  const costs = runs
    .map((run) => run.cost_estimate_usd)
    .filter((cost): cost is number => cost !== null);
  const costIsZero = costs.length > 0 && costs.every((cost) => cost === 0);

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Findings per run"
          note="Stacked by severity, from the stored report. A run without one leaves a gap instead of a zero."
          wide
        >
          {hasReports ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart
                data={points}
                margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
              >
                <CartesianGrid stroke={GRID_STROKE} vertical={false} />
                <XAxis
                  dataKey="i"
                  tick={AXIS_TICK}
                  tickLine={false}
                  interval="preserveStartEnd"
                  tickFormatter={(value) =>
                    String(points[Number(value)]?.label ?? "")
                  }
                />
                <YAxis
                  allowDecimals={false}
                  tick={AXIS_TICK}
                  tickLine={false}
                />
                <Tooltip
                  labelFormatter={(value) =>
                    String(points[Number(value)]?.label ?? "")
                  }
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "#f4f4f5" }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {SEVERITIES.map((severity) => (
                  <Bar
                    key={severity}
                    dataKey={severity}
                    stackId="severity"
                    fill={SEVERITY_COLORS[severity]}
                    name={severity}
                    isAnimationActive={false}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-muted-foreground">
              No run of this host has a stored report yet. The timeline draws
              itself when one finishes; a run's cost still appears below,
              because the audit row records it.
            </p>
          )}
        </ChartCard>

        <ChartCard
          title="Opened and closed"
          note="Between each run and the previous one that wrote a report. A pair that is not comparable has no counts."
        >
          {hasComparison ? (
            <ResponsiveContainer width="100%" height={210}>
              <BarChart
                data={points}
                margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
              >
                <CartesianGrid stroke={GRID_STROKE} vertical={false} />
                <XAxis
                  dataKey="i"
                  tick={AXIS_TICK}
                  tickLine={false}
                  interval="preserveStartEnd"
                  tickFormatter={(value) =>
                    String(points[Number(value)]?.label ?? "")
                  }
                />
                <YAxis
                  allowDecimals={false}
                  tick={AXIS_TICK}
                  tickLine={false}
                />
                <Tooltip
                  labelFormatter={(value) =>
                    String(points[Number(value)]?.label ?? "")
                  }
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: "#f4f4f5" }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar
                  dataKey="opened"
                  fill="#c2410c"
                  name="opened"
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="closed"
                  fill="#1d4d3b"
                  name="closed"
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-sm text-muted-foreground">
              No two runs in this window are comparable yet: a delta needs a
              previous report of the same page.
            </p>
          )}
          {comparisonIsZero && (
            <p className="mt-2 text-xs text-muted-foreground">
              Every comparable pair in this window opened and closed nothing.
            </p>
          )}
          {incomparable.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
              {incomparable.map((run) => (
                <li key={run.audit_id}>
                  {formatDate(run.started_at)}:{" "}
                  {run.comparison_notes.join("; ") || "not comparable"}
                </li>
              ))}
            </ul>
          )}
        </ChartCard>

        <ChartCard
          title="Findings by category"
          note="Post-dedupe counts, as the report groups them."
        >
          {categories.length > 0 ? (
            <>
              <label
                htmlFor="category-filter"
                className="mb-2 flex items-center gap-2 text-xs text-muted-foreground"
              >
                <span>Category</span>
                <Select
                  id="category-filter"
                  name="category"
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  className="h-8 w-40 text-xs"
                >
                  <option value="all">All</option>
                  {categories.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              </label>
              <ResponsiveContainer width="100%" height={190}>
                <LineChart
                  data={points}
                  margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
                >
                  <CartesianGrid stroke={GRID_STROKE} vertical={false} />
                  <XAxis
                    dataKey="i"
                    tick={AXIS_TICK}
                    tickLine={false}
                    interval="preserveStartEnd"
                    tickFormatter={(value) =>
                      String(points[Number(value)]?.label ?? "")
                    }
                  />
                  <YAxis
                    allowDecimals={false}
                    tick={AXIS_TICK}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP_STYLE}
                    labelFormatter={(value) =>
                      String(points[Number(value)]?.label ?? "")
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {selected.map((name) => (
                    <Line
                      key={name}
                      type="monotone"
                      dataKey={`cat_${name}`}
                      stroke={
                        CATEGORY_COLORS[
                          categories.indexOf(name) % CATEGORY_COLORS.length
                        ]
                      }
                      strokeWidth={2}
                      dot={{ r: 2 }}
                      name={name}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
              {latest !== undefined && (
                <ul className="mt-2 flex flex-col gap-1 text-xs">
                  {selected.map((name) => {
                    // A category that exists only in an older run is a real zero in the
                    // latest one; linking it to the latest report would open the report
                    // unfiltered, because that report has no such category to filter by.
                    const count = latest.by_category?.[name] ?? 0;
                    return (
                      <li key={name}>
                        {count > 0 ? (
                          <Link
                            className="text-brand hover:underline"
                            href={`/audits/${latest.audit_id}?category=${encodeURIComponent(name)}`}
                          >
                            {name}: {count} in the latest run
                          </Link>
                        ) : (
                          <span className="text-muted-foreground">
                            {name}: 0 in the latest run
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {hasReports
                ? "The runs in this window wrote reports but found nothing, so there is no category to break down."
                : "No stored report in this window, so there is no category to break down."}
            </p>
          )}
        </ChartCard>

        <ChartCard
          title="Cost per run"
          note="An estimate from the pinned price table, not an invoice; a run with an unpriced model has no bar."
          wide
        >
          {hasCost ? (
            <>
              <ResponsiveContainer width="100%" height={210}>
                <BarChart
                  data={points}
                  margin={{ top: 8, right: 8, bottom: 0, left: -8 }}
                >
                  <CartesianGrid stroke={GRID_STROKE} vertical={false} />
                  <XAxis
                    dataKey="i"
                    tick={AXIS_TICK}
                    tickLine={false}
                    interval="preserveStartEnd"
                    tickFormatter={(value) =>
                      String(points[Number(value)]?.label ?? "")
                    }
                  />
                  <YAxis
                    tick={AXIS_TICK}
                    tickLine={false}
                    tickFormatter={(value) => `$${value}`}
                  />
                  <Tooltip
                    labelFormatter={(value) =>
                      String(points[Number(value)]?.label ?? "")
                    }
                    contentStyle={TOOLTIP_STYLE}
                    cursor={{ fill: "#f4f4f5" }}
                    formatter={(value) => [
                      `$${Number(value).toFixed(4)}`,
                      "estimate",
                    ]}
                  />
                  <Bar
                    dataKey="cost"
                    fill="#1d4d3b"
                    name="cost (estimate)"
                    isAnimationActive={false}
                  />
                </BarChart>
              </ResponsiveContainer>
              {costIsZero && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Every recorded cost estimate in this window is zero.
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              No run in this window carries a cost estimate: no model was
              called, the model has no price in the table, or the provider
              reported no usage to price.
            </p>
          )}
        </ChartCard>
      </div>

      {runs.some((run) => run.duration_ms !== null) && (
        <p className="mt-3 px-1 text-[11px] leading-relaxed text-muted-foreground">
          Latest duration:{" "}
          {formatDuration(
            [...runs].reverse().find((run) => run.duration_ms !== null)
              ?.duration_ms ?? 0,
          )}
          . Tokens and calls are measured; the dollar figure is an estimate.
        </p>
      )}
    </>
  );
}
