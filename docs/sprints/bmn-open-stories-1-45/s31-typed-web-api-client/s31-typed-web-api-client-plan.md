# s31-typed-web-api-client: plan

Issue #31, wave 1 in `waves.json` (the story header says wave 2). Owns `web/lib/api/`, `web/app/api/`,
`web/scripts/gen-api-types.mjs`, `web/eslint/`, `api/src/cashapp/openapi_dump.py` and the two web test-support files.
No page or component. No auth flow (s04).

## Standards followed

- **CLAUDE.md *Ownership*:** Next.js is a thin client. Route handlers and server actions are thin proxies with no business rules. The OpenAPI schema is the contract, and `web/` is typed from it.
- **nextjs-fullstack-standards:**
  - `Result` values across boundaries, never thrown.
  - Zod at every boundary: error envelopes, action input and SSE payloads.
  - `import "server-only"` on every module that touches the token or `API_BASE_URL`.
  - Named exports, kebab-case files, no `any`, strict plus `noUncheckedIndexedAccess`.
- **BMN `references/nextjs.md`:**
  - NN1: await `params`.
  - NN12 / SSE-2: pass the upstream `ReadableStream` to `new Response`.
  - SSE-3/4/5: headers.
  - SSE-6: authenticate before the stream and answer 401 as plain JSON.
  - SSE-8: request-time reads.
  - SSE-9: Node runtime only, no `runtime` export.
  - SSE-17: pass `request.signal` upstream.
  - SSE-23: the `fetch` reader reconnects with backoff, sends `Last-Event-ID` and stops on a 4xx (408 and 429 excepted).
  - SSE-24: `useEffect` with `useEffectEvent`.
  - SSE-25: validate each payload.
  - SSE-27: `fetch` with `getReader()` and `TextDecoder({stream:true})`.
  - Tests: TEST-9 (route handlers called as plain functions under `// @vitest-environment node`) and TEST-10 (action logic in plain functions).
  - Vercel-only rules (SSE-16, SSE-22 `maxDuration`) don't apply on OCI.
- **python-web-app:** `openapi_dump` is a pure module with a `main()`. It doesn't touch the DB (s01's lazy engine), Vault or the network.
- **research.md a3:** openapi-typescript is the web contract tool. It's already pinned by s01, so no lockfile edits.

## Files to touch

### API (Python)

| Path | Action |
|---|---|
| `api/src/cashapp/openapi_dump.py` | new: `openapi_document()`, `render_openapi()`, `main()` |
| `api/src/cashapp/settings_placeholders.py` | new: `placeholder_settings(**overrides) -> Settings` (env `local`, fake values for every required field, built with `Settings.model_validate`, so it reads no env, `.env` or Vault) |
| `api/src/cashapp/main.py` | **edit (one signature line, after s27):** `def create_app(*, settings: Settings \| None = None) -> FastAPI`, where the body uses `settings = settings if settings is not None else get_settings()`. `create_app()` with no argument behaves exactly as before. |
| `api/tests/support/settings.py` | **edit (s27 file):** `make_settings(**overrides)` delegates to `placeholder_settings(**overrides)`, so the placeholder values exist once (DRY) |
| `api/tests/unit/test_openapi_dump.py` | tests (step 5) |

### Web

| Path | Action |
|---|---|
| `web/lib/result.ts` | new: `Result`, `ok`, `err`, `isOk`, `isErr` (no `server-only`) |
| `web/lib/api/openapi.json` | generated, committed |
| `web/lib/api/schema.d.ts` | generated, committed |
| `web/lib/api/.gitattributes` | new: `openapi.json text eol=lf linguist-generated=true` and `schema.d.ts text eol=lf linguist-generated=true` |
| `web/lib/api/types.ts` | new: path, method, params, body and response type helpers (types only, no `server-only`) |
| `web/lib/api/errors.ts` | new: `ApiError` type, `errorEnvelopeSchema`, `apiError()`, `networkError()` (no `server-only`, so client components can render errors) |
| `web/lib/api/client.ts` | new, `import "server-only"`: `api()`, `apiStream()` |
| `web/lib/api/actions.ts` | new, `import "server-only"`: `apiAction()` |
| `web/lib/api/stream-paths.ts` | new: `STREAM_PATHS`, `StreamPath`, `isStreamPath()` (no `server-only`) |
| `web/lib/api/sse-parser.ts` | new: `createSseParser()` (pure, no `server-only`) |
| `web/lib/api/use-event-stream.ts` | new, `"use client"`: `useEventStream()` |
| `web/app/api/stream/[...path]/route.ts` | new: `GET`, `POST` |
| `web/scripts/gen-api-types.mjs` | new: `renderSchema(doc)` export plus CLI main |
| `web/eslint/api-boundary-plugin.mjs` | new: local ESLint plugin `api-boundary` with two rules |
| `web/eslint.config.mjs` | **append-only edit (s01 file):** import the plugin and add one config block (see AC5) |
| `web/package.json` | **scripts only (s01 file):** `api:openapi`, `api:types`, `api:sync` (see AC1). No dependency changes. |
| `web/tests/support/api-mock.ts` | new (owned test support) |
| `web/tests/support/sse-mock.ts` | new (owned test support) |
| `web/tests/unit/api/*.test.ts(x)`, `web/tests/unit/api/client.typecheck.ts` | tests (step 5) |

## Design

### AC1: generation

**`openapi_dump.py`**

- `openapi_document()` returns `create_app(settings=placeholder_settings()).openapi()`, plus a root extension `"x-generated": "cashapp.openapi_dump. GENERATED, do not edit. On merge conflict: regenerate (npm run api:sync), never hand-merge."`. Root `x-` keys are legal OpenAPI.
- `render_openapi(doc)` returns `json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"`.
- `main(argv)` takes an optional `--out PATH`. It writes UTF-8 bytes with LF only: to `sys.stdout.buffer` when there's no `--out`, otherwise to the file with `newline=""`.
  - Why: text-mode stdout on Windows writes CRLF, and PowerShell 5.1's `>` re-encodes to UTF-16. `--out` is the documented path. The AC's `> web/lib/api/openapi.json` form still works from bash.
- `if __name__ == "__main__": raise SystemExit(main())`.

**`web/scripts/gen-api-types.mjs`**

- `export async function renderSchema(doc)`:
  - calls `openapiTS(doc, { defaultNonNullable: false, alphabetize: true })` and `astToString` (openapi-typescript v7 Node API; the coder confirms the installed major);
  - prepends the header `/* GENERATED by web/scripts/gen-api-types.mjs from lib/api/openapi.json — do not edit. On merge conflict: regenerate with `npm run api:sync`, never hand-merge. */`;
  - normalises to LF.
- `defaultNonNullable: false` is right because FastAPI's output schemas already list defaulted fields as `required`, while input schemas leave them optional.
- Run directly (`import.meta.url` is the entry point), it reads `lib/api/openapi.json` and writes `lib/api/schema.d.ts`.

**`package.json` scripts**

- `"api:openapi": "uv run --project ../api python -m cashapp.openapi_dump --out lib/api/openapi.json"`
- `"api:types": "node scripts/gen-api-types.mjs"`
- `"api:sync": "npm run api:openapi && npm run api:types"`

Both generated files are committed. **The merger rule:** any story that changes an API route or schema runs `npm run api:sync` and commits both files. On conflict, regenerate; never hand-merge.

### AC2: client

**`types.ts`**

- `HttpMethod = "get"|"put"|"post"|"delete"|"patch"`.
- `ApiPath = keyof paths & string`.
- `Method<P>` is the methods whose `NonNullable<paths[P][M]>` is not `never`.
- `Operation<P,M>`, `PathParamsOf<P,M>` (`parameters.path`), `QueryOf<P,M>` (`parameters.query`), `BodyOf<P,M>` (`requestBody.content["application/json"]`).
- `ResponseOf<P,M>` is the union of `content["application/json"]` over the 200, 201 and 202 responses, plus `undefined` when 204 is declared.
- `Schemas = components["schemas"]`.

**`client.ts`**

- `buildApiRequest()` is internal and shared by `api` and `apiStream` (one copy):
  - `getAccessToken()`. A `SessionExpiredError` becomes `err(apiError(401,"session_expired","Your session has expired. Sign in again.",null))` and no fetch happens.
  - URL: `new URL(path with {name} replaced by encodeURIComponent(params[name]), serverEnv.API_BASE_URL)`. Query values are added with `URLSearchParams`; arrays repeat the key, and `undefined` is skipped.
  - Headers: `Authorization: Bearer <t>`, `X-Request-ID` (from the `requestId` option, or `crypto.randomUUID()`), `Accept`, and `Content-Type: application/json` when there's a body.
  - `cache: "no-store"`, and `signal` is passed through.
- `api()`:
  - A `fetch` rejection that isn't an abort gives `networkError(requestId)`. An abort is rethrown.
  - **2xx:** 204 or an empty body gives `ok(undefined)`. Otherwise JSON-parse; a failure gives `apiError(status,"invalid_response",…)`. The JSON is trusted as `ResponseOf` (the contract is compile-time; see Assumptions).
  - **non-2xx:** `errorEnvelopeSchema.safeParse(json)`. On success, `{status, code, message, requestId: body.request_id, details}`. Otherwise `{status, code:"unexpected_response", message:"The API returned an unexpected <status> response.", requestId: header X-Request-ID ?? sent id, details: []}`.
- `apiStream()` returns the raw upstream `Response` on 2xx, or the same `ApiError` mapping on non-2xx. Only the SSE proxy uses it.

### AC3: actions

**`actions.ts`**

- `apiAction(fn)` and `apiAction(schema, fn)` wrap a server-action body:
  - `schema.safeParse(input)` failure gives `err(apiError(422,"validation_error","Some fields are invalid.",null, issues.map(i => ({path: i.path.join("."), message: i.message}))))`.
  - A throw from `fn` runs `unstable_rethrow(e)` first (from `next/navigation`), so `redirect` and `notFound` pass through. Anything else is logged once with `console.error(JSON.stringify({level:"error", message:"apiAction failed", name: e.name}))`, never `e.message` (TEST-35), and gives `err(apiError(500,"internal_error","Something went wrong.",null))`.
- The result is always plain data, so it's serialisable.
- Concrete `"use server"` files belong to UI stories and call `apiAction`.

### AC4: SSE

**`stream-paths.ts`**

- `STREAM_PATHS = ["/flow/stream", "/chat/stream"] as const`.
- Adding a stream means editing this one constant. s19 and s22 own the API endpoints behind these paths.

**`app/api/stream/[...path]/route.ts`**, `GET` and `POST`:

1. `const { path } = await ctx.params`, typed with `RouteContext<"/api/stream/[...path]">`. Then `p = "/" + path.join("/")`. A path that isn't allow-listed gets 404 `{error:{code:"not_found",…}}` and no upstream call.
2. `apiStream(method, p, { query: request.nextUrl.searchParams, body: POST ? await request.text() : undefined, headers: {Accept:"text/event-stream", "Last-Event-ID"?: forwarded}, signal: request.signal })`.
   - The body is read as text because chat prompts are small and that avoids Node's `duplex:"half"`. It's forwarded raw with `Content-Type: application/json`, and the API validates it.
3. `err` gives `Response.json({error:{code,message,request_id,details}}, {status: e.status || 502})`. Same single shape; `network_error` maps to 502.
4. `ok(upstream)` gives `new Response(upstream.body, { status: 200, headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "X-Request-ID": … } })`. No buffering and no `Connection` header. Heartbeats come from the API (sse-starlette ping).

**`sse-parser.ts`**

- `createSseParser(onFrame: (f: SseFrame) => void): { push(chunk: string): void; flush(): void }`, with `SseFrame = { id: string | null; event: string; data: string; retry: number | null }`.
- WHATWG rules: CRLF, CR and LF; multiple `data:` lines joined with `\n`; comments ignored; event defaults to `"message"`; a block with only `retry` or `id` dispatches nothing but updates the last id and retry.

**`use-event-stream.ts`**, `"use client"`:

- Fetches `new URL("/api/stream" + path, location.origin)`, with GET when there's no body and POST with a JSON body otherwise.
- Each frame: `event === "stream-error"` goes to `onStreamError`. Otherwise `JSON.parse(data)` then `schema?.safeParse`. An invalid frame is dropped with `console.warn` (name only) and doesn't crash.
- `live` is set once the response is 2xx.
- Backoff: `delay(n) = min(30_000, 1_000 * 2 ** n)`. `n` resets after a frame is received. `Last-Event-ID` is sent on reconnect.
- A 4xx other than 408 or 429 goes straight to `disconnected`. So does reaching `maxRetries` (default 8).
- `reconnect` defaults to `body === undefined`: chat never re-posts a prompt. When the stream ends cleanly with `reconnect: false`, status becomes `disconnected` and `retries` stays 0.
- `retry()` resets `n` and the retry count and connects again.
- The connection key is `path + JSON.stringify(body) + enabled`. Unmounting aborts the `AbortController` and clears the timer.
- Callbacks are read through `useEffectEvent`.

### AC5: lint guard

**`web/eslint/api-boundary-plugin.mjs`** (`meta.name: "api-boundary"`)

- **`no-direct-api-base-url`** reports:
  - `MemberExpression` reading property `API_BASE_URL`, whether named or computed with a string literal, on any object (`serverEnv`, `process.env` or another);
  - `Property` key `API_BASE_URL` inside an `ObjectPattern` (destructuring);
  - `fetch(...)` whose argument subtree contains an identifier `API_BASE_URL`.
- **`no-client-server-api-import`** works in files whose `Program.body` begins with the directive `"use client"`. It reports any `ImportDeclaration` or `ExportNamedDeclaration`/`ExportAllDeclaration` re-export whose source matches `/(^|\/)lib\/api\/(client|actions)(\.ts)?$/` or `/^\.\/(client|actions)(\.ts)?$/`. Type-only imports are reported too, because the module has `server-only`. Use `@/lib/api/types` and `@/lib/api/errors` instead.
- `eslint.config.mjs` appends one block:
  - `{ files: ["**/*.{ts,tsx,mts,mjs,js}"], ignores: ["lib/api/**", "lib/env.ts", "tests/**", "eslint/**", "scripts/**"], plugins: { "api-boundary": apiBoundary }, rules: { "api-boundary/no-direct-api-base-url": "error" } }`
  - plus `{ files: ["**/*.{ts,tsx}"], plugins: …, rules: { "api-boundary/no-client-server-api-import": "error" } }`, which applies everywhere, including `lib/api/use-event-stream.ts`.
- A plugin rather than `no-restricted-syntax`: another story's `no-restricted-syntax` block would silently replace this one, because flat config doesn't merge rule options.

## Interfaces provided (pinned)

```ts
// web/lib/result.ts
export type Result<T, E> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly error: E };
export function ok<T>(value: T): { readonly ok: true; readonly value: T };
export function err<E>(error: E): { readonly ok: false; readonly error: E };
export function isOk<T, E>(r: Result<T, E>): r is { readonly ok: true; readonly value: T };
export function isErr<T, E>(r: Result<T, E>): r is { readonly ok: false; readonly error: E };

// web/lib/api/errors.ts   (client-safe)
export type ApiError = Readonly<{
  status: number;            // HTTP status; 0 = network failure
  code: string;              // API code (lower snake) or web codes: network_error | session_expired | unexpected_response | invalid_response | validation_error | internal_error
  message: string;
  requestId: string | null;
  details: ReadonlyArray<Readonly<Record<string, unknown>>>;
}>;
export const errorEnvelopeSchema: z.ZodType<{ error: { code: string; message: string; request_id: string; details: Record<string, unknown>[] } }>;
export function apiError(status: number, code: string, message: string, requestId: string | null, details?: ApiError["details"]): ApiError;
export function networkError(requestId: string | null): ApiError;   // {status:0, code:"network_error", message:"The API could not be reached."}

// web/lib/api/types.ts    (types only, client-safe)
export type { paths, components } from "./schema";
export type HttpMethod = "get" | "put" | "post" | "delete" | "patch";
export type ApiPath = keyof paths & string;
export type Method<P extends ApiPath>;
export type PathParamsOf<P extends ApiPath, M extends Method<P>>;
export type QueryOf<P extends ApiPath, M extends Method<P>>;
export type BodyOf<P extends ApiPath, M extends Method<P>>;
export type ResponseOf<P extends ApiPath, M extends Method<P>>;
export type Schemas = components["schemas"];
export type ApiRequestOptions<P extends ApiPath, M extends Method<P>> = {
  params?: PathParamsOf<P, M>;   // required (not optional) when the operation declares path params
  query?: QueryOf<P, M>;
  body?: BodyOf<P, M>;           // required when the operation declares a required JSON body
  signal?: AbortSignal;
  requestId?: string;
};

// web/lib/api/client.ts   (import "server-only")
export function api<P extends ApiPath, M extends Method<P>>(
  method: M, path: P, options?: ApiRequestOptions<P, M>,
): Promise<Result<ResponseOf<P, M>, ApiError>>;
export function apiStream(
  method: "get" | "post", path: StreamPath,
  options: { query?: URLSearchParams; body?: string; lastEventId?: string | null; signal?: AbortSignal; requestId?: string },
): Promise<Result<Response, ApiError>>;

// web/lib/api/actions.ts  (import "server-only")
export function apiAction<A extends unknown[], T>(
  fn: (...args: A) => Promise<Result<T, ApiError>>,
): (...args: A) => Promise<Result<T, ApiError>>;
export function apiAction<S extends z.ZodType, T>(
  schema: S, fn: (input: z.infer<S>) => Promise<Result<T, ApiError>>,
): (input: unknown) => Promise<Result<T, ApiError>>;

// web/lib/api/stream-paths.ts
export const STREAM_PATHS: readonly ["/flow/stream", "/chat/stream"];
export type StreamPath = (typeof STREAM_PATHS)[number];
export function isStreamPath(p: string): p is StreamPath;

// web/lib/api/sse-parser.ts
export type SseFrame = { id: string | null; event: string; data: string; retry: number | null };
export function createSseParser(onFrame: (f: SseFrame) => void): { push(chunk: string): void; flush(): void };

// web/lib/api/use-event-stream.ts  ("use client")
export type StreamStatus = "live" | "reconnecting" | "disconnected";
export type StreamEvent<T> = { id: string | null; event: string; data: T };
export type UseEventStreamOptions<T> = {
  onEvent: (e: StreamEvent<T>) => void;
  body?: unknown;                         // present → POST JSON
  schema?: z.ZodType<T>;                  // validate each data payload (SSE-25); recommended
  onStreamError?: (data: unknown) => void;// "stream-error" frames
  enabled?: boolean;                      // default true
  reconnect?: boolean;                    // default body === undefined
  maxRetries?: number;                    // default 8
};
export function useEventStream<T>(path: StreamPath, options: UseEventStreamOptions<T>):
  { status: StreamStatus; retries: number; retry: () => void };
export const RECONNECT_BASE_MS = 1_000, RECONNECT_CAP_MS = 30_000;
export function reconnectDelay(attempt: number): number;   // min(cap, base * 2 ** attempt)

// web/tests/support/api-mock.ts  (Vitest + msw/node)
export const TEST_API_BASE_URL = "http://api.test";
export const TEST_ACCESS_TOKEN = "test-access-token";
export const apiServer: SetupServerApi;
export function useApiMockServer(): void;   // beforeAll listen({onUnhandledRequest:"error"}), afterEach resetHandlers, afterAll close; vi.stubEnv for every serverEnv key with test values (API_BASE_URL = TEST_API_BASE_URL)
export function sessionModuleMock(token?: string | null): Record<string, unknown>;  // for vi.mock("@/lib/auth/session", () => sessionModuleMock()); null → getAccessToken throws SessionExpiredError
export function mockApi<P extends ApiPath, M extends Method<P>>(
  path: P, method: M,
  response: { status?: number; body?: ResponseOf<P, M> | ErrorEnvelope; headers?: Record<string, string> }
          | ((req: { request: Request; params: Record<string, string> }) => Response | Promise<Response>),
): void;                                     // {name} → :name; records calls
export function mockApiError(path: ApiPath, method: HttpMethod, status: number, code: string, message?: string, details?: Record<string, unknown>[]): void;
export function lastApiRequest(): Request | undefined;
// Tests importing server-only modules add: vi.mock("server-only", () => ({}));

// web/tests/support/sse-mock.ts
export type SseStep =
  | { event?: string; id?: string; data: unknown }   // data JSON-stringified
  | { comment: string } | { retry: number } | { delayMs: number }
  | { close: true } | { error: true };              // error → stream errors (connection drop)
export function sseResponse(steps: readonly SseStep[], init?: ResponseInit): Response;
export function mockStream(path: StreamPath, steps: readonly SseStep[] | readonly (readonly SseStep[])[], opts?: { method?: "get" | "post"; status?: number }): void;   // web origin /api/stream<path>; array-of-arrays = one per successive connection
export function mockApiStream(path: StreamPath, steps: readonly SseStep[], opts?: { method?: "get" | "post"; status?: number }): void; // API_BASE_URL<path>
export function streamRequests(): Request[];   // requests seen by mockStream (body, Last-Event-ID)
```

```python
# api/src/cashapp/openapi_dump.py
GENERATED_MARKER: Final[str]
def openapi_document() -> dict[str, Any]: ...
def render_openapi(doc: Mapping[str, Any]) -> str: ...          # sorted, indent 2, LF, trailing newline
def main(argv: Sequence[str] | None = None) -> int: ...          # --out PATH; stdout bytes otherwise

# api/src/cashapp/settings_placeholders.py
def placeholder_settings(**overrides: Any) -> Settings: ...      # no env, no .env, no Vault

# api/src/cashapp/main.py (signature widened, backward compatible)
def create_app(*, settings: Settings | None = None) -> FastAPI: ...
```

Consumers:
- s19: `api`, `useEventStream("/flow/stream")`, `ApiError` for `error-alert`, both mocks.
- s20 and s21: `api`, `apiAction`.
- s22: `useEventStream("/chat/stream", {body})`.
- s41: `api`.
- Every API story that changes routes: `npm run api:sync`.

## Migrations

None.

## Test plan (written and run at step 5)

Web tests that import a `server-only` module start with `vi.mock("server-only", () => ({}))`. Route and client tests use `// @vitest-environment node`.

| AC | Test | Asserts |
|---|---|---|
| 1 | `api/tests/unit/test_openapi_dump.py::test_document_builds_without_env_db_or_vault` | under `isolated_env` (no `CASHAPP_*`), `openapi_document()` succeeds and no engine or Vault client is created |
| 1 | `…::test_render_is_deterministic_sorted_lf` | two renders are byte-identical, keys are sorted, no `\r`, one trailing `\n` |
| 1 | `…::test_document_has_health_error_envelope_and_marker` | `/health` path present; `ErrorEnvelope`/`ErrorBody` in components; `x-generated` mentions "never hand-merge" |
| 1 | `…::test_main_out_writes_utf8_lf_file` | `main(["--out", tmp])` returns 0 and the file equals `render_openapi(openapi_document())` as bytes |
| 1 | `…::test_main_stdout_writes_bytes` | capsys or `capfdbinary` output equals the render |
| 1 | `…::test_committed_openapi_matches_app` | `web/lib/api/openapi.json` equals a fresh render (catches drift) |
| 1 | `…::test_create_app_without_settings_still_fails_fast` | with no env, `create_app()` raises `SettingsError` (s27 behaviour kept) |
| 1 | `…::test_make_settings_delegates_to_placeholder_settings` | `make_settings()` equals `placeholder_settings()` |
| 1 | `web/tests/unit/api/gen-api-types.test.ts` › `renderSchema output equals committed schema.d.ts` | drift check |
| 1 | › `schema header carries the regenerate-never-hand-merge rule` | header text |
| 1 | › `package.json defines api:openapi, api:types and api:sync` | the scripts point at `cashapp.openapi_dump` and `scripts/gen-api-types.mjs` |
| 2 | `web/tests/unit/api/client.test.ts` › `attaches bearer token, X-Request-ID and uses API_BASE_URL` | msw sees `Authorization: Bearer test-access-token`, a valid `X-Request-ID`, and host `api.test` |
| 2 | › `substitutes encoded path params and serialises query` | `{id}` filled and encoded; arrays repeat; `undefined` skipped |
| 2 | › `sends JSON body with content-type on POST` | |
| 2 | › `2xx returns ok with parsed body; 204 returns ok undefined` | |
| 2 | › `non-2xx error envelope maps to ApiError` | `{status:409, code, message, requestId: body.request_id, details}` |
| 2 | › `non-2xx without envelope maps to unexpected_response` | `requestId` taken from the response header |
| 2 | › `network failure maps to status 0 network_error` | `HttpResponse.error()` |
| 2 | › `expired session maps to 401 session_expired without calling the API` | 0 requests |
| 2 | › `invalid JSON on 2xx maps to invalid_response` | |
| 2 | › `abort is rethrown, not mapped` | |
| 2 | `web/tests/unit/api/client.typecheck.ts` (checked by the tsc gate) | commented `@ts-expect-error` on an unknown path, an undeclared method, a wrong body type, and a missing path param |
| 2 | `web/tests/unit/result.test.ts` › `ok and err construct and isOk/isErr narrow` | |
| 2 | `web/tests/unit/api/errors.test.ts` › `errors module is client-safe (no server-only import)` | static |
| 3 | `web/tests/unit/api/actions.test.ts` › `passes the fn Result through unchanged` | |
| 3 | › `unexpected throw becomes internal_error without leaking the message` | `console.error` spy has no message text |
| 3 | › `redirect and notFound errors are rethrown` | |
| 3 | › `schema overload returns 422 validation_error with field details` | |
| 3 | › `result is structuredClone-able` | |
| 3 | › `route handlers and use-server modules reach the API only through lib/api` | static scan of `app/**/route.ts` and `"use server"` files: no `fetch(` aimed at the API and no `API_BASE_URL` (`app/auth/**` IdP calls are exempt) |
| 4 | `web/tests/unit/api/stream-route.test.ts` › `non-allow-listed path returns 404 error shape without calling the API` | |
| 4 | › `no session returns 401 session_expired JSON before streaming` | |
| 4 | › `GET forwards token, query and Last-Event-ID` | |
| 4 | › `POST forwards the JSON body` | |
| 4 | › `streams upstream chunks without buffering` | the first chunk is read before upstream finishes (upstream holds on `delayMs`) |
| 4 | › `sets text/event-stream and no-cache, no-transform with no Connection header` | |
| 4 | › `relays upstream error envelope and status` | |
| 4 | › `client abort aborts the upstream request` | upstream sees the abort signal |
| 4 | `web/tests/unit/api/sse-parser.test.ts` › `parses id, event and multi-line data` | |
| 4 | › `handles chunk boundaries and CRLF` | |
| 4 | › `ignores comments; retry/id-only blocks dispatch nothing` | |
| 4 | `web/tests/unit/api/use-event-stream.test.tsx` (jsdom, fake timers, `sse-mock`) › `goes live and delivers schema-validated events` | |
| 4 | › `reconnects with exponential backoff capped at 30s and counts retries` | `reconnectDelay` 1s, 2s, 4s … 30s; `retries` increments |
| 4 | › `sends Last-Event-ID on reconnect` | |
| 4 | › `POST body is sent as JSON and a clean end does not re-post` | |
| 4 | › `4xx response stops as disconnected; 429 retries` | |
| 4 | › `disconnected after maxRetries and retry() reconnects` | |
| 4 | › `invalid payload is dropped without crashing` | |
| 4 | › `stream-error frame calls onStreamError` | |
| 4 | › `unmount aborts the fetch` | |
| 5 | `web/tests/unit/api/eslint-api-boundary.test.ts` › `no-direct-api-base-url flags serverEnv.API_BASE_URL, process.env.API_BASE_URL, destructuring and fetch with API_BASE_URL` | ESLint `RuleTester` valid and invalid cases |
| 5 | › `no-client-server-api-import flags use-client imports of lib/api/client and actions` | `@/lib/api/client`, `./client`, type-only; allows `@/lib/api/types`, `errors` and server files |
| 5 | › `config wires both rules and exempts lib/api and lib/env.ts` | `new ESLint({cwd: web}).lintText(code, {filePath})` reports on `app/x/route.ts` and not on `lib/api/client.ts` |
| 5 | › `eslint passes on lib/api and app/api` | lint those real files, 0 errors |

## Assumptions and deviations

1. **The story header says wave 2; `waves.json` says wave 1.** Nothing changes: the deps are wave 0.
2. **`create_app` gains an optional keyword `settings`.** It's also the reason for `placeholder_settings`. s27 makes `create_app()` call `get_settings()`, which needs the full env, but the dump must run with no env (story assumption). One placeholder source is shared with `make_settings` (DRY). This edits s27's `main.py` and `tests/support/settings.py`.
3. **Responses are typed at compile time and not validated at runtime.** Error envelopes, action input and SSE payloads are Zod-parsed. A runtime response schema per endpoint would duplicate the OpenAPI contract.
4. **`api()` takes an optional third argument.** It also accepts `signal` and `requestId`. `apiStream()` is added for the SSE proxy, which can't JSON-parse.
5. **Web-originated error codes** are `session_expired`, `network_error`, `unexpected_response`, `invalid_response`, `validation_error` and `internal_error`. The proxy answers in the API's single error shape, with `network_error` mapped to 502.
6. **The initial hook status is `reconnecting` with `retries: 0`.** The AC allows only three states, and design §3 shows amber "Reconnecting…" while connecting. A POST stream that ends cleanly reports `disconnected`.
7. **`apiAction` has a second overload** with a Zod schema, for server-action input validation (boundary rule).
8. **The lint guard is a local plugin, not `no-restricted-syntax`** (see AC5).
9. **openapi-typescript runs with `defaultNonNullable: false` and `alphabetize: true`.**
10. **The POST proxy reads the body as text** and doesn't stream the request body.

## Risks

- **`openapi.json` drift.** Every API-route story must run `npm run api:sync`, or `test_committed_openapi_matches_app` and the `schema.d.ts` drift test fail. The merger regenerates on conflict and never hand-merges.
- **Shared-file edits.** These are `main.py` (one signature), `tests/support/settings.py`, `web/eslint.config.mjs` (append a block) and `web/package.json` (three scripts). Merge after s27 and s01. s04 or s27 may also append to `eslint.config.mjs`.
- **`server-only` throws under Vitest.** Each test mocks it. If s01's `vitest.config.ts` adds a `server-only` alias, these mocks become redundant but harmless.
- **`.env.test` may lack the serverEnv keys.** `useApiMockServer()` stubs every key so tests don't depend on it. Because `serverEnv` is memoized, all tests must use the same values.
- **msw and jsdom streaming.** `ReadableStream` bodies through msw in jsdom can buffer. If `use-event-stream` tests can't observe incremental frames, run them in `// @vitest-environment node` with `renderHook` from a minimal `happy-dom` environment, or set `globalThis.location` by hand. Record the choice; no dependency changes.
- **Next 16 `RouteContext` for catch-all segments** needs `next typegen` first. That's already part of the type gate.
- **openapi-typescript major.** If it isn't v7 (Node API `openapiTS` plus `astToString`), the coder adapts `renderSchema` and records it.
