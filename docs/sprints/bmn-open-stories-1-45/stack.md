# Stack
kind: mixed (api/ Python FastAPI+llm, web/ Next.js, infra/ Terraform). ui: true. No Vercel, no Supabase. dev_push_deploys: false.
Skills: python-web-app:building-python-web-apps, python-web-app:wiring-application-config, python-llm-features:building-llm-backed-features, claude-api, nextjs-fullstack-standards.
Reference: C:/Users/opc/.claude/plugins/cache/claude-skills/dev-bother-me-nope/3.3.2/skills/dev-bother-me-nope/references/nextjs.md
Gates api: lint `uv run ruff check . && uv run ruff format --check .`; types `uv run pyright`; related `uv run pytest <files>`; test `uv run pytest --cov`.
Gates web: lint `npx eslint .`; types `npx next typegen && npx tsc --noEmit`; related `npx vitest related --run <files>`; test `npx vitest run --coverage`; build `npx next build`.
Release: manual OCI step (OCIR images, rollout, Alembic to prod ATP) only on Jonathan's "release".
Screens: flow monitor, exception workbench, configuration, chat, reports/daily summary.
See /CLAUDE.md for all architecture rules.
