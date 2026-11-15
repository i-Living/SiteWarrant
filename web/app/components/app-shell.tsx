"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import type { SiteSummary } from "../lib/audits";
import { Sidebar } from "./sidebar";
import { TopBar } from "./top-bar";

/** The app shell, except on the login page: that page is the only public route. */
export function AppShell({
  recent,
  children,
}: {
  recent: SiteSummary[];
  children: ReactNode;
}) {
  const pathname = usePathname();

  if (pathname === "/login") {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-dvh bg-muted/30">
      <Sidebar recent={recent} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="mx-auto w-full max-w-[1180px] flex-1 px-4 py-5 lg:px-6 lg:py-6">
          {children}
        </main>
      </div>
    </div>
  );
}
