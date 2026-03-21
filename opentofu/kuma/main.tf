terraform {
  required_providers {
    uptimekuma = {
      source  = "breml/uptimekuma"
      version = "~> 0.1.12"
    }
  }
}

provider "uptimekuma" {
  endpoint = var.uptime_kuma_endpoint
  username = var.uptime_kuma_username
  password = var.uptime_kuma_password
}
