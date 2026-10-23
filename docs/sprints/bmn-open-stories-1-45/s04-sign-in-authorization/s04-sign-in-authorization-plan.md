# s04-sign-in-authorization — plan

Issue #4. Wave 1 spine, step 4 (after s01, s27, s02; before s28). Built against a fake JWKS and a fake IdP; nothing needs a live identity domain to merge.

## Standards followed

- **CLAUDE.md** *Authentication and authorization*: Next.js is the confidential client, the API validates every token itself (JWKS, `iss`, `aud`, `exp`), group→role mapping lives in the database, one shared dependency builds the `Principal`, services take `Principal` as a plain argument, workers use a system principal.
- **python-web-app:building-python-web-apps**: routes → services → repositories; shared dependencies as `Annotated` aliases; external I/O (JWKS fetch) isolated in one module; no logic in routers.
- **python-web-app:wiring-application-config**: identity settings read only through s27's `get_settings().identity`; no new deploy-time key on the API side.
- **CLAUDE.md data layer**: `GroupRoleRepository` subclasses `BaseRepository`, flushes and never commits; upper snake case DB objects; identity PK.
- **nextjs.md** (16.3.8): non-negotiables 1, 2, 3, 8, 14. Rule ids applied: SEC-1, SEC-2, SEC-3, SEC-4 (with the logged deviation below), SEC-6, SEC-7, SEC-8, SEC-10, SEC-11, SEC-15, SEC-16, SEC-18, SEC-37; TS-1, TS-10, TS-15, TS-19, TS-20, TS-24, TS-27, TS-28, TS-32, TS-34; API-2, API-3, API-8, API-12, API-17, API-18, API-28, API-30; TEST-1, TEST-2, TEST-6, TEST-9, TEST-11, TEST-14, TEST-15, TEST-23, TEST-35.
- **nextjs-fullstack-standards**: `server-only` on every secret/session module, Zod at every boundary (query params, IdP responses through oauth4webapi, sealed cookie payloads), named exports, kebab-case files.

## Files to touch

### API (`api/`), all new unless noted

| Path | Content |
|---|---|
| `api/src/cashapp/domain/principal.py` | `Role`, `Permission`, `ROLE_PERMISSIONS`, `Principal`, `GroupRoleAssignment`, `SYSTEM_PRINCIPAL`, `permissions_for(roles)`. Pure, no I/O, no framework imports. |
| `api/src/cashapp/auth/__init__.py` | empty |
| `api/src/cashapp/auth/tokens.py` | `Claims`, `TokenValidator`, `HttpxJWKClient(PyJWKClient)`, `extract_groups()`, `TokenError`. |
| `api/src/cashapp/auth/deps.py` | `get_token_validator`, `current_principal`, `require_permission`, `PrincipalDep`. |
| `api/src/cashapp/services/identity.py` | `async def resolve_principal(uow, claims, *, groups_claim) -> Principal`: claims → groups → roles → `Principal`. No fastapi import. |
| `api/src/cashapp/data/models/group_role.py` | ORM `GroupRoleMapping` → table `GROUP_ROLE_MAPPING`. |
| `api/src/cashapp/data/models/__init__.py` | **append-only (s02 owns)**: one import line for `group_role`, only if s02 aggregates models there for Alembic metadata. |
| `api/src/cashapp/data/repositories/group_roles.py` | `GroupRoleRepository(BaseRepository[GroupRoleMapping])`. |
| `api/src/cashapp/api/deps.py` | **new shared module, s04 creates it** if s01/s02 did not: `get_uow_factory() -> UowFactory` (cached, built from `get_settings().atp` through s01's `create_engine` and s02's `make_uow_factory`) and `UowFactoryDep`. If s02 already ships an equivalent dependency, use that one and don't create this file (non-negotiable 7). |
| `api/src/cashapp/api/schemas/me.py` | `MeResponse` Pydantic v2 model. (Location assumed; if s01 put schemas beside routers, follow s01.) |
| `api/src/cashapp/api/routers/me.py` | `router = APIRouter()`, `GET /me`. Picked up by s01's auto-discovery; `main.py` untouched. |
| `api/alembic/versions/<rev>_group_role_mapping.py` | One revision on the current head (see Migrations). |
| `api/tests/support/auth.py` | Test-support (owned): RSA key, JWKS, respx route, `mint_token`, `make_principal`, `override_principal`. |
| `api/tests/unit/domain/test_principal.py`, `api/tests/unit/auth/test_tokens.py`, `api/tests/unit/auth/test_deps.py`, `api/tests/unit/auth/test_layering_auth.py`, `api/tests/unit/data/test_group_roles_repository.py`, `api/tests/api/test_me.py`, `api/tests/integration/test_migration_group_role_mapping.py` | Test files the tester writes in step 5 (named below). |

### Web (`web/`), all new unless noted

| Path | Content |
|---|---|
| `web/lib/auth/oidc.ts` | `import "server-only"`. oauth4webapi wrapper: cached discovery, `buildAuthorizationRequest`, `exchangeCode`, `refreshTokens`, `endSessionUrl`. Client auth `ClientSecretBasic(serverEnv.OIDC_CLIENT_SECRET)`. |
| `web/lib/auth/cookies.ts` | `import "server-only"`. Cookie names, iron-session options, Zod schemas for every sealed payload, `sealSession`/`unsealSession` helpers that both `proxy.ts` and `session.ts` use (one copy). |
| `web/lib/auth/session.ts` | `import "server-only"`. `Session`, `getSession`, `requireSession`, `getAccessToken`, `saveTokens`, `destroySession`. |
| `web/lib/auth/refresh.ts` | `import "server-only"`. `needsRefresh(expiresAt, now)`, `refreshSession(...)` with single-flight per refresh-token hash. |
| `web/lib/auth/return-to.ts` | `parseReturnTo(value: unknown): string` (Zod; relative paths only, rejects `//`, `\`, schemes; default `/`). Pure. |
| `web/app/auth/sign-in/route.ts` | `GET` |
| `web/app/auth/callback/route.ts` | `GET` |
| `web/app/auth/sign-out/route.ts` | `POST` only |
| `web/proxy.ts` | Optimistic session gate and pre-expiry refresh. **Not `middleware.ts`** (deviation, see Assumptions). |
| `web/lib/env.ts` | **append-only (s27 owns)**: `OIDC_SCOPES: z.string().default("openid profile email offline_access")`. |
| `web/.env.example` | **append-only (s27 owns)**: `OIDC_SCOPES=`. |
| `web/tests/support/session.ts` | Owned Playwright fixture. |
| `web/tests/unit/auth/*.test.ts`, `web/tests/e2e/auth.spec.ts` | Test files the tester writes in step 5. |

No file outside these. `main.py`, `settings.py`, lockfiles and `components/ui` are untouched (all deps are pinned by s01: `pyjwt[crypto]`, `httpx`, `respx`, `oauth4webapi`, `iron-session`, `zod`, `msw`).

## Design

### API

- **Token validation** (`tokens.py`):
  - `HttpxJWKClient` subclasses PyJWT's `PyJWKClient` and overrides `fetch_data()` to use a sync `httpx.Client` (timeout 5 s). This keeps PyJWKClient's cache (JWK set lifespan 300 s, refetch once on an unknown `kid`), and respx can intercept it in tests (respx doesn't see urllib).
  - `validate()` runs `get_signing_key_from_jwt` in `asyncio.to_thread`, then calls `jwt.decode(token, key, algorithms=["RS256"], audience=..., issuer=..., leeway=60, options={"require": ["exp", "iss", "aud", "sub"]})`. The algorithm list is pinned, so `none` and HS256 tokens are rejected.
  - Every `jwt.PyJWTError` and `PyJWKClientError` caused by a bad token raises `ApiError(401, "invalid_token", "Invalid or expired access token")`.
  - A JWKS fetch that fails on transport (connection or 5xx) raises `ApiError(503, "identity_unavailable", ...)`. An IdP outage is not the caller's fault.
  - Neither the token nor the claims are logged. Only a reason code is logged, at WARNING.
- **Groups** (`extract_groups(raw, claim)`): accepts a list of strings or a list of objects with `name`/`display` (OCI identity domains have used both). A missing claim gives an empty set. This is **unverified against live**: the claim name is `identity.groups_claim` (default `groups`).
- **Display name and email**: display name is the first of `user_displayname`, `name`, `sub`; email is the first of `email`, `user_email`, else `None`. Both are unverified against live.
- **`current_principal`** checks `HTTPBearer(auto_error=False)`:
  - No credentials, or a scheme other than Bearer: `ApiError(401, "unauthenticated", "Sign-in required")`.
  - Otherwise: `validator.validate`, then `resolve_principal` (service) inside one read-only UoW, which is rolled back.
  - It sets `request.state.principal_subject` for logging (s29).
- **`require_permission(p)`** returns a dependency that depends on `current_principal` and raises `ApiError(403, "forbidden", "Missing permission <p>", details=[{"permission": p}])`.
- **`/me`** depends on `current_principal` only, with no permission check. An authenticated user with no mapped role gets 200 with empty roles, so s19 can render the "ask an administrator" state.
- **Group matching** is an exact string match on `GROUP_NAME`. Role values are checked by a DB constraint and by `Role(...)` on read; an unknown stored value is skipped and logged.

### Web

- **Cookies** (iron-session `sealData`/`unsealData`, password `serverEnv.SESSION_SECRET`): every cookie is `httpOnly`, `secure: true` and `sameSite: "lax"`.

  | Cookie | Path | Max age | Sealed payload |
  |---|---|---|---|
  | `cashapp_session` | `/` | 8 h | `{subject, displayName, accessToken, expiresAt}` |
  | `cashapp_refresh` | `/` | 8 h | `{refreshToken, idToken}` |
  | `cashapp_oidc` | `/auth` | 600 s | `{state, nonce, codeVerifier, returnTo}` |

  The session is split across two cookies so neither exceeds the 4 KB cookie limit; OCI access tokens carrying groups are large.
- **`GET /auth/sign-in?returnTo=`**:
  - generate state, nonce and a PKCE verifier (S256);
  - seal them into `cashapp_oidc`;
  - 302 to the authorization endpoint with `redirect_uri = APP_BASE_URL + "/auth/callback"` and `scope = OIDC_SCOPES`.
- **`GET /auth/callback`**:
  1. Unseal `cashapp_oidc`. If it is missing or invalid, redirect to `/signed-out?reason=error`.
  2. `validateAuthResponse` checks the state.
  3. `authorizationCodeGrantRequest` with `ClientSecretBasic` and the verifier.
  4. `processAuthorizationCodeResponse` with `expectedNonce` (oauth4webapi validates the ID token).
  5. Save both session cookies, delete `cashapp_oidc`, and 302 to `returnTo`.

  Any error goes to `/signed-out?reason=error`, the IdP error body is not echoed, and the error is logged as a JSON line (TEST-35).
- **`POST /auth/sign-out`**:
  - Reject a foreign `Origin` with 403 (API-17).
  - Read the `idToken`, delete both cookies, and 303 to `end_session_endpoint?id_token_hint=…&post_logout_redirect_uri=APP_BASE_URL/signed-out&client_id=…`.
  - Without an `end_session_endpoint`, 303 to `/signed-out`.
  - `GET` is not exported, so it returns 405.
- **`proxy.ts`**:
  - Matcher (literal, SEC-3) excludes `_next/static`, `_next/image`, `favicon.ico`, files with an extension, `/auth/` and `/signed-out`.
  - **No valid session cookie:** a path under `/api/` gets 401 `{error:{code:"unauthenticated",message}}`. Any other path gets a 307 to `/auth/sign-in?returnTo=<path+search>`.
  - **Session valid but `needsRefresh`** (expires within 120 s): `refreshSession` runs a refresh-token grant with a 5 s timeout.
    - On success, it reseals both cookies on the response, and on the forwarded request through `NextResponse.next({ request: { headers } })` (SEC-6), so the RSC render in the same request sees the fresh token.
    - On failure, it deletes the cookies, then 307s to sign-in (pages) or returns 401 (`/api`).
- **`session.ts`** only reads; it never refreshes, because cookies can't be set while an RSC renders. `getAccessToken()` returns the token, or throws `SessionExpiredError` if `expiresAt <= now`. Proxy guarantees freshness before that happens. `Session` deliberately has no token field.

## Interfaces provided (pinned)

```python
# cashapp/domain/principal.py
class Role(StrEnum): ADMIN="ADMIN"; OPERATOR="OPERATOR"; REVERSER="REVERSER"; VIEWER="VIEWER"
class Permission(StrEnum):
    ITEMS_READ="items:read"; ITEMS_WORK="items:work"; APPLY_REVERSE="apply:reverse"
    CLASSIFICATION_OVERRIDE="classification:override"; CONFIG_READ="config:read"
    CONFIG_WRITE="config:write"; REPORTS_READ="reports:read"; BACKLOG_RUN="backlog:run"; CHAT_USE="chat:use"
ROLE_PERMISSIONS: Final[Mapping[Role, frozenset[Permission]]]
def permissions_for(roles: Iterable[Role]) -> frozenset[Permission]
@dataclass(frozen=True, slots=True)
class Principal:
    subject: str; display_name: str; email: str | None
    groups: frozenset[str]; roles: frozenset[Role]; permissions: frozenset[Permission]
    is_system: bool = False
    def can(self, permission: Permission) -> bool
    @classmethod
    def from_roles(cls, *, subject: str, display_name: str, email: str | None,
                   groups: Iterable[str], roles: Iterable[Role]) -> "Principal"
@dataclass(frozen=True, slots=True)
class GroupRoleAssignment: group_name: str; role: Role
SYSTEM_PRINCIPAL: Final[Principal]  # subject "system:pipeline", display_name "Pipeline",
                                    # all permissions except APPLY_REVERSE, CONFIG_WRITE; is_system=True

# cashapp/auth/tokens.py
@dataclass(frozen=True, slots=True)
class Claims:
    subject: str; issuer: str; audience: tuple[str, ...]; expires_at: datetime
    display_name: str; email: str | None; raw: Mapping[str, Any]
    def groups(self, claim: str) -> frozenset[str]
def extract_groups(raw: Mapping[str, Any], claim: str) -> frozenset[str]
class TokenValidator:
    def __init__(self, *, issuer: str, audience: str | Sequence[str], jwks_url: str,
                 leeway_seconds: int = 60, jwks_cache_seconds: int = 300,
                 http_timeout_seconds: float = 5.0) -> None
    @classmethod
    def from_settings(cls, identity: IdentitySettings) -> "TokenValidator"
    async def validate(self, token: str) -> Claims   # ApiError 401 invalid_token | 503 identity_unavailable

# cashapp/services/identity.py
async def resolve_principal(uow: UnitOfWork, claims: Claims, *, groups_claim: str) -> Principal

# cashapp/auth/deps.py
def get_token_validator() -> TokenValidator                       # lru_cache; override in tests
async def current_principal(request: Request, credentials: HTTPAuthorizationCredentials | None = ...,
                            validator: TokenValidator = ..., uow_factory: UowFactory = ...) -> Principal
PrincipalDep = Annotated[Principal, Depends(current_principal)]
def require_permission(permission: Permission) -> Callable[..., Awaitable[Principal]]
# usage: principal: Annotated[Principal, Depends(require_permission(Permission.CONFIG_WRITE))]

# cashapp/data/repositories/group_roles.py
class GroupRoleRepository(BaseRepository[GroupRoleMapping]):
    async def roles_for_groups(self, groups: Iterable[str]) -> frozenset[Role]   # empty input → no query
    async def all(self) -> list[GroupRoleMapping]                                # ordered GROUP_NAME, ROLE
    async def replace_all(self, mappings: Sequence[GroupRoleAssignment], *, created_by: str) -> None
        # delete all + insert deduped; flush only. "last ADMIN" rule is s28's service check, not here.

# cashapp/data/models/group_role.py
class GroupRoleMapping(Base): id: int; group_name: str; role: str; created_by: str; created_at: datetime
```

`GET /me` (OpenAPI `MeResponse`):
```json
{"subject": "str", "display_name": "str", "email": "str|null",
 "groups": ["sorted str"], "roles": ["sorted Role"], "permissions": ["sorted Permission"]}
```
Errors use s01's single shape: `401 unauthenticated`, `401 invalid_token`, `403 forbidden` (details `[{"permission": "<p>"}]`), `503 identity_unavailable`.

```ts
// web/lib/auth/session.ts  (server-only)
export type Session = Readonly<{ subject: string; displayName: string; expiresAt: number /* epoch s */ }>;
export class SessionExpiredError extends Error {}
export function getSession(): Promise<Session | null>;          // never redirects (route handlers answer 401)
export function requireSession(): Promise<Session>;             // redirect("/auth/sign-in?returnTo=…") when absent
export function getAccessToken(): Promise<string>;              // throws SessionExpiredError when absent/expired
// web/lib/auth/return-to.ts
export function parseReturnTo(value: unknown): string;
// web/tests/support/session.ts  (Playwright)
export async function withSession(context: BrowserContext, opts: {
  roles: readonly ("ADMIN"|"OPERATOR"|"REVERSER"|"VIEWER")[]; subject?: string;
  accessToken?: string; expiresInSeconds?: number }): Promise<void>;  // seals both cookies with test SESSION_SECRET
```

```python
# api/tests/support/auth.py
TEST_ISSUER: str; TEST_AUDIENCE: str; TEST_JWKS_URL: str; TEST_KID: str
def jwks() -> dict[str, Any]
def mock_jwks(respx_mock: respx.MockRouter, *, url: str = TEST_JWKS_URL) -> respx.Route
def mint_token(groups: Sequence[str] = (), *, kid: str = TEST_KID, key: RSAPrivateKey | None = None,
               expires_in: int = 300, **claims: Any) -> str
def make_principal(roles: Iterable[Role] = (Role.VIEWER,), *, subject: str = "user@test",
                   groups: Iterable[str] = ()) -> Principal
@contextmanager
def override_principal(app: FastAPI, principal: Principal) -> Iterator[None]
```

## Migrations

One revision, `api/alembic/versions/<rev>_group_role_mapping.py`. `down_revision` is the head when it merges (s02's base; s27 has no revision). The merger re-points it and checks that `alembic heads` returns exactly one head.

- **Upgrade:** creates `GROUP_ROLE_MAPPING`:

  | Column | Type |
  |---|---|
  | `ID` | `NUMBER` identity PK |
  | `GROUP_NAME` | `VARCHAR2(256)` not null |
  | `ROLE` | `VARCHAR2(16)` not null, with `CK_GROUP_ROLE_MAPPING_ROLE` `IN ('ADMIN','OPERATOR','REVERSER','VIEWER')` |
  | `CREATED_BY` | `VARCHAR2(256)` not null |
  | `CREATED_AT` | `TIMESTAMP WITH TIME ZONE` not null, default `SYSTIMESTAMP` |

  It adds `UQ_GROUP_ROLE_MAPPING_GROUP_ROLE (GROUP_NAME, ROLE)`. It then inserts the bootstrap row `(get_settings().identity.bootstrap_admin_group, 'ADMIN', 'system:bootstrap')`.
- **Downgrade:** drops the table.
- **Scope:** DEV ATP only, through db-sync. No ad-hoc DDL.

## Test plan (written and run only in step 5)

Each test maps to one acceptance criterion. Unit tests run on aiosqlite (s02 `tests/support/db.py`); tests marked `atp` run against DEV ATP.

**AC1 [unit]** `api/tests/unit/domain/test_principal.py`
- `test_role_permissions_matrix_exact` (parametrized over the 4 roles, exact sets)
- `test_admin_has_every_permission`
- `test_principal_is_frozen`
- `test_principal_can_true_and_false`
- `test_from_roles_unions_permissions`
- `test_system_principal_excludes_reverse_and_config_write`
- `test_system_principal_subject_and_flag`

**AC2 [unit]** `api/tests/unit/auth/test_tokens.py` (respx JWKS)
- `test_valid_token_returns_claims`
- `test_wrong_issuer_401_invalid_token`
- `test_wrong_audience_401_invalid_token`
- `test_expired_401_invalid_token`
- `test_expired_within_60s_leeway_accepted`
- `test_nbf_in_future_beyond_leeway_rejected`
- `test_bad_signature_401_invalid_token`
- `test_unknown_kid_refetches_once_then_401`
- `test_alg_none_and_hs256_rejected`
- `test_jwks_cached_between_validations`
- `test_jwks_unreachable_503_identity_unavailable`
- `test_extract_groups_strings_objects_and_missing`

**AC3 [integration]** `api/tests/integration/test_migration_group_role_mapping.py` (`-m atp`)
- `test_upgrade_creates_group_role_mapping_columns`
- `test_bootstrap_admin_row_seeded_from_setting`
- `test_unique_group_name_role_enforced`
- `test_role_check_constraint_rejects_unknown`
- `test_downgrade_drops_table`
- `test_single_alembic_head`

**AC4 [unit]** `api/tests/unit/auth/test_deps.py`
- `test_missing_bearer_401_single_error_shape`
- `test_non_bearer_scheme_401`
- `test_current_principal_maps_groups_to_roles`
- `test_groups_claim_name_read_from_settings`
- `test_unmapped_groups_give_principal_without_roles`
- `test_require_permission_allows_holder`
- `test_require_permission_denies_403_single_error_shape`

`api/tests/unit/auth/test_layering_auth.py`
- `test_no_service_module_imports_fastapi` (AST scan of `cashapp/services/`)

**AC5 [api]** `api/tests/api/test_me.py`
- `test_get_me_returns_principal_fields_sorted`
- `test_get_me_without_token_401`
- `test_get_me_invalid_token_401`
- `test_get_me_user_without_roles_200_empty`

`api/tests/unit/data/test_group_roles_repository.py`
- `test_roles_for_groups_union`
- `test_roles_for_groups_empty_input_returns_empty`
- `test_all_ordered`
- `test_replace_all_replaces_dedupes_and_does_not_commit`

**AC6 [unit]** `api/tests/unit/auth/test_layering_auth.py`
- `test_workers_stations_pipeline_pollers_never_import_auth_tokens` (AST scan of `cashapp/workers`, `cashapp/stations`, `cashapp/pipeline`, `cashapp/pollers`; directories that don't exist yet pass vacuously)
- `test_system_principal_is_system`

**AC7 [integration]** `web/tests/unit/auth/` (Vitest, `// @vitest-environment node`, msw fake IdP, handlers called as plain functions per TEST-9)
- `sign-in.test.ts`:
  - "redirects to authorize with S256 PKCE, state, nonce and the configured scopes"
  - "sets the sealed oidc cookie httpOnly, Secure, SameSite=Lax, path /auth, 600 s"
  - "drops an absolute or protocol-relative returnTo"
- `callback.test.ts`:
  - "exchanges the code with client_secret_basic and saves both session cookies"
  - "state mismatch redirects to /signed-out?reason=error and saves nothing"
  - "missing oidc cookie redirects to error"
  - "nonce mismatch rejected"
  - "IdP error body is never echoed"
- `sign-out.test.ts`:
  - "clears both cookies and 303s to end_session with id_token_hint and post_logout_redirect_uri"
  - "foreign Origin gets 403"
  - "falls back to /signed-out without an end_session_endpoint"
- `refresh.test.ts`:
  - "needsRefresh true within 120 s skew"
  - "proxy refreshes before expiry and forwards resealed cookies on request and response"
  - "refresh failure clears session and redirects"
  - "concurrent refreshes share one grant"

`web/tests/e2e/auth.spec.ts` (Playwright with a stub IdP route, TEST-14 and TEST-15)
- "unauthenticated page visit lands on IdP authorize with returnTo preserved"
- "POST /auth/sign-out without session lands on /signed-out"

**AC8 [unit]** `web/tests/unit/auth/`
- `session.test.ts`:
  - "getSession returns null without cookie"
  - "getSession returns subject, displayName, expiresAt and no token field"
  - "requireSession redirects to /auth/sign-in"
  - "getAccessToken returns token"
  - "getAccessToken throws SessionExpiredError when expired"
- `proxy.test.ts`:
  - "matcher excludes /auth/*, /signed-out, _next/static, _next/image and files" (`unstable_doesProxyMatch`, TEST-11)
  - "unauthenticated page 307 to sign-in"
  - "unauthenticated /api 401 envelope"
- `no-token-in-client.test.ts`:
  - "no 'use client' module imports @/lib/auth/* or names accessToken/refreshToken/idToken" (static scan of `web/app`, `web/components` and `web/lib`)
  - "every lib/auth module except return-to starts with import 'server-only'"

`web/tests/e2e/auth.spec.ts`
- "withSession fixture reaches a protected page and the HTML contains no token" (TEST-2)

## Assumptions and deviations

1. **`web/proxy.ts` replaces the story's `web/middleware.ts`.** nextjs.md non-negotiable 2 and SEC-1 forbid adding `middleware.ts` on Next 16; the behaviour is the same.
2. **Token refresh runs in `proxy.ts`, a narrow deviation from SEC-4** ("no slow fetches in Proxy"). Proxy is the only place that can set cookies for RSC renders, Server Actions and route handlers alike. The refresh happens once per token lifetime, has a 5 s timeout and is single-flighted. `session.ts` stays read-only.
3. **PyJWKClient** fetches through httpx, by overriding `fetch_data`, so respx can mock it and the timeout is bounded. It is still "the cached PyJWKClient".
4. **A JWKS outage is a 503 `identity_unavailable`**, not a 401.
5. **The session is split across two sealed cookies**, to stay under the 4 KB cookie limit. The session cookie lifetime is a fixed 8 h, not configurable.
6. **`OIDC_SCOPES` is appended to s27's `web/lib/env.ts`.** The API audience scope of the identity domain resource app goes in this value at deploy time.
7. **`replace_all` takes a required keyword `created_by`.** s28 passes `principal.subject`.
8. **Claim names for groups, display name and email are unverified against live.** The fakes say so in comments; a primary-docs probe confirms them before release.
9. **Group names match exactly (case-sensitive).**
10. **`cashapp/api/deps.py` (`get_uow_factory`) is created here** only if s01 and s02 did not already provide a UoW dependency.

## Risks

- **The identity domain may not put groups in the access token at all.** They might be only in the ID token, or need a "include groups" setting or a custom claim. If so, every user resolves with no roles. Mitigations: `/me` makes this visible, and a pre-release live probe is required. No fallback to the SCIM `/Me` lookup in this story.
- **Refresh-token rotation and races.** Parallel prefetches near expiry could both refresh. Single-flight works within one Node process only; with several web replicas, a rotated refresh token can log a user out. Accepted for now; recorded for s25/s44 sizing (sticky sessions or one replica).
- **Cookie size.** If an access token alone exceeds about 3.8 KB sealed, saving the session fails. The callback test should assert a realistic 3 KB token fits.
- **The migration reads settings at upgrade time.** `bootstrap_admin_group` must be set in the migration environment, or its default `CashApp-Admins` is seeded.
- **Shared-file edits.** These are `web/lib/env.ts`, `web/.env.example`, `cashapp/data/models/__init__.py` and possibly `cashapp/api/deps.py`, all append-only. The merger should check for overlap with s27, s02 and s28.
