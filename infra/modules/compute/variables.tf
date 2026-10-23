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

variable "app_subnet_id" {
  description = "Private subnet for the container instances."
  type        = string
}

variable "lb_subnet_id" {
  description = "Public subnet for the load balancer."
  type        = string
}

variable "app_nsg_ids" {
  description = "NSG OCIDs for the container instance VNICs."
  type        = list(string)
}

variable "lb_nsg_ids" {
  description = "NSG OCIDs for the load balancer."
  type        = list(string)
}

variable "image_tag" {
  description = "Image tag for api, web and workers; the release rolls out with -var image_tag=<version>."
  type        = string
  default     = "bootstrap"
}

variable "api_env" {
  description = "Environment for the api and every worker container. Secret leaves are vault:<secret-ocid> references."
  type        = map(string)
}

variable "web_env" {
  description = "Environment for the web container."
  type        = map(string)
}

variable "worker_groups" {
  description = "Worker group name to the role names passed to --roles."
  type        = map(list(string))
  default = {
    pollers  = ["intake-poller", "receipt-watcher"]
    bus      = ["relay", "retry-forwarder"]
    llm      = ["classify", "extract", "adjudicate"]
    matching = ["validate", "resolve-customer", "fast-path", "match-receipt", "match-lines", "receipt-arrived"]
    fusion   = ["apply", "write-back", "notify"]
  }
}

variable "sizes" {
  description = "Container instance shape config keyed api, web, worker-<group>; the default key is the fallback."
  type = map(object({
    ocpus         = number
    memory_in_gbs = number
  }))
  default = {
    default = { ocpus = 1, memory_in_gbs = 4 }
  }

  validation {
    condition     = contains(keys(var.sizes), "default")
    error_message = "sizes must contain a \"default\" entry."
  }
}

variable "certificate_ocid" {
  description = "OCI Certificates-service certificate for the load balancer listener (created once, out of band)."
  type        = string
}

variable "api_hostname" {
  description = "Host header routed to the api backend set; everything else goes to web."
  type        = string
}

variable "lb_min_bandwidth_mbps" {
  description = "Flexible load balancer minimum bandwidth."
  type        = number
  default     = 10
}

variable "lb_max_bandwidth_mbps" {
  description = "Flexible load balancer maximum bandwidth."
  type        = number
  default     = 100
}
