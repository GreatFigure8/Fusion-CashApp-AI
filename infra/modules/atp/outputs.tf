output "atp_id" {
  description = "OCID of the Autonomous Database."
  value       = oci_database_autonomous_database.this.id
}

output "connect_string_secret_id" {
  description = "Vault secret holding the TLS connect string."
  value       = oci_vault_secret.dsn.id
}
