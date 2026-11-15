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

const SEVERITIES = ["blocker", "major", "minor", "info"] as const;

// The same palette as globals.css: the charts are part of the report's typography, not a
// second visual language. Explicit hex because SVG fills resolve `var()` per browser.
const SEVERITY_COLORS: Record<(typeof SEVERITIES)[number], string> = {
  blocker: "#a3231a",
  major: "#9d5209",
  minor: "#7a6a24",
  info: "#62676d",
};

const CATEGORY_COLORS = [
  "#1d4d3b",
  "#a3231a",
  "#4e5f8a",
  "#9d5209",
  "#7b4a74",
  "#3f6b6b",
  "#7a6a24",
  "#62676d",
];

const TOOLTIP_STYLE = {
  background: "var(--surface)",
  border: "1px solid var(--line)",
  fontFamily: "var(--mono)",
  fontSize: 11,
  color: "var(--ink)",
};

const AXIS_TICK = { fontSize: 11, fill: "#5f584c" };

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
    <article className={`dash-card${wide === true ? " dash-card-wide" : ""}`}>
      <h3>{title}</h3>
      <p className="note">{note}</p>
      <div className="chart-wrap">{children}</div>
    </article>
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
      point[`cat_${name}`] = run.by_category?.[name] ?? null;
    }
    return point;
  });

  const incomparable = runs.filter(
    (run) => run.compared_to !== null && run.comparable === false,
  );

  if (runs.every((run) => run.findings_total === null)) {
    return (
      <p className="empty">
        No run of this host has a stored report yet. The timeline draws itself
        when one finishes.
      </p>
    );
  }

  const selected = category === "all" ? categories : [category];
  const hasComparison = runs.some(
    (run) => run.new !== null || run.closed !== null,
  );
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
      <div className="dash-grid">
        <ChartCard
          title="Findings per run"
          note="Stacked by severity, from the stored report. A run without one leaves a gap instead of a zero."
          wide
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={points}
              margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
            >
              <CartesianGrid stroke="#dcd6c9" vertical={false} />
              <XAxis
                dataKey="i"
                tick={AXIS_TICK}
                tickLine={false}
                interval="preserveStartEnd"
                tickFormatter={(value) =>
                  String(points[Number(value)]?.label ?? "")
                }
              />
              <YAxis allowDecimals={false} tick={AXIS_TICK} tickLine={false} />
              <Tooltip
                labelFormatter={(value) =>
                  String(points[Number(value)]?.label ?? "")
                }
                contentStyle={TOOLTIP_STYLE}
                cursor={{ fill: "#e9e3d4" }}
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
                <CartesianGrid stroke="#dcd6c9" vertical={false} />
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
                  cursor={{ fill: "#e9e3d4" }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar
                  dataKey="opened"
                  fill="#9d5209"
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
            <p className="empty">
              No two runs in this window are comparable yet: a delta needs a
              previous report of the same page.
            </p>
          )}
          {comparisonIsZero && (
            <p className="chart-note">
              Every comparable pair in this window opened and closed nothing.
            </p>
          )}
          {incomparable.length > 0 && (
            <ul className="chart-note">
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
              <label className="filter-line">
                <span>Category</span>
                <select
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  <option value="all">All</option>
                  {categories.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <ResponsiveContainer width="100%" height={190}>
                <LineChart
                  data={points}
                  margin={{ top: 8, right: 8, bottom: 0, left: -18 }}
                >
                  <CartesianGrid stroke="#dcd6c9" vertical={false} />
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
                <ul className="category-list">
                  {selected.map((name) => (
                    <li key={name}>
                      <Link
                        href={`/audits/${latest.audit_id}?category=${encodeURIComponent(name)}`}
                      >
                        {name}: {latest.by_category?.[name] ?? "—"} in the
                        latest run
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p className="empty">
              The runs in this window wrote reports but found nothing, so there
              is no category to break down.
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
                  <CartesianGrid stroke="#dcd6c9" vertical={false} />
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
                    cursor={{ fill: "#e9e3d4" }}
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
                <p className="chart-note">
                  Every run with a cost figure in this window made no priced
                  model calls.
                </p>
              )}
            </>
          ) : (
            <p className="empty">
              No run in this window carries a cost estimate: either no model was
              called, or the model has no price in the table.
            </p>
          )}
        </ChartCard>
      </div>

      {runs.some((run) => run.duration_ms !== null) && (
        <p className="note dash-footnote">
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
