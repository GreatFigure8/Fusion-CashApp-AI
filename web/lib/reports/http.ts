import "server-only";

/** The one error envelope the report route handlers answer with. */
export function errorResponse(
  status: number,
  code: string,
  message: string,
  requestId: string | null,
  details: ReadonlyArray<Readonly<Record<string, unknown>>> = [],
): Response {
  return Response.json(
    { error: { code, message, request_id: requestId ?? "", details } },
    { status },
  );
}

/** The CSP an HTML report is served under: nothing but inline styles, and sandboxed. */
export const REPORT_CSP =
  "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox";
