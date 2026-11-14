"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  {
    href: "/",
    label: "Sites",
    active: (path: string) => path === "/" || path.startsWith("/sites"),
  },
  {
    href: "/audits",
    label: "Runs",
    active: (path: string) =>
      path === "/audits" ||
      (path.startsWith("/audits/") && path !== "/audits/new"),
  },
];

export function PrimaryNav() {
  const pathname = usePathname();
  const onNewAudit = pathname === "/audits/new";

  if (pathname === "/login") {
    return null;
  }

  return (
    <nav className="nav" aria-label="Main">
      {LINKS.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          aria-current={link.active(pathname) ? "page" : undefined}
        >
          {link.label}
        </Link>
      ))}
      {!onNewAudit && (
        <Link className="nav-cta" href="/audits/new">
          New audit
        </Link>
      )}
      <form action="/auth/logout" method="post" className="nav-form">
        <button className="nav-signout" type="submit">
          Sign out
        </button>
      </form>
    </nav>
  );
}
