locals {
  name = "cashapp-${var.environment}"

  # Secrets whose value Vault generates itself. The value never passes through Terraform.
  generated = {
    "atp-admin-password" = { type = "PASSPHRASE", template = "DBAAS_DEFAULT_PASSWORD", description = "ATP ADMIN password (generated)" }
    "atp-app-password"   = { type = "PASSPHRASE", template = "DBAAS_DEFAULT_PASSWORD", description = "ATP application schema password (generated)" }
    "session-secret"     = { type = "BYTES", template = "BYTES_512", description = "Web session encryption secret (generated)" }
  }

  # Secrets created with a fixed non-secret placeholder. The operator sets the real value in Vault;
  # ignore_changes keeps Terraform from ever reading or resetting it.
  placeholders = merge(
    {
      "streaming-auth-token" = "IAM auth token for the Streaming SASL user"
      "anthropic-api-key"    = "Anthropic API key (zero data retention organisation)"
      "oidc-client-secret"   = "OCI IAM Identity Domain confidential application client secret"
      "smtp-password"        = "SMTP password for notifications"
    },
    { for pod in var.fusion_pods : "fusion-${pod}-password" => "Fusion integration user password for pod ${pod}" },
  )
}

resource "oci_kms_vault" "this" {
  compartment_id = var.compartment_ocid
  display_name   = local.name
  vault_type     = "DEFAULT"
  freeform_tags  = local.tags
}

resource "oci_kms_key" "master" {
  compartment_id      = var.compartment_ocid
  display_name        = "${local.name}-master"
  management_endpoint = oci_kms_vault.this.management_endpoint
  protection_mode     = "HSM"
  freeform_tags       = local.tags

  key_shape {
    algorithm = "AES"
    length    = 32
  }
}

resource "oci_vault_secret" "generated" {
  for_each = local.generated

  compartment_id         = var.compartment_ocid
  vault_id               = oci_kms_vault.this.id
  key_id                 = oci_kms_key.master.id
  secret_name            = "${local.name}-${each.key}"
  description            = each.value.description
  enable_auto_generation = true
  freeform_tags          = local.tags

  secret_generation_context {
    generation_type     = each.value.type
    generation_template = each.value.template
  }
}

resource "oci_vault_secret" "placeholder" {
  for_each = local.placeholders

  compartment_id = var.compartment_ocid
  vault_id       = oci_kms_vault.this.id
  key_id         = oci_kms_key.master.id
  secret_name    = "${local.name}-${each.key}"
  description    = each.value
  freeform_tags  = local.tags

  secret_content {
    content_type = "BASE64"
    content      = base64encode("SET-IN-VAULT")
  }

  lifecycle {
    ignore_changes = [secret_content]
  }
}
