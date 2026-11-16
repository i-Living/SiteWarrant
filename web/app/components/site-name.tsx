import { splitSite } from "../lib/format";

export function SiteName({ site }: { site: string }) {
  const { host, path } = splitSite(site);

  return (
    <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
      <span className="truncate text-sm font-medium text-foreground">
        {host}
      </span>
      {path !== "" && (
        <span className="truncate font-mono text-xs text-muted-foreground">
          {path}
        </span>
      )}
    </span>
  );
}
