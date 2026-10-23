output "region" {
  description = "Hosting region."
  value       = "us-ashburn-1"
}

output "environment" {
  description = "Environment name."
  value       = local.environment
}

output "ocir_repository_urls" {
  description = "Image repository URLs (api, web) without a tag."
  value       = module.compute.ocir_repository_urls
}

output "container_instance_ids" {
  description = "Container instance OCIDs keyed api, web and worker-<group>."
  value       = module.compute.container_instance_ids
}

output "worker_groups" {
  description = "Worker group to the role names passed to --roles."
  value       = module.compute.worker_groups
}

output "load_balancer_ip" {
  description = "Public IP of the load balancer; DNS for the hostnames is managed out of band."
  value       = module.compute.load_balancer_ip
}

output "web_hostname" {
  description = "Public web hostname."
  value       = var.web_hostname
}

output "api_hostname" {
  description = "Public API hostname."
  value       = var.api_hostname
}

output "atp_id" {
  description = "OCID of the Autonomous Database."
  value       = module.atp.atp_id
}

output "atp_connect_string_secret_id" {
  description = "Vault secret holding the TLS connect string."
  value       = module.atp.connect_string_secret_id
}

output "atp_admin_password_secret_id" {
  description = "Vault secret holding the ADMIN password (used by the release to create the schema)."
  value       = module.vault.secret_ids["atp-admin-password"]
}

output "atp_app_password_secret_id" {
  description = "Vault secret holding the application schema password."
  value       = module.vault.secret_ids["atp-app-password"]
}

output "atp_app_schema" {
  description = "Application schema created by infra/sql/schemas.sql."
  value       = local.schema_name
}

output "atp_schema_script" {
  description = "Script the release runs to create the schema."
  value       = "infra/sql/schemas.sql"
}

output "stream_pool_id" {
  description = "OCID of the stream pool."
  value       = module.streaming.stream_pool_id
}

output "stream_pool_bootstrap_servers" {
  description = "Kafka bootstrap server of the stream pool."
  value       = module.streaming.bootstrap_servers
}

output "stream_topics" {
  description = "Every pre-created topic."
  value       = module.streaming.topics
}

output "bucket_name" {
  description = "Artifact bucket name."
  value       = module.object_storage.bucket_name
}

output "object_storage_namespace" {
  description = "Object Storage namespace."
  value       = module.object_storage.namespace
}

output "genai_endpoint_id" {
  description = "OCID of the dedicated generative AI endpoint."
  value       = module.genai.endpoint_id
}

output "genai_cluster_id" {
  description = "OCID of the dedicated AI cluster."
  value       = module.genai.cluster_id
}

output "vault_id" {
  description = "OCID of the vault."
  value       = module.vault.vault_id
}

output "vault_secret_ids" {
  description = "Secret name to OCID. No values."
  value       = local.secret_ids
}

output "alarm_topic_id" {
  description = "OCID of the alarm notification topic."
  value       = module.observability.alarm_topic_id
}

output "migration_env" {
  description = "Environment for the release migration container only: the bootstrap set plus the legacy variables the s48 data migration seeds the DB settings from."
  value       = merge(local.api_env, local.settings_seed_env)
  sensitive   = true
}
