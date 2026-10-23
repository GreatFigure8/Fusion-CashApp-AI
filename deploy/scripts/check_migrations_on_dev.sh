#!/usr/bin/env bash
# check_migrations_on_dev.sh <image_ref>
#
# Prod gets only migrations that are already applied on DEV. This reads DEV's live Alembic revision
# (through an ephemeral instance in the dev VCN, so it sees DEV ATP) and aborts unless the head of
# the code being released is in DEV's applied history. Alembic's linear chain makes that a complete
# check. `alembic heads` / `history` read only the script directory, not the database.
#
# Overrides for tests: RUN_IN_VCN (default deploy/scripts/run_in_vcn.sh), ALEMBIC (default `uv run alembic`).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ $# -eq 1 ]] || die "usage: check_migrations_on_dev.sh <image_ref>"
image_ref="$1"

run_in_vcn="${RUN_IN_VCN:-$(dirname "${BASH_SOURCE[0]}")/run_in_vcn.sh}"
read -r -a alembic_cmd <<< "${ALEMBIC:-uv run alembic}"
api_dir="${API_DIR:-$(repo_root)/api}"

rev_pattern='^[A-Za-z0-9_]+( \(head\))?[[:space:]]*$'

# The revision DEV is on: the last line of `alembic current` that is a bare revision id.
dev_out="$("$run_in_vcn" dev "$image_ref" -- alembic current)"
dev_rev="$(printf '%s\n' "$dev_out" | tr -d '\r' | grep -E "$rev_pattern" | tail -n 1 | awk '{print $1}' || true)"
[[ -n "$dev_rev" ]] || die "DEV reports no applied Alembic revision (empty DEV?); apply migrations on DEV first"

# The head of the code being released: must be exactly one.
heads_out="$(cd "$api_dir" && "${alembic_cmd[@]}" heads)"
mapfile -t heads < <(printf '%s\n' "$heads_out" | tr -d '\r' | grep -E "$rev_pattern" | awk '{print $1}')
(( ${#heads[@]} == 1 )) || die "expected exactly one Alembic head, found ${#heads[@]}: ${heads[*]:-none}"
target="${heads[0]}"

revisions_in() {
  # Revision ids from `alembic history` lines of the form "<down> -> <rev> [(head)], <message>".
  grep -oE -- '-> [A-Za-z0-9_]+' | awk '{print $2}'
}

history_out="$(cd "$api_dir" && "${alembic_cmd[@]}" history -r "base:$dev_rev")"
mapfile -t applied < <(printf '%s\n' "$history_out" | tr -d '\r' | revisions_in)

for rev in "${applied[@]}"; do
  if [[ "$rev" == "$target" ]]; then
    log "head $target is applied on DEV (DEV at $dev_rev); prod may take it"
    exit 0
  fi
done

missing_out="$(cd "$api_dir" && "${alembic_cmd[@]}" history -r "$dev_rev:$target" || true)"
missing="$(printf '%s\n' "$missing_out" | tr -d '\r' | revisions_in | grep -vx -- "$dev_rev" | tr '\n' ' ')"
die "head $target is not applied on DEV (DEV at $dev_rev). Revisions missing on DEV: ${missing:-$target}. Apply them to DEV first."
