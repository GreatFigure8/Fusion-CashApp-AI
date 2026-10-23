output "vault_id" {
  description = "OCID of the vault."
  value       = oci_kms_vault.this.id
}

output "key_id" {
  description = "OCID of the master encryption key."
  value       = oci_kms_key.master.id
}

output "secret_ids" {
  description = "Secret name (without the environment prefix) to secret OCID. No values."
  value = merge(
    { for name, secret in oci_vault_secret.generated : name => secret.id },
    { for name, secret in oci_vault_secret.placeholder : name => secret.id },
  )
}
