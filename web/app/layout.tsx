import type { Metadata } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import { AppShell } from "./components/app-shell";
import { listSites, type SiteSummary } from "./lib/audits";
import { SESSION_COOKIE, sessionSecret, verifySession } from "./lib/auth";
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
  // The sidebar's recent hosts are a convenience: without a verified session (the login page,
  // or a cookie somebody made up) or with an API that is down, the shell renders without them
  // instead of failing the page. The signature is checked here as well as in the middleware,
  // because a present cookie is not a session and a public response must not carry the ledger.
  const secret = sessionSecret();
  const authed =
    secret !== null &&
    (await verifySession(secret, (await cookies()).get(SESSION_COOKIE)?.value));

  let recent: SiteSummary[] = [];
  if (authed) {
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
