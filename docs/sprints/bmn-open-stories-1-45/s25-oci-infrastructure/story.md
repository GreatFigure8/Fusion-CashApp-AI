# s25-oci-infrastructure: OCI infrastructure in Ashburn

- Issue: #25
- Wave: 4 (owns `infra/modules/`, `infra/envs/`)
- breaking: false

## Story

As the operator, I want all runtime infrastructure defined as code in `us-ashburn-1`, so that environments are reproducible and nothing is clicked together by hand.

## Context

CLAUDE.md non-negotiable 8: 100% OCI, Ashburn only. Plans only during runs; applying happens only through the release (s44) after Jonathan says "release". No `terraform apply` in this story; `terraform validate` and `plan` (with a dummy/real read-only provider config if available) only.

## Acceptance criteria

1. [unit] Modules under `infra/modules/`: `network` (VCN, private subnets for app/db/streaming, public subnet for the load balancer only, NSGs, service gateway, NAT), `atp` (Autonomous AI Database with private endpoint, mTLS-free TLS connect, separate DEV and PROD schemas created via an init SQL script referenced from `infra/sql/schemas.sql` that the release runs), `streaming` (stream pool with Kafka endpoint, private endpoint; one stream per stage + `.retry`/`.dlq` + `receipt-arrived` + `notify`, partitions as variables), `object_storage` (bucket for artifacts, versioning on, customer-managed key from Vault, no public access), `vault` (vault, master key, secrets placeholders for ATP password, Streaming auth token, Anthropic key, Fusion credentials per pod, OIDC client secret, session secret — values never in Terraform state: created empty / with `lifecycle.ignore_changes`), `compute` (container instances for api, workers (one per role group), web; OCIR repos; load balancer with TLS for web and api), `genai` (dedicated AI cluster for `cohere.command-a-vision` + endpoint; size = variable `genai_units`, with a comment on hourly cost), `iam` (dynamic groups + policies for instance principals: read secrets, use stream pool, manage objects in the bucket, use the GenAI endpoint, post metrics, write logs), `observability` (log group, custom metric namespace, alarms on DLQ depth and consumer lag).
2. [unit] `infra/envs/dev` and `infra/envs/prod` compose the modules; `region` is hard-set to `us-ashburn-1` in the provider and a `check` block/validation fails any other region.
3. [unit] Private endpoints for ATP, Streaming and the GenAI endpoint where supported; Object Storage encryption with a customer-managed key.
4. [unit] `terraform fmt -check -recursive` and `terraform validate` pass for both envs; `infra/README.md` documents `plan` usage and states apply is the release step's only (s44).
5. [unit] A test (`api/tests/test_infra_static.py`) greps `infra/` for any region string other than `us-ashburn-1` and for any provider other than `oracle/oci` (and hashicorp utility providers), and fails if found.
6. [unit] Outputs needed by s44 are exported: OCIR repo URLs, container instance OCIDs, LB hostnames, ATP connect string secret OCID, stream pool bootstrap, bucket name, GenAI endpoint OCID.

## Out of scope

Applying anything; CI/CD (s44).

## Deps

- s01-scaffold-monorepo — `infra/` skeleton (provider pins, envs dirs). plannable.
- s27-settings-secrets-wiring — the settings names that secrets/outputs map to (`vault:<ocid>` values). plannable.

## Assumptions

- Compute is OCI Container Instances behind an OCI Load Balancer (simpler than OKE for 3 workloads); s44 deploys to it.
- Remote state in an OCI Object Storage bucket (S3-compatible backend), created manually once.
