# Home Assistant

Home Assistant Container (`ghcr.io/home-assistant/home-assistant`) running on
K3s. Note this is the container flavour — the Supervisor/OS "add-ons" feature is
not available under Kubernetes.

## Networking

Runs with `hostNetwork: true` (+ `dnsPolicy: ClusterFirstWithHostNet`) so mDNS/
DHCP device auto-discovery works on the LAN. HA binds `8123` directly on the
node. Toggle via `hostNetwork` in `values.yaml`.

## Access

- **LAN (Traefik):** https://home-assistant.homelab.local
- **Remote (Tailscale):** `home-assistant.<tailnet>` via the Tailscale ingress.

Both go through a reverse proxy that sets `X-Forwarded-For`. The chart seeds a
`configuration.yaml` with `http.use_x_forwarded_for` + `trusted_proxies` (see
`trustedProxies` in `values.yaml`) on first boot; without it HA returns
`400 Bad Request` for proxied requests. The seed only runs when no
`configuration.yaml` exists yet, so your later edits are preserved.

## Storage

All state (config, SQLite recorder DB) lives on the `/config` PVC
(`persistence.configStorage`, default 10Gi, `local-path`).

## Secrets

No Kubernetes-injected secrets are required — Home Assistant manages its own
`/config/secrets.yaml`. If a future integration needs a K8s secret, add Vault
scaffolding following the repo convention (see `AGENTS.md`).

## Future: Zigbee / Z-Wave USB coordinators

When you add a USB coordinator stick you'll need a `hostPath` device volume
(e.g. `/dev/ttyUSB0`), `nodeSelector` pinning HA to the node with the stick,
and device/privileged access. Not configured yet.
