# One Autonomous AI Database per environment, on a private endpoint with TLS (no wallet, no mTLS).
# The application schema (CASHAPP_DEV / CASHAPP_PROD) is created by infra/sql/schemas.sql, which the
# release (s44) runs with the ADMIN password read from Vault; Alembic owns every table.

locals {
  db_name = upper("cashapp${var.environment}")

  # TLS (server-authenticated) HIGH profile; there is no wallet to ship.
  tls_high = [
    for p in oci_database_autonomous_database.this.connection_strings[0].profiles : p.value
    if p.consumer_group == "HIGH" && p.tls_authentication == "SERVER" && p.protocol == "TCPS"
  ]
}

resource "oci_database_autonomous_database" "this" {
  compartment_id              = var.compartment_ocid
  db_name                     = local.db_name
  display_name                = "cashapp-${var.environment}"
  db_workload                 = "OLTP"
  compute_model               = "ECPU"
  compute_count               = var.compute_count
  data_storage_size_in_gb     = var.data_storage_size_in_gb
  is_auto_scaling_enabled     = var.is_auto_scaling_enabled
  license_model               = var.license_model
  is_mtls_connection_required = false
  subnet_id                   = var.subnet_id
  nsg_ids                     = var.nsg_ids
  private_endpoint_label      = "cashapp${var.environment}"
  vault_id                    = var.vault_id
  secret_id                   = var.admin_password_secret_id
  secret_version_number       = var.admin_password_secret_version
  freeform_tags               = local.tags
}

# The connect string is not a secret. It is stored in Vault so the application reads every
# setting uniformly as a vault: reference.
resource "oci_vault_secret" "dsn" {
  compartment_id = var.compartment_ocid
  vault_id       = var.vault_id
  key_id         = var.key_id
  secret_name    = "cashapp-${var.environment}-atp-dsn"
  description    = "ATP TLS connect string"
  freeform_tags  = local.tags

  secret_content {
    content_type = "BASE64"
    content      = base64encode(length(local.tls_high) > 0 ? local.tls_high[0] : "")
  }
}
