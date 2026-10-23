#!/bin/sh
# smoke.sh [--api URL --expect-version V] [--web URL] [--worker URL]... [--attempts N] [--delay S]
#
# POSIX sh: also runs inside the API image (/app/deploy/smoke.sh) for the private worker checks.
#   api:    GET <URL>/health -> 200 and JSON "version" == V
#   web:    GET <URL>/       -> 200 or 302 (redirects are not followed)
#   worker: GET <URL>/readyz -> 200
# Every check is retried up to N times (default 20), S seconds apart (default 15).
# Exits 1 and names every failed check.
set -eu

CURL="${CURL:-curl}"
api=""
version=""
web=""
workers=""
attempts=20
delay=15

die() { printf 'smoke: %s\n' "$*" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --api) [ $# -ge 2 ] || die "--api needs a value"; api="$2"; shift 2 ;;
    --expect-version) [ $# -ge 2 ] || die "--expect-version needs a value"; version="$2"; shift 2 ;;
    --web) [ $# -ge 2 ] || die "--web needs a value"; web="$2"; shift 2 ;;
    --worker) [ $# -ge 2 ] || die "--worker needs a value"; workers="$workers $2"; shift 2 ;;
    --attempts) [ $# -ge 2 ] || die "--attempts needs a value"; attempts="$2"; shift 2 ;;
    --delay) [ $# -ge 2 ] || die "--delay needs a value"; delay="$2"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$attempts" in ''|*[!0-9]*) die "--attempts must be an integer" ;; esac
case "$delay" in ''|*[!0-9]*) die "--delay must be an integer" ;; esac
[ -z "$api" ] || [ -n "$version" ] || die "--api requires --expect-version"
[ -n "$api$web$workers" ] || die "nothing to check"

body_file="$(mktemp)"
trap 'rm -f "$body_file"' EXIT
failed=""

# status_of <url>: prints the HTTP status ("000" when unreachable); the body goes to $body_file.
status_of() {
  "$CURL" --silent --show-error --max-time 10 --output "$body_file" --write-out '%{http_code}' "$1" 2>/dev/null || printf '000'
}

# retry <label> <function> <args...>: runs the check until it succeeds or attempts run out.
retry() {
  label="$1"; shift
  n=1
  while [ "$n" -le "$attempts" ]; do
    if "$@"; then
      printf 'smoke: ok   %s\n' "$label"
      return 0
    fi
    [ "$n" -ge "$attempts" ] || sleep "$delay"
    n=$((n + 1))
  done
  printf 'smoke: FAIL %s\n' "$label" >&2
  failed="$failed
  - $label"
  return 0
}

check_api() {
  code="$(status_of "$1/health")"
  [ "$code" = "200" ] || return 1
  # The reply is {"status":"ok","version":"X"}; compare the version without a JSON tool.
  tr -d ' \n\r' < "$body_file" | grep -q "\"version\":\"$2\""
}

check_web() {
  code="$(status_of "$1/")"
  [ "$code" = "200" ] || [ "$code" = "302" ]
}

check_worker() {
  code="$(status_of "$1/readyz")"
  [ "$code" = "200" ]
}

[ -z "$api" ] || retry "api $api/health version $version" check_api "$api" "$version"
[ -z "$web" ] || retry "web $web/ (200 or 302)" check_web "$web"
for worker in $workers; do
  retry "worker $worker/readyz" check_worker "$worker"
done

if [ -n "$failed" ]; then
  printf 'smoke: failed checks:%s\n' "$failed" >&2
  exit 1
fi
printf 'smoke: all checks passed\n'
