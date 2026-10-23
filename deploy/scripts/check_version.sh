#!/usr/bin/env bash
# check_version.sh <version>: the release version must equal [project].version in api/pyproject.toml.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ $# -eq 1 ]] || die "usage: check_version.sh <version>"
version="${1#v}"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || die "invalid version '$1'"

pyproject="${PYPROJECT:-$(repo_root)/api/pyproject.toml}"
[[ -f "$pyproject" ]] || die "missing $pyproject"
declared="$(awk '/^\[project\]/{p=1;next} /^\[/{p=0} p && /^version[[:space:]]*=/{gsub(/["[:space:]]/,"",$0); sub(/^version=/,"",$0); print; exit}' "$pyproject")"
[[ -n "$declared" ]] || die "no [project].version in $pyproject"

if [[ "$version" != "$declared" ]]; then
  die "release version '$version' does not match api/pyproject.toml version '$declared'"
fi
log "version $version matches api/pyproject.toml"
