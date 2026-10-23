data "oci_objectstorage_namespace" "this" {
  compartment_id = var.compartment_ocid
}

# Raw remittance artifacts. Never public; versioned; encrypted with the customer-managed key.
resource "oci_objectstorage_bucket" "artifacts" {
  compartment_id        = var.compartment_ocid
  namespace             = data.oci_objectstorage_namespace.this.namespace
  name                  = "cashapp-${var.environment}-artifacts"
  access_type           = "NoPublicAccess"
  versioning            = "Enabled"
  kms_key_id            = var.kms_key_id
  storage_tier          = "Standard"
  object_events_enabled = false
  freeform_tags         = local.tags
}
