# s26-ci-gates: CI gates on GitHub Actions for api and web

- Issue: #26
- Wave: 1 (serialized spine, step 6 of 6)
- breaking: false

## Story

As a reviewer, I want every push and PR to `dev` to run the same lint and type-check gates BMN uses, so that broken code can't merge.

## Context

stack.md: `dev_push_deploys: false`. Files owned: `.github/workflows/ci-api.yml`, `.github/workflows/ci-web.yml`. s44 owns `release.yml` separately.

## Acceptance criteria

1. [unit] `ci-api.yml` runs on `pull_request` and `push` to `dev`, path-filtered to `api/**` and the workflow file, with `astral-sh/setup-uv` and uv cache: `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`.
2. [unit] `ci-web.yml` runs on the same triggers, path-filtered to `web/**`, Node LTS with npm cache: `npm ci`, `npx next typegen && npx tsc --noEmit`, `npx eslint .`.
3. [unit] Neither workflow has deploy steps, secrets beyond `GITHUB_TOKEN`, database URLs or OCI credentials; a test (`api/tests/test_ci_workflows.py`) parses both YAML files and asserts: triggers limited to `pull_request`/`push: dev`, no `environment:`, no step mentioning `deploy`, `oci`, `alembic upgrade`, `vercel`, `supabase`.
4. [unit] `permissions: contents: read` at workflow level; `concurrency` cancels superseded runs per ref.

## Out of scope

Running tests in CI (BMN runs tests in its own cycles); release workflow (s44).

## Deps

- s01-scaffold-monorepo — the gate commands in CLAUDE.md *Commands*, lockfiles. plannable.

## Assumptions

- Tests are not part of CI gates now, matching BMN's code gates; adding them is a later decision.
