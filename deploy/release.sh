#!/usr/bin/env bash
# The one command the BMN release step runs.
#
#   deploy/release.sh --env dev|prod --version X.Y.Z [--fusion-write-enabled]
#   deploy/release.sh --env dev|prod --rollback [--to TAG] [--version X.Y.Z]
#
# It dispatches .github/workflows/release.yml, waits for the run, downloads the release record
# artifact into deploy/releases/ and commits it locally (it never pushes). Never run it during a BMN
# run: only after Jonathan says "release".
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/scripts/lib.sh"

usage() {
  cat >&2 <<'USAGE'
usage: deploy/release.sh --env dev|prod --version X.Y.Z [--fusion-write-enabled]
       deploy/release.sh --env dev|prod --rollback [--to TAG] [--version X.Y.Z]
USAGE
  exit 2
}

env_name=""; version=""; action="deploy"; rollback_to=""; write_enabled="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) [[ $# -ge 2 ]] || usage; env_name="$2"; shift 2 ;;
    --version) [[ $# -ge 2 ]] || usage; version="${2#v}"; shift 2 ;;
    --rollback) action="rollback"; shift ;;
    --to) [[ $# -ge 2 ]] || usage; rollback_to="$2"; shift 2 ;;
    --fusion-write-enabled) write_enabled="true"; shift ;;
    *) usage ;;
  esac
done

validate_env "$env_name"
if [[ "$action" == "deploy" ]]; then
  [[ -n "$version" ]] || usage
  [[ -z "$rollback_to" ]] || die "--to is only valid with --rollback"
else
  # The workflow requires a version input; a rollback does not use it for anything but the label.
  version="${version:-rollback}"
  [[ -z "$rollback_to" ]] || validate_tag "$rollback_to"
fi
validate_tag "$version"

# prod is released from main only; dev from the dev integration branch.
if [[ "$env_name" == "prod" ]]; then ref="main"; else ref="dev"; fi

require_cmd "$GH" git
root="$(repo_root)"
cd "$root"

started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
log "dispatching release.yml on $ref: env=$env_name action=$action version=$version"
"$GH" workflow run release.yml --ref "$ref" \
  -f "version=$version" -f "environment=$env_name" -f "action=$action" \
  -f "fusion_write_enabled=$write_enabled" ${rollback_to:+-f "rollback_to=$rollback_to"}

run_id=""
for _ in $(seq 1 30); do
  run_id="$("$GH" run list --workflow release.yml --branch "$ref" --event workflow_dispatch \
    --created ">=$started" --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
  [[ -n "$run_id" ]] && break
  sleep "${RELEASE_POLL_SECONDS:-5}"
done
[[ -n "$run_id" ]] || die "could not find the dispatched workflow run"
log "watching run $run_id"

"$GH" run watch "$run_id" --exit-status

mkdir -p deploy/releases
"$GH" run download "$run_id" -n "release-record-$env_name" -D deploy/releases
git add "deploy/releases/$env_name.json"
git commit -m "Record $action of $env_name to ${rollback_to:-$version} (run $run_id)"
log "release recorded and committed locally; push it through the release branch (this script never pushes)"
