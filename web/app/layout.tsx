import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { PrimaryNav } from "./components/nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "SiteWarrant",
  description: "Evidence-first website quality auditor.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="masthead">
          <Link href="/" className="brand">
            SiteWarrant
          </Link>
          <PrimaryNav />
        </header>
        {children}
      </body>
    </html>
  );
}
