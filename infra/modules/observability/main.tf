locals {
  name = "cashapp-${var.environment}"
}

resource "oci_logging_log_group" "this" {
  compartment_id = var.compartment_ocid
  display_name   = local.name
  freeform_tags  = local.tags
}

resource "oci_logging_log" "app" {
  display_name       = "app"
  log_group_id       = oci_logging_log_group.this.id
  log_type           = "CUSTOM"
  is_enabled         = true
  retention_duration = 30
  freeform_tags      = local.tags
}

resource "oci_ons_notification_topic" "alarms" {
  compartment_id = var.compartment_ocid
  name           = "${local.name}-alarms"
  description    = "CashApp ${var.environment} alarms"
  freeform_tags  = local.tags
}

resource "oci_ons_subscription" "email" {
  for_each = toset(var.alarm_emails)

  compartment_id = var.compartment_ocid
  topic_id       = oci_ons_notification_topic.alarms.id
  protocol       = "EMAIL"
  endpoint       = each.value
  freeform_tags  = local.tags
}

# The custom metric namespace needs no resource: it is created on the first PostMetricData.
resource "oci_monitoring_alarm" "dlq_depth" {
  compartment_id        = var.compartment_ocid
  metric_compartment_id = var.compartment_ocid
  display_name          = "${local.name}-dlq-depth"
  namespace             = var.metric_namespace
  query                 = "bus_dlq_depth[5m]{env = \"${var.environment}\"}.max() > 0"
  severity              = "CRITICAL"
  destinations          = [oci_ons_notification_topic.alarms.id]
  is_enabled            = true
  body                  = "Messages are in a dead-letter topic. Dequeue and fix them in the exception workbench."
  freeform_tags         = local.tags
}

resource "oci_monitoring_alarm" "consumer_lag" {
  compartment_id        = var.compartment_ocid
  metric_compartment_id = var.compartment_ocid
  display_name          = "${local.name}-consumer-lag"
  namespace             = var.metric_namespace
  query                 = "bus_consumer_lag[5m]{env = \"${var.environment}\"}.max() > ${var.lag_threshold}"
  severity              = "WARNING"
  pending_duration      = "PT10M"
  destinations          = [oci_ons_notification_topic.alarms.id]
  is_enabled            = true
  body                  = "A stage consumer is falling behind its topic."
  freeform_tags         = local.tags
}
