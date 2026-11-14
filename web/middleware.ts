import { type NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, sessionSecret, verifySession } from "./app/lib/auth";

const PUBLIC_PATHS = new Set(["/login", "/auth/login"]);
// Public report links will live under /share/<token>. Add that prefix here when the route
// exists; never make the whole app public to ship sharing.

export async function middleware(request: NextRequest): Promise<Response> {
  const { pathname, search } = request.nextUrl;
  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  const secret = sessionSecret();
  const allowed =
    secret !== null &&
    (await verifySession(secret, request.cookies.get(SESSION_COOKIE)?.value));

  if (allowed) {
    return NextResponse.next();
  }

  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { detail: "authentication required" },
      { status: 401 },
    );
  }

  const isNavigation = request.method === "GET" || request.method === "HEAD";
  const suffix = isNavigation
    ? `?next=${encodeURIComponent(`${pathname}${search}`)}`
    : "";
  const forwardedProto = request.headers
    .get("x-forwarded-proto")
    ?.split(",")[0]
    ?.trim();
  const proto = forwardedProto === "https" ? "https" : "http";
  const host = request.headers.get("host") ?? request.nextUrl.host;
  // Use the public host the proxy forwarded; request.nextUrl.origin is the loopback
  // address behind nginx. A form POST cannot be replayed against /login, so it gets a
  // 303 (GET) instead of a 307.
  return NextResponse.redirect(
    new URL(`/login${suffix}`, `${proto}://${host}`),
    {
      status: isNavigation ? 307 : 303,
    },
  );
}

export const config = {
  matcher: ["/((?!_next|favicon.ico).*)"],
};
