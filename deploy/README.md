# Release and deploy to OCI

Releases ship to OCI Ashburn (`us-ashburn-1`) only. The pipeline is `.github/workflows/release.yml`, a
`workflow_dispatch` workflow with no other trigger. It is never run during a BMN run: the BMN release step
runs it, and only after Jonathan says "release". Never during a BMN run, never from a feature branch.

## One-command release

```bash
deploy/release.sh --env dev  --version 0.1.0
deploy/release.sh --env prod --version 0.1.0                          # fusion_write_enabled defaults to false
deploy/release.sh --env prod --version 0.1.0 --fusion-write-enabled  # explicit opt-in to Fusion writes
```

`release.sh` dispatches the workflow (prod from `main`, dev from `dev`), watches it, downloads the
`release-record-<env>` artifact into `deploy/releases/<env>.json` and commits it locally. It never pushes:
`dev` and `main` are protected, so the record goes up with the release branch.

The version must equal `[project].version` in `api/pyproject.toml` (`/health` reports it, which is how smoke
proves the new image is serving). Bump it before releasing.

## What a deploy does

1. Check the version, then build and push `cashapp-<env>/api` and `cashapp-<env>/web` to
   `iad.ocir.io/<namespace>/`, tagged `<version>` and the full git sha. A version tag is immutable.
2. Prod only: `check_migrations_on_dev.sh` reads DEV's live Alembic revision and aborts unless the head being
   released is already applied on DEV.
3. `alembic upgrade head` against the target ATP, in an ephemeral Container Instance inside the VCN.
4. Roll out: `terraform apply` of `infra/envs/<env>` with `-var image_tag=<tag> -var fusion_write_enabled=<bool>`.
   This recreates the api, every worker group and the web container instances.
5. Smoke (`smoke.sh`): `/health` on api (and its version), `/readyz` on every worker group, web `/` is 200 or 302.
   A failure fails the job and the release is not recorded.
6. Record the release in `deploy/releases/<env>.json` (`previous` takes the old `current`).

One API image runs everything Python: `uvicorn cashapp.main:app` for the API, and
`python -m cashapp.workers run --roles <csv>` for each worker group in `deploy/worker-groups.json`.

## Rollback

```bash
deploy/release.sh --env prod --rollback               # back to previous in deploy/releases/prod.json
deploy/release.sh --env prod --rollback --to 0.0.9    # back to an explicit image tag
```

A rollback redeploys the earlier image tags and runs no migrations. Migrations are forward-only; a schema
change that must be undone is a new migration released the normal way.

## Environments and secrets

Create GitHub environments `dev` and `prod`, each with these secrets (API-key auth for the OCI CLI):

`OCI_CLI_USER`, `OCI_CLI_TENANCY`, `OCI_CLI_FINGERPRINT`, `OCI_CLI_KEY_CONTENT`, `OCIR_NAMESPACE`,
`OCIR_USERNAME`, `OCIR_AUTH_TOKEN`, `TF_STATE_ACCESS_KEY`, `TF_STATE_SECRET_KEY`.

`prod` has required reviewers and a deployment-branch rule of `main` only; the workflow also refuses prod
from any other ref. No application secret lives in the images or in GitHub: the containers get `vault:<ocid>`
references from Terraform and read OCI Vault at runtime. GitHub OIDC to OCI is a later improvement.

## Fusion writes

`fusion_write_enabled` defaults to false and sets `CASHAPP_FUSION__WRITE_ENABLED` on the workers. Turning it
on for prod is an explicit input on each release (`--fusion-write-enabled`).

## First-time bootstrap

1. Apply `infra/` once by hand for the env so the state bucket, OCIR repositories and network exist.
2. Create the GitHub environments and secrets above.
3. Release `dev` first; the first DEV run is what proves the container-instance recreate and the OCI CLI
   commands in `scripts/run_in_vcn.sh`.

## New worker roles

Every role found by `python -m cashapp.workers roles` must appear in exactly one group in
`deploy/worker-groups.json`; a role missing there is a role that never gets deployed.
