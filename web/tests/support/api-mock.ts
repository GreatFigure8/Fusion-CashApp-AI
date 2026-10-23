import { http, HttpResponse } from "msw";
import { setupServer, type SetupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import type { ApiPath, HttpMethod, Method, ResponseOf } from "@/lib/api/types";

export const TEST_API_BASE_URL = "http://api.test";
export const TEST_ACCESS_TOKEN = "test-access-token";

export type ErrorEnvelope = {
  error: { code: string; message: string; request_id: string; details: Record<string, unknown>[] };
};

type MockResponse<P extends ApiPath, M extends Method<P>> =
  | { status?: number; body?: ResponseOf<P, M> | ErrorEnvelope; headers?: Record<string, string> }
  | ((req: { request: Request; params: Record<string, string> }) => Response | Promise<Response>);

export const apiServer: SetupServer = setupServer();

const recorded: Request[] = [];

/** Every serverEnv key, with test values. serverEnv is memoized, so all tests share these. */
const TEST_ENV: Record<string, string> = {
  OIDC_ISSUER: "https://idp.test",
  OIDC_CLIENT_ID: "test-client",
  OIDC_CLIENT_SECRET: "test-client-secret",
  SESSION_SECRET: "test-session-secret-at-least-32-characters-long",
  API_BASE_URL: TEST_API_BASE_URL,
  APP_BASE_URL: "http://localhost:3000",
};

/** Call once at the top of a test file: starts msw, resets handlers per test, stubs the env. */
export function useApiMockServer(): void {
  beforeAll(() => {
    for (const [name, value] of Object.entries(TEST_ENV)) vi.stubEnv(name, value);
    apiServer.listen({ onUnhandledFrame: "error" });
  });
  afterEach(() => {
    apiServer.resetHandlers();
    recorded.length = 0;
  });
  afterAll(() => {
    apiServer.close();
    vi.unstubAllEnvs();
  });
}

/** For `vi.mock("@/lib/auth/session", () => sessionModuleMock())`. A null token means expired. */
export function sessionModuleMock(token: string | null = TEST_ACCESS_TOKEN): Record<string, unknown> {
  class SessionExpiredError extends Error {
    constructor() {
      super("Session is missing or expired");
      this.name = "SessionExpiredError";
    }
  }
  return {
    SessionExpiredError,
    getAccessToken: async () => {
      if (token === null) throw new SessionExpiredError();
      return token;
    },
    getSession: async () => null,
    requireSession: async () => ({ subject: "test", displayName: "Test", expiresAt: 0 }),
  };
}

function toMswPath(path: string): string {
  return `${TEST_API_BASE_URL}${path.replace(/\{([^}]+)\}/g, ":$1")}`;
}

/** Registers a handler for a path and method typed against the API contract. */
export function mockApi<P extends ApiPath, M extends Method<P>>(
  path: P,
  method: M,
  response: MockResponse<P, M>,
): void {
  const handler = http[method as "get"](toMswPath(path), async ({ request, params }) => {
    recorded.push(request.clone());
    if (typeof response === "function") {
      const flat: Record<string, string> = {};
      for (const [k, v] of Object.entries(params)) flat[k] = Array.isArray(v) ? v.join("/") : String(v);
      return response({ request, params: flat });
    }
    const status = response.status ?? 200;
    if (status === 204 || response.body === undefined) {
      return new HttpResponse(null, { status, headers: response.headers });
    }
    return HttpResponse.json(response.body, { status, headers: response.headers });
  });
  apiServer.use(handler);
}

export function mockApiError(
  path: ApiPath,
  method: HttpMethod,
  status: number,
  code: string,
  message: string = code,
  details: Record<string, unknown>[] = [],
): void {
  const body: ErrorEnvelope = { error: { code, message, request_id: "req-test", details } };
  apiServer.use(
    http[method](toMswPath(path), ({ request }) => {
      recorded.push(request.clone());
      return HttpResponse.json(body, { status, headers: { "X-Request-ID": "req-test" } });
    }),
  );
}

export function lastApiRequest(): Request | undefined {
  return recorded.at(-1);
}
