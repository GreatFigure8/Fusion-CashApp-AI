import { z } from "zod";

import { apiRaw } from "@/lib/api/client";

// Request-time only: an artifact is private and never cached or prerendered.
export const dynamic = "force-dynamic";

const paramsSchema = z.object({
  id: z.coerce.number().int().positive(),
  n: z.coerce.number().int().positive(),
});
const querySchema = z.object({ variant: z.enum(["original", "text"]).default("original") });

function problem(status: number, code: string, message: string, requestId: string | null) {
  return Response.json({ error: { code, message, request_id: requestId ?? "", details: [] } }, { status });
}

/** Streams a stored artifact part to the browser with the session's bearer token attached. */
export async function GET(request: Request, ctx: RouteContext<"/api/items/[id]/parts/[n]">) {
  const params = paramsSchema.safeParse(await ctx.params);
  const query = querySchema.safeParse(
    Object.fromEntries(new URL(request.url).searchParams.entries()),
  );
  if (!params.success || !query.success) {
    return problem(422, "validation_error", "Invalid item or part number.", null);
  }

  const result = await apiRaw("/items/{item_id}/parts/{part_no}", {
    params: { item_id: params.data.id, part_no: params.data.n },
    query: { variant: query.data.variant },
    signal: request.signal,
  });
  if (!result.ok) {
    const e = result.error;
    return problem(e.status || 502, e.code, e.message, e.requestId);
  }

  const upstream = result.value;
  const headers = new Headers({
    "Content-Type": upstream.headers.get("Content-Type") ?? "application/octet-stream",
    "Content-Disposition": upstream.headers.get("Content-Disposition") ?? "inline",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store",
  });
  // The upstream body is passed through untouched, so nothing is buffered here.
  return new Response(upstream.body, { status: 200, headers });
}
