import type { NextRequest } from "next/server";

import { apiFile } from "@/lib/api/file";
import { getSession } from "@/lib/auth/session";
import { exportParams } from "@/lib/reports/schemas";

// Request-time only: an export is never cached or prerendered.
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

export async function GET(
  request: NextRequest,
  ctx: RouteContext<"/api/reports/[report]/export">,
): Promise<Response> {
  const session = await getSession();
  if (!session) return errorResponse(401, "unauthenticated", "Sign-in required", null);

  const { report } = await ctx.params;
  const sp = request.nextUrl.searchParams;
  const parsed = exportParams.safeParse({
    report,
    format: sp.get("format") ?? undefined,
    date: sp.get("date") ?? undefined,
    from: sp.get("from") ?? undefined,
    to: sp.get("to") ?? undefined,
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
  const p = parsed.data;

  const result =
    p.report === "daily-summary"
      ? await apiFile("/reports/daily-summary", {
          format: p.format,
          ...(p.date ? { date: p.date } : {}),
        })
      : await apiFile("/reports/partially-paid", {
          format: p.format,
          ...(p.from ? { from: p.from } : {}),
          ...(p.to ? { to: p.to } : {}),
        });

  if (!result.ok) {
    const e = result.error;
    return errorResponse(e.status || 502, e.code, e.message, e.requestId, e.details);
  }

  // Pass through the body and its two file headers, nothing else from upstream.
  const upstream = result.value;
  const headers = new Headers({ "Cache-Control": "private, no-store" });
  const type = upstream.headers.get("Content-Type");
  const disposition = upstream.headers.get("Content-Disposition");
  if (type) headers.set("Content-Type", type);
  if (disposition) headers.set("Content-Disposition", disposition);
  return new Response(upstream.body, { status: 200, headers });
}
