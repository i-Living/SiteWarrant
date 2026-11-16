import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Kpi } from "./components/kpi";
import { PageHeader } from "./components/page-header";
import { SeverityLine } from "./components/severity-line";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent } from "./components/ui/card";
import { listSites, type SiteSummary } from "./lib/audits";
import { formatDate, isLocalHost } from "./lib/format";

function SiteRow({ site }: { site: SiteSummary }) {
  return (
    <li className="border-t border-border first:border-t-0">
      <Link
        href={`/sites/${encodeURIComponent(site.host)}`}
        title={site.host}
        className="grid gap-x-4 gap-y-2 px-4 py-3 transition-colors hover:bg-muted/50 md:grid-cols-[minmax(0,1fr)_12rem_auto] md:items-center"
      >
        <div className="min-w-0">
          <span className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{site.host}</span>
            {isLocalHost(site.host) && (
              <Badge variant="outline" className="text-[10px]">
                local
              </Badge>
            )}
          </span>
          <p className="mt-1 text-xs text-muted-foreground">
            {site.pages} {site.pages === 1 ? "page" : "pages"} · {site.runs}{" "}
            {site.runs === 1 ? "run" : "runs"} · last{" "}
            {formatDate(site.last_activity)}
          </p>
        </div>
        <SeverityLine
          counts={site.by_severity}
          total={site.findings_total}
          status={site.running > 0 ? "running" : "completed"}
          coverage={{ measured: site.measured_pages, pages: site.pages }}
        />
        <div className="flex items-center gap-2 md:justify-end">
          {site.running > 0 && (
            <Badge
              variant="outline"
              className="gap-1.5 border-blue-200 bg-blue-50 text-blue-700"
            >
              <span className="size-1.5 animate-pulse rounded-full bg-current" />
              {site.running} running
            </Badge>
          )}
          {site.failed > 0 && (
            <Badge
              variant="outline"
              className="border-red-200 bg-red-50 text-red-700"
            >
              {site.failed} failed
            </Badge>
          )}
          <ChevronRight
            className="size-4 text-muted-foreground"
            aria-hidden="true"
          />
        </div>
      </Link>
    </li>
  );
}

function SiteList({ sites }: { sites: SiteSummary[] }) {
  return (
    <ul>
      {sites.map((site) => (
        <SiteRow key={site.host} site={site} />
      ))}
    </ul>
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
  const pages = sites.reduce((total, site) => total + site.pages, 0);
  const localPages = localSites.reduce((total, site) => total + site.pages, 0);
  const publicPages = publicSites.reduce(
    (total, site) => total + site.pages,
    0,
  );
  const runs = sites.reduce((total, site) => total + site.runs, 0);
  const failed = sites.reduce((total, site) => total + site.failed, 0);

  return (
    <>
      <PageHeader
        title="Sites"
        description="Every audited host, with its latest result per page. Open a host to see its pages."
        actions={
          <Button asChild variant="brand">
            <Link href="/audits/new">New audit</Link>
          </Button>
        }
      />

      {error !== null ? (
        <Card className="mb-5 border-red-200 bg-red-50/60">
          <CardContent className="py-1 text-sm text-red-800">
            <p className="font-medium">{error}</p>
            <p className="mt-1 text-red-700/80">
              Start the API with{" "}
              <code className="font-mono">uv run sitewarrant-api</code>, or
              point <code className="font-mono">SITEWARRANT_API</code> at it.
            </p>
          </CardContent>
        </Card>
      ) : sites.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-start gap-3 py-6">
            <div>
              <p className="text-sm font-medium">
                No host has been audited yet.
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Point SiteWarrant at a page or a sitemap and the ledger fills
                itself.
              </p>
            </div>
            <Button asChild variant="brand">
              <Link href="/audits/new">Run the first audit</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Hosts" value={sites.length} hint="one row per host" />
            <Kpi
              label="Pages"
              value={pages}
              hint={`${localPages} local, ${publicPages} public`}
            />
            <Kpi label="Runs recorded" value={runs} hint="all statuses" />
            <Kpi
              label="In flight"
              value={running}
              hint={failed > 0 ? `${failed} failed` : "nothing failed"}
            />
          </div>

          {running > 0 && (
            <Link
              href="/audits"
              className="mb-5 flex items-center gap-3 rounded-xl border border-brand/20 bg-brand/5 px-4 py-3 text-sm transition-colors hover:bg-brand/10"
            >
              <span className="size-2 animate-pulse rounded-full bg-brand" />
              <span className="flex-1">
                {running === 1
                  ? "One page audit is running now"
                  : `${running} page audits are running now`}
              </span>
              <span className="text-xs font-medium text-brand">Follow →</span>
            </Link>
          )}

          {publicSites.length > 0 && (
            <Card className="mb-5 gap-0 overflow-hidden py-0">
              <div className="flex items-center justify-between px-4 py-2.5">
                <h2 className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
                  Sites
                </h2>
                <Badge variant="muted">{publicSites.length}</Badge>
              </div>
              <SiteList sites={publicSites} />
            </Card>
          )}

          {localSites.length > 0 && (
            <details
              className="group rounded-xl border border-border bg-card"
              open={publicSites.length === 0}
            >
              <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-xs font-medium tracking-wider text-muted-foreground uppercase">
                <span>Local hosts</span>
                <Badge variant="muted">{localSites.length}</Badge>
              </summary>
              <p className="px-4 pb-1 text-xs text-muted-foreground">
                Fixture and benchmark pages served from this machine.
              </p>
              <div className="mt-2 border-t border-border">
                <SiteList sites={localSites} />
              </div>
            </details>
          )}
        </>
      )}
    </>
  );
}
