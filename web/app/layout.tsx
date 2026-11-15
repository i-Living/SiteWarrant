import type { Metadata } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { AppShell } from "./components/app-shell";
import { listSites, type SiteSummary } from "./lib/audits";
import "./globals.css";

export const metadata: Metadata = {
  title: "SiteWarrant",
  description: "Evidence-first website quality auditor.",
};

export default async function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  // The sidebar's recent hosts are a convenience: without a session (the login page) or with
  // an API that is down, the shell renders without them instead of failing the page.
  const session = (await cookies()).get("sitewarrant_session");
  let recent: SiteSummary[] = [];
  if (session !== undefined) {
    try {
      recent = (await listSites()).slice(0, 3);
    } catch {
      recent = [];
    }
  }

  return (
    <html lang="en">
      <body>
        <AppShell recent={recent}>{children}</AppShell>
      </body>
    </html>
  );
}
