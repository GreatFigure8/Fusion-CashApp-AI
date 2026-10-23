output "ocir_repository_urls" {
  description = "Image repository URLs without a tag."
  value = {
    api = "${local.ocir_base}/api"
    web = "${local.ocir_base}/web"
  }
}

output "container_instance_ids" {
  description = "Container instance OCIDs keyed api, web and worker-<group>."
  value = merge(
    {
      api = oci_container_instances_container_instance.api.id
      web = oci_container_instances_container_instance.web.id
    },
    { for name, instance in oci_container_instances_container_instance.worker : name => instance.id },
  )
}

output "worker_groups" {
  description = "Worker group name to the role names passed to --roles."
  value       = var.worker_groups
}

output "load_balancer_ip" {
  description = "Public IP address of the load balancer."
  value       = oci_load_balancer_load_balancer.this.ip_address_details[0].ip_address
}
