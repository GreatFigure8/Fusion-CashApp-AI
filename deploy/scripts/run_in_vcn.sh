#!/usr/bin/env bash
# run_in_vcn.sh <env> <image_ref> -- <command...>
#
# Runs one command from the API image inside the environment's VCN, where ATP and the worker
# health ports are reachable. It creates an ephemeral OCI Container Instance from the env's
# `job_launch_spec` Terraform output, waits for the container to exit, prints its logs, exits with
# the container's exit code and always deletes the instance.
#
# VERIFY (OCI CLI): the `container-instances container-instance create|delete` and
# `container-instances container get|retrieve-logs` command and flag names below were written from
# the CLI reference; confirm with `oci container-instances ... --help` on the pinned CLI version
# on the first DEV release.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ $# -ge 4 && "$3" == "--" ]] || die "usage: run_in_vcn.sh <env> <image_ref> -- <command...>"
env_name="$1"; image_ref="$2"
shift 3
validate_env "$env_name"
[[ "$image_ref" =~ ^iad\.ocir\.io/[0-9A-Za-z]+/cashapp-(dev|prod)/api:[0-9A-Za-z][0-9A-Za-z._-]{0,127}$ ]] \
  || die "image_ref must be an Ashburn OCIR cashapp api image, got '$image_ref'"
[[ "$image_ref" == *"/cashapp-$env_name/"* ]] || die "image_ref does not belong to environment $env_name"
[[ -n "${OCIR_USERNAME:-}" && -n "${OCIR_AUTH_TOKEN:-}" ]] || die "OCIR_USERNAME and OCIR_AUTH_TOKEN are required to pull the image"
require_cmd "$OCI" "$PYTHON"

timeout_s="${RUN_IN_VCN_TIMEOUT:-900}"
poll_s="${RUN_IN_VCN_POLL:-10}"
[[ "$timeout_s" =~ ^[0-9]+$ && "$poll_s" =~ ^[0-9]+$ ]] || die "RUN_IN_VCN_TIMEOUT and RUN_IN_VCN_POLL must be integers"

work_dir="$(mktemp -d)"
instance_id=""
cleanup() {
  local rc=$?
  if [[ -n "$instance_id" ]]; then
    log "deleting ephemeral container instance $instance_id"
    "$OCI" container-instances container-instance delete --container-instance-id "$instance_id" --force >/dev/null 2>&1 \
      || log "WARNING: could not delete container instance $instance_id; remove it manually"
  fi
  rm -rf "$work_dir"
  exit "$rc"
}
trap cleanup EXIT

spec="$(tf_output "$env_name" job_launch_spec json)"
printf '%s' "$spec" > "$work_dir/spec.json"

# Build the CLI JSON arguments from the launch spec in Python so nothing is shell-quoted by hand.
umask 077
RUN_IMAGE="$image_ref" "$PYTHON" - "$work_dir" "$@" <<'PY'
import base64, json, os, sys

work, command = sys.argv[1], sys.argv[2:]
spec = json.load(open(os.path.join(work, "spec.json")))
containers = [{
    "displayName": "job",
    "imageUrl": os.environ["RUN_IMAGE"],
    "command": command,
    "environmentVariables": {str(k): str(v) for k, v in spec["environment"].items()},
}]
shape_config = {"ocpus": spec["ocpus"], "memoryInGBs": spec["memory_in_gbs"]}
vnics = [{"subnetId": spec["subnet_id"], "isPublicIpAssigned": False}]
b64 = lambda value: base64.b64encode(value.encode()).decode()
secrets = [{
    "secretType": "BASIC",
    "registryEndpoint": "iad.ocir.io",
    "username": b64(os.environ["OCIR_USERNAME"]),
    "password": b64(os.environ["OCIR_AUTH_TOKEN"]),
}]
for name, value in (("containers", containers), ("shape_config", shape_config), ("vnics", vnics), ("secrets", secrets)):
    with open(os.path.join(work, name + ".json"), "w") as handle:
        json.dump(value, handle)
for name in ("compartment_id", "availability_domain", "shape"):
    with open(os.path.join(work, name + ".txt"), "w") as handle:
        handle.write(str(spec[name]))
PY

compartment_id="$(<"$work_dir/compartment_id.txt")"
availability_domain="$(<"$work_dir/availability_domain.txt")"
shape="$(<"$work_dir/shape.txt")"
display_name="cashapp-job-${env_name}-$(date -u +%Y%m%d%H%M%S)-$$"

log "creating ephemeral container instance $display_name"
created="$("$OCI" container-instances container-instance create \
  --compartment-id "$compartment_id" \
  --availability-domain "$availability_domain" \
  --shape "$shape" \
  --shape-config "file://$work_dir/shape_config.json" \
  --vnics "file://$work_dir/vnics.json" \
  --containers "file://$work_dir/containers.json" \
  --image-pull-secrets "file://$work_dir/secrets.json" \
  --container-restart-policy NEVER \
  --display-name "$display_name" \
  --wait-for-state ACTIVE)"
instance_id="$(printf '%s' "$created" | json_get 'd["data"]["id"]')"
container_id="$(printf '%s' "$created" | json_get 'd["data"]["containers"][0]["container-id"]')"
log "container instance $instance_id is ACTIVE; waiting for container $container_id to exit"

elapsed=0
state=""
exit_code=""
while true; do
  current="$("$OCI" container-instances container get --container-id "$container_id")"
  state="$(printf '%s' "$current" | json_get 'd["data"]["lifecycle-state"]')"
  if [[ "$state" == "INACTIVE" || "$state" == "FAILED" || "$state" == "DELETED" ]]; then
    exit_code="$(printf '%s' "$current" | json_get 'd["data"].get("exit-code")')"
    break
  fi
  if (( elapsed >= timeout_s )); then
    log "timed out after ${timeout_s}s waiting for the container (state $state)"
    "$OCI" container-instances container retrieve-logs --container-id "$container_id" --file - || true
    exit 124
  fi
  sleep "$poll_s"
  elapsed=$(( elapsed + poll_s ))
done

"$OCI" container-instances container retrieve-logs --container-id "$container_id" --file - || log "WARNING: could not retrieve logs"

if ! [[ "$exit_code" =~ ^[0-9]+$ ]]; then
  die "container ended in state $state without an exit code"
fi
log "container exited with code $exit_code"
exit "$exit_code"
