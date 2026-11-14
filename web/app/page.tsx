import Link from "next/link";
import { redirect } from "next/navigation";
import { SeverityLine } from "./components/severity-line";
import { listSites, type SiteSummary } from "./lib/audits";
import { formatDate, isLocalHost } from "./lib/format";

function SiteLedger({ sites }: { sites: SiteSummary[] }) {
  return (
    <ol className="ledger">
      {sites.map((site) => (
        <li key={site.host} className="ledger-row">
          <Link
            href={`/sites/${encodeURIComponent(site.host)}`}
            className="row-grid row-link"
            title={site.host}
          >
            <span className="row-main">
              <span className="site-name">
                <span className="site-host">
                  {site.host}
                  {isLocalHost(site.host) && (
                    <span className="site-tag">local</span>
                  )}
                </span>
              </span>
              <span className="row-meta">
                {site.pages} {site.pages === 1 ? "page" : "pages"} · {site.runs}{" "}
                {site.runs === 1 ? "run" : "runs"} · last{" "}
                {formatDate(site.last_activity)}
              </span>
            </span>
            <SeverityLine
              counts={site.by_severity}
              total={site.findings_total}
              status={site.running > 0 ? "running" : "completed"}
            />
            <span className="site-flags">
              {site.running > 0 && (
                <span className="flag" data-state="running">
                  <span className="status-dot" aria-hidden="true" />
                  {site.running} running
                </span>
              )}
              {site.failed > 0 && (
                <span className="flag" data-state="failed">
                  {site.failed} failed
                </span>
              )}
            </span>
            <span className="row-arrow" aria-hidden="true">
              →
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ audit?: string }>;
}) {
  const { audit } = await searchParams;
  // The report used to live on the home page; old links keep working.
  if (audit) {
    redirect(`/audits/${audit}`);
  }

  let sites: SiteSummary[] = [];
  let error: string | null = null;
  try {
    sites = await listSites();
  } catch (cause) {
    error =
      cause instanceof Error
        ? cause.message
        : "The audit API could not be reached.";
  }

  const publicSites = sites.filter((site) => !isLocalHost(site.host));
  const localSites = sites.filter((site) => isLocalHost(site.host));
  const running = sites.reduce((total, site) => total + site.running, 0);

  return (
    <main>
      <header className="page-head">
        <p className="eyebrow">Audit ledger</p>
        <h1>Sites</h1>
        <p className="lede">
          Every audited host, with its latest result per page. Open a host to
          see its pages.
        </p>
      </header>

      {running > 0 && (
        <Link href="/audits" className="live-bar">
          <span className="pulse" aria-hidden="true" />
          <span>
            {running === 1
              ? "One page audit is running now"
              : `${running} page audits are running now`}
          </span>
          <span className="live-bar-go">Follow →</span>
        </Link>
      )}

      {error !== null && (
        <div className="notice">
          <p>{error}</p>
          <p className="note">
            Start the API with <code>uv run sitewarrant-api</code>, or point{" "}
            <code>SITEWARRANT_API</code> at it.
          </p>
        </div>
      )}

      {error === null && sites.length === 0 && (
        <div className="empty-state">
          <p>No host has been audited yet.</p>
          <Link className="button-link" href="/audits/new">
            Run the first audit
          </Link>
        </div>
      )}

      {publicSites.length > 0 && (
        <section>
          <h2 className="section-label">
            <span>Sites</span>
            <span className="section-count">{publicSites.length}</span>
          </h2>
          <SiteLedger sites={publicSites} />
        </section>
      )}

      {localSites.length > 0 && (
        <details className="ledger-group" open={publicSites.length === 0}>
          <summary>
            <span>Local hosts</span>
            <span className="group-count">{localSites.length}</span>
          </summary>
          <p className="group-note">
            Fixture and benchmark pages served from this machine.
          </p>
          <SiteLedger sites={localSites} />
        </details>
      )}
    </main>
  );
}
