variable "tenancy_ocid" {
  description = "OCID of the OCI tenancy."
  type        = string
}

variable "compartment_ocid" {
  description = "OCID of the compartment that holds the environment's resources."
  type        = string
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

variable "image_tag" {
  description = "Image tag rolled out to api, web and workers."
  type        = string
  default     = "bootstrap"
}

variable "certificate_ocid" {
  description = "OCI Certificates-service certificate for the load balancer (created once, out of band)."
  type        = string
}

variable "web_hostname" {
  description = "Public hostname of the web app."
  type        = string
}

variable "api_hostname" {
  description = "Public hostname of the API."
  type        = string
}

variable "fusion_pods" {
  description = "Fusion pods by lower-case key. Passwords live in Vault, never here."
  type = map(object({
    base_url      = string
    username      = string
    is_production = bool
  }))
}

variable "fusion_default_pod" {
  description = "Key of the default Fusion pod."
  type        = string
}

variable "fusion_write_enabled" {
  description = "Whether Fusion writes (apply, write-back) are enabled."
  type        = bool
  default     = false
}

variable "fusion_relationships_report_path" {
  description = "BI Publisher path of the pay-on-behalf relationships report."
  type        = string
}

variable "identity" {
  description = "OCI IAM Identity Domain settings. The client secret lives in Vault."
  type = object({
    issuer         = string
    jwks_url       = string
    audience       = string
    oidc_client_id = string
  })
}

variable "smtp" {
  description = "SMTP settings for notifications; null disables them. The password lives in Vault."
  type = object({
    host         = string
    port         = number
    username     = string
    from_address = string
  })
  default = null
}

variable "drop_folder" {
  description = "Intake drop folder path inside the containers."
  type        = string
  default     = "/data/drop"
}

variable "atp_compute_count" {
  description = "ATP ECPU count."
  type        = number
  default     = 2
}

variable "atp_storage_gb" {
  description = "ATP storage in GB."
  type        = number
  default     = 128
}

variable "genai_units" {
  description = "Dedicated AI cluster units. Billed hourly whether used or not."
  type        = number
  default     = 1
}

variable "genai_unit_shape" {
  description = "Hosting unit shape. VERIFY against a live plan."
  type        = string
  default     = "LARGE_GENERIC"
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
  description = "Container instance sizes keyed api, web, worker-<group>, plus a default."
  type = map(object({
    ocpus         = number
    memory_in_gbs = number
  }))
  default = {
    default = { ocpus = 1, memory_in_gbs = 4 }
  }
}

variable "alarm_emails" {
  description = "Email addresses subscribed to alarms."
  type        = list(string)
  default     = []
}
