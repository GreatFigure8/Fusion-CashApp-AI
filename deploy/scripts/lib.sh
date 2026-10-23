#!/usr/bin/env bash
# Shared helpers for the release scripts. Source it; do not execute it.
# External commands are overridable through the environment so tests can stub them.

OCI="${OCI:-oci}"
TERRAFORM="${TERRAFORM:-terraform}"
DOCKER="${DOCKER:-docker}"
CURL="${CURL:-curl}"
GH="${GH:-gh}"
PYTHON="${PYTHON:-python3}"
OCIR_HOST="iad.ocir.io"

log() { printf '[%s] %s\n' "$(basename "${0:-deploy}")" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

require_cmd() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || die "required command not found: $cmd"
  done
}

repo_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  (cd "$here/../.." && pwd)
}

validate_env() {
  [[ "${1:-}" =~ ^(dev|prod)$ ]] || die "environment must be dev or prod, got '${1:-}'"
}

validate_tag() {
  [[ "${1:-}" =~ ^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$ ]] || die "invalid image tag '${1:-}'"
}

validate_bool() {
  [[ "${1:-}" =~ ^(true|false)$ ]] || die "expected true or false, got '${1:-}'"
}

# image_repo <env> <api|web>  ->  iad.ocir.io/<namespace>/cashapp-<env>/<kind>
image_repo() {
  local env="$1" kind="$2"
  validate_env "$env"
  [[ "$kind" =~ ^(api|web)$ ]] || die "image kind must be api or web, got '$kind'"
  [[ -n "${OCIR_NAMESPACE:-}" ]] || die "OCIR_NAMESPACE is not set"
  [[ "$OCIR_NAMESPACE" =~ ^[0-9A-Za-z]+$ ]] || die "OCIR_NAMESPACE has an unexpected format"
  printf '%s/%s/cashapp-%s/%s' "$OCIR_HOST" "$OCIR_NAMESPACE" "$env" "$kind"
}

# tf_output <env> <name> [raw|json]  ->  terraform output of infra/envs/<env>
tf_output() {
  local env="$1" name="$2" mode="${3:-raw}"
  validate_env "$env"
  [[ "$name" =~ ^[a-z][a-z0-9_]*$ ]] || die "invalid terraform output name '$name'"
  case "$mode" in
    raw) "$TERRAFORM" -chdir="$(repo_root)/infra/envs/$env" output -raw "$name" ;;
    json) "$TERRAFORM" -chdir="$(repo_root)/infra/envs/$env" output -json "$name" ;;
    *) die "tf_output mode must be raw or json" ;;
  esac
}

# json_get <python expression over d>   (JSON on stdin), e.g. json_get 'd["a"]["b"]'
# The expression is always a literal written in this repo, never user input.
json_get() {
  "$PYTHON" -c 'import json,sys; d=json.load(sys.stdin); v=eval(sys.argv[1], {"d": d}); print(v if isinstance(v,str) else json.dumps(v))' "$1"
}
