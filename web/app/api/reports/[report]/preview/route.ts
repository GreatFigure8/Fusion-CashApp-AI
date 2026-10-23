import type { NextRequest } from "next/server";

import { apiFile } from "@/lib/api/file";
import { getSession } from "@/lib/auth/session";
import { errorResponse, REPORT_CSP } from "@/lib/reports/http";
import { htmlReportParams } from "@/lib/reports/schemas";

// Request-time only: a preview is never cached or prerendered.
export const dynamic = "force-dynamic";

/** The HTML progress report preview. Only the document and its has-data flag are passed through. */
export async function GET(
  request: NextRequest,
  ctx: RouteContext<"/api/reports/[report]/preview">,
): Promise<Response> {
  const session = await getSession();
  if (!session) return errorResponse(401, "unauthenticated", "Sign-in required", null);

  const { report } = await ctx.params;
  if (report !== "html") return errorResponse(404, "not_found", "No such report.", null);

  const sp = request.nextUrl.searchParams;
  const parsed = htmlReportParams.safeParse({
    kind: sp.get("kind") ?? undefined,
    window: sp.get("window") ?? undefined,
    sections: sp.getAll("sections"),
  });
  if (!parsed.success) {
    return errorResponse(
      422,
      "validation_error",
      "Request validation failed.",
      null,
      parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
    );
  }

  const query = new URLSearchParams({ kind: parsed.data.kind, window: parsed.data.window });
  for (const section of parsed.data.sections) query.append("sections", section);
  const result = await apiFile("/reports/html/preview", query);
  if (!result.ok) {
    const e = result.error;
    return errorResponse(e.status || 502, e.code, e.message, e.requestId, e.details);
  }

  // Only the document and its has-data flag come through; the CSP is ours, not upstream's.
  const upstream = result.value;
  const headers = new Headers({
    "Cache-Control": "private, no-store",
    "Content-Security-Policy": REPORT_CSP,
    "X-Content-Type-Options": "nosniff",
    "Content-Type": upstream.headers.get("Content-Type") ?? "text/html; charset=utf-8",
  });
  const hasData = upstream.headers.get("X-Report-Has-Data");
  if (hasData) headers.set("X-Report-Has-Data", hasData);
  return new Response(upstream.body, { status: 200, headers });
}
