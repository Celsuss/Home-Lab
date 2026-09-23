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

## YAML in git: `packages/`

Every `packages/*.yaml` file in this chart is rendered into a ConfigMap and
mounted read-only at `/config/packages`; `configuration.yaml` loads the
directory with `homeassistant: packages: !include_dir_named packages`. This is
the mechanism for all HA YAML (automations, scripts, helpers, template
sensors…) — add a file, commit, ArgoCD syncs, the pod restarts (the
deployment carries a `checksum/packages` annotation) and HA loads it. Files
are copied verbatim, so HA's own Jinja templates are fine; there is no Helm
templating inside packages.

- Automations/scripts from packages show up in the UI but are **read-only**
  there; UI-created ones keep living in `automations.yaml` alongside them.
- Give every automation a stable `id:` so traces/enable state survive edits.
- The init container appends the `packages:` include to an existing
  `configuration.yaml` once if it's missing. If you already have your own
  `homeassistant:` block it refuses (duplicate key) and logs a warning — add
  `packages: !include_dir_named packages` under it by hand.
- A broken package fails HA's config check at startup (HA keeps the old
  config and shows a repair). Validate before pushing:
  Settings → System → Repairs, or `ha` logs.

Current packages: `announcements.yaml` (Phase 2 Google Home smoke test),
`telegram.yaml` (Phase 4 Telegram chat).

## Secrets

No Kubernetes-injected secrets are required — Home Assistant manages its own
`/config/secrets.yaml`. If a future integration needs a K8s secret, add Vault
scaffolding following the repo convention (see `AGENTS.md`).

Credentials that are entered through a UI config flow (e.g. the Telegram bot
token) live in HA's `.storage`, but are **also** kept in Vault as the source of
record so they can be re-entered after a `/config` rebuild:

```bash
vault kv get secret/homelab/home-assistant
```

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

## Voice pipeline (Wyoming)

Speech-to-text, text-to-speech and wake word run as their own charts in this
namespace (HA Container has no add-ons): `wyoming-whisper`, `wyoming-piper`,
`wyoming-openwakeword`. Each README documents its options; this is the HA
side, again a UI config flow (repeat after a `/config` rebuild):

1. **Settings → Devices & services → Add integration → Wyoming Protocol**,
   three times:
   | Host                                                    | Port    | Provides                |
   |---------------------------------------------------------|---------|-------------------------|
   | `wyoming-whisper.home-assistant.svc.cluster.local`      | `10300` | STT (faster-whisper)    |
   | `wyoming-piper.home-assistant.svc.cluster.local`        | `10200` | TTS (Piper, all voices) |
   | `wyoming-openwakeword.home-assistant.svc.cluster.local` | `10400` | Wake word               |
2. **Settings → Voice assistants → Home Assistant** (or add a second
   assistant for the other language — HA sends the assistant's language to
   Whisper and the chosen voice to Piper, so one deployment of each serves
   both):
   - Language: Swedish (or English)
   - Conversation agent: **Ollama** (Phase 1)
   - Speech-to-text: **faster-whisper**
   - Text-to-speech: **piper**, voice `sv_SE-nst-medium` (`en_US-lessac-medium`
     for English)
   - Wake word: **openWakeWord** → `okay_nabu` (only used by streaming
     satellites / the "always listening" browser mode)
3. Test: the microphone icon in the Assist dialog (web UI, needs HTTPS — use
   the Traefik or Tailscale URL, not plain `http://192.168.0.142:8123`) and
   the Companion app (Assist → tap-to-talk). Settings → Voice assistants →
   ⋮ → **Debug** shows each stage's timing (STT / intent / TTS).
4. Optional accuracy boost: create a long-lived token for Whisper's
   name-biasing (`helm/charts/wyoming-whisper/README.md`).
5. Google Home as output: expose the Cast `media_player` to Assist with an
   alias ("kitchen speaker") so volume/play/pause work by voice, and add the
   smoke-test announcement from `docs/home-assistant/announcements.md`.

## Telegram: chat with the assistant

Phase 4 of the plan. Messages to a Telegram bot go to the same Ollama
conversation agent as Assist, and the answer is sent back — including device
commands. HA's built-in **Telegram bot** integration does the transport; the
glue is `packages/telegram.yaml` (automation `telegram_assist_chat`). No extra
services.

One-time setup:

1. **Create the bot**: message `@BotFather` → `/newbot`, keep the token. Get
   your numeric user id from `@userinfobot`. Send your new bot `/start` once
   (Telegram bots cannot message a user who hasn't started them).
2. **Vault** (source of record):
   ```bash
   vault kv put secret/homelab/home-assistant \
     TELEGRAM_BOT_TOKEN=123456:ABC... TELEGRAM_ALLOWED_CHAT_ID=123456789
   ```
3. **HA UI → Settings → Devices & services → Add integration → Telegram bot**
   - Platform: **Polling** (outbound only; webhooks would need a public URL)
   - API key: the token. Leave API endpoint / proxy at defaults.
   - After it's created: entry ⋮ → **Add allowed chat ID** → your user id.
     Only allow-listed chats are ever processed — this *is* the access
     control (plan 5.4: one chat id, no groups).
   - Cogwheel → Options → Parse mode `plain_text` (the package sets it per
     message anyway).
4. **Check the agent entity id** in `packages/telegram.yaml`
   (`agent_id: conversation.ollama_conversation`): Settings → Devices &
   services → Ollama → the conversation entity. If yours differs, change the
   package and push.
5. Send the bot a message. Reply should come from GLaDOS. Traces:
   Settings → Automations → "Telegram: chat with the assistant" → Traces.

How it works: `telegram_text` event → `telegram_bot.send_chat_action`
(typing…) → `conversation.process` with `conversation_id: telegram-<chat id>`
(HA keeps the chat history per id, expires after 5 min idle) →
`telegram_bot.send_message` with `parse_mode: plain_text` (LLM text is not
valid Telegram Markdown; Markdown would 400 on a stray `*`). `/start` gets a
canned greeting; other `/commands` are ignored.

Not covered yet (plan 4.3): proactive notifications (`notify.telegram_bot_*`
entities are created per allowed chat — use `notify.send_message`), voice
notes.

## Future: Zigbee / Z-Wave USB coordinators

When you add a USB coordinator stick you'll need a `hostPath` device volume
(e.g. `/dev/ttyUSB0`), `nodeSelector` pinning HA to the node with the stick,
and device/privileged access. Not configured yet.
