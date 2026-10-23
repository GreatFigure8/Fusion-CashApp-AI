import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

import { expiredCookieSpecs, OIDC_COOKIE, unsealOidcTransaction } from "@/lib/auth/cookies";
import { exchangeCode, SIGNED_OUT_PATH } from "@/lib/auth/oidc";
import { parseReturnTo } from "@/lib/auth/return-to";
import { saveTokens } from "@/lib/auth/session";
import { serverEnv } from "@/lib/env";

function failure(reason: string): NextResponse {
  // Only a reason code is logged: never the IdP response body.
  console.error(JSON.stringify({ level: "error", event: "auth.callback_failed", reason }));
  return NextResponse.redirect(
    new URL(`${SIGNED_OUT_PATH}?reason=error`, serverEnv.APP_BASE_URL),
    302,
  );
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const store = await cookies();
  const transaction = await unsealOidcTransaction(store.get(OIDC_COOKIE)?.value);
  if (!transaction) return failure("missing_transaction");

  try {
    const tokens = await exchangeCode(request.nextUrl.searchParams, transaction);
    await saveTokens(tokens);
  } catch (error) {
    return failure(error instanceof Error ? error.name : "unknown");
  }

  const oidcExpiry = expiredCookieSpecs().find((spec) => spec.name === OIDC_COOKIE);
  if (oidcExpiry) store.set(oidcExpiry.name, oidcExpiry.value, oidcExpiry.options);
  return NextResponse.redirect(
    new URL(parseReturnTo(transaction.returnTo), serverEnv.APP_BASE_URL),
    302,
  );
}
