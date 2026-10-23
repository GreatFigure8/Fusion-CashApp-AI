#!/usr/bin/env bash
# smoke_env.sh <env> <expected_version> <api_image_ref>
#
# api and web are public behind the load balancer and are checked from the runner. Workers have
# private health ports, so their /readyz checks run from the API image inside the VCN.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ $# -eq 3 ]] || die "usage: smoke_env.sh <env> <expected_version> <api_image_ref>"
env_name="$1"; expected="$2"; image_ref="$3"
validate_env "$env_name"
validate_tag "$expected"

script_dir="$(dirname "${BASH_SOURCE[0]}")"
run_in_vcn="${RUN_IN_VCN:-$script_dir/run_in_vcn.sh}"
smoke="${SMOKE:-$script_dir/smoke.sh}"
attempts="${SMOKE_ATTEMPTS:-20}"
delay="${SMOKE_DELAY:-15}"

api_url="$(tf_output "$env_name" api_lb_url)"
web_url="$(tf_output "$env_name" web_lb_url)"
worker_urls="$(tf_output "$env_name" worker_health_urls json | json_get '" ".join(d.values())')"

# The release version in /health is the package version; a rollback tag may not be a version
# number (a git sha), in which case only reachability is checked on the api.
log "checking api and web of $env_name from the runner"
if [[ "$expected" =~ ^[0-9]+\.[0-9]+\.[0-9]+ ]]; then
  "$smoke" --api "$api_url" --expect-version "${expected#v}" --web "$web_url" --attempts "$attempts" --delay "$delay"
else
  log "tag $expected is not a version number; skipping the api version comparison"
  "$smoke" --web "$web_url" --attempts "$attempts" --delay "$delay"
fi

if [[ -n "$worker_urls" ]]; then
  worker_args=()
  for url in $worker_urls; do
    [[ "$url" =~ ^http://[0-9A-Za-z.:-]+$ ]] || die "unexpected worker health url '$url'"
    worker_args+=(--worker "$url")
  done
  log "checking workers of $env_name from inside the VCN"
  "$run_in_vcn" "$env_name" "$image_ref" -- /app/deploy/smoke.sh "${worker_args[@]}" --attempts "$attempts" --delay "$delay"
fi
