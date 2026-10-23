# Plan: s25-oci-infrastructure

Terraform for every runtime resource in `us-ashburn-1`, composed per environment under `infra/envs/{dev,prod}`.
Nothing is applied in this story: the gates are `terraform init -backend=false`, `fmt -check -recursive`
and `validate` for both envs, plus a static Python test. `apply` belongs to the release step (s44) only.

## Standards followed

- **CLAUDE.md non-negotiable 8:** 100% OCI, Ashburn only. The region is a literal in every provider block, every
  module re-asserts it through a validated `region` variable, each env has a `check` block, and
  `api/tests/test_infra_static.py` fails the build on any other region string or any non-OCI provider.
- **CLAUDE.md non-negotiable 9 / Fusion:** nothing here touches Fusion except per-pod credential secret placeholders.
- **CLAUDE.md *Working with BMN → Deploys*:** no `terraform apply`, no `plan` against a real tenancy is required
  to pass. The README states that apply is s44's job only.
- **CLAUDE.md data layer:** DEV and PROD schemas live in separate ATPs (one per env). The schema is created
  by `infra/sql/schemas.sql`, which s44's release runs; Alembic owns all tables (no DDL for tables here).
- **CLAUDE.md conventions (PII, secrets):** no secret value ever enters Terraform state. Secrets are either
  Vault-generated (`enable_auto_generation`) or created with a fixed non-secret placeholder and
  `lifecycle { ignore_changes = [secret_content] }`; the operator sets the real value in Vault. Banned in
  `infra/`: `random_password`, `random_string`, `oci_identity_auth_token`, `oci_load_balancer_certificate`
  (private key in state), `tls_private_key`. The LB uses an OCI Certificates-service certificate by OCID.
- **python-web-app skill (Deployment):** one image runs API and workers via different commands; infra is
  Terraform; secrets are not committed and are set out of band.
- **s27 (pinned):** container environment uses s27's exact env var names (`CASHAPP_` prefix, `__` delimiter)
  and `vault:<secret-ocid>` values for secret leaves, which `VaultSecretSource` resolves via resource principal.
- **s03 (pinned):** topic names `{prefix}.{env}.{stage lower}` + `.retry` / `.dlq` for `CONSUMED_STAGES`,
  `{prefix}.{env}.notify`, and s14's `{prefix}.{env}.receipt-arrived`. `prefix = "cashapp"`.
- **s29 (pinned):** custom metrics `bus_dlq_depth` and `bus_consumer_lag` (dimension `stage`) in namespace
  `cashapp` (`observability.oci_monitoring_namespace` default).
- **s30 (pinned):** workers run `python -m cashapp.workers run --roles <comma list>`; health on
  `settings.worker.health_port` (8081) at `/readyz`.
- **Never guess a provider attribute:** the coder runs `terraform providers schema -json` after `init` and
  confirms every resource/attribute used below; `validate` is the backstop. Any rename is recorded in the
  coder return and here.

## Files to touch (all owned by this story; disjoint from every other story)

s01 owns `infra/versions.tf`, `infra/providers.tf`, `infra/variables.tf`, `infra/main.tf`,
`infra/.terraform.lock.hcl` and the `.gitkeep` files. This story deletes `infra/modules/.gitkeep`,
`infra/envs/dev/.gitkeep`, `infra/envs/prod/.gitkeep` (replaced by real files) and edits nothing else of s01's.

### Modules (`infra/modules/<name>/{main.tf,variables.tf,outputs.tf,versions.tf}`)

Every module: `versions.tf` declares `required_providers { oci = { source = "oracle/oci" } }` (no version; the
root pins it); `variables.tf` has `compartment_ocid`, `environment` (validation `dev|prod`), `region`
(default `"us-ashburn-1"`, validation `var.region == "us-ashburn-1"`), `freeform_tags` (map, merged with
`{ app = "cashapp", env = var.environment }`).

| Module | Resources (OCI provider) |
|---|---|
| `network` | `oci_core_vcn`; `oci_core_internet_gateway` (LB subnet only); `oci_core_nat_gateway`; `oci_core_service_gateway` (all-services in Oracle Services Network, via `data oci_core_services`); route tables `public` (IGW) and `private` (NAT + SGW); subnets `lb` (public, `prohibit_public_ip_on_vnic = false`), `app`, `db`, `streaming`, `genai` (all private, `prohibit_public_ip_on_vnic = true`); NSGs `lb`, `app`, `db`, `streaming`, `genai` with rules: internet→lb 443; lb→app 8000 (api) and 3000 (web) and 8081 (worker health); app→db 1521-1522; app→streaming 9092; app→genai 443; egress app→0.0.0.0/0 443 via NAT (Anthropic API, Fusion). CIDRs are variables (`vcn_cidr`, `subnet_cidrs` map) with defaults. |
| `atp` | `oci_database_autonomous_database` (`db_workload = "OLTP"`, `compute_model = "ECPU"`, `compute_count`, `data_storage_size_in_gb` variables, `is_mtls_connection_required = false`, `subnet_id` = db subnet, `nsg_ids`, `private_endpoint_label`, `secret_id` = Vault-generated admin password secret (no `admin_password`), `is_auto_scaling_enabled`, `license_model` variable); `oci_vault_secret` `atp-dsn` whose content is the TLS (non-mTLS) `high` connection string from `connection_strings[0].profiles` (not secret; stored so the app reads `vault:` uniformly — output `atp_connect_string_secret_id`). `infra/sql/schemas.sql` is referenced from the module README comment and the env output `atp_schema_script = "infra/sql/schemas.sql"`. |
| `streaming` | `oci_streaming_stream_pool` (`kafka_settings { auto_create_topics_enable = false, log_retention_hours = var.retention_hours, num_partitions = var.default_partitions }`, `private_endpoint_settings { subnet_id, nsg_ids }`, `custom_encryption_key { kms_key_id }`); `oci_streaming_stream` `for_each` over `local.topics` with `partitions = lookup(var.partitions, name, var.default_partitions)` and `retention_in_hours`. `local.topics` = for each of `var.stages`: `cashapp.<env>.<stage>`, `.retry`, `.dlq`; plus `cashapp.<env>.<extra>` for each of `var.extra_topics` (default `["receipt-arrived", "notify"]`). `var.stages` default = `["classify","extract","adjudicate","validate","resolve_customer","fast_path","match_receipt","match_lines","apply","write_back"]` (= s03 `CONSUMED_STAGES`, lower-cased). |
| `object_storage` | `data oci_objectstorage_namespace`; `oci_objectstorage_bucket` `cashapp-<env>-artifacts` (`access_type = "NoPublicAccess"`, `versioning = "Enabled"`, `kms_key_id = var.kms_key_id`, `storage_tier = "Standard"`, `object_events_enabled = false`). |
| `vault` | `oci_kms_vault` (`vault_type = "DEFAULT"`); `oci_kms_key` master key (AES-256, `protection_mode = "HSM"`); `oci_vault_secret` per entry of `local.secrets`. Auto-generated (`enable_auto_generation = true`, `secret_generation_context { generation_type = "PASSPHRASE", generation_template = "DBAAS_DEFAULT_PASSWORD" }` / `BYTES` for session): `atp-admin-password`, `atp-app-password`, `session-secret`. Placeholder + `ignore_changes = [secret_content]` (content `base64encode("SET-IN-VAULT")`): `streaming-auth-token`, `anthropic-api-key`, `oidc-client-secret`, `smtp-password`, and `fusion-<pod>-password` for each of `var.fusion_pods` (list of lower-case pod keys). |
| `compute` | `oci_artifacts_container_repository` `cashapp/api` and `cashapp/web` (`is_public = false`, `is_immutable = true`); `oci_container_instances_container_instance` for `api`, `web` and one per key of `var.worker_groups` (shape `CI.Standard.E4.Flex`, `shape_config` from `var.sizes[<name>]`, `vnics { subnet_id = app, nsg_ids, is_public_ip_assigned = false }`, `container_restart_policy = "ALWAYS"`, one container each: image `iad.ocir.io/<ns>/cashapp/<api|web>:<var.image_tag>`, `command`/`arguments` (api: `uvicorn cashapp.main:app --host 0.0.0.0 --port 8000 --proxy-headers`; worker: `python -m cashapp.workers run --roles <group roles>`), `environment_variables = var.api_env` / `var.web_env`, `health_checks` (HTTP `/health` 8000, `/readyz` 8081, web `/` 3000)); `oci_load_balancer_load_balancer` (shape `flexible`, min/max bandwidth variables, `subnet_ids = [lb]`, `network_security_group_ids = [lb nsg]`, `is_private = false`); backend sets `api` and `web` with health checkers; `oci_load_balancer_backend` = each instance's private IP (from `vnics[0].private_ip` via `data oci_core_vnic` if not exposed directly; VERIFY); one HTTPS listener 443 with `ssl_configuration { certificate_ids = [var.certificate_ocid], protocols = ["TLSv1.2","TLSv1.3"] }` and `oci_load_balancer_load_balancer_routing_policy` routing `host == var.api_hostname` → `api`, default → `web`. |
| `genai` | `oci_generative_ai_dedicated_ai_cluster` (`type = "HOSTING"`, `unit_shape = var.genai_unit_shape`, `unit_count = var.genai_units`) with a comment block: billed per unit-hour whether used or not; size for peak extraction throughput; utilisation goes to the flow monitor; `oci_generative_ai_generative_ai_private_endpoint` in the genai subnet (`dns_prefix`, `nsg_ids`); `oci_generative_ai_endpoint` (`model_id` from `data oci_generative_ai_models` filtered on `display_name = var.genai_model_name` default `"cohere.command-a-vision"`, `dedicated_ai_cluster_id`, `generative_ai_private_endpoint_id`, `content_moderation_config { is_enabled = false }`). |
| `iam` | `oci_identity_dynamic_group` `cashapp-<env>-containers` (matching rule `ALL {resource.type = 'computecontainerinstance', resource.compartment.id = '<compartment>'}`); `oci_identity_policy` `cashapp-<env>-runtime` with statements: `read secret-bundles in compartment … where target.vault.id = '<vault>'`; `use stream-push` and `use stream-pull in compartment … where target.streampool.id = '<pool>'`; `manage objects in compartment … where target.bucket.name = '<bucket>'`; `use generative-ai-family in compartment …` (scoped to the endpoint where the policy language allows; VERIFY); `use metrics in compartment … where target.metrics.namespace = 'cashapp'`; `use log-content in compartment …`; `read repos in compartment …` (image pull without a pull secret). `oci_identity_policy` `cashapp-<env>-services`: `allow service objectstorage-us-ashburn-1 to use keys in compartment … where target.key.id = '<key>'` and the streaming service key grant. `tenancy_ocid` input for policy placement. |
| `observability` | `oci_logging_log_group` `cashapp-<env>`; `oci_logging_log` (custom, `log_type = "CUSTOM"`) `app`; `oci_ons_notification_topic` `cashapp-<env>-alarms` (+ optional `oci_ons_subscription` for `var.alarm_emails`); `oci_monitoring_alarm` `dlq-depth` (namespace `var.metric_namespace` default `"cashapp"`, query `bus_dlq_depth[5m]{env = "<env>"}.max() > 0`, severity CRITICAL) and `consumer-lag` (`bus_consumer_lag[5m].max() > var.lag_threshold`, default 100, pending duration `PT10M`, severity WARNING). The custom namespace needs no resource (created on first `PostMetricData`). |

### Environments

| Path | Purpose |
|---|---|
| `infra/envs/dev/versions.tf`, `infra/envs/prod/versions.tf` | `required_version >= 1.6`, `oracle/oci` with the same constraint as s01's root (copied literally) |
| `infra/envs/{dev,prod}/providers.tf` | `provider "oci" { region = "us-ashburn-1" tenancy_ocid = var.tenancy_ocid }` (literal region, auth from the caller's OCI config / s44's OIDC) |
| `infra/envs/{dev,prod}/variables.tf` | `tenancy_ocid`, `compartment_ocid`, `region` (validated), `image_tag` (default `"bootstrap"`), `certificate_ocid`, `web_hostname`, `api_hostname`, `fusion_pods` (map pod → `{base_url, username, is_production}`), `fusion_default_pod`, `identity` (`issuer`, `jwks_url`, `audience`, `oidc_client_id`), `genai_units`, `genai_unit_shape`, `worker_groups`, `sizes`, `partitions`, `alarm_emails` |
| `infra/envs/{dev,prod}/main.tf` | `locals { environment = "dev"/"prod" }`, `check "region_is_ashburn" { assert { condition = var.region == "us-ashburn-1" … } }`, and the nine module blocks wired together; builds `local.api_env` / `local.web_env` (below) |
| `infra/envs/{dev,prod}/outputs.tf` | the pinned outputs (below), identical names in both envs |
| `infra/envs/{dev,prod}/terraform.tfvars.example` | non-secret example values; real `*.tfvars` are gitignored (risk 7) |
| `infra/envs/{dev,prod}/backend.tf.example` | `terraform { backend "s3" { … OCI Object Storage S3-compatible endpoint `https://<ns>.compat.objectstorage.us-ashburn-1.oraclecloud.com`, `region = "us-ashburn-1"`, `skip_region_validation`, `skip_credentials_validation`, `use_path_style` … } }`; s44 copies it to `backend.tf` before `init` (see assumption A2) |
| `infra/sql/schemas.sql` | SQL*Plus/SQLcl script, parameters `&1` = schema name (`CASHAPP_DEV`/`CASHAPP_PROD`), `&2` = password (passed by s44 from Vault, never in the file): `CREATE USER … IDENTIFIED BY "&2" QUOTA UNLIMITED ON DATA`; grants `CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, CREATE VIEW, CREATE PROCEDURE`; idempotent (PL/SQL block skips if the user exists). No table DDL. |
| `infra/README.md` | layout, module list, prerequisites (one-time manual: state bucket, OCI Certificates cert, IAM user + auth token for Streaming SASL, setting placeholder secrets' real values, GenAI service limits), `terraform -chdir=infra/envs/dev init -backend=false && … validate`, `plan` usage with `-var-file`, the statement "`terraform apply` is run only by the release pipeline (s44) after Jonathan says release", cost note on the GenAI cluster, how to rotate a secret |
| `api/tests/test_infra_static.py` | static tests (step 5) |

Container environment built in each env's `main.tf` (s27 names; `vault:` = `"vault:${secret_id}"`):

- `api_env` (API and every worker): `CASHAPP_ENV`, `CASHAPP_ATP__DSN` (vault: atp-dsn), `CASHAPP_ATP__USER`
  (`CASHAPP_<ENV>`), `CASHAPP_ATP__PASSWORD` (vault: atp-app-password), `CASHAPP_STREAMING__BOOTSTRAP_SERVERS`
  (pool output), `CASHAPP_STREAMING__SASL_USERNAME` (`<tenancy name>/<user>/<pool ocid>`; user is a variable
  `streaming_user`), `CASHAPP_STREAMING__SASL_PASSWORD` (vault: streaming-auth-token),
  `CASHAPP_STREAMING__CONSUMER_GROUP` (`cashapp-<env>`, never changes), `CASHAPP_OBJECT_STORAGE__NAMESPACE`,
  `CASHAPP_OBJECT_STORAGE__BUCKET`, `CASHAPP_ANTHROPIC__API_KEY` (vault:), `CASHAPP_OCI_GENAI__COMPARTMENT_OCID`,
  `CASHAPP_OCI_GENAI__DEDICATED_ENDPOINT_OCID`, `CASHAPP_IDENTITY__ISSUER/JWKS_URL/AUDIENCE`,
  `CASHAPP_FUSION__DEFAULT_POD`, `CASHAPP_FUSION__WRITE_ENABLED` (`var.fusion_write_enabled`, default `false`),
  `CASHAPP_FUSION__RELATIONSHIPS_REPORT_PATH`, per pod `CASHAPP_FUSION__PODS__<POD>__BASE_URL/USERNAME/IS_PRODUCTION`
  and `__PASSWORD` (vault:), `CASHAPP_INTAKE__DROP_FOLDER`, `CASHAPP_OBSERVABILITY__OCI_MONITORING_NAMESPACE`
  (`cashapp`). SMTP vars only when `var.smtp` is set.
- `web_env`: `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `API_BASE_URL` (`https://<api_hostname>`), `APP_BASE_URL`
  (`https://<web_hostname>`), and **`OIDC_CLIENT_SECRET_VAULT_OCID`, `SESSION_SECRET_VAULT_OCID`** (assumption A3).

## Interfaces provided (pinned; consumed by s44)

Outputs of both `infra/envs/dev` and `infra/envs/prod` (same names, same types):

```hcl
output "region"                        { value = "us-ashburn-1" }
output "environment"                   { value = local.environment }               # "dev" | "prod"
output "ocir_repository_urls"          { value = { api = "iad.ocir.io/<ns>/cashapp/api", web = "iad.ocir.io/<ns>/cashapp/web" } }
output "container_instance_ids"        { value = map(string) }  # keys: "api", "web", "worker-<group>" for each worker_groups key
output "worker_groups"                 { value = map(list(string)) }               # group -> role names (as passed to --roles)
output "load_balancer_ip"              { value = string }
output "web_hostname"                  { value = var.web_hostname }
output "api_hostname"                  { value = var.api_hostname }
output "atp_id"                        { value = string }
output "atp_connect_string_secret_id"  { value = string }      # Vault secret holding the TLS connect string
output "atp_admin_password_secret_id"  { value = string }      # s44 runs schemas.sql / alembic as needed
output "atp_app_password_secret_id"    { value = string }
output "atp_app_schema"                { value = "CASHAPP_DEV" | "CASHAPP_PROD" }
output "atp_schema_script"             { value = "infra/sql/schemas.sql" }
output "stream_pool_id"                { value = string }
output "stream_pool_bootstrap_servers" { value = string }
output "stream_topics"                 { value = list(string) }
output "bucket_name"                   { value = string }
output "object_storage_namespace"      { value = string }
output "genai_endpoint_id"             { value = string }
output "genai_cluster_id"              { value = string }
output "vault_id"                      { value = string }
output "vault_secret_ids"              { value = map(string) }  # secret name (above) -> OCID; nothing sensitive
output "alarm_topic_id"                { value = string }
```

Pinned variable defaults s44 relies on:

```hcl
variable "image_tag"     { type = string, default = "bootstrap" }   # s44 rolls out with -var image_tag=<version>
variable "worker_groups" { default = {
  pollers  = ["intake-poller", "receipt-watcher"]
  bus      = ["relay", "retry-forwarder"]
  llm      = ["classify", "extract", "adjudicate"]
  matching = ["validate", "resolve-customer", "fast-path", "match-receipt", "match-lines", "receipt-arrived"]
  fusion   = ["apply", "write-back", "notify"]
} }
```

Rollout contract for s44: `terraform -chdir=infra/envs/<env> apply -var image_tag=<tag> -var-file=<env>.tfvars`
replaces container instances (image is immutable on a container instance) and re-points LB backends.
Topic contract for s03/s14/s18/s42: topics are pre-created (`auto_create_topics_enable = false`); a new topic
requires a change here.

## Migrations

None. No Alembic revision; the Alembic head is unchanged. `infra/sql/schemas.sql` creates only the schema
user and grants and is run by s44 before `alembic upgrade head`.

## TEST PLAN (written and run in step 5 only; all in `api/tests/test_infra_static.py`)

Helpers in the test module: `INFRA = repo_root / "infra"`, `tf_files()` (all `*.tf`, excluding `.terraform/`),
`blocks(text, kind, type)` regex extraction of `resource "<type>" "<name>" { … }` bodies by brace matching
(no new dependency; `python-hcl2` is not pinned), and `scan_infra(root) -> list[Finding]` used by the AC5 tests.

| AC | Test | Asserts |
|---|---|---|
| 1 | `test_all_modules_present` | the nine module dirs exist, each with `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` |
| 1 | `test_modules_declare_required_resources` | parametrized table module → required resource types (as in the module table) all present |
| 1 | `test_network_only_lb_subnet_public` | exactly one `oci_core_subnet` without `prohibit_public_ip_on_vnic = true`, and it is `lb`; an IGW route is only on the public route table |
| 1 | `test_atp_tls_without_mtls_and_no_admin_password` | `is_mtls_connection_required = false`; `secret_id` set; no `admin_password` attribute; `infra/sql/schemas.sql` exists, has `CREATE USER`, no literal password (`IDENTIFIED BY "&2"` only) |
| 1 | `test_streaming_topics_match_consumed_stages` | `var.stages` default (parsed) == `[s.value.lower() for s in CONSUMED_STAGES]`; `extra_topics` default == `["receipt-arrived", "notify"]`; `partitions` is a variable; topic local builds `.retry` and `.dlq` |
| 1 | `test_vault_secrets_never_hold_values` | every `oci_vault_secret` (except `atp-dsn`) has `enable_auto_generation = true` or `ignore_changes` containing `secret_content`; placeholder secrets cover anthropic, streaming token, oidc, session, atp passwords, fusion per pod; no banned resource (`random_password`, `random_string`, `oci_identity_auth_token`, `oci_load_balancer_certificate`, `tls_private_key`) anywhere |
| 1 | `test_compute_instances_and_repos` | OCIR repos `cashapp/api`, `cashapp/web` private; container instances for api, web and `for_each` workers; worker command uses `cashapp.workers run --roles`; LB listener uses `certificate_ids` |
| 1 | `test_genai_cluster_sized_by_variable_with_cost_comment` | `unit_count = var.genai_units`; module text contains a comment mentioning hourly cost |
| 1 | `test_iam_policy_covers_runtime_needs` | policy statements contain `read secret-bundles`, `stream-push`, `stream-pull`, `manage objects`, `generative-ai`, `use metrics`, `log-content`, `read repos`; dynamic group matches `computecontainerinstance` |
| 1 | `test_observability_alarms_on_dlq_and_lag` | `oci_logging_log_group` present; two `oci_monitoring_alarm` with queries on `bus_dlq_depth` and `bus_consumer_lag` in namespace var default `cashapp` |
| 2 | `test_envs_compose_every_module` (parametrized dev/prod) | `main.tf` has a `module` block with `source = "../../modules/<m>"` for all nine |
| 2 | `test_env_region_literal_and_check_block` (parametrized) | provider `region = "us-ashburn-1"` literal (no `var.` on that line); a `check` block asserting `us-ashburn-1`; `region` variable validation present in envs and every module |
| 3 | `test_private_endpoints_and_cmk` | ATP has `subnet_id` + `private_endpoint_label`; stream pool has `private_endpoint_settings`; GenAI endpoint references `generative_ai_private_endpoint_id`; bucket has `kms_key_id` and `access_type = "NoPublicAccess"` and `versioning = "Enabled"` |
| 4 | `test_terraform_fmt_and_validate_envs` (`skipif terraform not on PATH`, parametrized dev/prod) | `init -backend=false`, `fmt -check -recursive` (on `infra/`), `validate` exit 0 |
| 4 | `test_readme_documents_plan_and_release_only_apply` | `infra/README.md` contains `terraform plan`, `-backend=false`, and states apply is s44/release-only; no `.tf` / script in `infra/` runs `apply` |
| 5 | `test_no_region_other_than_ashburn` | `scan_infra(INFRA)` finds no region-like token (`\b(?:[a-z]{2}|[a-z]{2}-[a-z]+)-[a-z]+-\d\b` and OCIR region keys `\b[a-z]{3}\.ocir\.io` other than `iad`) except `us-ashburn-1` in any file under `infra/` (`.tf`, `.sql`, `.md`, `.example`, `.hcl`) |
| 5 | `test_only_oci_and_hashicorp_utility_providers` | every `source =` in `required_providers` and every provider in `.terraform.lock.hcl` files is `oracle/oci` or `hashicorp/{null,time,local,external,cloudinit,http}` |
| 5 | `test_scanner_flags_foreign_region_and_provider` | `scan_infra(tmp_path)` with a fake `.tf` containing `eu-frankfurt-1` and `hashicorp/aws` reports both (proves the guard is not vacuous) |
| 6 | `test_env_outputs_exported_for_release` (parametrized) | `outputs.tf` declares every pinned output name; dev and prod name sets are equal |

## Assumptions / deviations (logged)

- **A1** One ATP per environment; "separate DEV and PROD schemas" = `CASHAPP_DEV` in the dev ATP and
  `CASHAPP_PROD` in the prod ATP, created by `schemas.sql` run by s44.
- **A2** s01's test asserts no `backend` block in `infra/`. Remote state (OCI Object Storage, S3-compatible) is
  therefore shipped as `backend.tf.example` per env; s44 copies it to `backend.tf` in the CI workspace only (never
  committed) before `terraform init`. Local `validate` uses `-backend=false`.
- **A3** Container Instances cannot inject Vault secrets as env values, and the web app (s27 `env.ts`) reads
  plain values. The web container gets `OIDC_CLIENT_SECRET_VAULT_OCID` and `SESSION_SECRET_VAULT_OCID`; s44's
  `web/Dockerfile` entrypoint resolves them through the resource principal before `node server.js`. The
  Python side needs nothing extra (s27 resolves `vault:`).
- **A4** The LB TLS certificate is an OCI Certificates-service certificate created once out of band
  (`certificate_ocid` variable), so no private key enters state. DNS for `web_hostname`/`api_hostname` is out
  of band; outputs give the LB IP.
- **A5** Streaming SASL uses an IAM user auth token; the user and token are created manually (a token
  resource would put the token in state). `streaming_user` is a variable.
- **A6** Worker role groups use s30 role names known today; `receipt-watcher`/`receipt-arrived` (s14),
  `notify` (s42), `fast-path` (s16) are taken from their stories.
- **A7** Image rollout is `terraform apply -var image_tag=…` by s44 (container instance images are immutable),
  rather than an imperative CLI update, so Terraform state stays the truth.

## Risks

1. **Terraform is not installed** on this machine (s01 notes the same). Coder installs it (winget or the
   HashiCorp zip); otherwise the fmt/validate test skips and the gate is recorded as not run.
2. **Provider attribute names** for newer services (GenAI private endpoint, `secret_generation_context`,
   ATP `secret_id`, container instance `vnics[0].private_ip`, routing policy) may differ in the pinned `oracle/oci`
   major: verify with `terraform providers schema -json`; adjust and record. Unverifiable items get a `# VERIFY`
   comment and are listed in the README "first plan" checklist.
3. **GenAI unit shape for `cohere.command-a-vision`** is not confirmed; `genai_unit_shape` has no reliance on a
   guessed default being right (default chosen from the provider docs at coding time, `# VERIFY` against a live
   `plan` before release). Cluster costs per hour: dev default `genai_units = 1`.
4. **Service limits:** 32 streams/env and their partitions, dedicated AI cluster units, Container Instance
   OCPUs. README lists the limit requests. Stream names with dots are valid Kafka topic names; VERIFY that OCI
   stream naming accepts them (s03 already depends on it).
5. **Resource principal env var** (`OCI_RESOURCE_PRINCIPAL_VERSION`) in Container Instances is what s27's
   `VaultSecretSource.from_environment` keys on: VERIFY on first release; if absent, set it explicitly in `api_env`.
6. **s30 discovery** fails on an unknown role name; if a story renames a role, the worker group default here
   must change. `test_env_outputs_exported_for_release` doesn't catch that; s44 smoke does.
7. **tfvars hygiene:** only `*.tfvars.example` is committed; coder adds `*.tfvars` (but not `*.tfvars.example`)
   to the root `.gitignore` — the only edit outside `infra/`/test file (one line, s01 owns the file; merger notes it).
