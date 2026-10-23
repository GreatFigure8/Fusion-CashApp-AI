output "endpoint_id" {
  description = "OCID of the dedicated generative AI endpoint."
  value       = oci_generative_ai_endpoint.this.id
}

output "cluster_id" {
  description = "OCID of the dedicated AI cluster."
  value       = oci_generative_ai_dedicated_ai_cluster.this.id
}
