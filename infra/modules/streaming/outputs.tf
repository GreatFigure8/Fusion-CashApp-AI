output "stream_pool_id" {
  description = "OCID of the stream pool."
  value       = oci_streaming_stream_pool.this.id
}

output "bootstrap_servers" {
  description = "Kafka bootstrap server of the stream pool (host:port)."
  value       = oci_streaming_stream_pool.this.kafka_settings[0].bootstrap_servers
}

output "topics" {
  description = "Full topic names."
  value       = sort(values(local.topics))
}
