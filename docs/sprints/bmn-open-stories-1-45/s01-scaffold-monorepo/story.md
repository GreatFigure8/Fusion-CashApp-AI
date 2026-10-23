# s01-scaffold-monorepo: Scaffold the monorepo (api, web, infra skeleton)

- Issue: #1
- Wave: 1 (serialized spine, step 1 of 6)
- breaking: false

## Story

As a developer on this repo, I want the three projects CLAUDE.md describes to exist with every known dependency pinned and the code gates green, so that every later story has a home and never edits a lockfile, `main.py` or the shadcn set.

## Context

Greenfield. research.md (a3 stack, a1 build order): pin every known dependency up front so later waves never touch `uv.lock` / `package-lock.json`. Paths used by every later story:

- Python package: `api/src/cashapp/` (below, `cashapp/` means `api/src/cashapp/`). Layers: `cashapp/data/`, `cashapp/domain/`, `cashapp/services/`, `cashapp/pipeline/`, `cashapp/stations/<stage>/`, `cashapp/pollers/<name>/`, `cashapp/integrations/<system>/`, `cashapp/api/routers/`, `cashapp/workers/`, `cashapp/observability/`, `cashapp/auth/`, `cashapp/tools/`.
- Web: `web/` (App Router, `src/`-less: `web/app`, `web/components/ui`, `web/components/common`, `web/lib`).
- Infra: `infra/` (Terraform).

## Acceptance criteria

1. [unit] `api/` is a uv project (Python 3.12+, `requires-python >=3.12`) with package `cashapp` under `api/src/`; `uv sync` succeeds and `uv run ruff check . && uv run ruff format --check .` and `uv run pyright` (strict on `src/`) pass.
2. [unit] `pyproject.toml` pins every runtime dependency later stories need: fastapi, uvicorn[standard], sqlalchemy[asyncio]>=2, oracledb, alembic, pydantic>=2, pydantic-settings, sse-starlette, aiokafka, pyjwt[crypto], httpx, anthropic, oci, defusedxml, opentelemetry-api/-sdk/-exporter-otlp, python-json-logger, python-multipart, openpyxl, pypdf, pillow, python-docx, extract-msg, beautifulsoup4, aioimaplib, typer; dev: aiosqlite, pytest, pytest-asyncio, pytest-cov, respx, time-machine, ruff, pyright. `uv.lock` committed.
3. [api] `cashapp/main.py` builds the FastAPI app with: `GET /health` → `200 {"status":"ok","version":"<pkg version>"}`; a request-id middleware (reads/sets `X-Request-ID`); router auto-discovery that includes every module in `cashapp/api/routers/` exposing `router: APIRouter` (no later story edits `main.py`); one error shape for every error: `{"error":{"code":str,"message":str,"request_id":str,"details":list}}` defined once in `cashapp/api/errors.py` (`ApiError` exception + handlers for `ApiError`, `RequestValidationError`, `HTTPException`, unhandled `Exception` → 500 without leaking internals).
4. [integration] `cashapp/data/engine.py` exposes `create_engine(url: str, **opts) -> AsyncEngine` for `oracle+oracledb` (thin mode, async) and `alembic/` is initialised with an async `env.py` reading the URL from settings (wired in s27); `uv run alembic heads` runs with no revisions.
5. [unit] `web/` is Next.js App Router + TypeScript `strict` + `noUncheckedIndexedAccess`, Tailwind v4, shadcn initialised (neutral base, CSS variables, `--radius: 0.375rem`), Geist Sans/Mono; `npx next typegen && npx tsc --noEmit` and `npx eslint .` pass.
6. [unit] Every shadcn primitive listed in design.md §9 is added with `npx shadcn@latest add` into `web/components/ui/` (sidebar, breadcrumb, command, card, table, badge, button, input, select, tabs, sheet, dialog, alert-dialog, alert, popover, calendar, progress, skeleton, tooltip, sonner, form, switch, collapsible, chart), and `package.json` pins: zod, openapi-typescript, oauth4webapi, iron-session, @tanstack/react-table, react-hook-form, @hookform/resolvers, recharts, lucide-react, react-markdown, rehype-sanitize, pdfjs-dist, next-themes; dev: vitest, @vitest/coverage-v8, @testing-library/react, jsdom, msw, @playwright/test. Lockfile committed.
7. [unit] Test harness config only (nothing is run in this story): `api/pyproject.toml` `[tool.pytest.ini_options]` (asyncio_mode=auto, markers `atp` and `live` registered, skipped by default unless `-m atp`/`-m live`), `api/tests/conftest.py` (empty root conftest), `web/vitest.config.ts` (jsdom, `tests/setup.ts`), `web/playwright.config.ts` (baseURL from `PLAYWRIGHT_BASE_URL`, `webServer: npm run dev`).
8. [unit] `infra/` holds a Terraform skeleton: `versions.tf` (oracle/oci provider pinned), `providers.tf` with `region = "us-ashburn-1"` hard-set, `variables.tf`, empty `modules/` and `envs/dev`, `envs/prod`; `terraform fmt -check` and `terraform validate` pass (no state, no apply).
9. [unit] CLAUDE.md *Repository layout* and *Commands* sections are rewritten to the real paths and commands (api, web, infra), removing "Proposed".
10. [unit] `.gitignore` covers `.venv`, `__pycache__`, `.env*` (except `.env.example`), `node_modules`, `.next`, `*.tfstate*`, `.terraform/`, coverage and Playwright output.

## Out of scope

Business logic, settings (s27), data layer (s02), CI workflows (s26), any deploy.

## Deps

None.

## Test-support files owned

`api/tests/conftest.py` (root), pytest config, `web/vitest.config.ts`, `web/tests/setup.ts`, `web/playwright.config.ts`.

## Assumptions

- Router auto-discovery and the single error shape land here (research.md placed auto-registration in #2); moving them into the scaffold means `main.py` is written once. Deviation logged.
- Package name `cashapp`.
- Web uses no `src/` directory.
