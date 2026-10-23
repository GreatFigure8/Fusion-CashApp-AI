output "dynamic_group_name" {
  description = "Name of the container instances' dynamic group."
  value       = oci_identity_dynamic_group.containers.name
}
