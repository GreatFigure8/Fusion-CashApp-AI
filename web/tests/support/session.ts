import type { BrowserContext } from "@playwright/test";
import { sealData } from "iron-session";

// Must equal the SESSION_SECRET the app under test runs with (see .env.test).
const TEST_SESSION_SECRET =
  process.env.SESSION_SECRET ?? "test-session-secret-at-least-32-characters-long";
const TTL = 8 * 60 * 60;

type TestRole = "ADMIN" | "OPERATOR" | "REVERSER" | "VIEWER";

export async function withSession(
  context: BrowserContext,
  opts: {
    roles: readonly TestRole[];
    subject?: string;
    accessToken?: string;
    expiresInSeconds?: number;
  },
): Promise<void> {
  const subject = opts.subject ?? `e2e-${opts.roles.join("-").toLowerCase()}@test`;
  const expiresAt = Math.floor(Date.now() / 1000) + (opts.expiresInSeconds ?? 3600);
  const session = {
    subject,
    displayName: `E2E ${opts.roles.join(", ")}`,
    accessToken: opts.accessToken ?? `test-access-token.${opts.roles.join(".")}`,
    expiresAt,
  };
  const refresh = { refreshToken: "test-refresh-token", idToken: "test-id-token" };
  const baseURL = process.env.APP_BASE_URL ?? "http://localhost:3000";
  const url = new URL(baseURL);
  await context.addCookies([
    {
      name: "cashapp_session",
      value: await sealData(session, { password: TEST_SESSION_SECRET, ttl: TTL }),
      domain: url.hostname,
      path: "/",
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
    {
      name: "cashapp_refresh",
      value: await sealData(refresh, { password: TEST_SESSION_SECRET, ttl: TTL }),
      domain: url.hostname,
      path: "/",
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
}
