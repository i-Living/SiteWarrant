import { splitSite } from "../lib/format";

export function SiteName({ site }: { site: string }) {
  const { host, path } = splitSite(site);

  return (
    <span className="site-name">
      <span className="site-host">{host}</span>
      {path !== "" && <span className="site-path">{path}</span>}
    </span>
  );
}
