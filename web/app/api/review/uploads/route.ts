import { apiUpload } from "@/lib/api/file";

// Request-time only: an upload is private and never cached or prerendered.
export const dynamic = "force-dynamic";

// The largest request the API could ever accept (20 files x 10 MiB, its configuration maxima plus
// framing). The API applies the configured, smaller limit; this only stops an absurd body early.
const ABSOLUTE_MAX_BYTES = 20 * 10 * 1024 * 1024 + 1024 * 1024;

function problem(status: number, code: string, message: string, requestId: string | null) {
  return Response.json({ error: { code, message, request_id: requestId ?? "", details: [] } }, { status });
}

/** Streams a multipart upload to the API with the session's bearer token. Holds no rules. */
export async function POST(request: Request) {
  const contentType = request.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
    return problem(415, "unsupported_media_type", "Send the files as multipart/form-data.", null);
  }
  const contentLength = request.headers.get("Content-Length");
  if (contentLength === null) {
    return problem(411, "length_required", "A Content-Length header is required.", null);
  }
  const declared = Number(contentLength);
  if (!Number.isFinite(declared) || declared < 0) {
    return problem(400, "bad_request", "Invalid Content-Length.", null);
  }
  if (declared > ABSOLUTE_MAX_BYTES) {
    return problem(413, "payload_too_large", "The upload is too large.", null);
  }
  if (request.body === null) {
    return problem(400, "bad_request", "The upload has no body.", null);
  }

  const stageOnly = new URL(request.url).searchParams.get("stage_only") === "true";
  const result = await apiUpload(
    "/review/uploads",
    request.body,
    { contentType, contentLength },
    stageOnly ? { stage_only: "true" } : undefined,
    { signal: request.signal },
  );
  if (!result.ok) {
    const e = result.error;
    return problem(e.status || 502, e.code, e.message, e.requestId);
  }

  const upstream = result.value;
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" },
  });
}
