variable "beszel_endpoint" {
  description = "Beszel URL"
  type        = string
  default     = "https://beszel.homelab.local"
}

variable "beszel_admin_email" {
  description = "Beszel admin email"
  type        = string
  sensitive   = true
}

variable "beszel_admin_password" {
  description = "Beszel admin password"
  type        = string
  sensitive   = true
}

variable "notification_webhook_url" {
  description = "Shoutrrr-format notification URL (e.g. discord://token@id, telegram://token@telegram?chats=@channel)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "alert_thresholds" {
  description = "Alert threshold configuration"
  type = object({
    cpu_percent    = optional(number, 95)
    memory_percent = optional(number, 90)
    disk_percent   = optional(number, 85)
  })
  default = {}
}
