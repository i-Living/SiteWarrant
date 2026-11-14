"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { RunRow } from "../components/run-row";
import type { AuditSummary } from "../lib/audits";
import { formatClock, isBenchmarkSite, isLocalSite } from "../lib/format";

const REFRESH_MS = 2000;

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
            if (row.status !== "running") {
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

  const running = rows?.filter((audit) => audit.status === "running") ?? [];
  const finished = rows?.filter((audit) => audit.status !== "running") ?? [];
  const publicFinished = finished.filter((audit) => !isLocalSite(audit.site));
  const recent = publicFinished.slice(0, 25);
  const fixtureFinished = finished.filter(
    (audit) => isLocalSite(audit.site) && !isBenchmarkSite(audit.site),
  );
  const fixture = fixtureFinished.slice(0, 10);
  const bench = finished.filter((audit) => isBenchmarkSite(audit.site));

  return (
    <main>
      <header className="page-head">
        <p className="eyebrow">Live queue</p>
        <h1>Runs</h1>
        <p className="lede">
          {audits === null
            ? "Reading the queue…"
            : running.length === 0
              ? "Nothing is running."
              : `${running.length} ${running.length === 1 ? "audit" : "audits"} running.`}{" "}
          {audits !== null && updated !== null && (
            <>
              Updated {formatClock(updated)}; auto-refresh every{" "}
              {REFRESH_MS / 1000} s.{" "}
            </>
          )}
        </p>
      </header>

      {error !== null && (
        <div className="notice">
          <p>{error}</p>
          <p className="note">
            The page keeps the last answer it received and retries on the next
            tick.
          </p>
        </div>
      )}

      {audits !== null && (
        <>
          <section>
            <h2 className="section-label">
              <span>Running</span>
              <span className="section-count">{running.length}</span>
            </h2>
            {running.length === 0 ? (
              <p className="empty">
                Nothing is running now.{" "}
                <Link href="/audits/new">Start one</Link>.
              </p>
            ) : (
              <ol className="ledger">
                {running.map((audit) => (
                  <RunRow
                    key={audit.audit_id}
                    audit={audit}
                    now={now}
                    highlighted={audit.audit_id === highlight}
                  />
                ))}
              </ol>
            )}
          </section>

          <section>
            <h2 className="section-label">
              <span>Recent</span>
              <span className="section-count">{recent.length}</span>
            </h2>
            {recent.length === 0 ? (
              <p className="empty">No public run has finished yet.</p>
            ) : (
              <ol className="ledger">
                {recent.map((audit) => (
                  <RunRow
                    key={audit.audit_id}
                    audit={audit}
                    now={now}
                    highlighted={audit.audit_id === highlight}
                  />
                ))}
              </ol>
            )}
          </section>

          {fixture.length > 0 && (
            <section>
              <h2 className="section-label">
                <span>Local fixture</span>
                <span className="section-count">{fixture.length}</span>
              </h2>
              <ol className="ledger">
                {fixture.map((audit) => (
                  <RunRow
                    key={audit.audit_id}
                    audit={audit}
                    now={now}
                    highlighted={audit.audit_id === highlight}
                  />
                ))}
              </ol>
              {fixtureFinished.length > fixture.length && (
                <p className="empty">
                  Showing the {fixture.length} most recent of{" "}
                  {fixtureFinished.length} fixture runs.
                </p>
              )}
            </section>
          )}

          {bench.length > 0 && (
            <details className="ledger-group">
              <summary>
                <span>Benchmark corpus</span>
                <span className="group-count">{bench.length}</span>
              </summary>
              <p className="group-note">
                Generated pages from the frozen eval corpus, not customer sites.
              </p>
              <ol className="ledger">
                {bench.map((audit) => (
                  <RunRow
                    key={audit.audit_id}
                    audit={audit}
                    now={now}
                    highlighted={audit.audit_id === highlight}
                  />
                ))}
              </ol>
            </details>
          )}
        </>
      )}
    </main>
  );
}
