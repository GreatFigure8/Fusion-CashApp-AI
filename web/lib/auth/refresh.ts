import "server-only";

import { createHash } from "node:crypto";

import type { SessionTokens, StoredSession } from "@/lib/auth/cookies";
import { refreshTokens } from "@/lib/auth/oidc";

export const REFRESH_SKEW_SECONDS = 120;

export function needsRefresh(expiresAt: number, now: number): boolean {
  return expiresAt - now <= REFRESH_SKEW_SECONDS;
}

const inFlight = new Map<string, Promise<SessionTokens | null>>();

/**
 * Runs a refresh-token grant, one at a time per refresh token (single-flight within this
 * process). Resolves null when the session cannot be refreshed.
 */
export function refreshSession(stored: StoredSession): Promise<SessionTokens | null> {
  const refreshToken = stored.refresh?.refreshToken;
  const idToken = stored.refresh?.idToken;
  if (!refreshToken || !idToken) return Promise.resolve(null);

  const key = createHash("sha256").update(refreshToken).digest("hex");
  const existing = inFlight.get(key);
  if (existing) return existing;

  const run = refreshTokens({
    subject: stored.session.subject,
    displayName: stored.session.displayName,
    refreshToken,
    idToken,
  })
    .catch((error: unknown) => {
      console.error(
        JSON.stringify({
          level: "error",
          event: "auth.refresh_failed",
          reason: error instanceof Error ? error.name : "unknown",
        }),
      );
      return null;
    })
    .finally(() => {
      inFlight.delete(key);
    });
  inFlight.set(key, run);
  return run;
}
