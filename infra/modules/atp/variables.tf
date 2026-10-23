variable "compartment_ocid" {
  description = "OCID of the compartment that holds the environment's resources."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be \"dev\" or \"prod\"."
  }
}

variable "region" {
  description = "OCI region. Hosting is Ashburn only."
  type        = string
  default     = "us-ashburn-1"

  validation {
    condition     = var.region == "us-ashburn-1"
    error_message = "region must be us-ashburn-1; hosting is Ashburn only."
  }
}

variable "freeform_tags" {
  description = "Extra freeform tags merged over the standard app and env tags."
  type        = map(string)
  default     = {}
}

locals {
  tags = merge(var.freeform_tags, { app = "cashapp", env = var.environment })
}

variable "subnet_id" {
  description = "Database subnet OCID (private endpoint)."
  type        = string
}

variable "nsg_ids" {
  description = "NSG OCIDs attached to the database private endpoint."
  type        = list(string)
}

variable "vault_id" {
  description = "Vault that stores the connect-string secret."
  type        = string
}

variable "key_id" {
  description = "Master key that encrypts the connect-string secret."
  type        = string
}

variable "admin_password_secret_id" {
  description = "Vault secret (auto-generated) that holds the ADMIN password."
  type        = string
}

variable "admin_password_secret_version" {
  description = "Version number of the admin password secret to use."
  type        = number
  default     = 1
}

variable "compute_count" {
  description = "ECPU count."
  type        = number
  default     = 2
}

variable "data_storage_size_in_gb" {
  description = "Storage in GB."
  type        = number
  default     = 128
}

variable "is_auto_scaling_enabled" {
  description = "Allow compute auto scaling."
  type        = bool
  default     = true
}

variable "license_model" {
  description = "LICENSE_INCLUDED or BRING_YOUR_OWN_LICENSE."
  type        = string
  default     = "LICENSE_INCLUDED"
}
