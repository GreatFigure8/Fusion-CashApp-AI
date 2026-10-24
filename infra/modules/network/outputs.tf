output "vcn_id" {
  description = "OCID of the VCN."
  value       = oci_core_vcn.this.id
}

output "subnet_ids" {
  description = "Subnet OCIDs keyed lb, app, db, genai."
  value = {
    lb        = oci_core_subnet.lb.id
    app       = oci_core_subnet.app.id
    db        = oci_core_subnet.db.id
    genai     = oci_core_subnet.genai.id
  }
}

output "nsg_ids" {
  description = "Network security group OCIDs keyed lb, app, db, genai."
  value       = local.nsg
}
