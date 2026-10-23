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
  description = "Streaming subnet OCID (private endpoint)."
  type        = string
}

variable "nsg_ids" {
  description = "NSG OCIDs attached to the stream pool private endpoint."
  type        = list(string)
}

variable "kms_key_id" {
  description = "Customer-managed key that encrypts the stream pool."
  type        = string
}

variable "topic_prefix" {
  description = "Topic prefix; matches settings.streaming.topic_prefix."
  type        = string
  default     = "cashapp"
}

variable "stages" {
  description = "Consumed pipeline stages (the pipeline's CONSUMED_STAGES, lower-cased). Each gets a main, .retry and .dlq topic."
  type        = list(string)
  default = [
    "classify",
    "extract",
    "adjudicate",
    "validate",
    "resolve_customer",
    "fast_path",
    "match_receipt",
    "match_lines",
    "apply",
    "write_back",
  ]
}

variable "extra_topics" {
  description = "Non-stage topics."
  type        = list(string)
  default     = ["receipt-arrived", "notify"]
}

variable "default_partitions" {
  description = "Partitions for a topic with no entry in var.partitions."
  type        = number
  default     = 3
}

variable "partitions" {
  description = "Partition count overrides keyed by the topic's short name (stage, stage.retry, stage.dlq or extra topic)."
  type        = map(number)
  default     = {}
}

variable "retention_hours" {
  description = "Message retention in hours (OCI Streaming allows 24 to 168)."
  type        = number
  default     = 168
}
