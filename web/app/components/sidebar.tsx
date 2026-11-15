"use client";

import {
  Activity,
  LayoutGrid,
  ListChecks,
  Plus,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { SiteSummary } from "../lib/audits";
import { cn } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

const NAV = [
  {
    href: "/",
    label: "Sites",
    icon: LayoutGrid,
    active: (path: string) => path === "/" || path.startsWith("/sites"),
  },
  {
    href: "/audits",
    label: "Runs",
    icon: ListChecks,
    active: (path: string) => path === "/audits" || path.startsWith("/audits/"),
  },
];

/**
 * The same destinations as the sidebar, for the viewports where the sidebar is hidden. The
 * top bar only carries breadcrumbs and sign-out, so without this the Runs list would have no
 * link at all on a phone.
 */
export function CompactNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Main"
      className="flex items-center gap-1 border-b border-border bg-background px-3 py-2 lg:hidden"
    >
      {NAV.map((item) => {
        const isActive = item.active(pathname);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex h-8 flex-1 items-center justify-center gap-1.5 rounded-md text-xs transition-colors",
              isActive
                ? "bg-brand/10 font-medium text-brand"
                : "text-muted-foreground hover:bg-accent hover:text-foreground",
            )}
          >
            <item.icon className="size-3.5" aria-hidden="true" />
            {item.label}
          </Link>
        );
      })}
      <Link
        href="/audits/new"
        className="flex h-8 items-center gap-1 rounded-md bg-brand px-2.5 text-xs font-medium text-white"
      >
        <Plus className="size-3.5" aria-hidden="true" />
        New
      </Link>
    </nav>
  );
}

export function Sidebar({ recent }: { recent: SiteSummary[] }) {
  const pathname = usePathname();

  return (
    <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-4 lg:flex">
      <Link href="/" className="flex items-center gap-2.5 px-2">
        <span className="flex size-7 items-center justify-center rounded-md bg-foreground text-background">
          <ShieldCheck className="size-4" aria-hidden="true" />
        </span>
        <span className="text-sm font-semibold tracking-tight">
          SiteWarrant
        </span>
      </Link>

      <nav aria-label="Main" className="mt-6 flex flex-col gap-1">
        {NAV.map((item) => {
          const isActive = item.active(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors",
                isActive
                  ? "bg-brand/10 font-medium text-brand"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <item.icon className="size-4" aria-hidden="true" />
              {item.label}
            </Link>
          );
        })}
        <Button asChild variant="brand" className="mt-3 w-full">
          <Link href="/audits/new">
            <Plus className="size-4" aria-hidden="true" />
            New audit
          </Link>
        </Button>
      </nav>

      {recent.length > 0 && (
        <div className="mt-7">
          <p className="px-2 text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
            Recent hosts
          </p>
          <ul className="mt-2 flex flex-col gap-0.5">
            {recent.map((site) => (
              <li key={site.host}>
                <Link
                  href={`/sites/${encodeURIComponent(site.host)}`}
                  className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-secondary text-[10px] font-medium uppercase">
                    {site.host.slice(0, 1)}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{site.host}</span>
                  {site.running > 0 && (
                    <Activity
                      className="size-3.5 text-blue-600"
                      aria-label="running"
                    />
                  )}
                  <Badge variant="muted" className="px-1.5 py-0 text-[10px]">
                    {site.runs}
                  </Badge>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-auto flex items-center gap-2.5 border-t border-sidebar-border px-2 pt-3">
        <span className="flex size-7 items-center justify-center rounded-full bg-secondary text-[11px] font-medium">
          OP
        </span>
        <span className="min-w-0">
          <span className="block truncate text-xs font-medium">Operator</span>
          <span className="block text-[11px] text-muted-foreground">
            single-tenant
          </span>
        </span>
      </div>
    </aside>
  );
}
