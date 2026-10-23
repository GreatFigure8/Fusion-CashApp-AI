import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { sealOidcTransaction } from "@/lib/auth/cookies";
import { buildAuthorizationRequest, SIGNED_OUT_PATH } from "@/lib/auth/oidc";
import { parseReturnTo } from "@/lib/auth/return-to";
import { serverEnv } from "@/lib/env";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const returnTo = parseReturnTo(request.nextUrl.searchParams.get("returnTo"));
  try {
    const { url, transaction } = await buildAuthorizationRequest(returnTo);
    const spec = await sealOidcTransaction(transaction);
    (await cookies()).set(spec.name, spec.value, spec.options);
    return NextResponse.redirect(url, 302);
  } catch (error) {
    console.error(
      JSON.stringify({
        level: "error",
        event: "auth.sign_in_failed",
        reason: error instanceof Error ? error.name : "unknown",
      }),
    );
    return NextResponse.redirect(
      new URL(`${SIGNED_OUT_PATH}?reason=error`, serverEnv.APP_BASE_URL),
      302,
    );
  }
}
