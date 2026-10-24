import type { NextRequest } from "next/server";
import { z } from "zod";

import { apiFile } from "@/lib/api/file";
import { getSession } from "@/lib/auth/session";
import { errorResponse, REPORT_CSP } from "@/lib/reports/http";

export const dynamic = "force-dynamic";

const exportId = z.coerce.number().int().positive();

/** Re-download a logged HTML export (the chat card's Download link). */
export async function GET(
  _request: NextRequest,
  ctx: RouteContext<"/api/reports/[report]/exports/[id]">,
): Promise<Response> {
  const session = await getSession();
  if (!session) return errorResponse(401, "unauthenticated", "Sign-in required", null);

  const { report, id } = await ctx.params;
  if (report !== "html") return errorResponse(404, "not_found", "No such report.", null);
  const parsed = exportId.safeParse(id);
  if (!parsed.success) {
    return errorResponse(422, "validation_error", "Request validation failed.", null, [
      { path: "id", message: "Must be a positive whole number." },
    ]);
  }

  const result = await apiFile("/reports/html/exports/{export_id}/file", undefined, {
    params: { export_id: parsed.data },
  });
  if (!result.ok) {
    const e = result.error;
    return errorResponse(e.status || 502, e.code, e.message, e.requestId, e.details);
  }
  const upstream = result.value;
  const headers = new Headers({
    "Cache-Control": "private, no-store",
    "Content-Security-Policy": REPORT_CSP,
    "X-Content-Type-Options": "nosniff",
  });
  const type = upstream.headers.get("Content-Type");
  const disposition = upstream.headers.get("Content-Disposition");
  if (type) headers.set("Content-Type", type);
  if (disposition) headers.set("Content-Disposition", disposition);
  return new Response(upstream.body, { status: 200, headers });
}
