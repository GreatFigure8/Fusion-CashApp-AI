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

# Chat-staged receipt uploads that were never submitted expire after a day. The app has no
# scheduler, so the bucket removes them. Needs the usual object-storage service policy for
# lifecycle rules (`Allow service objectstorage-<region> to manage object-family`).
resource "oci_objectstorage_object_lifecycle_policy" "staging_expiry" {
  namespace = data.oci_objectstorage_namespace.this.namespace
  bucket    = oci_objectstorage_bucket.artifacts.name

  rules {
    name        = "expire-staged-uploads"
    action      = "DELETE"
    is_enabled  = true
    target      = "objects"
    time_amount = 1
    time_unit   = "DAYS"

    object_name_filter {
      inclusion_prefixes = ["staging/"]
    }
  }

  rules {
    name        = "expire-staged-upload-versions"
    action      = "DELETE"
    is_enabled  = true
    target      = "previous-object-versions"
    time_amount = 1
    time_unit   = "DAYS"

    object_name_filter {
      inclusion_prefixes = ["staging/"]
    }
  }
}
