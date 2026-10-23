import { NextResponse, type NextRequest } from "next/server";

import { expiredCookieSpecs, sealSession, unsealSession } from "@/lib/auth/cookies";
import { needsRefresh, refreshSession } from "@/lib/auth/refresh";
import { serverEnv } from "@/lib/env";

function reject(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  let response: NextResponse;
  if (pathname.startsWith("/api/")) {
    response = NextResponse.json(
      { error: { code: "unauthenticated", message: "Sign-in required" } },
      { status: 401 },
    );
  } else {
    const url = new URL("/auth/sign-in", serverEnv.APP_BASE_URL);
    url.searchParams.set("returnTo", `${pathname}${search}`);
    response = NextResponse.redirect(url, 307);
  }
  for (const spec of expiredCookieSpecs()) {
    response.cookies.set(spec.name, spec.value, spec.options);
  }
  return response;
}

/** Optimistic session gate. Also the one place the session is refreshed before it expires. */
export async function proxy(request: NextRequest): Promise<NextResponse> {
  const stored = await unsealSession((name) => request.cookies.get(name)?.value);
  if (!stored) return reject(request);

  const now = Math.floor(Date.now() / 1000);
  if (!needsRefresh(stored.session.expiresAt, now)) return NextResponse.next();

  const refreshed = await refreshSession(stored);
  if (!refreshed) {
    // Still-valid token but no way to refresh it: let the request through until it expires.
    if (stored.session.expiresAt > now) return NextResponse.next();
    return reject(request);
  }

  const specs = await sealSession(refreshed);
  const fresh = new Map(specs.map((spec) => [spec.name, spec.value]));

  // The RSC render in this same request must see the new token, so rewrite the forwarded
  // Cookie header as well as the response cookies.
  const merged = request.cookies
    .getAll()
    .filter((cookie) => !fresh.has(cookie.name))
    .map((cookie) => `${cookie.name}=${cookie.value}`);
  for (const [name, value] of fresh) merged.push(`${name}=${value}`);
  const headers = new Headers(request.headers);
  headers.set("cookie", merged.join("; "));

  const response = NextResponse.next({ request: { headers } });
  for (const spec of specs) response.cookies.set(spec.name, spec.value, spec.options);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico|auth/|signed-out|.*\\..*).*)"],
};
