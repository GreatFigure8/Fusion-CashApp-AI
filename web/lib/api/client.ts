import "server-only";

import { serverEnv } from "@/lib/env";
import { getAccessToken, SessionExpiredError } from "@/lib/auth/session";
import { err, ok, type Result } from "@/lib/result";

import { apiError, errorEnvelopeSchema, networkError, type ApiError } from "./errors";
import type { StreamPath } from "./stream-paths";
import type { ApiArgs, ApiPath, Method, ResponseOf } from "./types";

type RawOptions = {
  params?: Readonly<Record<string, unknown>>;
  query?: unknown;
  body?: unknown;
  rawBody?: string;
  headers?: Readonly<Record<string, string>>;
  signal?: AbortSignal;
  requestId?: string;
};

type Prepared = { request: Request; requestId: string };

function isAbort(e: unknown): boolean {
  return e instanceof Error && e.name === "AbortError";
}

function fillPath(path: string, params: RawOptions["params"]): string {
  return path.replace(/\{([^}]+)\}/g, (_m, name: string) =>
    encodeURIComponent(String(params?.[name] ?? "")),
  );
}

function applyQuery(url: URL, query: unknown): void {
  if (query instanceof URLSearchParams) {
    query.forEach((value, key) => url.searchParams.append(key, value));
    return;
  }
  if (typeof query !== "object" || query === null) return;
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    const values: unknown[] = Array.isArray(value) ? value : [value];
    for (const v of values) url.searchParams.append(key, String(v));
  }
}

/** The one place a request to the API is assembled. Shared by `api` and `apiStream`. */
export async function buildApiRequest(
  method: string,
  path: string,
  accept: string,
  options: RawOptions,
): Promise<Result<Prepared, ApiError>> {
  const requestId = options.requestId ?? crypto.randomUUID();
  let token: string;
  try {
    token = await getAccessToken();
  } catch (e) {
    if (e instanceof SessionExpiredError) {
      return err(
        apiError(401, "session_expired", "Your session has expired. Sign in again.", null),
      );
    }
    throw e;
  }

  const url = new URL(fillPath(path, options.params), serverEnv.API_BASE_URL);
  applyQuery(url, options.query);

  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("X-Request-ID", requestId);
  headers.set("Accept", accept);

  let body: string | undefined;
  if (options.rawBody !== undefined) body = options.rawBody;
  else if (options.body !== undefined) body = JSON.stringify(options.body);
  if (body !== undefined) headers.set("Content-Type", "application/json");

  return ok({
    request: new Request(url, {
      method: method.toUpperCase(),
      headers,
      body,
      cache: "no-store",
      signal: options.signal,
    }),
    requestId,
  });
}

export async function send(prepared: Prepared): Promise<Result<Response, ApiError>> {
  try {
    return ok(await fetch(prepared.request));
  } catch (e) {
    if (isAbort(e)) throw e;
    return err(networkError(prepared.requestId));
  }
}

export async function errorFromResponse(response: Response, sentId: string): Promise<ApiError> {
  const status = response.status;
  let json: unknown = null;
  try {
    json = await response.json();
  } catch {
    json = null;
  }
  const parsed = errorEnvelopeSchema.safeParse(json);
  if (parsed.success) {
    const { code, message, request_id, details } = parsed.data.error;
    return apiError(status, code, message, request_id, details);
  }
  return apiError(
    status,
    "unexpected_response",
    `The API returned an unexpected ${status} response.`,
    response.headers.get("X-Request-ID") ?? sentId,
  );
}

/** Typed call to the Python API. Returns a Result; only an abort is thrown. */
export async function api<P extends ApiPath, M extends Method<P>>(
  method: M,
  path: P,
  ...args: ApiArgs<P, M>
): Promise<Result<ResponseOf<P, M>, ApiError>> {
  const options = (args[0] ?? {}) as RawOptions;
  const prepared = await buildApiRequest(method, path, "application/json", options);
  if (!prepared.ok) return prepared;
  const sent = await send(prepared.value);
  if (!sent.ok) return sent;
  const response = sent.value;

  if (!response.ok) {
    return err(await errorFromResponse(response, prepared.value.requestId));
  }
  const text = response.status === 204 ? "" : await response.text();
  if (text === "") return ok(undefined as ResponseOf<P, M>);
  try {
    // The contract is checked at compile time against the OpenAPI schema (no per-endpoint schema).
    return ok(JSON.parse(text) as ResponseOf<P, M>);
  } catch {
    return err(
      apiError(
        response.status,
        "invalid_response",
        "The API returned a response that is not valid JSON.",
        response.headers.get("X-Request-ID") ?? prepared.value.requestId,
      ),
    );
  }
}

/** Opens an event stream to the API; returns the raw upstream response. Used by the SSE proxy. */
export async function apiStream(
  method: "get" | "post",
  path: StreamPath,
  options: {
    query?: URLSearchParams;
    body?: string;
    lastEventId?: string | null;
    signal?: AbortSignal;
    requestId?: string;
  },
): Promise<Result<Response, ApiError>> {
  const headers: Record<string, string> = {};
  if (options.lastEventId) headers["Last-Event-ID"] = options.lastEventId;
  const prepared = await buildApiRequest(method, path, "text/event-stream", {
    query: options.query,
    rawBody: options.body,
    headers,
    signal: options.signal,
    requestId: options.requestId,
  });
  if (!prepared.ok) return prepared;
  const sent = await send(prepared.value);
  if (!sent.ok) return sent;
  if (!sent.value.ok) return err(await errorFromResponse(sent.value, prepared.value.requestId));
  return sent;
}
