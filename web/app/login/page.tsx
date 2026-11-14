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
    <main>
      <div className="login-card">
        <div className="login-top">
          <header className="page-head">
            <p className="eyebrow">Restricted</p>
            <h1>Sign in</h1>
            <p className="lede">
              The audit ledger is private. Enter the operator login and password
              to continue.
            </p>
          </header>

          {!configured && (
            <div className="notice">
              <p>Authentication is not configured.</p>
              <p className="note">
                Set <code>SITEWARRANT_AUTH_LOGIN</code>,{" "}
                <code>SITEWARRANT_AUTH_PASSWORD</code> and{" "}
                <code>SITEWARRANT_AUTH_SECRET</code> (32 characters or more),
                then restart the web app.
              </p>
            </div>
          )}

          {error === "1" && (
            <p className="form-error">Wrong login or password.</p>
          )}
        </div>

        {configured && (
          <form className="login-form" action="/auth/login" method="post">
            <label htmlFor="login">Login</label>
            <div className="input-line">
              <input
                id="login"
                name="login"
                type="text"
                autoComplete="username"
                required
              />
            </div>
            <label htmlFor="password">Password</label>
            <div className="input-line">
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </div>
            <button className="login-submit" type="submit">
              Sign in
            </button>
            <input type="hidden" name="next" value={target} />
          </form>
        )}
      </div>
    </main>
  );
}
