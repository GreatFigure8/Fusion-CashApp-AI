import "server-only";

import * as oauth from "oauth4webapi";
import { z } from "zod";

import type { OidcPayload, SessionTokens } from "@/lib/auth/cookies";
import { serverEnv } from "@/lib/env";

const DISCOVERY_TTL_MS = 60 * 60 * 1000;
const HTTP_TIMEOUT_MS = 5000;
const DEFAULT_SCOPES = "openid profile email offline_access groups";

// Read here until s27's env schema carries OIDC_SCOPES. The API audience scope of the
// identity-domain resource app goes in this value at deploy time.
const scopesSchema = z.string().min(1).default(DEFAULT_SCOPES);

export const AUTH_CALLBACK_PATH = "/auth/callback";
export const SIGNED_OUT_PATH = "/signed-out";

let discovery: { at: number; as: Promise<oauth.AuthorizationServer> } | null = null;

function client(): oauth.Client {
  return { client_id: serverEnv.OIDC_CLIENT_ID };
}

function clientAuth(): oauth.ClientAuth {
  return oauth.ClientSecretBasic(serverEnv.OIDC_CLIENT_SECRET);
}

function requestOptions() {
  const insecure = new URL(serverEnv.OIDC_ISSUER).protocol === "http:";
  return {
    signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
    ...(insecure ? { [oauth.allowInsecureRequests]: true } : {}),
  };
}

export function redirectUri(): string {
  return new URL(AUTH_CALLBACK_PATH, serverEnv.APP_BASE_URL).toString();
}

async function authorizationServer(): Promise<oauth.AuthorizationServer> {
  const now = Date.now();
  if (discovery && now - discovery.at < DISCOVERY_TTL_MS) return discovery.as;
  const issuer = new URL(serverEnv.OIDC_ISSUER);
  const expectedIssuer = new URL(serverEnv.OIDC_EXPECTED_ISSUER ?? serverEnv.OIDC_ISSUER);
  const as = oauth
    .discoveryRequest(issuer, { algorithm: "oidc", ...requestOptions() })
    .then((response) => oauth.processDiscoveryResponse(expectedIssuer, response));
  discovery = { at: now, as };
  try {
    return await as;
  } catch (error) {
    discovery = null;
    throw error;
  }
}

export async function buildAuthorizationRequest(
  returnTo: string,
): Promise<{ url: URL; transaction: OidcPayload }> {
  const as = await authorizationServer();
  if (!as.authorization_endpoint) throw new Error("authorization_endpoint missing");
  const state = oauth.generateRandomState();
  const nonce = oauth.generateRandomNonce();
  const codeVerifier = oauth.generateRandomCodeVerifier();
  const challenge = await oauth.calculatePKCECodeChallenge(codeVerifier);

  const url = new URL(as.authorization_endpoint);
  url.searchParams.set("client_id", serverEnv.OIDC_CLIENT_ID);
  url.searchParams.set("redirect_uri", redirectUri());
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", scopesSchema.parse(process.env.OIDC_SCOPES || undefined));
  url.searchParams.set("state", state);
  url.searchParams.set("nonce", nonce);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  return { url, transaction: { state, nonce, codeVerifier, returnTo } };
}

function expiresAtFrom(expiresIn: number | undefined): number {
  return Math.floor(Date.now() / 1000) + (expiresIn ?? 300);
}

function nameFrom(claims: oauth.IDToken): string {
  for (const key of ["name", "preferred_username", "email"] as const) {
    const value = claims[key];
    if (typeof value === "string" && value) return value;
  }
  return claims.sub;
}

/** Validates the callback (state, nonce, PKCE, ID token) and exchanges the code. */
export async function exchangeCode(
  callbackParams: URLSearchParams,
  transaction: OidcPayload,
): Promise<SessionTokens> {
  const as = await authorizationServer();
  const callbackUrl = new URL(AUTH_CALLBACK_PATH, serverEnv.APP_BASE_URL);
  callbackUrl.search = callbackParams.toString();
  const params = oauth.validateAuthResponse(as, client(), callbackUrl, transaction.state);
  const response = await oauth.authorizationCodeGrantRequest(
    as,
    client(),
    clientAuth(),
    params,
    redirectUri(),
    transaction.codeVerifier,
    requestOptions(),
  );
  const result = await oauth.processAuthorizationCodeResponse(as, client(), response, {
    expectedNonce: transaction.nonce,
    requireIdToken: true,
  });
  const claims = oauth.getValidatedIdTokenClaims(result);
  if (!claims || !result.id_token) throw new Error("id_token missing");
  return {
    subject: claims.sub,
    displayName: nameFrom(claims),
    accessToken: result.access_token,
    expiresAt: expiresAtFrom(result.expires_in),
    refreshToken: result.refresh_token ?? null,
    idToken: result.id_token,
  };
}

/** Refresh-token grant. Keeps the old refresh and ID tokens when the IdP does not rotate them. */
export async function refreshTokens(previous: {
  subject: string;
  displayName: string;
  refreshToken: string;
  idToken: string;
}): Promise<SessionTokens> {
  const as = await authorizationServer();
  const response = await oauth.refreshTokenGrantRequest(
    as,
    client(),
    clientAuth(),
    previous.refreshToken,
    requestOptions(),
  );
  const result = await oauth.processRefreshTokenResponse(as, client(), response);
  return {
    subject: previous.subject,
    displayName: previous.displayName,
    accessToken: result.access_token,
    expiresAt: expiresAtFrom(result.expires_in),
    refreshToken: result.refresh_token ?? previous.refreshToken,
    idToken: result.id_token ?? previous.idToken,
  };
}

/** RP-initiated logout URL, or null when the IdP publishes no end_session_endpoint. */
export async function endSessionUrl(idToken: string | null): Promise<URL | null> {
  const as = await authorizationServer();
  if (!as.end_session_endpoint) return null;
  const url = new URL(as.end_session_endpoint);
  if (idToken) url.searchParams.set("id_token_hint", idToken);
  url.searchParams.set("client_id", serverEnv.OIDC_CLIENT_ID);
  url.searchParams.set(
    "post_logout_redirect_uri",
    new URL(SIGNED_OUT_PATH, serverEnv.APP_BASE_URL).toString(),
  );
  return url;
}
