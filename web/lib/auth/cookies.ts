import "server-only";

import { sealData, unsealData } from "iron-session";
import { z } from "zod";

import { serverEnv } from "@/lib/env";

export const SESSION_COOKIE = "cashapp_session";
export const REFRESH_COOKIE = "cashapp_refresh";
export const OIDC_COOKIE = "cashapp_oidc";

// A browser drops a cookie over about 4 KB, so a sealed value is split across chunk cookies:
// `name`, `name.1`, `name.2`... An IAM access token with groups seals to more than one chunk.
const CHUNK_SIZE = 3500;
const MAX_CHUNKS = 4;

export const SESSION_TTL_SECONDS = 8 * 60 * 60;
export const OIDC_TTL_SECONDS = 600;

// Two cookies so neither crosses the 4 KB limit: OCI access tokens carry groups and are large.
export const sessionPayloadSchema = z.object({
  subject: z.string().min(1),
  displayName: z.string().min(1),
  accessToken: z.string().min(1),
  expiresAt: z.number().int().positive(),
});
export type SessionPayload = z.infer<typeof sessionPayloadSchema>;

export const refreshPayloadSchema = z.object({
  refreshToken: z.string().min(1).nullable(),
  idToken: z.string().min(1),
});
export type RefreshPayload = z.infer<typeof refreshPayloadSchema>;

export const oidcPayloadSchema = z.object({
  state: z.string().min(1),
  nonce: z.string().min(1),
  codeVerifier: z.string().min(1),
  returnTo: z.string().min(1),
});
export type OidcPayload = z.infer<typeof oidcPayloadSchema>;

export type CookieOptions = Readonly<{
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: string;
  maxAge: number;
}>;

export type CookieSpec = Readonly<{
  name: string;
  value: string;
  options: CookieOptions;
}>;

export type SessionTokens = Readonly<{
  subject: string;
  displayName: string;
  accessToken: string;
  /** Epoch seconds. */
  expiresAt: number;
  refreshToken: string | null;
  idToken: string;
}>;

export type StoredSession = Readonly<{
  session: SessionPayload;
  refresh: RefreshPayload | null;
}>;

function options(path: string, maxAge: number): CookieOptions {
  // Secure only outside development, as in the other apps: a plain-HTTP dev origin may not keep them.
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path,
    maxAge,
  };
}

async function seal(payload: unknown, ttlSeconds: number): Promise<string> {
  return sealData(payload, {
    password: serverEnv.SESSION_SECRET,
    ttl: ttlSeconds,
  });
}

async function unseal<T>(
  value: string | undefined,
  schema: z.ZodType<T>,
  ttlSeconds: number,
): Promise<T | null> {
  if (!value) return null;
  try {
    const data = await unsealData(value, {
      password: serverEnv.SESSION_SECRET,
      ttl: ttlSeconds,
    });
    const parsed = schema.safeParse(data);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

function chunkName(name: string, index: number): string {
  return index === 0 ? name : `${name}.${index}`;
}

/** Splits a sealed value across chunk cookies and expires the chunk slots it does not use. */
function chunkSpecs(
  name: string,
  sealed: string,
  maxAge: number,
): CookieSpec[] {
  const count = Math.max(1, Math.ceil(sealed.length / CHUNK_SIZE));
  if (count > MAX_CHUNKS)
    throw new Error(`session cookie ${name} needs ${count} chunks`);
  const specs: CookieSpec[] = [];
  for (let i = 0; i < MAX_CHUNKS; i += 1) {
    specs.push(
      i < count
        ? {
            name: chunkName(name, i),
            value: sealed.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE),
            options: options("/", maxAge),
          }
        : { name: chunkName(name, i), value: "", options: options("/", 0) },
    );
  }
  return specs;
}

function joinChunks(
  name: string,
  get: (name: string) => string | undefined,
): string | undefined {
  let joined = get(name);
  if (!joined) return undefined;
  for (let i = 1; i < MAX_CHUNKS; i += 1) {
    const part = get(chunkName(name, i));
    if (!part) break;
    joined += part;
  }
  return joined;
}

export async function sealSession(
  tokens: SessionTokens,
): Promise<readonly CookieSpec[]> {
  const session: SessionPayload = {
    subject: tokens.subject,
    displayName: tokens.displayName,
    accessToken: tokens.accessToken,
    expiresAt: tokens.expiresAt,
  };
  const refresh: RefreshPayload = {
    refreshToken: tokens.refreshToken,
    idToken: tokens.idToken,
  };
  return [
    ...chunkSpecs(
      SESSION_COOKIE,
      await seal(session, SESSION_TTL_SECONDS),
      SESSION_TTL_SECONDS,
    ),
    ...chunkSpecs(
      REFRESH_COOKIE,
      await seal(refresh, SESSION_TTL_SECONDS),
      SESSION_TTL_SECONDS,
    ),
  ];
}

/** Reads both session cookies through any cookie getter (next/headers or a NextRequest). */
export async function unsealSession(
  get: (name: string) => string | undefined,
): Promise<StoredSession | null> {
  const session = await unseal(
    joinChunks(SESSION_COOKIE, get),
    sessionPayloadSchema,
    SESSION_TTL_SECONDS,
  );
  if (!session) return null;
  const refresh = await unseal(
    joinChunks(REFRESH_COOKIE, get),
    refreshPayloadSchema,
    SESSION_TTL_SECONDS,
  );
  return { session, refresh };
}

export async function sealOidcTransaction(
  payload: OidcPayload,
): Promise<CookieSpec> {
  return {
    name: OIDC_COOKIE,
    value: await seal(payload, OIDC_TTL_SECONDS),
    options: options("/auth", OIDC_TTL_SECONDS),
  };
}

export function unsealOidcTransaction(
  value: string | undefined,
): Promise<OidcPayload | null> {
  return unseal(value, oidcPayloadSchema, OIDC_TTL_SECONDS);
}

/** Specs that expire the session cookies (and the oidc one) in the browser. */
export function expiredCookieSpecs(): readonly CookieSpec[] {
  const chunks = [SESSION_COOKIE, REFRESH_COOKIE].flatMap((name) =>
    Array.from({ length: MAX_CHUNKS }, (_, i) => ({
      name: chunkName(name, i),
      value: "",
      options: options("/", 0),
    })),
  );
  return [
    ...chunks,
    { name: OIDC_COOKIE, value: "", options: options("/auth", 0) },
  ];
}
