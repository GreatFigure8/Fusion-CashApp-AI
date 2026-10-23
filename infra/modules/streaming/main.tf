locals {
  # Short topic names: <stage>, <stage>.retry, <stage>.dlq and the extra topics.
  stage_topics = flatten([for s in var.stages : [s, "${s}.retry", "${s}.dlq"]])
  short_names  = concat(local.stage_topics, var.extra_topics)

  # Full Kafka topic names, keyed by short name: <prefix>.<env>.<short name>.
  topics = { for n in local.short_names : n => "${var.topic_prefix}.${var.environment}.${n}" }
}

resource "oci_streaming_stream_pool" "this" {
  compartment_id = var.compartment_ocid
  name           = "cashapp-${var.environment}"
  freeform_tags  = local.tags

  # Topics are pre-created below; a new topic needs a change here.
  kafka_settings {
    auto_create_topics_enable = false
    log_retention_hours       = var.retention_hours
    num_partitions            = var.default_partitions
  }

  private_endpoint_settings {
    subnet_id = var.subnet_id
    nsg_ids   = var.nsg_ids
  }

  custom_encryption_key {
    kms_key_id = var.kms_key_id
  }
}

resource "oci_streaming_stream" "topic" {
  for_each = local.topics

  name               = each.value
  stream_pool_id     = oci_streaming_stream_pool.this.id
  partitions         = lookup(var.partitions, each.key, var.default_partitions)
  retention_in_hours = var.retention_hours
  freeform_tags      = local.tags
}
