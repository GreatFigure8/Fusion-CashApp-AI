#!/usr/bin/env bash
# build_push.sh <env> <version> <sha>: build the api and web images and push both tags to OCIR.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ $# -eq 3 ]] || die "usage: build_push.sh <env> <version> <sha>"
env_name="$1"; version="$2"; sha="$3"
validate_env "$env_name"
validate_tag "$version"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "sha must be a full 40-character commit id"
[[ -n "${OCIR_USERNAME:-}" ]] || die "OCIR_USERNAME is not set"
[[ -n "${OCIR_AUTH_TOKEN:-}" ]] || die "OCIR_AUTH_TOKEN is not set"
require_cmd "$DOCKER"

api_repo="$(image_repo "$env_name" api)"
web_repo="$(image_repo "$env_name" web)"

printf '%s' "$OCIR_AUTH_TOKEN" | "$DOCKER" login "$OCIR_HOST" --username "$OCIR_USERNAME" --password-stdin >/dev/null

# Release tags are immutable: refuse to overwrite a published version.
for repo in "$api_repo" "$web_repo"; do
  if "$DOCKER" buildx imagetools inspect "$repo:$version" >/dev/null 2>&1; then
    die "$repo:$version already exists; versions are immutable, bump the version"
  fi
done

cd "$(repo_root)"

log "building api image $api_repo:$version"
"$DOCKER" buildx build --platform linux/amd64 \
  --build-arg "VERSION=$version" --build-arg "GIT_SHA=$sha" \
  -f api/Dockerfile -t "$api_repo:$version" -t "$api_repo:$sha" --push .

log "building web image $web_repo:$version"
"$DOCKER" buildx build --platform linux/amd64 \
  --build-arg "VERSION=$version" --build-arg "GIT_SHA=$sha" \
  -t "$web_repo:$version" -t "$web_repo:$sha" --push web

log "pushed $version and $sha for api and web"
