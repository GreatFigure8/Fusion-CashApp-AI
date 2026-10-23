output "alarm_topic_id" {
  description = "OCID of the alarm notification topic."
  value       = oci_ons_notification_topic.alarms.id
}

output "log_group_id" {
  description = "OCID of the log group."
  value       = oci_logging_log_group.this.id
}
