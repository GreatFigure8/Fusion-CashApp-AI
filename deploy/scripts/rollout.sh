#!/usr/bin/env bash
# rollout.sh <env> <tag> <fusion_write_enabled:true|false>
#
# The rollout is a Terraform apply of infra/envs/<env>: container instances are recreated with the
# new image tag and environment, and the load balancer backends follow. A plan is always produced
# first and written to the job summary.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ $# -eq 3 ]] || die "usage: rollout.sh <env> <tag> <fusion_write_enabled:true|false>"
env_name="$1"; tag="$2"; write_enabled="$3"
validate_env "$env_name"
validate_tag "$tag"
validate_bool "$write_enabled"
require_cmd "$DOCKER" "$TERRAFORM"

for kind in api web; do
  repo="$(image_repo "$env_name" "$kind")"
  "$DOCKER" buildx imagetools inspect "$repo:$tag" >/dev/null 2>&1 \
    || die "image $repo:$tag does not exist; nothing was changed"
done

script_dir="$(dirname "${BASH_SOURCE[0]}")"
"$script_dir/tf_init.sh" "$env_name"

tf_dir="$(repo_root)/infra/envs/$env_name"
plan_file="release.tfplan"
log "planning $env_name at image tag $tag (fusion_write_enabled=$write_enabled)"
"$TERRAFORM" -chdir="$tf_dir" plan -input=false -out="$plan_file" \
  -var "image_tag=$tag" -var "fusion_write_enabled=$write_enabled"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    printf '### Terraform plan: %s @ %s\n\n```\n' "$env_name" "$tag"
    "$TERRAFORM" -chdir="$tf_dir" show -no-color "$plan_file"
    printf '```\n'
  } >> "$GITHUB_STEP_SUMMARY"
fi

log "applying plan"
"$TERRAFORM" -chdir="$tf_dir" apply -input=false "$plan_file"
