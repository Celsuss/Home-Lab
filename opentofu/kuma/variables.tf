variable "uptime_kuma_endpoint" {
  description = "Uptime Kuma URL"
  type        = string
  default     = "https://uptime-kuma.homelab.local"
}

variable "uptime_kuma_username" {
  description = "Uptime Kuma admin username"
  type        = string
  sensitive   = true
}

variable "uptime_kuma_password" {
  description = "Uptime Kuma admin password"
  type        = string
  sensitive   = true
}

variable "notification_webhook_url" {
  description = "Webhook URL for alerts (Discord, Slack, Telegram, etc.)"
  type        = string
  default     = ""
  sensitive   = true
}

variable "monitored_services" {
  description = "Map of services to monitor with their URLs and check intervals"
  type = map(object({
    url      = string
    interval = optional(number, 60)
  }))
  default = {
    argocd          = { url = "https://argocd.homelab.local" }
    audiobookshelf  = { url = "https://audiobookshelf.homelab.local" }
    beszel          = { url = "https://beszel.homelab.local" }
    donetick        = { url = "https://donetick.homelab.local" }
    ezbookkeeping   = { url = "https://ezbookkeeping.homelab.local" }
    forgejo         = { url = "https://forgejo.homelab.local" }
    glance          = { url = "https://glance.homelab.local" }
    jellyfin        = { url = "https://jellyfin.homelab.local" }
    kanidm          = { url = "https://kanidm.homelab.local" }
    karakeep        = { url = "https://karakeep.homelab.local" }
    khoj            = { url = "https://khoj.homelab.local" }
    ollama          = { url = "https://ollama.homelab.local", interval = 120 }
    open-webui      = { url = "https://open-webui.homelab.local" }
    tandoor-recipes = { url = "https://tandoor.homelab.local" }
    uptime-kuma     = { url = "https://uptime-kuma.homelab.local" }
    vault           = { url = "https://vault.homelab.local" }
    woodpecker      = { url = "https://woodpecker.homelab.local" }
  }
}
