# Stack (stack-scout, 2026-10-23)

kind: mixed. api/ = Python FastAPI + llm (python-web-app, python-llm-features, claude-api). web/ = Next.js App Router, TS, Tailwind v4, shadcn base-nova (nextjs-fullstack-standards + plugin nextjs.md). ui: true. No Vercel, no Supabase. Hosting OCI only; deploys only at release (deploy/release.sh -> .github/workflows/release.yml). dev is protected: land by PR.

Routed skills: python-web-app:building-python-web-apps, python-web-app:wiring-application-config, python-web-app:rendering-untrusted-content, python-llm-features:building-llm-backed-features, python-llm-features:reporting-derived-metrics, claude-api, nextjs-fullstack-standards.
Review lenses: python-library-quality:auditing-python-security, rendering-untrusted-content, verifying-external-behavior, guarding-destructive-operations, designing-python-apis, nextjs-fullstack-standards.
Routed references (Read): <plugin>/skills/dev-bother-me-nope/references/nextjs.md, .../references/nextjs/testing-and-observability.md, docs/reference/prior-implementation-lessons.md, web/AGENTS.md, CLAUDE.md.

Gates
- lint: api `cd api && uv run ruff check . && uv run ruff format --check .`; web `cd web && npx eslint .`
- types: api `cd api && uv run pyright`; web `cd web && npx next typegen && npx tsc --noEmit`
- related: api `cd api && uv run pytest <tests>`; web `cd web && npx vitest related --run <files>`
- test (full): api `uv run pytest --cov`; web `npx vitest run --coverage` then `npx playwright test`
- build: `cd web && npx next build`. Run `npm ci` in web/ first (node_modules absent in a fresh worktree). After API changes: `npm run api:sync`.

UI conventions: web/components.json base-nova, neutral, CSS vars, lucide. Tokens in web/app/globals.css (:root oklch line ~57, .dark ~98; --status-success/progress/waiting/attention/error/locked; chart-1..5). Geist Sans/Mono in app/layout.tsx. next-themes defaultTheme=system. components/ui = shadcn CLI only; shared in components/common (kpi-card, data-table, status-badge, money, empty-state, error-alert, history-timeline, live-indicator, lock-banner, llm-chat + llm-chat/ parts). Feature dirs: config, exceptions, flow, items, reports, shell. recharts installed. API access via lib/api/client `api()`; types from lib/api/openapi.json.

Existing screens: /flow, /flow/[stage], /exceptions, /items/[id], /reports, /config, /signed-out, /auth/*. Existing API routers of interest: chat.py, reports.py, llm_usage.py.
New: progress dashboard, assistant chat (aix-payroll-compare style, D:\AIX-Payroll-Compare webapp/), failed-receipt image submission (new API router + intake path + Next proxy route), app shell/theme.

Release: api/pyproject.toml version 0.1.0 (source of truth), no changelog, no git tags, no GitHub releases; image tag = version.
