output "bucket_name" {
  description = "Artifact bucket name."
  value       = oci_objectstorage_bucket.artifacts.name
}

output "namespace" {
  description = "Object Storage namespace of the tenancy."
  value       = data.oci_objectstorage_namespace.this.namespace
}
