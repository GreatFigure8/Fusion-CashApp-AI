import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { unsealSession } from "@/lib/auth/cookies";
import { endSessionUrl, SIGNED_OUT_PATH } from "@/lib/auth/oidc";
import { destroySession } from "@/lib/auth/session";
import { serverEnv } from "@/lib/env";

function isForeignOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (origin !== null) return origin !== new URL(serverEnv.APP_BASE_URL).origin;
  return request.headers.get("sec-fetch-site") === "cross-site";
}

// POST only: a GET export would make sign-out a CSRF-able link.
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (isForeignOrigin(request)) {
    return NextResponse.json(
      { error: { code: "forbidden", message: "Cross-origin sign-out refused" } },
      { status: 403 },
    );
  }

  const store = await cookies();
  const stored = await unsealSession((name) => store.get(name)?.value);
  const idToken = stored?.refresh?.idToken ?? null;
  await destroySession();

  let target: URL | null = null;
  try {
    target = await endSessionUrl(idToken);
  } catch {
    target = null;
  }
  return NextResponse.redirect(target ?? new URL(SIGNED_OUT_PATH, serverEnv.APP_BASE_URL), 303);
}
