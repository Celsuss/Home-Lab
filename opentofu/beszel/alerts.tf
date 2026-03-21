resource "terraform_data" "beszel_config" {
  triggers_replace = {
    cpu_threshold    = var.alert_thresholds.cpu_percent
    memory_threshold = var.alert_thresholds.memory_percent
    disk_threshold   = var.alert_thresholds.disk_percent
    webhook_url      = var.notification_webhook_url
  }

  provisioner "local-exec" {
    command     = "${path.module}/scripts/configure-beszel.sh"
    interpreter = ["bash", "-e"]
    environment = {
      BESZEL_URL         = var.beszel_endpoint
      BESZEL_EMAIL       = var.beszel_admin_email
      BESZEL_PASSWORD    = var.beszel_admin_password
      WEBHOOK_URL        = var.notification_webhook_url
      CPU_THRESHOLD      = var.alert_thresholds.cpu_percent
      MEMORY_THRESHOLD   = var.alert_thresholds.memory_percent
      DISK_THRESHOLD     = var.alert_thresholds.disk_percent
    }
  }
}
