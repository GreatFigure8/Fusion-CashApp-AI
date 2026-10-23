# Credentials come from the caller's OCI config or the release pipeline's OIDC identity.
provider "oci" {
  region       = "us-ashburn-1"
  tenancy_ocid = var.tenancy_ocid
}
