import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import {
  expiredCookieSpecs,
  sealSession,
  unsealSession,
  type SessionTokens,
  type StoredSession,
} from "@/lib/auth/cookies";

/** What server components may see. Deliberately has no token field. */
export type Session = Readonly<{ subject: string; displayName: string; expiresAt: number }>;

export class SessionExpiredError extends Error {
  constructor() {
    super("Session is missing or expired");
    this.name = "SessionExpiredError";
  }
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

async function readStored(): Promise<StoredSession | null> {
  const store = await cookies();
  return unsealSession((name) => store.get(name)?.value);
}

/** Never redirects: route handlers answer 401 themselves. Never refreshes: proxy.ts does. */
export async function getSession(): Promise<Session | null> {
  const stored = await readStored();
  if (!stored || stored.session.expiresAt <= nowSeconds()) return null;
  const { subject, displayName, expiresAt } = stored.session;
  return { subject, displayName, expiresAt };
}

export async function requireSession(returnTo: string = "/"): Promise<Session> {
  const session = await getSession();
  if (!session) redirect(`/auth/sign-in?returnTo=${encodeURIComponent(returnTo)}`);
  return session;
}

/** For server-side calls to the Python API. Never pass the result to a client component. */
export async function getAccessToken(): Promise<string> {
  const stored = await readStored();
  if (!stored || stored.session.expiresAt <= nowSeconds()) throw new SessionExpiredError();
  return stored.session.accessToken;
}

/** Route handlers and server actions only. */
export async function saveTokens(tokens: SessionTokens): Promise<void> {
  const store = await cookies();
  for (const spec of await sealSession(tokens)) store.set(spec.name, spec.value, spec.options);
}

export async function destroySession(): Promise<void> {
  const store = await cookies();
  for (const spec of expiredCookieSpecs()) store.set(spec.name, spec.value, spec.options);
}
