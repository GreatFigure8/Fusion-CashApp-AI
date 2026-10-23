# s04-sign-in-authorization: Sign-in and authorization (OCI Identity Domains, token validation, group-to-role mapping)

- Issue: #4
- Wave: 1 (serialized spine, step 4 of 6; moved ahead of s28 because the config API needs `require_permission`)
- breaking: false

## Story

As a person using the app, I want to sign in with OCI Identity Domains and have the API decide what I may do from my OCI groups, so that access is controlled in one place and the UI only hides what I can't do.

## Context

CLAUDE.md *Authentication and authorization*. research.md: PyJWT `PyJWKClient`. The identity-domain groups claim name is unverified: it is the setting `identity.groups_claim` (s27), default `groups`, recorded "unverified against live" until probed. Built against a fake JWKS; no live identity domain is needed to merge.

## Acceptance criteria

1. [unit] `cashapp/domain/principal.py`: `Role` StrEnum (ADMIN, OPERATOR, REVERSER, VIEWER), `Permission` StrEnum (`items:read`, `items:work`, `apply:reverse`, `classification:override`, `config:read`, `config:write`, `reports:read`, `backlog:run`, `chat:use`), `ROLE_PERMISSIONS` (ADMIN all; OPERATOR items:read, items:work, classification:override, reports:read, chat:use, config:read; REVERSER apply:reverse; VIEWER items:read, reports:read, config:read), frozen `Principal{subject, display_name, email|None, groups: frozenset[str], roles: frozenset[Role], permissions: frozenset[Permission], is_system: bool}` with `can(p)`, and `SYSTEM_PRINCIPAL` (subject `system:pipeline`, all permissions except `apply:reverse` and `config:write`).
2. [unit] `cashapp/auth/tokens.py`: `TokenValidator.validate(token) -> Claims` checks signature against the identity domain JWKS (cached `PyJWKClient`), `iss`, `aud`, `exp`, `nbf` with 60 s leeway; failures raise `ApiError(401, "invalid_token")`. Tests cover wrong issuer, wrong audience, expired, bad signature, unknown kid.
3. [integration] One Alembic revision creates `GROUP_ROLE_MAPPING` (ID, GROUP_NAME, ROLE, CREATED_BY, CREATED_AT; unique GROUP_NAME+ROLE) and seeds one bootstrap row mapping the group named by setting `identity.bootstrap_admin_group` (default `CashApp-Admins`) to ADMIN.
4. [unit] `cashapp/auth/deps.py`: `current_principal` FastAPI dependency (Bearer token → validated claims → groups from `identity.groups_claim` → roles via `GroupRoleRepository` → `Principal`) and `require_permission(p: Permission) -> Callable[..., Awaitable[Principal]]` returning 403 in the single error shape when missing. Services receive `Principal` as a plain argument; a static test asserts no module under `cashapp/services/` imports `fastapi`.
5. [api] `GET /me` → `{subject, display_name, email, groups, roles, permissions}`. `cashapp/data/repositories/group_roles.py`: `GroupRoleRepository` with `roles_for_groups(groups) -> frozenset[Role]`, `all() -> list[GroupRoleMapping]`, `replace_all(mappings) -> None` (the admin endpoints over it are s28's).
6. [unit] Pipeline workers use `SYSTEM_PRINCIPAL`; no worker code path reads a user token (asserted by a test that `cashapp/workers` and `cashapp/stations` never import `cashapp.auth.tokens`).
7. [integration] Web (`web/lib/auth/`, `web/app/auth/`): Next.js is the confidential client using `oauth4webapi` authorization code + PKCE: `GET /auth/sign-in` (state, nonce, PKCE verifier in a short-lived sealed cookie), `GET /auth/callback` (code exchange server-side with the client secret from `serverEnv`), `POST /auth/sign-out` (clears session, RP-initiated logout, redirects to `/signed-out`). Session is an `iron-session` encrypted httpOnly, Secure, SameSite=Lax cookie holding access/refresh tokens; refresh happens server-side before expiry.
8. [unit] `web/lib/auth/session.ts` (server-only) exports `getSession(): Promise<Session | null>`, `requireSession(): Promise<Session>` (redirects to `/auth/sign-in`), `getAccessToken(): Promise<string>`; `web/middleware.ts` redirects unauthenticated requests (except `/auth/*`, `/signed-out`, static) to sign-in. A test asserts no token value is serialised into any client component props (no `accessToken` reachable from a `"use client"` module).

## Out of scope

The `/signed-out` page and unauthorized empty state (s19 owns all shell screens); admin UI for the mapping (s21).

## Deps

- s01-scaffold-monorepo — `ApiError`, router auto-discovery, oauth4webapi and iron-session pinned. plannable.
- s27-settings-secrets-wiring — `Settings.identity{issuer, jwks_url, audience, groups_claim, bootstrap_admin_group}` (add `bootstrap_admin_group` to that group), `serverEnv`. plannable.
- s02-data-layer-foundation — `BaseRepository`, `UnitOfWork.repo`. plannable.

## Test-support files owned

`api/tests/support/auth.py`: test RSA key + JWKS served via respx, `mint_token(groups=[...], **claims)`, `make_principal(roles=...)`, `override_principal(app, principal)`. `web/tests/support/session.ts`: Playwright fixture that seals a session cookie for a given role set with the test `SESSION_SECRET`.

## Assumptions

- Groups arrive in the access token under a configurable claim; verify against the real domain before release.
- Role set (ADMIN, OPERATOR, REVERSER, VIEWER) and their permissions are a starting point an admin can't change in the UI; only group→role is admin-editable.
