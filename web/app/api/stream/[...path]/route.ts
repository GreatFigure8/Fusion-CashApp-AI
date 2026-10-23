import type { NextRequest } from "next/server";

import { apiStream } from "@/lib/api/client";
import { isStreamPath } from "@/lib/api/stream-paths";

// Request-time only: a stream is never cached or prerendered.
export const dynamic = "force-dynamic";

function errorResponse(
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

async function proxy(
  request: NextRequest,
  ctx: RouteContext<"/api/stream/[...path]">,
  method: "get" | "post",
): Promise<Response> {
  const { path } = await ctx.params;
  const upstreamPath = `/${path.join("/")}`;
  if (!isStreamPath(upstreamPath)) {
    return errorResponse(404, "not_found", "Not found", null);
  }

  const result = await apiStream(method, upstreamPath, {
    query: request.nextUrl.searchParams,
    // Read as text: chat prompts are small, and the API validates the JSON.
    body: method === "post" ? await request.text() : undefined,
    lastEventId: request.headers.get("Last-Event-ID"),
    signal: request.signal,
  });

  if (!result.ok) {
    const e = result.error;
    return errorResponse(e.status || 502, e.code, e.message, e.requestId, e.details);
  }

  const upstream = result.value;
  const headers: Record<string, string> = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
  };
  const requestId = upstream.headers.get("X-Request-ID");
  if (requestId) headers["X-Request-ID"] = requestId;
  // The upstream body is passed through untouched, so nothing is buffered here.
  return new Response(upstream.body, { status: 200, headers });
}

export function GET(request: NextRequest, ctx: RouteContext<"/api/stream/[...path]">) {
  return proxy(request, ctx, "get");
}

export function POST(request: NextRequest, ctx: RouteContext<"/api/stream/[...path]">) {
  return proxy(request, ctx, "post");
}
