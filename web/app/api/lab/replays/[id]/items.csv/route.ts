import type { NextRequest } from "next/server";

import { apiFile } from "@/lib/api/file";
import { getSession } from "@/lib/auth/session";
import { replayId } from "@/lib/lab/schemas";
import { errorResponse } from "@/lib/reports/http";

// Request-time only: an export is never cached or prerendered.
export const dynamic = "force-dynamic";

/** Thin proxy for the replay CSV: the file and its two headers are passed through. */
export async function GET(
  _request: NextRequest,
  ctx: RouteContext<"/api/lab/replays/[id]/items.csv">,
): Promise<Response> {
  const session = await getSession();
  if (!session) return errorResponse(401, "unauthenticated", "Sign-in required", null);

  const { id } = await ctx.params;
  const parsed = replayId.safeParse(id);
  if (!parsed.success) {
    return errorResponse(422, "validation_error", "Request validation failed.", null, [
      { path: "id", message: "Not a replay id." },
    ]);
  }

  const result = await apiFile("/lab/replays/{replay_id}/items.csv", undefined, {
    params: { replay_id: parsed.data },
  });
  if (!result.ok) {
    const e = result.error;
    return errorResponse(e.status || 502, e.code, e.message, e.requestId, e.details);
  }
  const upstream = result.value;
  const headers = new Headers({ "Cache-Control": "private, no-store" });
  const type = upstream.headers.get("Content-Type");
  const disposition = upstream.headers.get("Content-Disposition");
  if (type) headers.set("Content-Type", type);
  if (disposition) headers.set("Content-Disposition", disposition);
  return new Response(upstream.body, { status: 200, headers });
}
