variable "b2_application_key_id" {
  description = "Backblaze B2 master application key ID"
  type        = string
  sensitive   = true
}

variable "b2_application_key" {
  description = "Backblaze B2 master application key"
  type        = string
  sensitive   = true
}

variable "b2_s3_endpoint" {
  description = "Backblaze B2 S3-compatible endpoint (region-specific, e.g. s3.us-west-004.backblazeb2.com)"
  type        = string
}

variable "buckets" {
  description = "Map of B2 buckets to create for Volsync backups"
  type = map(object({
    lifecycle_days = optional(number, 30)
  }))
  default = {
    "lord-homelab-backup" = {}
  }
}
