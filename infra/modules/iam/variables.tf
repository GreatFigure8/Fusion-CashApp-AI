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

variable "tenancy_ocid" {
  description = "Tenancy OCID; dynamic groups and policies are placed here."
  type        = string
}

variable "vault_id" {
  description = "Vault whose secret bundles the containers may read."
  type        = string
}

variable "key_id" {
  description = "Master key used by Object Storage."
  type        = string
}

variable "bucket_name" {
  description = "Artifact bucket the containers may manage objects in."
  type        = string
}

variable "genai_endpoint_id" {
  description = "Generative AI dedicated endpoint the containers may call."
  type        = string
}

variable "metric_namespace" {
  description = "Custom metric namespace the containers post to."
  type        = string
  default     = "cashapp"
}
