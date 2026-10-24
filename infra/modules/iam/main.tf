locals {
  name = "cashapp-${var.environment}"
  comp = "compartment id ${var.compartment_ocid}"
}

# Container instances authenticate as a resource principal; no keys are baked into images.
resource "oci_identity_dynamic_group" "containers" {
  compartment_id = var.tenancy_ocid
  name           = "${local.name}-containers"
  description    = "CashApp ${var.environment} container instances"
  matching_rule  = "ALL {resource.type = 'computecontainerinstance', resource.compartment.id = '${var.compartment_ocid}'}"
  freeform_tags  = local.tags
}

resource "oci_identity_policy" "runtime" {
  compartment_id = var.tenancy_ocid
  name           = "${local.name}-runtime"
  description    = "Runtime permissions of CashApp ${var.environment} containers"
  freeform_tags  = local.tags

  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.containers.name} to read secret-bundles in ${local.comp} where target.vault.id = '${var.vault_id}'",
    "Allow dynamic-group ${oci_identity_dynamic_group.containers.name} to manage objects in ${local.comp} where target.bucket.name = '${var.bucket_name}'",
    # VERIFY: scope to the endpoint (target.generativeai-endpoint.id) if the policy language allows it.
    "Allow dynamic-group ${oci_identity_dynamic_group.containers.name} to use generative-ai-family in ${local.comp}",
    "Allow dynamic-group ${oci_identity_dynamic_group.containers.name} to use metrics in ${local.comp} where target.metrics.namespace = '${var.metric_namespace}'",
    "Allow dynamic-group ${oci_identity_dynamic_group.containers.name} to use log-content in ${local.comp}",
    "Allow dynamic-group ${oci_identity_dynamic_group.containers.name} to read repos in ${local.comp}",
  ]
}

# Service principals that need the customer-managed key.
resource "oci_identity_policy" "services" {
  compartment_id = var.tenancy_ocid
  name           = "${local.name}-services"
  description    = "Services that use the CashApp ${var.environment} master key"
  freeform_tags  = local.tags

  statements = [
    "Allow service objectstorage-${var.region} to use keys in ${local.comp} where target.key.id = '${var.key_id}'",
  ]
}
