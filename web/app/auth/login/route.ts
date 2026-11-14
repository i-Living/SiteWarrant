import { timingSafeEqual } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";
import {
  authSettings,
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  safeNextPath,
  signSession,
} from "../../lib/auth";

export const runtime = "nodejs";

function sameValue(left: string, right: string): boolean {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function redirectTo(location: string): NextResponse {
  return new NextResponse(null, {
    status: 303,
    headers: { Location: location },
  });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const settings = authSettings();
  if (settings === null) {
    return redirectTo("/login?error=config");
  }

  const form = await request.formData();
  const login = form.get("login");
  const password = form.get("password");
  const target = safeNextPath(form.get("next"));

  const loginOk = typeof login === "string" && sameValue(login, settings.login);
  const passwordOk =
    typeof password === "string" && sameValue(password, settings.password);

  if (!loginOk || !passwordOk) {
    const failure = new URLSearchParams({ error: "1", next: target });
    return redirectTo(`/login?${failure.toString()}`);
  }

  const response = redirectTo(target);
  response.cookies.set(
    SESSION_COOKIE,
    await signSession(settings.secret, SESSION_TTL_SECONDS),
    {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: SESSION_TTL_SECONDS,
    },
  );
  return response;
}
