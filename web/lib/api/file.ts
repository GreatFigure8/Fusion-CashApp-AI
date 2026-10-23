import "server-only";

import { err, type Result } from "@/lib/result";

import { buildApiRequest, errorFromResponse, send } from "./client";
import type { ApiError } from "./errors";
import type { ApiPath } from "./types";

/**
 * GET a file (CSV, XLSX) from the Python API and return the raw upstream response, so the caller
 * can pass the body through. The raw-body twin of `api()`: same base URL, token and request id.
 */
export async function apiFile(
  path: ApiPath,
  query?: Readonly<Record<string, string>>,
  init?: { signal?: AbortSignal; requestId?: string },
): Promise<Result<Response, ApiError>> {
  const prepared = await buildApiRequest("get", path, "*/*", {
    query,
    signal: init?.signal,
    requestId: init?.requestId,
  });
  if (!prepared.ok) return prepared;
  const sent = await send(prepared.value);
  if (!sent.ok) return sent;
  if (!sent.value.ok) return err(await errorFromResponse(sent.value, prepared.value.requestId));
  return sent;
}
