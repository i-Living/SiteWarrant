import { ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import { authSettings, safeNextPath } from "../lib/auth";

export const metadata: Metadata = {
  title: "Sign in · SiteWarrant",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; next?: string }>;
}) {
  const { error, next } = await searchParams;
  const configured = authSettings() !== null;
  const target = safeNextPath(next);

  return (
    <main className="flex min-h-dvh flex-col items-center px-6 py-8">
      <div className="flex w-full max-w-sm items-center gap-2.5">
        <span className="flex size-7 items-center justify-center rounded-md bg-foreground text-background">
          <ShieldCheck className="size-4" aria-hidden="true" />
        </span>
        <span className="text-sm font-semibold tracking-tight">
          SiteWarrant
        </span>
      </div>

      {/* The two fields sit on the middle line of the screen; the heading and the submit
          split the free space above and below them. */}
      <div className="grid w-full max-w-sm flex-1 grid-rows-[1fr_auto_1fr]">
        <div className="self-end pb-8">
          <p className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
            Restricted
          </p>
          <h1 className="mt-1.5 text-2xl font-semibold tracking-tight">
            Sign in
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            The audit ledger is private. Enter the operator login and password
            to continue.
          </p>
          {!configured && (
            <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <p className="font-medium">Authentication is not configured.</p>
              <p className="mt-1">
                Set <code className="font-mono">SITEWARRANT_AUTH_LOGIN</code>,{" "}
                <code className="font-mono">SITEWARRANT_AUTH_PASSWORD</code> and{" "}
                <code className="font-mono">SITEWARRANT_AUTH_SECRET</code> (32
                characters or more), then restart the web app.
              </p>
            </div>
          )}
          {error === "1" && (
            <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
              Wrong login or password.
            </p>
          )}
        </div>

        {configured && (
          <form
            action="/auth/login"
            method="post"
            className="flex w-full max-w-sm flex-col gap-3"
          >
            <div className="flex flex-col gap-1.5">
              <label htmlFor="login" className="text-xs font-medium">
                Login
              </label>
              <input
                id="login"
                name="login"
                type="text"
                autoComplete="username"
                required
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="password" className="text-xs font-medium">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </div>
            <button
              className="mt-1 h-9 w-full rounded-md bg-brand px-4 text-sm font-medium text-white transition-colors hover:bg-brand/90"
              type="submit"
            >
              Sign in
            </button>
            <input type="hidden" name="next" value={target} />
          </form>
        )}

        <div aria-hidden="true" />
      </div>
    </main>
  );
}
