"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

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
        body: JSON.stringify({ url: target }),
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
    <main>
      <header className="page-head">
        <p className="eyebrow">New audit</p>
        <h1>Point it at one page.</h1>
        <p className="lede">
          SiteWarrant captures the page at every configured viewport and reports
          each finding with the fact behind it. The run continues in the
          background, so this tab can close once it starts.
        </p>
      </header>

      <form className="audit-form" onSubmit={submit}>
        <label htmlFor="site">Page URL</label>
        <div className="input-line">
          <input
            id="site"
            name="site"
            value={site}
            onChange={(event) => setSite(event.target.value)}
            placeholder="https://example.com/pricing"
            autoComplete="url"
            spellCheck={false}
            disabled={submitting}
          />
          <button type="submit" disabled={submitting}>
            {submitting ? "Starting…" : "Start audit"}
          </button>
        </div>
        {error !== null && <p className="form-error">{error}</p>}
      </form>

      <dl className="facts">
        <div>
          <dt>Scope</dt>
          <dd>One public page</dd>
        </div>
        <div>
          <dt>Passes</dt>
          <dd>Eight measurement channels</dd>
        </div>
        <div>
          <dt>Output</dt>
          <dd>Findings, causes, evidence</dd>
        </div>
      </dl>

      <p className="note">
        Private addresses are refused unless the deployment names the host in{" "}
        <code>SITEWARRANT_ALLOW_PRIVATE_HOSTS</code>.
      </p>
    </main>
  );
}
