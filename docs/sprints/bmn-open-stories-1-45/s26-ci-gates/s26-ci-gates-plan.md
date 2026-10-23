# s26-ci-gates plan: CI gates on GitHub Actions for api and web

Issue #26. Wave 1, spine step 6 of 6. Depends on s01 (lockfiles, gate commands, `api/tests/conftest.py`).
No migrations. No secrets. Nothing deploys.

## Files to touch (all new, owned by this story)

| Path | Purpose |
|---|---|
| `.github/workflows/ci-api.yml` | ruff + pyright gate for `api/` |
| `.github/workflows/ci-web.yml` | tsc + eslint gate for `web/` |
| `api/tests/support/__init__.py` | empty package marker (create only if s01/s02 have not; if it exists, leave it alone) |
| `api/tests/support/workflows.py` | shared YAML workflow loader (reused by s44's `release.yml` test, so it exists once) |
| `api/tests/test_ci_workflows.py` | the AC tests (written and run in step 5 only) |

File-disjoint from every other story: s44 owns `.github/workflows/release.yml`; s01 owns the lockfiles,
`pyproject.toml` and the root `conftest.py`. This story edits none of them.

## Standards followed

- `python-library-quality:running-github-actions-efficiently`: `push` scoped to `dev` only, so a PR
  commit is not built twice for the same reason; path filters; top-level `concurrency` with
  `cancel-in-progress: true` (safe: CI writes no external state); built-in setup-* caching keyed on the
  lockfile; Linux runners only (1x); `timeout-minutes` on every job; cheap checks first.
- CLAUDE.md non-negotiables: no deploy, no OCI, no Vercel, no Supabase, no DB. Code gates are lint +
  type-check only; tests are not run in CI (story out of scope).
- `python-web-app:building-python-web-apps` test layout: tests under `api/tests/`, pure functions, no I/O
  beyond reading the repo's own files.

## Workflow content (pinned, coder writes exactly this shape)

### `.github/workflows/ci-api.yml`

```yaml
name: ci-api
on:
  pull_request:
    branches: [dev]
    paths: ["api/**", ".github/workflows/ci-api.yml"]
  push:
    branches: [dev]
    paths: ["api/**", ".github/workflows/ci-api.yml"]
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  gates:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: api
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: "api/uv.lock"
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pyright
```

Python version: uv resolves it from `api/pyproject.toml` `requires-python` / `api/.python-version` (s01).
No `setup-python` step.

### `.github/workflows/ci-web.yml`

```yaml
name: ci-web
on:
  pull_request:
    branches: [dev]
    paths: ["web/**", ".github/workflows/ci-web.yml"]
  push:
    branches: [dev]
    paths: ["web/**", ".github/workflows/ci-web.yml"]
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  gates:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: lts/*
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npx next typegen && npx tsc --noEmit
      - run: npx eslint .
```

Neither file has `env:` with secrets, `environment:`, `secrets.*` references, `id-token` permission or
service containers.

## Interfaces provided

`api/tests/support/workflows.py` (consumed by s44's release-workflow test; pinned):

```python
from pathlib import Path
from typing import Any

REPO_ROOT: Path            # Path(__file__).resolve().parents[3]  (api/tests/support -> repo root)
WORKFLOWS_DIR: Path        # REPO_ROOT / ".github" / "workflows"

def load_workflow(name: str) -> dict[str, Any]:
    """Parse WORKFLOWS_DIR / name with yaml.safe_load. PyYAML (YAML 1.1) reads the
    `on:` key as boolean True; this function renames that key back to "on" so callers
    always use workflow["on"]. Raises FileNotFoundError if absent."""

def workflow_triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return workflow["on"] normalised to a dict: a str becomes {name: None}, a list
    becomes {name: None for name in list}."""

def iter_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Every step of every job, in file order."""

def step_text(step: dict[str, Any]) -> str:
    """Lower-cased concatenation of a step's name, uses, run and the str() of its with/env,
    for forbidden-word scans."""
```

## TEST PLAN (written and run only in step 5)

All in `api/tests/test_ci_workflows.py`, `[unit]`, no network. Mapped 1:1 to the acceptance criteria.

| AC | Test | Asserts |
|---|---|---|
| 1 | `test_ci_api_triggers_and_paths` | triggers are exactly `{pull_request, push}`; `push.branches == ["dev"]`; `pull_request.branches == ["dev"]`; both `paths` contain `api/**` and `.github/workflows/ci-api.yml` and nothing outside `api/` + that file |
| 1 | `test_ci_api_runs_uv_gates_in_order` | a step uses `astral-sh/setup-uv@…` with `enable-cache: true`; the `run` steps are, in order, `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`; job working-directory is `api` |
| 2 | `test_ci_web_triggers_and_paths` | same trigger shape; `paths` contain `web/**` and `.github/workflows/ci-web.yml` only |
| 2 | `test_ci_web_runs_node_gates_in_order` | a step uses `actions/setup-node@…` with `node-version` LTS (`lts/*` or an even major) and `cache: npm`; `run` steps in order `npm ci`, `npx next typegen && npx tsc --noEmit`, `npx eslint .`; working-directory `web` |
| 3 | `test_workflows_have_no_environment` (parametrised over both files) | no `environment:` at workflow or job level |
| 3 | `test_workflows_have_no_forbidden_steps` (parametrised) | no step text contains `deploy`, `oci`, `alembic upgrade`, `vercel`, `supabase` (word-aware for `oci` so `oci` matches as a token, avoiding false hits) |
| 3 | `test_workflows_use_only_github_token` (parametrised) | raw file text has no `secrets.` reference other than `secrets.GITHUB_TOKEN`; no `DATABASE_URL`, `CASHAPP_DB`, `OCI_` keys in any `env:`; no `services:` block |
| 4 | `test_workflows_permissions_contents_read` (parametrised) | top-level `permissions == {"contents": "read"}`; no job overrides `permissions` |
| 4 | `test_workflows_cancel_superseded_runs` (parametrised) | top-level `concurrency.group` contains `github.ref` and `github.workflow`; `cancel-in-progress is True` |

## Migrations

None.

## Risks

- **PyYAML is not a direct dev dependency.** s01 pins the lockfile and later stories must not edit it.
  PyYAML arrives transitively through `uvicorn[standard]`. Assumption: the test imports `yaml` from that
  transitive install. If step 5 finds it missing, the fix is a one-line dev-dep add by the merger
  (`pyyaml`, `types-pyyaml`), recorded as a lockfile exception. `tests/` is outside pyright strict
  (s01 makes strict apply to `src/`), so missing stubs do not fail the type gate; if pyright complains,
  use `import yaml  # pyright: ignore[reportMissingTypeStubs]`.
- **YAML 1.1 `on:` → True.** Handled once in `load_workflow`; tests must never index `wf[True]`.
- **Path filters vs required checks.** If Jonathan later makes `ci-api`/`ci-web` required status checks on
  `dev`, a PR touching only `web/` would leave `ci-api` pending forever. Not configured in this story
  (branch protection is a repo setting, not code). Recorded so whoever adds required checks uses a
  path-independent aggregator job or leaves them non-required.
- **`next typegen`** needs Next.js 15.5+; s01 pins Next. If absent, s01's gate fails first.
- **Docs-only and `docs/sprints/**` changes** trigger neither workflow by design.
- **`oci` forbidden-word scan** could false-positive on words like "associate"; matched as a token
  (`\boci\b`) for that reason.

## Assumptions

- `pull_request` is also limited to base branch `dev` (story says "push and PR to dev"); PRs into `main`
  happen only during release, under s44.
- Actions pinned by major tag (`@v4`, `@v6`), not SHA; SHA pinning is a later hardening decision.
- Node `lts/*` rather than a fixed major, so the gate tracks the current LTS.
- The shared loader lives in `api/tests/support/` so s44 reuses it instead of writing a second YAML
  loader (non-negotiable 7).
