import { z } from "zod";

/** Client-safe: no server-only import, so client components can render these. */
export type ApiError = Readonly<{
  /** HTTP status; 0 means the API could not be reached. */
  status: number;
  /**
   * API code (lower snake) or a web code: network_error, session_expired, unexpected_response,
   * invalid_response, validation_error, internal_error.
   */
  code: string;
  message: string;
  requestId: string | null;
  details: ReadonlyArray<Readonly<Record<string, unknown>>>;
}>;

/** The API's single error shape. */
export const errorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: z.string(),
    details: z.array(z.record(z.string(), z.unknown())).default([]),
  }),
});

export function apiError(
  status: number,
  code: string,
  message: string,
  requestId: string | null,
  details: ApiError["details"] = [],
): ApiError {
  return { status, code, message, requestId, details };
}

export function networkError(requestId: string | null): ApiError {
  return apiError(0, "network_error", "The API could not be reached.", requestId);
}
