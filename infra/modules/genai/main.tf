data "oci_generative_ai_models" "base" {
  compartment_id = var.compartment_ocid

  filter {
    name   = "display_name"
    values = [var.genai_model_name]
  }
}

locals {
  model_id = data.oci_generative_ai_models.base.model_collection[0].items[0].id
}

# COST WARNING: a dedicated AI cluster is billed per unit-hour whether or not it is used.
# On-demand cohere.command-a-vision was retired in Ashburn, so Reader B runs on this cluster.
# Size genai_units for peak extraction throughput, not average load. Cluster utilisation is
# exposed in the flow monitor so the unit count can be tuned against real demand.
resource "oci_generative_ai_dedicated_ai_cluster" "this" {
  compartment_id = var.compartment_ocid
  display_name   = "cashapp-${var.environment}-cohere-vision"
  type           = "HOSTING"
  unit_shape     = var.genai_unit_shape
  unit_count     = var.genai_units
  freeform_tags  = local.tags
}

resource "oci_generative_ai_generative_ai_private_endpoint" "this" {
  compartment_id = var.compartment_ocid
  display_name   = "cashapp-${var.environment}"
  dns_prefix     = "cashapp${var.environment}"
  subnet_id      = var.subnet_id
  nsg_ids        = var.nsg_ids
  freeform_tags  = local.tags
}

resource "oci_generative_ai_endpoint" "this" {
  compartment_id                    = var.compartment_ocid
  display_name                      = "cashapp-${var.environment}-cohere-vision"
  model_id                          = local.model_id
  dedicated_ai_cluster_id           = oci_generative_ai_dedicated_ai_cluster.this.id
  generative_ai_private_endpoint_id = oci_generative_ai_generative_ai_private_endpoint.this.id
  freeform_tags                     = local.tags

  content_moderation_config {
    is_enabled = false
  }
}
