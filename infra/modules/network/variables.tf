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

variable "vcn_cidr" {
  description = "CIDR block of the VCN."
  type        = string
  default     = "10.20.0.0/16"
}

variable "subnet_cidrs" {
  description = "CIDR block per subnet: lb, app, db, genai."
  type        = map(string)
  default = {
    lb        = "10.20.0.0/24"
    app       = "10.20.1.0/24"
    db        = "10.20.2.0/24"
    genai     = "10.20.4.0/24"
  }

  validation {
    condition     = alltrue([for k in ["lb", "app", "db", "genai"] : contains(keys(var.subnet_cidrs), k)])
    error_message = "subnet_cidrs must define lb, app, db and genai."
  }
}
