# Plan: s44-release-deploy-pipeline

Issue #44. Wave 4. Owns `.github/workflows/release.yml`, `deploy/`, `api/Dockerfile`, `web/Dockerfile`
(plus their dockerignore files). No migration, no application code. Nothing here is run during the
BMN run: the workflow is `workflow_dispatch` only and is triggered by the BMN release step after
Jonathan says "release".

## Shape of the release (decisions)

1. **One API image** (`cashapp-api`) runs the API (`uvicorn cashapp.main:app`), every worker role
   group (`python -m cashapp.workers run --roles <csv>`, s30) and one-shot jobs (`alembic upgrade
   head`, `alembic current`, worker smoke). One web image (`cashapp-web`, Next.js standalone).
2. **Rollout is a Terraform apply of the target env** (`infra/envs/<env>`, s25) with
   `-var image_tag=<tag> -var fusion_write_enabled=<bool>`. Container Instances are recreated by
   Terraform with the new image and env, and the LB backends follow. Chosen over "mutable tag +
   restart" because (a) it is unverified that a Container Instance restart re-pulls a tag, and
   (b) the Fusion `write_enabled` input is an env var, which a restart cannot change. s25 states
   apply is the release step's job only; this is that step.
3. **Anything that needs the private network runs inside the VCN** as an ephemeral Container
   Instance launched from the API image (`deploy/scripts/run_in_vcn.sh`): ATP and the worker
   `/readyz` ports are private (s25), so a GitHub-hosted runner cannot reach them. The script
   creates the instance, waits for the container to exit, prints its logs, returns its exit code
   and always deletes the instance (`trap`).
4. **OCI auth: protected GitHub environment secrets** (API-key auth for the OCI CLI, an OCIR auth
   token, Terraform state keys), one set per GitHub environment `dev` / `prod`. `prod` has
   required reviewers configured in GitHub; the job declares `environment: ${{ inputs.environment }}`.
   GitHub OIDC to OCI (identity-domain token exchange) is noted as a later improvement; it is not
   verified on this tenancy, so not used.
5. **Image naming is deterministic** so the build never needs Terraform output:
   `iad.ocir.io/${OCIR_NAMESPACE}/cashapp-<env>/api` and `.../web`, tagged `<version>` and
   `<git sha>` (full 40-char sha). Prod releases promote nothing from dev: they build from the
   dispatched ref (must be `refs/heads/main` for prod).
6. **Release record** `deploy/releases/<env>.json` is rewritten by `record_release.py` at the end
   of every successful deploy or rollback (`previous` ← old `current`), uploaded as workflow
   artifact `release-record-<env>`, and committed by `deploy/release.sh` (the one command the BMN
   release step runs) into the release branch. The workflow itself has `contents: read` only;
   it never pushes (dev/main are protected).

## Standards followed

- CLAUDE.md non-negotiable 8 (OCI Ashburn only: `iad.ocir.io`, `OCI_CLI_REGION=us-ashburn-1`,
  no Vercel/Supabase); *Working with BMN → Deploys / Database* (prod gets only migrations already
  applied on DEV; nothing deploys before "release"; no ad-hoc DDL: migrations only via Alembic);
  *Fusion* (`CASHAPP_FUSION__WRITE_ENABLED` defaults false; prod writes are an explicit input).
- `python-web-app:building-python-web-apps` DEPLOYMENT: one image, web/worker/migrate are
  different commands; uv two-stage sync for layer caching; non-root; `--proxy-headers`;
  migrations run pre-rollout, never at app start.
- s27 env naming (`CASHAPP_*`, `__` nesting); secrets are `vault:<ocid>` refs set by s25 on the
  container instances, so no image and no workflow ever holds an app secret.
- `nextjs-fullstack-standards` / BMN nextjs reference: `output: "standalone"` (s01 already sets it),
  no secrets in `NEXT_PUBLIC_*`, server secrets read at runtime.
- GitHub Actions hygiene (`python-library-quality:running-github-actions-efficiently`): Linux
  runner, every `uses:` pinned to a full commit SHA with a `# vX.Y.Z` comment, `permissions:
  contents: read`, per-environment `concurrency` with `cancel-in-progress: false` (never cancel a
  half-done release).
- DRY: s26's `api/tests/support/workflows.py` is reused for YAML loading; worker role groups are
  defined once in `deploy/worker-groups.json` and consumed by both s25 (Terraform `for_each`) and
  this workflow.
- Shell: `#!/usr/bin/env bash`, `set -euo pipefail`, every script sources `deploy/scripts/lib.sh`
  (logging, `require_cmd`, `die`), external commands overridable via env for tests (`OCI`, `TERRAFORM`,
  `DOCKER`, `CURL`, `GH`, `RUN_IN_VCN`), no `eval`, all inputs validated against regexes before use.

## Files to touch (all new, owned by this story)

| Path | Purpose |
|---|---|
| `api/Dockerfile` | multi-stage: `builder` = `ghcr.io/astral-sh/uv:<pinned>-python3.12-bookworm-slim`, `uv sync --frozen --no-dev --no-install-project` then source + `uv sync --frozen --no-dev --no-editable`; `runtime` = `python:3.12-slim-bookworm` (pinned patch tag), `apt-get install --no-install-recommends curl ca-certificates` (worker smoke), copies `/app/.venv`, `api/alembic.ini`, `api/alembic/`, `deploy/scripts/smoke.sh` → `/app/deploy/smoke.sh`; `useradd -u 10001 app`; `USER 10001`; `ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1`; `WORKDIR /app`; `EXPOSE 8000 8081`; no `ENTRYPOINT`; `CMD ["uvicorn","cashapp.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips","*"]`. Only build args: `VERSION`, `GIT_SHA` (OCI labels). Build context = repo root (`docker buildx build -f api/Dockerfile .`). |
| `api/Dockerfile.dockerignore` | BuildKit per-Dockerfile ignore: `**`, then `!api/pyproject.toml !api/uv.lock !api/README* !api/src/** !api/alembic.ini !api/alembic/** !deploy/scripts/smoke.sh`; and `**/.env*`, `**/__pycache__`, `**/.venv` |
| `web/Dockerfile` | `deps` (`node:22-bookworm-slim` pinned, `npm ci`), `builder` (`npx next build`, `NEXT_TELEMETRY_DISABLED=1`), `runtime` (same base, `useradd -u 10001 nextjs`, copies `.next/standalone`, `.next/static`, `public`; `USER 10001`; `ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0`; `EXPOSE 3000`; `CMD ["node","server.js"]`). Build args: `VERSION`, `GIT_SHA` only. Context `web/`. |
| `web/.dockerignore` | `node_modules`, `.next`, `.env*` (incl. `.env.test`), `coverage`, `playwright-report`, `test-results`, `e2e`, `tests` |
| `.github/workflows/release.yml` | the release workflow (below) |
| `deploy/README.md` | one-command release, rollback, environment secrets, first-time bootstrap, prod approval, write_enabled |
| `deploy/release.sh` | the one command: `deploy/release.sh --env dev\|prod --version X.Y.Z [--fusion-write-enabled] [--rollback [--to TAG]]` → `gh workflow run release.yml --ref <dev\|main> -f …`, finds the run id, `gh run watch --exit-status`, `gh run download -n release-record-<env> -D deploy/releases`, `git add deploy/releases/<env>.json && git commit` (no push) |
| `deploy/worker-groups.json` | `{"groups": {"<group>": ["role", …]}}`, groups `intake`, `extraction`, `matching`, `fusion`, `pipeline`; members filled by the coder from `uv run python -m cashapp.workers roles` (see risk 3) |
| `deploy/releases/dev.json`, `deploy/releases/prod.json` | initial `{"environment": "<env>", "current": null, "previous": null, "history": []}` |
| `deploy/scripts/lib.sh` | `log`, `die`, `require_cmd`, `validate_env` (`^(dev\|prod)$`), `validate_tag` (`^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$`), `image_repo <env> <api\|web>`, `tf_output <env> <name>` (`terraform -chdir=infra/envs/<env> output -raw\|-json`) |
| `deploy/scripts/check_version.sh` | `check_version.sh <version>`: `<version>` equals `[project].version` in `api/pyproject.toml` (a leading `v` is stripped); else exit 1 |
| `deploy/scripts/build_push.sh` | `build_push.sh <env> <version> <sha>`: `docker login iad.ocir.io` (password on stdin from `OCIR_AUTH_TOKEN`), then for api and web `docker buildx build --platform linux/amd64 --build-arg VERSION --build-arg GIT_SHA -t <repo>:<version> -t <repo>:<sha> --push`; refuses to overwrite an existing `<version>` tag (`docker buildx imagetools inspect` succeeds → exit 1) |
| `deploy/scripts/tf_init.sh` | `tf_init.sh <env>`: `terraform -chdir=infra/envs/<env> init -input=false` with the S3-compatible backend creds from `TF_STATE_ACCESS_KEY`/`TF_STATE_SECRET_KEY` (exported as `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` for the backend only) |
| `deploy/scripts/run_in_vcn.sh` | `run_in_vcn.sh <env> <image_ref> -- <command…>`: reads `job_launch_spec` output, `oci container-instances container-instance create … --wait-for-state ACTIVE`, polls the container until `lifecycle-state` is `INACTIVE` (timeout `RUN_IN_VCN_TIMEOUT`, default 900 s), `oci container-instances container retrieve-logs`, exit with the container's `exit-code`; `trap` deletes the instance on every exit path |
| `deploy/scripts/check_migrations_on_dev.sh` | `check_migrations_on_dev.sh <image_ref>`: `dev_rev` = last revision id from `run_in_vcn.sh dev <image_ref> -- alembic current` (dev env's launch spec, so DEV ATP settings); `target` = `alembic heads` run offline in `api/` (must be exactly one head); `applied` = revision ids from `alembic history -r base:<dev_rev>`; abort (exit 1, message naming the missing revisions from `alembic history -r <dev_rev>:<target>`) unless `target ∈ applied`. Missing `dev_rev` (empty DEV) → abort |
| `deploy/scripts/migrate.sh` | `migrate.sh <env> <image_ref>`: `run_in_vcn.sh <env> <image_ref> -- alembic upgrade head` |
| `deploy/scripts/rollout.sh` | `rollout.sh <env> <tag> <fusion_write_enabled:true\|false>`: verifies both `<repo>:<tag>` images exist (`imagetools inspect`), `tf_init.sh`, `terraform plan -input=false -out=release.tfplan -var image_tag=<tag> -var fusion_write_enabled=<bool>`, writes `terraform show -no-color` summary to `$GITHUB_STEP_SUMMARY` when set, `terraform apply -input=false release.tfplan` |
| `deploy/scripts/smoke.sh` | POSIX sh (also runs inside the API image): `smoke.sh [--api URL --expect-version V] [--web URL] [--worker URL]… [--attempts N --delay S]`; api `GET <URL>/health` 200 and JSON `version == V`; web `GET <URL>/` status 200 or 302 (no redirect follow); worker `GET <URL>/readyz` 200; retries each check up to N (default 20) with delay S (default 15); exit 1 naming every failed check |
| `deploy/scripts/smoke_env.sh` | `smoke_env.sh <env> <expected_version> <api_image_ref>`: runner-side api/web checks against `api_lb_url`/`web_lb_url` outputs; worker checks via `run_in_vcn.sh <env> <api_image_ref> -- /app/deploy/smoke.sh --worker <url>…` from `worker_health_urls` |
| `deploy/scripts/record_release.py` | stdlib only, Python 3.12: `record_release.py record <env> --action deploy\|rollback --version V --sha S --run-id R [--path DIR]` (previous ← current, current ← new entry with `deployed_at` UTC ISO-8601, history newest-first capped at 20); `record_release.py previous <env> [--path DIR]` prints `previous.version` or exits 1 if none |
| `api/tests/deploy/__init__.py` | package marker |
| `api/tests/deploy/test_dockerfiles.py` | AC1 tests |
| `api/tests/deploy/test_release_workflow.py` | AC2/AC3/AC4/AC5 workflow-shape tests |
| `api/tests/deploy/test_deploy_scripts.py` | AC3/AC4/AC5 script behaviour tests with stubbed CLIs |
| `api/tests/deploy/test_deploy_readme.py` | AC6 |
| `api/tests/support/deploy_stubs.py` | `stub_bin(tmp_path, name, script) -> Path`, `run_script(path, *args, env) -> CompletedProcess`, `calls(tmp_path, name) -> list[list[str]]` (each stub appends its argv as one JSON line to `<tmp>/calls/<name>.jsonl`) |

File-disjoint: s25 owns `infra/`, s26 owns `ci-*.yml` and `api/tests/support/workflows.py` (reused,
not edited), s01 owns `next.config.ts`/lockfiles (read only), s30 owns `cashapp/workers/` (read only).

## `.github/workflows/release.yml` (pinned shape)

```yaml
name: release
on:
  workflow_dispatch:
    inputs:
      version:              { description: "Release version (= api/pyproject.toml version)", required: true, type: string }
      environment:          { required: true, type: choice, options: [dev, prod] }
      action:               { required: true, type: choice, options: [deploy, rollback], default: deploy }
      rollback_to:          { description: "Image tag to roll back to; empty = previous in deploy/releases/<env>.json", required: false, type: string, default: "" }
      fusion_write_enabled: { description: "Set CASHAPP_FUSION__WRITE_ENABLED on workers", required: false, type: boolean, default: false }
permissions:
  contents: read
concurrency:
  group: release-${{ inputs.environment }}
  cancel-in-progress: false
jobs:
  release:
    runs-on: ubuntu-24.04
    environment: ${{ inputs.environment }}
    timeout-minutes: 90
    env:
      OCI_CLI_REGION: us-ashburn-1
      OCI_CLI_USER: ${{ secrets.OCI_CLI_USER }}
      OCI_CLI_TENANCY: ${{ secrets.OCI_CLI_TENANCY }}
      OCI_CLI_FINGERPRINT: ${{ secrets.OCI_CLI_FINGERPRINT }}
      OCI_CLI_KEY_CONTENT: ${{ secrets.OCI_CLI_KEY_CONTENT }}
      OCIR_NAMESPACE: ${{ secrets.OCIR_NAMESPACE }}
      OCIR_USERNAME: ${{ secrets.OCIR_USERNAME }}
      OCIR_AUTH_TOKEN: ${{ secrets.OCIR_AUTH_TOKEN }}
      TF_STATE_ACCESS_KEY: ${{ secrets.TF_STATE_ACCESS_KEY }}
      TF_STATE_SECRET_KEY: ${{ secrets.TF_STATE_SECRET_KEY }}
      ENV_NAME: ${{ inputs.environment }}
      VERSION: ${{ inputs.version }}
    steps:
      - name: Guard prod ref            # prod only from main
        if: inputs.environment == 'prod'
        run: test "$GITHUB_REF" = "refs/heads/main" || { echo "prod releases run from main only"; exit 1; }
      - uses: actions/checkout@<sha>    # vX
      - uses: actions/setup-python@<sha>   # 3.12 (record_release.py)
      - uses: astral-sh/setup-uv@<sha>     # offline alembic heads/history in check_migrations_on_dev
      - uses: hashicorp/setup-terraform@<sha>   # terraform_wrapper: false
      - uses: docker/setup-buildx-action@<sha>
      - name: Install OCI CLI
        run: pipx install oci-cli==<pinned>
      - name: Check version
        if: inputs.action == 'deploy'
        run: deploy/scripts/check_version.sh "$VERSION"
      - name: Build and push images
        if: inputs.action == 'deploy'
        run: deploy/scripts/build_push.sh "$ENV_NAME" "$VERSION" "$GITHUB_SHA"
      - name: Init Terraform
        run: deploy/scripts/tf_init.sh "$ENV_NAME"
      - name: Check migrations are applied on DEV
        if: inputs.action == 'deploy' && inputs.environment == 'prod'
        run: deploy/scripts/tf_init.sh dev && deploy/scripts/check_migrations_on_dev.sh "iad.ocir.io/$OCIR_NAMESPACE/cashapp-prod/api:$VERSION"
      - name: Migrate
        if: inputs.action == 'deploy'
        run: deploy/scripts/migrate.sh "$ENV_NAME" "iad.ocir.io/$OCIR_NAMESPACE/cashapp-$ENV_NAME/api:$VERSION"
      - name: Resolve tag
        id: tag
        env: { ROLLBACK_TO: "${{ inputs.rollback_to }}", ACTION: "${{ inputs.action }}" }
        run: … # deploy → $VERSION; rollback → $ROLLBACK_TO or `record_release.py previous $ENV_NAME`; writes tag=… to $GITHUB_OUTPUT
      - name: Roll out
        run: deploy/scripts/rollout.sh "$ENV_NAME" "${{ steps.tag.outputs.tag }}" "${{ inputs.fusion_write_enabled }}"
      - name: Smoke
        run: deploy/scripts/smoke_env.sh "$ENV_NAME" "${{ steps.tag.outputs.tag }}" "iad.ocir.io/$OCIR_NAMESPACE/cashapp-$ENV_NAME/api:${{ steps.tag.outputs.tag }}"
      - name: Record release
        run: python deploy/scripts/record_release.py record "$ENV_NAME" --action "${{ inputs.action }}" --version "${{ steps.tag.outputs.tag }}" --sha "$GITHUB_SHA" --run-id "$GITHUB_RUN_ID"
      - uses: actions/upload-artifact@<sha>
        with: { name: "release-record-${{ inputs.environment }}", path: "deploy/releases/${{ inputs.environment }}.json" }
```

Every input reaches `run:` through `env:` or a validated script argument; inputs are never
interpolated into shell text other than the two boolean/choice values above, and scripts validate
every argument (`validate_env`, `validate_tag`, version regex). No step has `continue-on-error`;
no step uses `if: always()`, so a smoke failure fails the job and skips the record.

## Interfaces provided (pinned)

- **Image contract.** `iad.ocir.io/<ns>/cashapp-<env>/api:<tag>` and `…/web:<tag>`, `<tag>` ∈
  {release version, 40-char git sha}. API image: default command serves the API on 8000; workers
  run `python -m cashapp.workers run --roles <csv>` (health on `CASHAPP_WORKER__HEALTH_PORT`,
  default 8081); one-shot `alembic upgrade head` / `alembic current` work from `WORKDIR /app`;
  `/app/deploy/smoke.sh` present. Web image: `node server.js` on 3000. Both run as uid 10001 and
  read all configuration from runtime env (s27 names, `vault:` refs).
- **`deploy/worker-groups.json`** (single source for s25's worker instances):
  `{"groups": {"<name matching ^[a-z][a-z0-9-]{0,20}$>": ["<role>", …]}}`; each role appears in
  exactly one group; the instance command is `python -m cashapp.workers run --roles <","-joined>`.
  Groups with an empty list get no instance.
- **`deploy/releases/<env>.json`**:
  ```json
  {"environment": "dev|prod",
   "current":  {"version": "str", "sha": "str", "action": "deploy|rollback", "run_id": "str", "deployed_at": "ISO-8601 UTC"} | null,
   "previous": { same } | null,
   "history":  [ same, … newest first, ≤ 20 ]}
  ```
- **Required from s25 (`infra/envs/<env>`)**, pinned here because s25 has no plan yet:
  - variables `image_tag` (string, no default) and `fusion_write_enabled` (bool, default `false`),
    mapped to every container's image `iad.ocir.io/<ns>/cashapp-<env>/{api,web}:${var.image_tag}`
    and to `CASHAPP_FUSION__WRITE_ENABLED` on worker containers;
  - OCIR repos named `cashapp-<env>/api` and `cashapp-<env>/web`;
  - worker container instances `for_each` over non-empty groups of
    `jsondecode(file("${path.root}/../../../deploy/worker-groups.json")).groups`;
  - outputs: `api_lb_url` (string, `https://…`), `web_lb_url` (string), `worker_health_urls`
    (map group → `http://<private-ip>:8081`), `container_instance_ids` (map), and
    `job_launch_spec` (object: `compartment_id`, `availability_domain`, `subnet_id`, `shape`,
    `ocpus`, `memory_in_gbs`, `environment` (map of the same non-secret `CASHAPP_*` env and
    `vault:` refs the workers get)), plus the s25 AC6 outputs;
  - the IAM dynamic group matches every `computecontainerinstance` in the env compartment, so the
    ephemeral job instances can read Vault secrets;
  - backend: S3-compatible OCI Object Storage, credentials from `AWS_ACCESS_KEY_ID` /
    `AWS_SECRET_ACCESS_KEY`, state keys `dev/terraform.tfstate`, `prod/terraform.tfstate` in one
    bucket.
- **GitHub environments** `dev` and `prod` with secrets `OCI_CLI_USER`, `OCI_CLI_TENANCY`,
  `OCI_CLI_FINGERPRINT`, `OCI_CLI_KEY_CONTENT`, `OCIR_NAMESPACE`, `OCIR_USERNAME`,
  `OCIR_AUTH_TOKEN`, `TF_STATE_ACCESS_KEY`, `TF_STATE_SECRET_KEY`; `prod` has required reviewers
  and a deployment-branch rule of `main` only (documented in README; configured by Jonathan).

## Migrations

None. Expected Alembic parent: unchanged (this story adds no revision).

## TEST PLAN

All `[unit]`, no network, no Docker daemon unless marked. Scripts are executed with `bash` (Git Bash
on Windows, bash on Linux) with stub `oci`, `terraform`, `docker`, `curl`, `gh`, `alembic`/`uv`
binaries placed first on `PATH` by `api/tests/support/deploy_stubs.py`; workflow YAML is read
with s26's `load_workflow` / `workflow_triggers` / `iter_steps`.

| AC | Test | Asserts |
|---|---|---|
| 1 | `api/tests/deploy/test_dockerfiles.py::test_api_dockerfile_is_multistage_uv_nonroot` | ≥ 2 `FROM`; builder `FROM ghcr.io/astral-sh/uv:` with an exact tag; `uv sync --frozen --no-dev`; final stage has `USER` that is neither `root` nor `0`; no `ENTRYPOINT`; `CMD` runs `uvicorn cashapp.main:app` |
| 1 | `…::test_api_image_carries_worker_and_migration_commands` | final stage copies `.venv`, `alembic.ini`, `alembic/`, `smoke.sh`; `PATH` includes `/app/.venv/bin`; `deploy/README.md` and `worker-groups.json` command template use `python -m cashapp.workers run --roles` on the same `…/api:` image |
| 1 | `…::test_web_dockerfile_is_standalone_nonroot` | multi-stage; copies `.next/standalone` and `.next/static`; final `USER` non-root; `CMD ["node","server.js"]`; `web/next.config.ts` contains `output: "standalone"` |
| 1 | `…::test_dockerfiles_bake_no_secrets` (parametrised api/web) | every `ARG`/`ENV` name ∈ allowlist (`VERSION`, `GIT_SHA`, `PATH`, `PYTHONUNBUFFERED`, `UV_*`, `NODE_ENV`, `PORT`, `HOSTNAME`, `NEXT_TELEMETRY_DISABLED`); no name matching `SECRET|PASSWORD|TOKEN|KEY|DSN|CREDENTIAL`; no `NEXT_PUBLIC_`; no `COPY`/`ADD` of `.env*`; no `--secret` needed |
| 1 | `…::test_dockerignores_exclude_env_and_build_junk` | `api/Dockerfile.dockerignore` starts with `**` deny-all and re-includes only the listed paths; both ignore `.env*`; web ignores `node_modules`, `.next`, `.env*` |
| 1 | `…::test_worker_groups_cover_every_discovered_role_once` | groups parse to the pinned schema; names match the regex; roles disjoint; union == `discover_roles().keys()` (s30) |
| 1 | `…::test_images_build_without_build_secrets` (`@pytest.mark.live`, deselected by default) | `docker buildx build` of both images with only `VERSION`/`GIT_SHA` succeeds; `docker run --rm <api> id -u` ≠ 0 |
| 2 | `api/tests/deploy/test_release_workflow.py::test_release_triggers_only_on_workflow_dispatch` | `workflow_triggers(wf).keys() == {"workflow_dispatch"}`; none of `push`, `pull_request`, `pull_request_target`, `schedule`, `workflow_run`, `release` |
| 2 | `…::test_release_inputs_contract` | `version` required string; `environment` choice `[dev, prod]`; `action` choice `[deploy, rollback]` default `deploy`; `rollback_to` optional string default `""`; `fusion_write_enabled` boolean default `False` |
| 3 | `…::test_deploy_steps_run_in_order` | `run` steps (in order) reference `check_version.sh`, `build_push.sh`, `tf_init.sh`, `check_migrations_on_dev.sh`, `migrate.sh`, `rollout.sh`, `smoke_env.sh`, `record_release.py record`; then `upload-artifact` with name `release-record-${{ inputs.environment }}` |
| 3 | `…::test_migration_check_is_prod_only_and_before_migrate` | `check_migrations_on_dev` step `if` contains `inputs.environment == 'prod'` and `inputs.action == 'deploy'`; its index < migrate's index |
| 3 | `…::test_smoke_failure_fails_job_and_skips_record` | no step or job has `continue-on-error`; no `if:` contains `always()`/`failure()`/`cancelled()` |
| 3 | `api/tests/deploy/test_deploy_scripts.py::test_build_push_tags_version_and_sha_for_api_and_web` | stub docker: login to `iad.ocir.io` with password on stdin (token never in argv); two `buildx build --push` calls with `-t iad.ocir.io/ns/cashapp-dev/{api,web}:1.2.3` and `:<sha>`; api uses `-f api/Dockerfile .`, web context `web` |
| 3 | `…::test_build_push_refuses_existing_version_tag` | `imagetools inspect` stub succeeds → exit 1, no build call |
| 3 | `…::test_check_version_matches_pyproject` | `0.1.0`/`v0.1.0` pass against a tmp pyproject; `0.2.0` exits 1 |
| 3 | `…::test_check_migrations_passes_when_head_applied_on_dev` | stub `RUN_IN_VCN` prints `abc123 (head)`; stub alembic history `base:abc123` lists target head → exit 0 |
| 3 | `…::test_check_migrations_aborts_when_revision_missing_on_dev` | dev at older rev → exit 1, stderr names the missing revision(s); also aborts on empty `alembic current` and on two heads |
| 3 | `…::test_migrate_runs_alembic_upgrade_inside_vcn` | stub `RUN_IN_VCN` receives `<env> <image> -- alembic upgrade head` |
| 3 | `…::test_run_in_vcn_returns_exit_code_and_always_deletes` | stub `oci`: create → ACTIVE, container INACTIVE with `exit-code` 3 → script exits 3, prints logs, and the delete call is recorded; also deleted when the poll times out |
| 3 | `…::test_rollout_plans_and_applies_with_tag_and_write_flag` | stub terraform: `init`, `plan … -var image_tag=1.2.3 -var fusion_write_enabled=false -out=release.tfplan`, `apply release.tfplan`; images verified first; missing image → exit 1 before terraform |
| 3 | `…::test_smoke_passes_on_health_ready_and_web_200_or_302` | stub curl: api 200 with `{"status":"ok","version":"1.2.3"}`, worker `/readyz` 200, web 302 → exit 0 |
| 3 | `…::test_smoke_fails_on_bad_status_or_version` (parametrised: api 503, version mismatch, web 500, worker 503) | exit 1 after `--attempts 2 --delay 0`; stderr names the failed check |
| 4 | `test_release_workflow.py::test_rollback_skips_build_and_migrations` | `check_version`, `build_push`, `check_migrations_on_dev`, `migrate` steps all carry `inputs.action == 'deploy'` in `if`; `rollout`, `smoke`, `record` carry no action condition |
| 4 | `test_deploy_scripts.py::test_resolve_tag_uses_rollback_to_or_previous` | executing the `Resolve tag` step's `run` text (extracted from the YAML) with `ACTION=rollback ROLLBACK_TO=1.1.0` → `tag=1.1.0`; with empty `ROLLBACK_TO` and a record whose `previous.version` is `1.0.9` → `tag=1.0.9`; no previous → exit 1; `ACTION=deploy` → `$VERSION` |
| 4 | `…::test_record_release_shifts_current_to_previous` | `record` twice on a tmp dir → `previous` = first entry, `current` = second, `history` newest-first, `deployed_at` UTC; history capped at 20; initial committed `deploy/releases/{dev,prod}.json` match the empty schema |
| 4 | `…::test_rollback_runs_no_migration` | running the scripts the rollback path calls (rollout + smoke_env with stubs) records no `alembic` or `RUN_IN_VCN … alembic` call |
| 5 | `test_release_workflow.py::test_release_job_uses_environment_protection_and_prod_ref_guard` | job `environment == "${{ inputs.environment }}"`; first step is the prod guard with `if: inputs.environment == 'prod'` checking `refs/heads/main` |
| 5 | `…::test_release_auth_from_environment_secrets_only` | `permissions == {"contents": "read"}` (no `id-token`, no write); every `secrets.X` ∈ the pinned nine; `OCI_CLI_REGION == "us-ashburn-1"`; raw text has no other region string, no `vercel`/`supabase`/`ocir.io` host other than `iad.ocir.io` |
| 5 | `…::test_fusion_write_enabled_defaults_false_and_reaches_rollout` | input default `False`; the rollout step passes `inputs.fusion_write_enabled`; `rollout.sh` rejects any value other than `true`/`false` |
| 5 | `…::test_actions_pinned_to_commit_sha` | every `uses:` matches `^[\w.-]+/[\w.-]+@[0-9a-f]{40}$` |
| 5 | `…::test_release_concurrency_never_cancels` | `concurrency.group` contains `inputs.environment`; `cancel-in-progress is False` |
| 6 | `api/tests/deploy/test_deploy_readme.py::test_readme_documents_one_command_release_and_rollback` | README contains `deploy/release.sh --env prod --version`, a `--rollback` example (with and without `--to`), the nine secret names, "required reviewers", `fusion_write_enabled` default false, and "never during a BMN run" |
| 6 | `test_deploy_scripts.py::test_release_sh_dispatches_watches_and_records` | stub gh: `workflow run release.yml --ref main -f version=1.2.3 -f environment=prod -f action=deploy -f fusion_write_enabled=false`, then `run watch <id> --exit-status`, then `run download <id> -n release-record-prod`; stub git `commit` called; no `git push`; `--env prod` from a ref other than main still dispatches with `--ref main` |

## Risks and assumptions

1. **Container Instances via Terraform recreate.** Each rollout replaces instances (brief
   downtime per instance; LB health checks cover api/web). Accepted for a 3-workload system;
   s25's LB backend set must follow the new private IPs (Terraform does). Unverified against
   live; first release on DEV proves it.
2. **Ephemeral job instances** (`run_in_vcn.sh`) depend on s25's `job_launch_spec` output and the
   dynamic-group rule. If s25 lands a different output name, the merger aligns it to this pin.
   OCI CLI command/flag names (`container-instances container-instance create`, `container
   retrieve-logs`, `exit-code`) must be confirmed with `oci … --help` on the pinned CLI version
   before coding; recorded as VERIFY.
3. **Worker group membership** is filled from the roles discoverable when the coder runs (waves
   1–3). Wave-5 stations (apply, write-back, …) add roles later; the coverage test then fails until
   `deploy/worker-groups.json` assigns them. That failure is intended (no role silently left
   undeployed); the merger/fixer of the later story adds the role to the right group.
4. **Release record lives in git, written by `release.sh`.** The workflow cannot push (protected
   branches, `contents: read`). If the BMN release step skips `release.sh`, the record goes stale;
   `rollback_to` explicit always works.
5. **DEV migration check reads DEV's live `alembic_version`** via an ephemeral instance in the dev
   env, so the prod job needs dev Terraform state read access (same state bucket keys). Linear
   Alembic chain (research.md: exactly one head) makes "target ∈ history(base:dev_rev)" a complete
   check.
6. **`check_version.sh` ties the release version to `api/pyproject.toml`** so `/health.version`
   proves the new image is serving; the BMN release step bumps the version before dispatch.
7. **Web build without env.** `next build` must not require runtime secrets; if a page reads env at
   import time the build fails, which is the desired signal (secrets never become build args).
   `web/public` must exist (s01 scaffold keeps it); the coder adds `.gitkeep` only if absent and
   notes it.
8. **Windows test host.** Script tests need `bash` on PATH (Git Bash present on this machine);
   `record_release.py` is run with `sys.executable`. jq is not used anywhere.
9. **OIDC deviation.** AC5 allows "OIDC or a protected environment secret"; secrets chosen because
   OCI workload-identity federation for GitHub is not verified on this tenancy.
10. **Stub `alembic`.** `check_migrations_on_dev.sh` calls `uv run alembic` in `api/` through an
    `ALEMBIC` override so tests stub it; the real call needs no DB (`heads`/`history` read only the
    script directory, not `env.py`).
