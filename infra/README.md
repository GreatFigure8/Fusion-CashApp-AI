# Infrastructure

Terraform for every runtime resource, hosted 100% in OCI `us-ashburn-1`. One composition per environment:
`envs/dev` and `envs/prod`, both built from the same nine modules under `modules/`.

**`terraform apply` is run only by the release pipeline (s44), after Jonathan says "release".**
During a run, only `init -backend=false`, `fmt`, `validate` and `plan` are used. Nothing in this directory
runs apply.

## Layout

| Path | Purpose |
|---|---|
| `versions.tf`, `providers.tf`, `variables.tf`, `main.tf` | Root skeleton (provider pin) |
| `modules/network` | VCN, public load balancer subnet, private app/db/streaming/genai subnets, NSGs, service gateway, NAT |
| `modules/atp` | Autonomous AI Database on a private endpoint, TLS connect string (no wallet), connect string secret |
| `modules/streaming` | Stream pool with Kafka endpoint, pre-created topics (main, `.retry`, `.dlq` per stage, plus `receipt-arrived`, `notify`) |
| `modules/object_storage` | Artifact bucket: versioned, no public access, customer-managed key |
| `modules/vault` | Vault, master key, secrets (generated or placeholders) |
| `modules/compute` | OCIR repositories, container instances (api, web, one per worker group), load balancer with TLS |
| `modules/genai` | Dedicated AI cluster and endpoint for `cohere.command-a-vision`, private endpoint |
| `modules/iam` | Dynamic group and policies for the containers' resource principal |
| `modules/observability` | Log group, alarm topic, alarms on DLQ depth and consumer lag |
| `envs/{dev,prod}` | Compose the modules, build the container environment, export the outputs the release needs |
| `sql/schemas.sql` | Creates the `CASHAPP_DEV` / `CASHAPP_PROD` schema; run by the release before `alembic upgrade head` |

## Validate and plan

```bash
terraform -chdir=infra/envs/dev init -backend=false
terraform fmt -check -recursive infra
terraform -chdir=infra/envs/dev validate

# plan needs OCI credentials and a real tfvars file (copy terraform.tfvars.example)
terraform -chdir=infra/envs/dev init            # after copying backend.tf.example to backend.tf
terraform -chdir=infra/envs/dev plan -var-file=dev.tfvars
```

Real `*.tfvars` files are gitignored; only `*.tfvars.example` is committed. `backend.tf` is copied from
`backend.tf.example` by the release pipeline and is never committed (remote state lives in an OCI Object
Storage bucket through its S3-compatible API).

## Rollout contract (s44)

`terraform -chdir=infra/envs/<env> apply -var image_tag=<tag> -var-file=<env>.tfvars` replaces the container
instances (the image of an instance is immutable) and re-points the load balancer backends. Outputs
(`ocir_repository_urls`, `container_instance_ids`, `load_balancer_ip`, `atp_connect_string_secret_id`,
`stream_pool_bootstrap_servers`, `bucket_name`, `genai_endpoint_id`, and the rest) are the release's inputs.
The first apply needs images tagged `bootstrap` (or the chosen tag) already pushed to OCIR.

Topics are pre-created and the stream pool refuses to create new ones: a new topic needs a change here.

## Secrets

No secret value ever enters Terraform state. Vault generates the ATP passwords and the web session secret.
The others (`streaming-auth-token`, `anthropic-api-key`, `oidc-client-secret`, `smtp-password`,
`fusion-<pod>-password`) are created with the placeholder `SET-IN-VAULT` and `ignore_changes` on the content.
The operator sets the real value as a new secret version in Vault (console or `oci vault secret update-base64`),
which is also how a secret is rotated; the containers read the current version at start-up, so roll the
container instances after a rotation. Containers receive `vault:<secret-ocid>` references, never values.

## One-time manual prerequisites

1. A bucket for Terraform state and a customer secret key for its S3-compatible API.
2. An OCI Certificates-service certificate for the load balancer (`certificate_ocid`), so no private key enters state.
3. An IAM user and auth token for the Streaming SASL login (`streaming_user`); store the token in the
   `streaming-auth-token` secret.
4. Set the placeholder secrets' real values (above).
5. DNS records for `web_hostname` and `api_hostname` pointing at the `load_balancer_ip` output.
6. Service limits: about 32 streams per environment and their partitions, dedicated AI cluster units for
   the model, and Container Instance OCPUs.
7. The pay-on-behalf BI Publisher report must exist in each Fusion pod (`fusion_relationships_report_path`).

## Cost

The dedicated AI cluster (`genai_units`) is billed per unit-hour whether or not it is used. Size it for peak
extraction throughput; its utilisation is shown in the flow monitor.

## First plan checklist (items marked VERIFY in the code)

- GenAI `genai_unit_shape` for `cohere.command-a-vision`.
- Load balancer routing policy Host header condition syntax.
- IAM statement for the GenAI endpoint (scope it to the endpoint if the policy language allows).
- Stream names containing dots and underscores are accepted.
- Container Instances expose the resource principal environment the secret resolver keys on; if not, set it
  explicitly in `api_env`.
- On the first apply, if Streaming or Object Storage creation fails on key authorisation, the service key
  policy had not propagated yet: apply again.
