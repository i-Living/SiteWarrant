export const SESSION_COOKIE = "sitewarrant_session";
export const SESSION_TTL_SECONDS = 60 * 60 * 24 * 7;
const SESSION_VERSION = "v1";

export function sessionSecret(): string | null {
  const secret = process.env.SITEWARRANT_AUTH_SECRET;
  return secret !== undefined && secret.length >= 32 ? secret : null;
}

export function authSettings(): {
  login: string;
  password: string;
  secret: string;
} | null {
  const login = process.env.SITEWARRANT_AUTH_LOGIN;
  const password = process.env.SITEWARRANT_AUTH_PASSWORD;
  const secret = sessionSecret();
  if (!login || !password || secret === null) {
    return null;
  }
  return { login, password, secret };
}

/**
 * A `next` value is a path on this origin, never an absolute URL. Re-parse it so a
 * backslash or a protocol-relative value cannot escape, and drop the fragment.
 */
export function safeNextPath(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /[\r\n]/.test(value)
  ) {
    return "/";
  }
  try {
    const parsed = new URL(value, "http://placeholder.invalid");
    if (parsed.origin !== "http://placeholder.invalid") {
      return "/";
    }
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return "/";
  }
}

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

function fromBase64Url(value: string): Uint8Array<ArrayBuffer> {
  const base64 = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

/** A session token is `v1.<expires>.<hmac>`; the expiry is inside the signed payload. */
export async function signSession(
  secret: string,
  ttlSeconds: number,
): Promise<string> {
  const expires = Math.floor(Date.now() / 1000) + ttlSeconds;
  const payload = `${SESSION_VERSION}.${expires}`;
  const signature = await crypto.subtle.sign(
    "HMAC",
    await hmacKey(secret),
    new TextEncoder().encode(payload),
  );
  return `${payload}.${toBase64Url(new Uint8Array(signature))}`;
}

export async function verifySession(
  secret: string,
  token: string | undefined,
): Promise<boolean> {
  if (token === undefined) {
    return false;
  }
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== SESSION_VERSION) {
    return false;
  }
  const expires = Number(parts[1]);
  if (!Number.isInteger(expires) || expires <= Math.floor(Date.now() / 1000)) {
    return false;
  }
  try {
    return await crypto.subtle.verify(
      "HMAC",
      await hmacKey(secret),
      fromBase64Url(parts[2]),
      new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
    );
  } catch {
    return false;
  }
}
