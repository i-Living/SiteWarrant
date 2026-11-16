"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { PageHeader } from "../../components/page-header";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";

function normalizeSite(value: string): string | null {
  const trimmed = value.trim();
  if (trimmed === "") {
    return null;
  }
  const withScheme = /^[a-z][a-z\d+.-]*:\/\//i.test(trimmed)
    ? trimmed
    : `https://${trimmed}`;
  try {
    const url = new URL(withScheme);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

export default function NewAuditPage() {
  const router = useRouter();
  const [site, setSite] = useState("");
  const [scope, setScope] = useState<"page" | "sitemap">("page");
  const [pages, setPages] = useState("10");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = normalizeSite(site);
    if (target === null) {
      setError("Enter a site address, for example https://example.com.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/api/audits", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(
          scope === "sitemap"
            ? { url: target, scope, max_pages: Number(pages) }
            : { url: target, scope },
        ),
      });
      if (!response.ok) {
        setError(
          `The API refused the audit (${response.status}). ${await response.text()}`,
        );
        return;
      }
      const created = (await response.json()) as { audit_id: string };
      router.push(`/audits#${created.audit_id}`);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The audit API could not be reached.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="New audit"
        description="Point SiteWarrant at a page or a sitemap. It captures the page at every configured viewport and reports each finding with the fact behind it."
      />

      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <Card>
          <CardContent>
            <form onSubmit={submit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="site">
                  {scope === "sitemap" ? "Site URL" : "Page URL"}
                </Label>
                <Input
                  id="site"
                  name="site"
                  value={site}
                  onChange={(event) => setSite(event.target.value)}
                  placeholder={
                    scope === "sitemap"
                      ? "https://example.com/"
                      : "https://example.com/pricing"
                  }
                  autoComplete="url"
                  spellCheck={false}
                  disabled={submitting}
                />
              </div>

              <div className="flex flex-wrap gap-3">
                <div className="flex min-w-52 flex-col gap-2">
                  <Label htmlFor="scope">Scope</Label>
                  <Select
                    id="scope"
                    name="scope"
                    value={scope}
                    onChange={(event) =>
                      setScope(
                        event.target.value === "sitemap" ? "sitemap" : "page",
                      )
                    }
                    disabled={submitting}
                  >
                    <option value="page">This page</option>
                    <option value="sitemap">Every page in sitemap.xml</option>
                  </Select>
                </div>
                {scope === "sitemap" && (
                  <div className="flex min-w-40 flex-col gap-2">
                    <Label htmlFor="pages">Pages</Label>
                    <Select
                      id="pages"
                      name="pages"
                      value={pages}
                      onChange={(event) => setPages(event.target.value)}
                      disabled={submitting}
                    >
                      <option value="10">Up to 10</option>
                      <option value="50">All (50 at most)</option>
                    </Select>
                  </div>
                )}
              </div>

              {error !== null && (
                <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
                  {error}
                </p>
              )}

              <div className="flex items-center gap-3">
                <Button type="submit" variant="brand" disabled={submitting}>
                  {submitting ? "Starting…" : "Start audit"}
                </Button>
                <p className="text-xs text-muted-foreground">
                  The run continues in the background; this tab can close once
                  it starts.
                </p>
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-3">
          <Card className="gap-1 py-3">
            <CardContent>
              <p className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
                Scope
              </p>
              <p className="mt-1 text-sm">
                One page, or up to 50 sitemap pages
              </p>
            </CardContent>
          </Card>
          <Card className="gap-1 py-3">
            <CardContent>
              <p className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
                Passes
              </p>
              <p className="mt-1 text-sm">Eight measurement channels</p>
            </CardContent>
          </Card>
          <Card className="gap-1 py-3">
            <CardContent>
              <p className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
                Output
              </p>
              <p className="mt-1 text-sm">Findings, causes, evidence</p>
            </CardContent>
          </Card>
        </div>
      </div>

      <p className="mt-4 px-1 text-xs text-muted-foreground">
        Private addresses are refused unless the deployment names the host in{" "}
        <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
          SITEWARRANT_ALLOW_PRIVATE_HOSTS
        </code>
        .
      </p>
    </>
  );
}
