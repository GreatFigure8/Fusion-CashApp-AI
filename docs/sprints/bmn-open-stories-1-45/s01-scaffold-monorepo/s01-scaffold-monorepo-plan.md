# s01-scaffold-monorepo plan

Story: [story.md](story.md) (issue #1). Wave 1, spine step 1 of 6. No deps. Everything later builds on the
paths and interfaces pinned below.

## Standards followed

- **CLAUDE.md**: layered architecture (routers never import SQLAlchemy; only `cashapp/data/` touches the
  ORM), one error shape, no scheduler, OCI `us-ashburn-1` only, Alembic for every schema change, BMN gates
  (ruff + pyright; tsc + eslint).
- **python-web-app:building-python-web-apps**: uv + `pyproject.toml` + `uv.lock`, hatchling, `src/` layout,
  FastAPI app with routers registered in a loop, `Annotated` deps, lazy async engine with `pool_pre_ping`,
  Alembic, ruff + pytest + pytest-asyncio.
- **nextjs-fullstack-standards** and **references/nextjs.md** (wins on conflict). Rule ids applied:
  - TS-1, TS-2 (`strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `noFallthroughCasesInSwitch`),
    TS-3, TS-4, TS-5 (`next typegen` before `tsc`), TS-6, TS-7 (typed `next.config.ts`), TS-8
    (`typedRoutes: true` top level), TS-9 (`@/*` alias, no `src/`), TS-11, TS-12 (ESLint CLI +
    `eslint-config-next` flat config, never `next lint`), TS-28 (no `any`).
  - TEST-3, TEST-4 (Vitest set up the Next.js way: `@vitejs/plugin-react`, `jsdom`,
    `vite-tsconfig-paths`), TEST-6, TEST-8 (`web/.env.test` committed with non-secret defaults), TEST-12,
    TEST-13 (Playwright per-checkout port, reuse only on request), TEST-37 (gate order).
  - Non-negotiable 2 (no `middleware.ts`; nothing intercepts in s01), 9 (lint outside build).
  - Placement rule 10: this repo's layout is the story's `src/`-less one (`web/app`, `web/components`,
    `web/lib`), as CLAUDE.md and the story pin it.

## Files to touch (all new unless noted)

Owned exclusively by s01. Later stories add new files under these dirs; the only shared files later
spine stories may edit are noted in *Interfaces provided*.

### Root

- `/.gitignore` (AC10)
- `/CLAUDE.md` (edit: *Repository layout* and *Commands* only, AC9)

### `api/`

- `api/pyproject.toml`, `api/uv.lock`, `api/.python-version` (`3.12`)
- `api/alembic.ini`, `api/alembic/env.py`, `api/alembic/script.py.mako`, `api/alembic/versions/.gitkeep`
- `api/src/cashapp/__init__.py` (`__version__` from `importlib.metadata`), `api/src/cashapp/py.typed`
- `api/src/cashapp/main.py`
- `api/src/cashapp/api/__init__.py`
- `api/src/cashapp/api/errors.py` (`ApiError`, `ErrorBody`, `ErrorEnvelope`, `install_error_handlers`, `ERROR_RESPONSES`)
- `api/src/cashapp/api/request_context.py` (`REQUEST_ID_HEADER`, `request_id_var`, `get_request_id`)
- `api/src/cashapp/api/middleware.py` (`RequestIdMiddleware`, pure ASGI, SSE-safe; not `BaseHTTPMiddleware`)
- `api/src/cashapp/api/discovery.py` (`discover_routers`)
- `api/src/cashapp/api/routers/__init__.py` (empty)
- `api/src/cashapp/api/routers/health.py` (`router`, `HealthResponse`) — itself auto-discovered, proving discovery
- `api/src/cashapp/data/__init__.py`, `api/src/cashapp/data/engine.py`, `api/src/cashapp/data/base.py`
- `api/src/cashapp/data/models/__init__.py` (empty), `api/src/cashapp/data/repositories/__init__.py` (empty)
- Empty `__init__.py` in: `cashapp/domain/`, `cashapp/services/`, `cashapp/pipeline/`, `cashapp/stations/`,
  `cashapp/pollers/`, `cashapp/integrations/`, `cashapp/workers/`, `cashapp/observability/`, `cashapp/auth/`,
  `cashapp/tools/`
- `api/tests/conftest.py` (empty root conftest), `api/tests/__init__.py`, `api/tests/support/__init__.py`
  (empty package so s02/s27 can add `support/*.py` without touching it)

### `web/`

Created with `npx create-next-app@16.3 web --ts --tailwind --eslint --app --no-src-dir --import-alias "@/*" --use-npm`,
then `npx shadcn@latest init` (base color neutral, CSS variables), then
`npx shadcn@latest add sidebar breadcrumb command card table badge button input select tabs sheet dialog alert-dialog alert popover calendar progress skeleton tooltip sonner form switch collapsible chart`.

- `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/next.config.ts`,
  `web/eslint.config.mjs`, `web/postcss.config.mjs`, `web/components.json`, `web/next-env.d.ts` (generated, gitignored per Next default if so)
- `web/app/layout.tsx` (Geist Sans/Mono via `next/font/google`, `ThemeProvider`-free placeholder; s19 owns the shell),
  `web/app/page.tsx` (minimal placeholder "CashApp", replaced by s19), `web/app/globals.css`
- `web/components/ui/*` (shadcn CLI output only), `web/components/common/.gitkeep`
- `web/lib/utils.ts` (shadcn `cn`), `web/hooks/use-mobile.ts` (sidebar dependency, CLI output)
- `web/vitest.config.ts`, `web/tests/setup.ts`, `web/playwright.config.ts`, `web/.env.test`, `web/e2e/.gitkeep`

### `infra/`

- `infra/versions.tf`, `infra/providers.tf`, `infra/variables.tf`, `infra/main.tf` (empty body comment only)
- `infra/modules/.gitkeep`, `infra/envs/dev/.gitkeep`, `infra/envs/prod/.gitkeep`
- `infra/.terraform.lock.hcl` (committed: provider lock from `terraform init -backend=false`)

## Implementation notes

### api/pyproject.toml

- `[project] name = "cashapp"`, `version = "0.1.0"`, `requires-python = ">=3.12"`. Build backend hatchling,
  `[tool.hatch.build.targets.wheel] packages = ["src/cashapp"]`.
- Runtime deps (lower bounds `>=` at the current release; exact versions locked in `uv.lock`): fastapi,
  `uvicorn[standard]`, `sqlalchemy[asyncio]>=2.0.30`, `oracledb>=2`, alembic, `pydantic>=2`, pydantic-settings,
  sse-starlette, aiokafka, `pyjwt[crypto]`, httpx, anthropic, oci, defusedxml, opentelemetry-api,
  opentelemetry-sdk, opentelemetry-exporter-otlp, python-json-logger, python-multipart, openpyxl, pypdf,
  pillow, python-docx, extract-msg, beautifulsoup4, aioimaplib, typer.
- `[dependency-groups] dev`: aiosqlite, pytest, pytest-asyncio, pytest-cov, respx, time-machine, ruff, pyright.
- `[project.scripts] cashapp = "cashapp.tools.cli:app"` is NOT added now (no module yet; s30/s23 add their own).
- `[tool.ruff]`: `line-length = 100`, `target-version = "py312"`, `src = ["src", "tests"]`; lint select
  `E,F,W,I,UP,B,SIM,ASYNC,RUF,S,PT,N`; per-file ignore `S101` in `tests/**`; `alembic/versions/*` ignore `E501`.
- `[tool.pyright]`: `include = ["src", "tests", "alembic"]`, `strict = ["src"]`, `pythonVersion = "3.12"`,
  `venvPath = "."`, `venv = ".venv"`, `reportMissingTypeStubs = false` (oci, aiokafka, extract-msg ship no
  stubs; strict otherwise unchanged).
- `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`,
  `testpaths = ["tests"]`, `markers = ["atp: needs the DEV ATP schema (opt in with -m atp)", "live: calls a live external system (opt in with -m live)"]`,
  `addopts = ["--strict-markers", "-m", "not atp and not live"]` (a later `-m atp` on the CLI wins).
- `[tool.coverage.run] source = ["cashapp"]`, `branch = true`.

### main.py

```python
def create_app() -> FastAPI: ...
app = create_app()
```

`create_app` builds `FastAPI(title="Fusion CashApp API", version=__version__, responses=ERROR_RESPONSES)`,
adds `RequestIdMiddleware`, calls `install_error_handlers(app)`, then
`for r in discover_routers("cashapp.api.routers"): app.include_router(r)`. No settings yet (s27 adds a
`get_settings()` call inside `create_app`; that is the only planned later edit of `main.py`).

### Error handling (`api/errors.py`)

- `ApiError` → its `status_code`, body from its fields.
- `RequestValidationError` → 422, `code="validation_error"`, `details=[{"loc": [...], "msg": str, "type": str}]`
  (never the `input` value: no PII echoed).
- Starlette `HTTPException` → its status, code from `{400:"bad_request",401:"unauthorized",403:"forbidden",404:"not_found",405:"method_not_allowed",409:"conflict",429:"rate_limited"}` else `"http_error"`; keeps its headers.
- `Exception` → 500, `code="internal_error"`, `message="An unexpected error occurred."`, logged with
  `logger.exception` (std `logging`; s29 swaps the formatter). The handler sets `X-Request-ID` itself,
  because `ServerErrorMiddleware` sits outside `RequestIdMiddleware`. The request id is read from
  `scope["state"]["request_id"]`, which the middleware writes, so it survives the middleware unwinding.

### Request id

`RequestIdMiddleware` reads `X-Request-ID`; accepts it if it matches `^[A-Za-z0-9._-]{1,128}$`, otherwise
generates `uuid4().hex`. Sets `scope["state"]["request_id"]`, `request_id_var`, and adds the header to
every response start message.

### Data / Alembic

- `create_engine` normalises `oracle://` → `oracle+oracledb://`, sets `oracledb.defaults.fetch_decimals = True`
  once (the a6 rail s02 relies on), and calls `create_async_engine(url, pool_pre_ping=True, **opts)`.
  Thin mode is oracledb's default; never call `init_oracle_client`. Works unchanged for `sqlite+aiosqlite`.
- `data/base.py`: `class Base(DeclarativeBase)` with `metadata = MetaData(naming_convention={...})` using
  upper snake, ≤128-char names (`PK_%(table_name)s`, `FK_%(table_name)s_%(column_0_name)s`,
  `UQ_%(table_name)s_%(column_0_name)s`, `IX_%(table_name)s_%(column_0_name)s`,
  `CK_%(table_name)s_%(constraint_name)s`).
- `alembic/env.py`: async (`async_engine_from_config`-equivalent via `cashapp.data.engine.create_engine` +
  `connection.run_sync(do_run_migrations)`), offline mode supported. `target_metadata = Base.metadata` after
  importing every module in `cashapp.data.models` with `pkgutil.iter_modules` (so s02 and later never edit
  `env.py` to register models). URL comes from one function `_database_url() -> str` that reads env var
  `CASHAPP_DATABASE_URL` and raises a clear error if unset; s27 replaces only that function body with
  `get_settings().atp`. `compare_type=True`. `alembic.ini` has no URL.
- `uv run alembic heads` prints nothing (no revisions) and exits 0.

### web

- `tsconfig.json`: create-next-app defaults plus `noUncheckedIndexedAccess`, `noImplicitOverride`,
  `noFallthroughCasesInSwitch`; keep the `next` plugin and `.next/types/**/*.ts`, `.next/dev/types/**/*.ts` includes.
- `next.config.ts`: `typedRoutes: true`, `output: "standalone"` (OCI container image later), nothing else.
- `components.json`: style per CLI default for shadcn v4 (Base UI base), `baseColor: "neutral"`,
  `cssVariables: true`, aliases `@/components`, `@/components/ui`, `@/lib`, `@/hooks`.
- `globals.css`: shadcn neutral tokens with `--radius: 0.375rem`, plus the design.md §2 status tokens
  (`--status-success|progress|waiting|attention|error|locked`, light and dark) registered in `@theme inline`
  as `--color-status-*`, so s19 never edits this file for tokens. Geist variables `--font-sans`,
  `--font-mono` mapped to the `next/font` CSS variables.
- `package.json` deps added with `npm install` (exact versions recorded by the lockfile; `^` ranges as npm
  writes them): zod, openapi-typescript, oauth4webapi, iron-session, @tanstack/react-table, react-hook-form,
  @hookform/resolvers, recharts, lucide-react, react-markdown, rehype-sanitize, pdfjs-dist, next-themes,
  server-only. Dev: vitest, @vitest/coverage-v8, @vitejs/plugin-react, vite-tsconfig-paths,
  @testing-library/react, @testing-library/dom, @testing-library/jest-dom, jsdom, msw, @playwright/test.
  (`server-only`, `@vitejs/plugin-react`, `vite-tsconfig-paths`, `@testing-library/dom`,
  `@testing-library/jest-dom` are additions the story list omits; needed by TS-27 and TEST-4.)
- Scripts: `dev`, `build`, `start`, `lint: eslint .`, `typecheck: next typegen && tsc --noEmit`,
  `test: vitest run`, `test:e2e: playwright test`.
- `vitest.config.ts`: `plugins: [tsconfigPaths(), react()]`, `test.environment = "jsdom"`,
  `setupFiles: ["./tests/setup.ts"]`, `include: ["tests/**/*.test.{ts,tsx}", "**/*.test.{ts,tsx}"]`,
  `exclude: ["e2e/**", "node_modules/**", ".next/**"]`, coverage provider v8.
- `tests/setup.ts`: `import "@testing-library/jest-dom/vitest";` only.
- `playwright.config.ts`: `testDir: "./e2e"`, `use.baseURL = process.env.PLAYWRIGHT_BASE_URL ?? \`http://localhost:${port}\``,
  `port = Number(process.env.PLAYWRIGHT_PORT ?? 3100)`; `webServer` present only when
  `PLAYWRIGHT_BASE_URL` is unset: `command: \`npm run build && npm run start -- --port ${port}\``,
  `reuseExistingServer: process.env.PLAYWRIGHT_REUSE === "1"`.
- `eslint.config.mjs`: flat config from `eslint-config-next` (core-web-vitals + typescript), ignores
  `.next/**`, `node_modules/**`, `next-env.d.ts`, `playwright-report/**`, `test-results/**`, `coverage/**`.
  If CLI-generated `components/ui/*` fails a rule, add a narrowly scoped override for that rule on
  `components/ui/**` only (never edit generated primitives to satisfy lint) and record it in the coder return.

### infra

- `versions.tf`: `terraform { required_version = ">= 1.6" required_providers { oci = { source = "oracle/oci", version = "~> 7.0" } } }`
  (coder confirms the current major from the registry during `terraform init` and adjusts the constraint
  to that major; record it).
- `providers.tf`: `provider "oci" { region = "us-ashburn-1" tenancy_ocid = var.tenancy_ocid }` — region is a
  literal, never a variable. No backend block (no state).
- `variables.tf`: `tenancy_ocid`, `compartment_ocid`, `environment` (validation `contains(["dev","prod"], ...)`).
- Gate: `terraform -chdir=infra init -backend=false && terraform -chdir=infra fmt -check -recursive && terraform -chdir=infra validate`.

### .gitignore (root)

`.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `.coverage`, `coverage.xml`, `htmlcov/`,
`.env`, `.env.*`, `!.env.example`, `!.env.test`, `node_modules/`, `.next/`, `out/`, `coverage/`,
`playwright-report/`, `test-results/`, `blob-report/`, `playwright/.cache/`, `*.tfstate`, `*.tfstate.*`,
`.terraform/`, `*.tfplan`, `next-env.d.ts`, `*.tsbuildinfo`. (Keep `.terraform.lock.hcl` tracked.)
`web/.gitignore` from create-next-app is deleted in favour of the root file (one ignore file).

### CLAUDE.md

Rewrite only *Repository layout* (real tree: `api/src/cashapp/{api/routers,data/{models,repositories},domain,services,pipeline,stations,pollers,integrations,workers,observability,auth,tools}`, `api/alembic`, `api/tests`, `web/{app,components/{ui,common},lib,hooks,tests,e2e}`, `infra/{modules,envs/dev,envs/prod}`) and *Commands* (real api/web/infra commands incl. `uv run fastapi dev src/cashapp/main.py`, `npx vitest run`, `npx playwright test`, the terraform gate line). Remove "Proposed" from both. Record in *Repository layout* that router auto-discovery means no story edits `main.py` to add a router.

## Interfaces provided (pinned)

```python
# cashapp/main.py
def create_app() -> FastAPI: ...
app: FastAPI

# cashapp/api/errors.py
class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[dict[str, Any]] = []

class ErrorEnvelope(BaseModel):
    error: ErrorBody

class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,                       # lower snake, e.g. "invalid_token", "not_found"
        message: str | None = None,      # defaults to code with underscores → spaces, capitalised
        *,
        details: Sequence[Mapping[str, Any]] = (),
        headers: Mapping[str, str] | None = None,
    ) -> None: ...
    status_code: int; code: str; message: str; details: list[dict[str, Any]]; headers: dict[str, str] | None

ERROR_RESPONSES: dict[int | str, dict[str, Any]]   # {"4XX": {"model": ErrorEnvelope}, "5XX": {"model": ErrorEnvelope}}
def install_error_handlers(app: FastAPI) -> None: ...

# cashapp/api/request_context.py
REQUEST_ID_HEADER: Final = "X-Request-ID"
request_id_var: ContextVar[str | None]
def get_request_id() -> str | None: ...

# cashapp/api/middleware.py
class RequestIdMiddleware:   # pure ASGI: __init__(self, app: ASGIApp); async __call__(scope, receive, send)

# cashapp/api/discovery.py
def discover_routers(package: str) -> list[APIRouter]: ...
# imports every non-underscore module directly in `package` (sorted by name), returns each module's
# `router` attribute that is an APIRouter; import errors propagate (fail fast at startup).

# cashapp/api/routers/health.py
class HealthResponse(BaseModel): status: Literal["ok"]; version: str
router: APIRouter            # GET /health -> HealthResponse

# cashapp/data/engine.py
def create_engine(url: str, **opts: Any) -> AsyncEngine: ...

# cashapp/data/base.py
class Base(DeclarativeBase): metadata = MetaData(naming_convention=...)

# alembic/env.py
def _database_url() -> str: ...    # the one function s27 rewires to get_settings().atp
```

Error JSON (every non-2xx): `{"error": {"code": str, "message": str, "request_id": str, "details": list}}`
and response header `X-Request-ID`.

Conventions pinned for dependents:
- New HTTP endpoints = a new module in `cashapp/api/routers/` exporting `router`. Never edit `main.py`.
- New ORM models = a new module in `cashapp/data/models/` subclassing `cashapp.data.base.Base`. Never edit `alembic/env.py`.
- Test helpers go in new files under `api/tests/support/`.
- Web shared components go in `web/components/common/`; shadcn primitives only via the CLI into `web/components/ui/`.
- No later story edits `uv.lock` / `package-lock.json` unless a dependency is truly missing (then it is
  logged as an assumption and the merger resolves the lockfile).

## Migrations

None. Alembic is initialised with zero revisions; s02 adds the base revision.

## TEST PLAN

Nobody writes or runs these until step 5. Repo-level tests locate the repo root as
`Path(__file__).resolve().parents[N]` up to the dir containing `CLAUDE.md`.

| AC | Test (file::name) | Asserts |
|---|---|---|
| 1 | `api/tests/scaffold/test_project_config.py::test_project_is_cashapp_requiring_python_312` | `pyproject` name `cashapp`, `requires-python` `>=3.12`, `src/cashapp/__init__.py` exists, `cashapp.__version__` equals `importlib.metadata.version("cashapp")` |
| 1 | `…::test_pyright_is_strict_on_src_and_ruff_configured` | `[tool.pyright].strict` contains `src`; `[tool.ruff]` present with `target-version = "py312"` |
| 1 | `…::test_layer_packages_exist` | every package in story Context (`data`, `domain`, `services`, `pipeline`, `stations`, `pollers`, `integrations`, `api/routers`, `workers`, `observability`, `auth`, `tools`) has `__init__.py` |
| 2 | `…::test_runtime_dependencies_declared` | each of the 27 runtime names appears in `[project].dependencies` (normalised names, extras `uvicorn[standard]`, `sqlalchemy[asyncio]`, `pyjwt[crypto]`) |
| 2 | `…::test_dev_dependencies_declared` | each dev name in `[dependency-groups].dev` |
| 2 | `…::test_uv_lock_committed_and_resolves_every_dependency` | `uv.lock` exists, is tracked (`git ls-files`), and has a `[[package]]` for every declared dep |
| 3 | `api/tests/api/test_app_shell.py::test_health_returns_ok_and_package_version` | `GET /health` → 200 `{"status":"ok","version": cashapp.__version__}` |
| 3 | `…::test_request_id_echoed_when_valid` | supplied `X-Request-ID: abc-123` echoed in response header |
| 3 | `…::test_request_id_generated_when_absent_or_invalid` | absent or `"bad id\n"` → 32-hex generated id in header |
| 3 | `…::test_discover_routers_includes_modules_exposing_router` | tmp package (via `tmp_path` + `monkeypatch.syspath_prepend`) with `a.py` (router), `b.py` (no router), `_c.py` (router) → only `a`'s router returned |
| 3 | `…::test_app_includes_health_router_via_discovery` | `/health` route present on `create_app()` and `main.py` source has no `include_router(` call naming a specific module |
| 3 | `…::test_api_error_uses_single_error_shape` | route raising `ApiError(409, "conflict_x", "Clash", details=[{"k":1}])` → 409, body matches `ErrorEnvelope`, `request_id` equals header |
| 3 | `…::test_validation_error_uses_single_error_shape_without_input` | bad body → 422 `validation_error`, each detail has `loc,msg,type` and no `input` key; posted value absent from body text |
| 3 | `…::test_http_exception_maps_to_single_error_shape` | unknown path → 404 `not_found` in envelope |
| 3 | `…::test_unhandled_exception_returns_500_without_internals` | route raising `RuntimeError("secret-detail")` (client `raise_server_exceptions=False`) → 500 `internal_error`, `"secret-detail"` and `"Traceback"` not in body, `X-Request-ID` header present and equal to body `request_id` |
| 3 | `…::test_openapi_declares_error_envelope` | `/openapi.json` components include `ErrorEnvelope` and `ErrorBody` |
| 4 | `api/tests/data/test_engine.py::test_create_engine_builds_async_oracledb_engine` | `create_engine("oracle+oracledb://u:p@h:1521/?service_name=s")` → `AsyncEngine`, `dialect.name == "oracle"`, `dialect.driver == "oracledb"`, `dialect.is_async`; no connection opened |
| 4 | `…::test_create_engine_normalises_plain_oracle_scheme` | `oracle://…` → driver `oracledb` |
| 4 | `…::test_create_engine_sets_fetch_decimals` | `oracledb.defaults.fetch_decimals is True` after the call |
| 4 | `…::test_create_engine_works_with_aiosqlite` | `sqlite+aiosqlite://` engine executes `SELECT 1` |
| 4 | `api/tests/data/test_alembic_env.py::test_alembic_has_no_revisions` | `ScriptDirectory.from_config(Config("alembic.ini")).get_heads() == []` |
| 4 | `…::test_alembic_env_is_async_and_targets_base_metadata` | `env.py` imports `cashapp.data.engine.create_engine`, uses `run_sync`, sets `target_metadata = Base.metadata`, defines `_database_url` |
| 4 | `…::test_alembic_database_url_requires_env` | importing the helper with `CASHAPP_DATABASE_URL` unset raises an error naming the variable (helper factored so it is importable, or exercised via `alembic upgrade head --sql` subprocess with env unset → non-zero, message names var) |
| 5 | `web/tests/scaffold/project-config.test.ts` › `tsconfig is strict with noUncheckedIndexedAccess` | parse `tsconfig.json`: `strict`, `noUncheckedIndexedAccess`, `paths["@/*"] = ["./*"]` |
| 5 | › `next config enables typedRoutes` | `next.config.ts` text contains `typedRoutes: true` |
| 5 | › `shadcn initialised neutral with css variables and 0.375rem radius` | `components.json` `tailwind.baseColor === "neutral"`, `cssVariables === true`; `globals.css` contains `--radius: 0.375rem` and `@import "tailwindcss"` |
| 5 | › `root layout loads Geist Sans and Geist Mono` | `app/layout.tsx` imports `Geist` and `Geist_Mono` |
| 5 | › `globals.css defines status tokens light and dark` | all six `--status-*` tokens appear in `:root` and `.dark` |
| 6 | `web/tests/scaffold/dependencies.test.ts` › `every design.md primitive exists in components/ui` | 24 files (`sidebar.tsx` … `chart.tsx`) exist |
| 6 | › `runtime and dev dependencies are declared` | every listed package in `dependencies` / `devDependencies` |
| 6 | › `package-lock is committed` | `package-lock.json` exists and is git-tracked |
| 7 | `api/tests/scaffold/test_project_config.py::test_pytest_config_registers_markers_and_skips_by_default` | `asyncio_mode == "auto"`, markers `atp`, `live` registered, `addopts` contains `-m` `not atp and not live`, `--strict-markers` |
| 7 | `api/tests/scaffold/test_marker_selection.py::test_atp_and_live_deselected_by_default` | `pytester` run of a file with one plain, one `@pytest.mark.atp`, one `@pytest.mark.live` test using the project ini → 1 passed, 2 deselected; with `-m atp` → the atp test selected |
| 7 | `web/tests/scaffold/test-config.test.ts` › `vitest uses jsdom and tests/setup.ts` | import `vitest.config.ts` default, assert `test.environment === "jsdom"`, `setupFiles` includes `./tests/setup.ts` |
| 7 | › `playwright baseURL comes from PLAYWRIGHT_BASE_URL` | set env, import config fresh (`vi.resetModules`), `use.baseURL` equals env; unset env → `webServer` defined |
| 8 | `api/tests/scaffold/test_infra.py::test_terraform_skeleton_layout` | `versions.tf`, `providers.tf`, `variables.tf`, `modules/`, `envs/dev/`, `envs/prod/` exist |
| 8 | `…::test_oci_provider_pinned_and_region_hard_set` | `versions.tf` has `source = "oracle/oci"` and a `version =` constraint; `providers.tf` has literal `region = "us-ashburn-1"` and no `var.` on the region line; no `backend` block anywhere |
| 8 | `…::test_terraform_fmt_and_validate` (marked `@pytest.mark.skipif(shutil.which("terraform") is None)`) | `terraform init -backend=false`, `fmt -check -recursive`, `validate` all exit 0 |
| 9 | `api/tests/scaffold/test_claude_md.py::test_layout_and_commands_sections_are_real` | extract both H2 sections: no `Proposed`/`proposed`; layout mentions `api/src/cashapp`, `web/components/ui`, `infra/envs`; commands mention `uv run pyright`, `npx next typegen && npx tsc --noEmit`, `npx eslint .`, `terraform` |
| 10 | `api/tests/scaffold/test_gitignore.py::test_gitignore_covers_required_patterns` | `git check-ignore -q` true for `api/.venv/x`, `api/src/cashapp/__pycache__/x.pyc`, `api/.env`, `web/.env.local`, `web/node_modules/x`, `web/.next/x`, `infra/terraform.tfstate`, `infra/terraform.tfstate.backup`, `infra/.terraform/x`, `api/htmlcov/x`, `web/coverage/x`, `web/playwright-report/x`, `web/test-results/x`; false for `api/.env.example`, `web/.env.example`, `web/.env.test` |

Gates the tester also runs for this story (they are the AC1/AC5/AC8 "pass" clauses): `uv sync --frozen`,
ruff check + format check, pyright, `uv run alembic heads`; `npx next typegen && npx tsc --noEmit`,
`npx eslint .`; the terraform gate line.

## Risks

1. **`uv` and `terraform` are not on PATH on this machine** (checked: only Python 3.14 and
   `~/.local/bin/python3.12.exe`). Coder installs uv (`python -m pip install --user uv` or the official
   astral installer) and Terraform (official HashiCorp Windows zip from releases.hashicorp.com, or
   `winget install Hashicorp.Terraform`), and pins `api/.python-version` to 3.12 so uv uses 3.12 (uv can
   fetch it). If Terraform cannot be installed, `test_terraform_fmt_and_validate` skips and the gate is
   reported as not run, never faked.
2. **shadcn v4 with Base UI may have replaced `form` with `field`.** If `npx shadcn@latest add form` is
   unavailable for the chosen base, add `field` instead, keep react-hook-form + @hookform/resolvers, and
   log the substitution as an assumption; the AC6 test list is then adjusted to `field.tsx` by the tester.
   Same rule for any other renamed primitive. Never hand-write a primitive.
3. **Version drift**: `create-next-app@16.3` resolves the current 16.3.x LTS; confirm React 19 and Tailwind
   v4 in the generated `package.json`, don't assume. If `next typegen` is missing, stop and record (it is
   required by TS-5).
4. **oracledb async through SQLAlchemy** needs SQLAlchemy ≥ 2.0.25 (async `oracle+oracledb`). The floor
   `>=2.0.30` covers it; no live connection is made in this story.
5. **Pyright strict + untyped libraries** (oci, aiokafka): `reportMissingTypeStubs = false` only; no other
   strict rule relaxed. Later stories wrap untyped calls behind typed interfaces.
6. **Lockfile churn**: pinning everything up front is the point; a later story needing a new package
   resolves it at merge, not in parallel coders.
7. **Story deviations logged** (assumptions):
   - Playwright `webServer` runs `npm run build && npm run start` on a per-checkout port instead of
     `npm run dev` (TEST-12/TEST-13 from the dated nextjs.md win over the story's wording); `baseURL` still
     comes from `PLAYWRIGHT_BASE_URL`.
   - `/health` is liveness only (no DB ping): the AC pins its exact body and there is no DB config until
     s27; a readiness probe that pings ATP belongs to s30's worker host / s02.
   - `oracledb.defaults.fetch_decimals = True` is set in `create_engine` (s01-owned file) rather than by s02.
   - Status colour tokens from design.md §2 land in `globals.css` now so s19 doesn't edit it.
   - Extra web deps `server-only`, `@vitejs/plugin-react`, `vite-tsconfig-paths`, `@testing-library/dom`,
     `@testing-library/jest-dom` added (needed by TS-27 / TEST-4).
   - Alembic URL read from `CASHAPP_DATABASE_URL` until s27 rewires `_database_url()`.
