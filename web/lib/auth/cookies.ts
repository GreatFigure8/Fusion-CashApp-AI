import "server-only";

import { sealData, unsealData } from "iron-session";
import { z } from "zod";

import { serverEnv } from "@/lib/env";

export const SESSION_COOKIE = "cashapp_session";
export const REFRESH_COOKIE = "cashapp_refresh";
export const OIDC_COOKIE = "cashapp_oidc";

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
  secure: true;
  sameSite: "lax";
  path: string;
  maxAge: number;
}>;

export type CookieSpec = Readonly<{ name: string; value: string; options: CookieOptions }>;

export type SessionTokens = Readonly<{
  subject: string;
  displayName: string;
  accessToken: string;
  /** Epoch seconds. */
  expiresAt: number;
  refreshToken: string | null;
  idToken: string;
}>;

export type StoredSession = Readonly<{ session: SessionPayload; refresh: RefreshPayload | null }>;

function options(path: string, maxAge: number): CookieOptions {
  return { httpOnly: true, secure: true, sameSite: "lax", path, maxAge };
}

async function seal(payload: unknown, ttlSeconds: number): Promise<string> {
  return sealData(payload, { password: serverEnv.SESSION_SECRET, ttl: ttlSeconds });
}

async function unseal<T>(
  value: string | undefined,
  schema: z.ZodType<T>,
  ttlSeconds: number,
): Promise<T | null> {
  if (!value) return null;
  try {
    const data = await unsealData(value, { password: serverEnv.SESSION_SECRET, ttl: ttlSeconds });
    const parsed = schema.safeParse(data);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export async function sealSession(tokens: SessionTokens): Promise<readonly CookieSpec[]> {
  const session: SessionPayload = {
    subject: tokens.subject,
    displayName: tokens.displayName,
    accessToken: tokens.accessToken,
    expiresAt: tokens.expiresAt,
  };
  const refresh: RefreshPayload = { refreshToken: tokens.refreshToken, idToken: tokens.idToken };
  return [
    {
      name: SESSION_COOKIE,
      value: await seal(session, SESSION_TTL_SECONDS),
      options: options("/", SESSION_TTL_SECONDS),
    },
    {
      name: REFRESH_COOKIE,
      value: await seal(refresh, SESSION_TTL_SECONDS),
      options: options("/", SESSION_TTL_SECONDS),
    },
  ];
}

/** Reads both session cookies through any cookie getter (next/headers or a NextRequest). */
export async function unsealSession(
  get: (name: string) => string | undefined,
): Promise<StoredSession | null> {
  const session = await unseal(get(SESSION_COOKIE), sessionPayloadSchema, SESSION_TTL_SECONDS);
  if (!session) return null;
  const refresh = await unseal(get(REFRESH_COOKIE), refreshPayloadSchema, SESSION_TTL_SECONDS);
  return { session, refresh };
}

export async function sealOidcTransaction(payload: OidcPayload): Promise<CookieSpec> {
  return {
    name: OIDC_COOKIE,
    value: await seal(payload, OIDC_TTL_SECONDS),
    options: options("/auth", OIDC_TTL_SECONDS),
  };
}

export function unsealOidcTransaction(value: string | undefined): Promise<OidcPayload | null> {
  return unseal(value, oidcPayloadSchema, OIDC_TTL_SECONDS);
}

/** Specs that expire the session cookies (and the oidc one) in the browser. */
export function expiredCookieSpecs(): readonly CookieSpec[] {
  return [
    { name: SESSION_COOKIE, value: "", options: options("/", 0) },
    { name: REFRESH_COOKIE, value: "", options: options("/", 0) },
    { name: OIDC_COOKIE, value: "", options: options("/auth", 0) },
  ];
}
