import "server-only";

import { err, type Result } from "@/lib/result";

import { buildApiRequest, errorFromResponse, send } from "./client";
import type { ApiError } from "./errors";
import type { ApiPath } from "./types";

/**
 * POST a raw body stream (a multipart upload) to the Python API and return the upstream response.
 * The raw-body twin of `apiFile`: same base URL, token and request id. The body is streamed, never
 * buffered, so `duplex: "half"` is required and the caller passes the original `Content-Length`.
 */
export async function apiUpload(
  path: ApiPath,
  body: ReadableStream<Uint8Array>,
  headers: Readonly<{ contentType: string; contentLength: string }>,
  query?: Readonly<Record<string, string>>,
  init?: { signal?: AbortSignal; requestId?: string },
): Promise<Result<Response, ApiError>> {
  const prepared = await buildApiRequest("post", path, "application/json", {
    query,
    signal: init?.signal,
    requestId: init?.requestId,
    headers: { "Content-Type": headers.contentType, "Content-Length": headers.contentLength },
  });
  if (!prepared.ok) return prepared;
  const request = new Request(prepared.value.request, {
    method: "POST",
    body,
    duplex: "half",
  } as RequestInit & { duplex: "half" });
  const sent = await send({ request, requestId: prepared.value.requestId });
  if (!sent.ok) return sent;
  if (!sent.value.ok) return err(await errorFromResponse(sent.value, prepared.value.requestId));
  return sent;
}

/**
 * GET a file (CSV, XLSX) from the Python API and return the raw upstream response, so the caller
 * can pass the body through. The raw-body twin of `api()`: same base URL, token and request id.
 */
export async function apiFile(
  path: ApiPath,
  query?: Readonly<Record<string, string>> | URLSearchParams,
  init?: {
    signal?: AbortSignal;
    requestId?: string;
    method?: "get" | "post";
    body?: unknown;
    params?: Readonly<Record<string, string | number>>;
  },
): Promise<Result<Response, ApiError>> {
  const prepared = await buildApiRequest(init?.method ?? "get", path, "*/*", {
    params: init?.params,
    query,
    body: init?.body,
    signal: init?.signal,
    requestId: init?.requestId,
  });
  if (!prepared.ok) return prepared;
  const sent = await send(prepared.value);
  if (!sent.ok) return sent;
  if (!sent.value.ok) return err(await errorFromResponse(sent.value, prepared.value.requestId));
  return sent;
}
