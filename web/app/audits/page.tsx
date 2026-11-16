"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { PageHeader } from "../components/page-header";
import { RunRow } from "../components/run-row";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import type { AuditSummary } from "../lib/audits";
import { formatClock, isBenchmarkSite, isLocalSite } from "../lib/format";

const REFRESH_MS = 2000;

function RunSection({
  title,
  count,
  rows,
  now,
  highlight,
  empty,
  note,
}: {
  title: string;
  count: number;
  rows: AuditSummary[];
  now: number;
  highlight: string | null;
  empty: string;
  note?: string;
}) {
  return (
    <Card className="mb-5 gap-0 overflow-hidden py-0">
      <div className="flex items-center justify-between px-4 py-2.5">
        <h2 className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
          {title}
        </h2>
        <Badge variant="muted">{count}</Badge>
      </div>
      {note !== undefined && (
        <p className="px-4 pb-2 text-xs text-muted-foreground">{note}</p>
      )}
      <div className="hidden grid-cols-[minmax(0,1fr)_11rem_6.5rem_5.5rem] gap-x-4 border-t border-border px-4 py-1.5 text-[10px] font-medium tracking-wider text-muted-foreground uppercase md:grid">
        <span>Run</span>
        <span>Findings</span>
        <span>Status</span>
        <span className="text-right">Report</span>
      </div>
      {rows.length === 0 ? (
        <p className="border-t border-border px-4 py-3 text-sm text-muted-foreground">
          {empty}
        </p>
      ) : (
        <div className="border-t border-border md:border-t-0">
          {rows.map((audit) => (
            <div
              key={audit.audit_id}
              className="border-b border-border last:border-b-0"
            >
              <RunRow
                audit={audit}
                now={now}
                highlighted={audit.audit_id === highlight}
              />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function AuditsPage() {
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);
  const [pinned, setPinned] = useState<AuditSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [updated, setUpdated] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const scrolled = useRef(false);

  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (hash !== "") {
      setHighlight(hash);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load(force: boolean) {
      if (document.hidden && !force) {
        return;
      }
      try {
        const response = await fetch("/api/audits?limit=100", {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(`The audit API answered ${response.status}.`);
        }
        const body = (await response.json()) as AuditSummary[];
        if (!cancelled) {
          setAudits(body);
          setError(null);
          setNow(Date.now());
          setUpdated(Date.now());
        }
      } catch (cause) {
        if (!cancelled) {
          setError(
            cause instanceof Error
              ? cause.message
              : "The audit API could not be reached.",
          );
        }
      }
    }

    void load(true);
    const timer = setInterval(() => void load(false), REFRESH_MS);
    const onVisibility = () => {
      if (!document.hidden) {
        void load(true);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  // The list is a bounded window of the newest runs, so the audit the visitor came for is read
  // on its own path — same origin through the /api rewrite, never the browser reaching for the
  // API's address — and kept fresh until it reaches a terminal status, because the window stops
  // carrying it. A failed attempt is retried on the next tick instead of ending the recovery.
  useEffect(() => {
    if (highlight === null) {
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let misses = 0;
    const refresh = async () => {
      try {
        const response = await fetch(
          `/api/audits/${encodeURIComponent(highlight)}`,
          {
            cache: "no-store",
          },
        );
        if (cancelled) {
          return;
        }
        if (response.status === 404) {
          // `POST /audits` answers 202 before its row exists, so the first poll of a fresh
          // submission can miss it. Keep trying for about half a minute; an id that never
          // resolves is not worth polling forever.
          misses += 1;
          if (misses > 15) {
            return;
          }
        } else {
          misses = 0;
          if (response.ok) {
            const row = (await response.json()) as AuditSummary;
            if (cancelled) {
              return;
            }
            setPinned(row);
            if (row.status !== "running" && row.status !== "queued") {
              return;
            }
          }
        }
      } catch {
        // Retried below; the list keeps its own error banner.
      }
      if (cancelled) {
        // The page was left while this request was in flight: a new timer here would poll
        // forever, because the cleanup that would have cleared it has already run.
        return;
      }
      timer = setTimeout(refresh, REFRESH_MS);
    };
    void refresh();
    return () => {
      cancelled = true;
      if (timer !== undefined) {
        clearTimeout(timer);
      }
    };
  }, [highlight]);

  const pinnedRow =
    highlight !== null && pinned !== null && pinned.audit_id === highlight
      ? pinned
      : null;
  const rows =
    audits === null
      ? null
      : pinnedRow !== null &&
          !audits.some((audit) => audit.audit_id === pinnedRow.audit_id)
        ? [pinnedRow, ...audits]
        : audits;

  useEffect(() => {
    if (highlight === null || rows === null || scrolled.current) {
      return;
    }
    const row = document.getElementById(highlight);
    if (row !== null) {
      row.scrollIntoView({ block: "center" });
      scrolled.current = true;
    }
  }, [highlight, rows]);

  const inFlight =
    rows?.filter(
      (audit) => audit.status === "running" || audit.status === "queued",
    ) ?? [];
  const finished =
    rows?.filter(
      (audit) => audit.status !== "running" && audit.status !== "queued",
    ) ?? [];
  const publicFinished = finished.filter((audit) => !isLocalSite(audit.site));
  const recent = publicFinished.slice(0, 25);
  const fixtureFinished = finished.filter(
    (audit) => isLocalSite(audit.site) && !isBenchmarkSite(audit.site),
  );
  const fixture = fixtureFinished.slice(0, 10);
  const bench = finished.filter((audit) => isBenchmarkSite(audit.site));

  return (
    <>
      <PageHeader
        title="Runs"
        description={
          audits === null
            ? "Reading the queue…"
            : inFlight.length === 0
              ? "Nothing is queued or running."
              : `${inFlight.length} ${inFlight.length === 1 ? "audit" : "audits"} queued or running.`
        }
        meta={
          audits !== null && updated !== null ? (
            <>
              Updated {formatClock(updated)}; auto-refresh every{" "}
              {REFRESH_MS / 1000} s.
            </>
          ) : undefined
        }
        actions={
          <Button asChild variant="brand">
            <Link href="/audits/new">New audit</Link>
          </Button>
        }
      />

      {error !== null && (
        <Card className="mb-5 border-red-200 bg-red-50/60">
          <CardContent className="py-1 text-sm text-red-800">
            <p className="font-medium">{error}</p>
            <p className="mt-1 text-red-700/80">
              The page keeps the last answer it received and retries on the next
              tick.
            </p>
          </CardContent>
        </Card>
      )}

      {audits === null ? (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            Reading the queue…
          </CardContent>
        </Card>
      ) : (
        <>
          <RunSection
            title="In flight"
            count={inFlight.length}
            rows={inFlight}
            now={now}
            highlight={highlight}
            empty="Nothing is queued or running now."
          />
          <RunSection
            title="Recent"
            count={recent.length}
            rows={recent}
            now={now}
            highlight={highlight}
            empty="No public run has finished yet."
          />
          {fixture.length > 0 && (
            <RunSection
              title="Local fixture"
              count={fixture.length}
              rows={fixture}
              now={now}
              highlight={highlight}
              empty=""
              note={
                fixtureFinished.length > fixture.length
                  ? `Showing the ${fixture.length} most recent of ${fixtureFinished.length} fixture runs.`
                  : undefined
              }
            />
          )}
          {bench.length > 0 && (
            <details className="group rounded-xl border border-border bg-card">
              <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-xs font-medium tracking-wider text-muted-foreground uppercase">
                <span>Benchmark corpus</span>
                <Badge variant="muted">{bench.length}</Badge>
              </summary>
              <p className="px-4 pb-2 text-xs text-muted-foreground">
                Generated pages from the frozen eval corpus, not customer sites.
              </p>
              <ul className="border-t border-border">
                {bench.map((audit) => (
                  <li
                    key={audit.audit_id}
                    className="border-b border-border last:border-b-0"
                  >
                    <RunRow
                      audit={audit}
                      now={now}
                      highlighted={audit.audit_id === highlight}
                    />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </>
  );
}
