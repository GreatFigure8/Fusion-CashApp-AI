#!/usr/bin/env bash
# migrate.sh <env> <image_ref>: run `alembic upgrade head` against the env's ATP, inside its VCN.
# Migrations run before the rollout and never at application start.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ $# -eq 2 ]] || die "usage: migrate.sh <env> <image_ref>"
env_name="$1"; image_ref="$2"
validate_env "$env_name"

run_in_vcn="${RUN_IN_VCN:-$(dirname "${BASH_SOURCE[0]}")/run_in_vcn.sh}"
log "applying migrations to $env_name with $image_ref"
# The migration container alone gets the legacy variables the s48 seed reads (output migration_env).
RUN_IN_VCN_ENV_OUTPUT=migration_env "$run_in_vcn" "$env_name" "$image_ref" -- alembic upgrade head
