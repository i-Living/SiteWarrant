"use client";

import { ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Avatar } from "./ui/avatar";

function crumbs(pathname: string): string[] {
  if (pathname === "/") {
    return ["Sites"];
  }
  const parts = pathname
    .split("/")
    .filter(Boolean)
    .map((part) => {
      try {
        return decodeURIComponent(part);
      } catch {
        return part;
      }
    });
  if (parts[0] === "sites" && parts[1] !== undefined) {
    return parts[2] === "dashboard"
      ? ["Sites", parts[1], "Dashboard"]
      : ["Sites", parts[1]];
  }
  if (parts[0] === "audits") {
    if (parts[1] === undefined) {
      return ["Runs"];
    }
    return parts[1] === "new"
      ? ["Runs", "New audit"]
      : ["Runs", parts[1].slice(0, 8)];
  }
  return [];
}

export function TopBar() {
  const pathname = usePathname();
  const trail = crumbs(pathname);

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-4 border-b border-border bg-card/95 px-4 backdrop-blur lg:px-6">
      <Link href="/" className="flex items-center gap-2 lg:hidden">
        <span className="flex size-6 items-center justify-center rounded-md bg-foreground text-background">
          <ShieldCheck className="size-3.5" aria-hidden="true" />
        </span>
        <span className="text-sm font-semibold">SiteWarrant</span>
      </Link>

      <nav aria-label="Breadcrumb" className="hidden min-w-0 lg:block">
        <ol className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
          {trail.map((crumb, index) => (
            <li
              key={trail.slice(0, index + 1).join("/")}
              className="flex min-w-0 items-center gap-1.5"
            >
              {index > 0 && (
                <span aria-hidden="true" className="text-border">
                  /
                </span>
              )}
              <span
                className={
                  index === trail.length - 1
                    ? "truncate font-medium text-foreground"
                    : "truncate"
                }
                aria-current={index === trail.length - 1 ? "page" : undefined}
              >
                {crumb}
              </span>
            </li>
          ))}
        </ol>
      </nav>

      <div className="flex items-center gap-3">
        <form action="/auth/logout" method="post">
          <button
            type="submit"
            className="text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Sign out
          </button>
        </form>
        <Avatar aria-hidden="true">OP</Avatar>
      </div>
    </header>
  );
}
