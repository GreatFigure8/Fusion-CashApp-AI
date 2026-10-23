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
  description = "Subnet OCID for the generative AI private endpoint."
  type        = string
}

variable "nsg_ids" {
  description = "NSG OCIDs for the private endpoint."
  type        = list(string)
}

variable "genai_units" {
  description = "Dedicated AI cluster unit count. Billed hourly per unit whether used or not."
  type        = number
  default     = 1
}

variable "genai_unit_shape" {
  description = "Hosting unit shape for the model. VERIFY against a live plan before release."
  type        = string
  default     = "LARGE_GENERIC"
}

variable "genai_model_name" {
  description = "Base model display name hosted on the dedicated cluster."
  type        = string
  default     = "cohere.command-a-vision"
}
