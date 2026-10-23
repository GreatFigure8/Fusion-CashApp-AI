# s44-release-deploy-pipeline: Release deploy pipeline to OCI

- Issue: #44
- Wave: 4 (owns `.github/workflows/release.yml`, `deploy/`, `api/Dockerfile`, `web/Dockerfile`)
- breaking: false

## Story

As BMN's release step, I want one reliable, repeatable way to ship to OCI, so that nothing deploys outside it.

## Context

CLAUDE.md *Working with BMN → Deploys*: nothing deploys before Jonathan says "release". This story only writes the pipeline; it is never triggered during the run. Targets are s25's outputs (Container Instances behind a load balancer, OCIR in Ashburn).

## Acceptance criteria

1. [unit] `api/Dockerfile` (multi-stage, uv, non-root, one image used for both API (`uvicorn cashapp.main:app`) and workers (`python -m cashapp.workers run --roles …`)) and `web/Dockerfile` (Next.js standalone output, non-root). Both build without secrets baked in.
2. [unit] `.github/workflows/release.yml` triggers on `workflow_dispatch` only (inputs: `version`, `environment: dev|prod`, `action: deploy|rollback`, `rollback_to`); a test asserts no `push`/`pull_request`/`schedule` triggers.
3. [unit] Deploy job: build and push `api` and `web` images to OCIR Ashburn tagged `<version>` and `<git sha>`; run `alembic upgrade head` against the target ATP (prod only after verifying that every revision being applied is already applied on DEV: `deploy/scripts/check_migrations_on_dev.sh` compares `alembic_version`/history and aborts otherwise); roll out container instances (api, each worker role group, web) to the new tag; run `deploy/scripts/smoke.sh` (`/health` on api, `/readyz` on workers, web home 200/302) and fail the job if smoke fails.
4. [unit] Rollback: `action=rollback` redeploys `rollback_to` image tags without running migrations; the previous tag is recorded per environment in `deploy/releases/<env>.json` by each successful deploy.
5. [unit] OCI auth via GitHub OIDC → OCI or a protected environment secret; the workflow uses GitHub `environment:` protection for prod; Fusion `write_enabled` for prod is an explicit input defaulting to false.
6. [unit] `deploy/README.md` documents the one-command release the BMN release step runs and the rollback.

## Out of scope

Running it; infrastructure definitions (s25); CI gates (s26).

## Deps

- s25-oci-infrastructure — outputs: OCIR repo URLs, container instance OCIDs, LB hostnames, ATP connect secret OCID. plannable (same wave).
- s30-worker-host — worker CLI and `/readyz`. plannable.
- s01-scaffold-monorepo — `/health`, app entry points. plannable.
- s27-settings-secrets-wiring — env/Vault setting names. plannable.

## Assumptions

- One image for API and workers keeps the dependency set single.
