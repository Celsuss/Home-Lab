output "s3_endpoint" {
  description = "Backblaze B2 S3-compatible endpoint"
  value       = var.b2_s3_endpoint
}

output "bucket_credentials" {
  description = "Per-bucket S3 credentials for Volsync"
  value = {
    for name, _ in var.buckets : name => {
      bucket_name       = b2_bucket.volsync[name].bucket_name
      bucket_id         = b2_bucket.volsync[name].bucket_id
      access_key_id     = b2_application_key.volsync[name].application_key_id
      secret_access_key = b2_application_key.volsync[name].application_key
    }
  }
  sensitive = true
}
