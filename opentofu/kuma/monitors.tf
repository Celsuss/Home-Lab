resource "uptimekuma_monitor_http" "services" {
  for_each = var.monitored_services

  name     = each.key
  url      = each.value.url
  interval = each.value.interval

  accepted_status_codes = ["200-299", "301", "302"]
  ignore_tls           = true
}
