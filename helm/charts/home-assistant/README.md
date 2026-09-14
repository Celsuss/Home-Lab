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

## Assist: local LLM via Ollama

The conversation agent is the in-cluster Ollama (`helm/charts/ollama`,
namespace `ai-workloads`). The model is pinned declaratively in
`ollama/values.yaml` under `models.list`; the system prompt is versioned in
`docs/home-assistant/system-prompt.md`. Roadmap: `HOME-ASSISTANT-AI-PLAN.md`.

The integration itself is a config flow that writes to HA's `.storage`, so it
is set up once in the UI (repeat after a rebuild of the `/config` PVC):

1. **Settings → Devices & services → Add integration → Ollama**
   - URL: `http://ollama.ai-workloads.svc.cluster.local:11434`
     (resolves because the pod runs with `dnsPolicy: ClusterFirstWithHostNet`)
   - Model: the assistant model from `ollama/values.yaml` (`gemma4:e4b-it-q8_0`)
2. **Configure** the integration:
   - Instructions: paste the prompt from `docs/home-assistant/system-prompt.md`
   - Control Home Assistant: **Assist** (lets the LLM call services)
   - **Prefer handling commands locally**: on — built-in intents answer
     instantly, the LLM is only the fallback
3. **Settings → Voice assistants → Home Assistant** (the default assistant) →
   Conversation agent: **Ollama**.

### Assist conventions (do this for every new device)

The LLM only sees entities that are **exposed** to Assist, and it identifies
them by name, area and aliases. Answer quality depends on keeping this tidy:

- **Expose sparingly.** Settings → Voice assistants → Expose. Expose the
  lights, switches, climate, media players and the handful of sensors you
  actually ask about. Every exposed entity is sent in the prompt on every
  request; a big list slows the model down and makes it pick wrong entities.
  Do not expose diagnostic/config entities, or anything destructive
  (locks, alarm disarm) — see Phase 5.4 of the plan.
- **Friendly names.** Rename entities to what you would say out loud
  ("Kitchen ceiling light", not "Shelly 1PM 3F2A"). Keep the area name out
  of the entity name if the device is in an Area — HA adds it.
- **Every device in an Area.** Kitchen, Living room, Bedroom, … — the LLM
  uses areas to resolve "the lights in here" and "bedroom temperature". Keep
  the list in `docs/home-assistant/system-prompt.md` in sync.
- **Aliases** for alternate wording (Settings → Voice assistants → Expose →
  entity → Aliases): "TV" / "telly" / "tv:n", Swedish and English forms.
- **Test in Assist after changes** (the chat bubble top-right, or Settings →
  Voice assistants → Assist debug) — the debug view shows whether a command
  hit a local intent or fell through to the LLM.

## Future: Zigbee / Z-Wave USB coordinators

When you add a USB coordinator stick you'll need a `hostPath` device volume
(e.g. `/dev/ttyUSB0`), `nodeSelector` pinning HA to the node with the stick,
and device/privileged access. Not configured yet.
