#!/usr/bin/env bash
# tf_init.sh <env>: initialise the Terraform backend (OCI Object Storage, S3-compatible) for infra/envs/<env>.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ $# -eq 1 ]] || die "usage: tf_init.sh <env>"
env_name="$1"
validate_env "$env_name"
[[ -n "${TF_STATE_ACCESS_KEY:-}" ]] || die "TF_STATE_ACCESS_KEY is not set"
[[ -n "${TF_STATE_SECRET_KEY:-}" ]] || die "TF_STATE_SECRET_KEY is not set"
require_cmd "$TERRAFORM"

# The backend reads the S3-style names; they are set for this one command only.
AWS_ACCESS_KEY_ID="$TF_STATE_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$TF_STATE_SECRET_KEY" \
  "$TERRAFORM" -chdir="$(repo_root)/infra/envs/$env_name" init -input=false -reconfigure
