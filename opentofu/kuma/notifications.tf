resource "uptimekuma_notification_webhook" "alerts" {
  count = var.notification_webhook_url != "" ? 1 : 0

  name            = "homelab-alerts"
  webhook_url     = var.notification_webhook_url
  is_default      = true
  apply_existing  = true
}
