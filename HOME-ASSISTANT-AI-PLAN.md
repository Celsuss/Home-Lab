# Home Assistant AI Roadmap

**Created**: 2026-09-14
**Goal**: Turn Home Assistant into a self-hosted, voice-driven smart home assistant backed by Ollama, then grow it into a general agent reachable over Telegram that can run tasks across the homelab.
**Timeline**: Multi-session. Phases are ordered so each one is usable on its own; later phases build on earlier ones.

Progress is tracked with checkboxes in this file. Mark a phase `✅ DONE` with a date when it is finished, and add a short "Discoveries" note under a phase if something turned out differently than planned.

---

## Current state (what we build on)

| Component | Status | Notes |
|---|---|---|
| `helm/charts/home-assistant` | Deployed | HA Container, `hostNetwork: true` + `dnsPolicy: ClusterFirstWithHostNet` (so it can resolve `*.svc.cluster.local`), 10Gi `/config` PVC, Traefik + Tailscale ingress. No add-ons (container flavour). |
| `helm/charts/ollama` | Deployed in `ai-workloads` | `ollama:0.30.5`, 1 GPU share, 100Gi models PVC. `models.enabled: false` — models on the PVC (several coding models + `gemma4:e4b-it-q8_0`) were pulled by hand and are not in git yet. Reachable at `http://ollama.ai-workloads.svc.cluster.local:11434`. |
| `helm/charts/open-webui` | Deployed | Already talks to Ollama via `OLLAMA_BASE_URL`. Useful for testing models/prompts. |
| `helm/charts/mcpo` | Deployed in `ai-workloads` | MCP→OpenAPI proxy (fetch + memory servers) for Open WebUI. Not usable by HA directly (HA speaks MCP/SSE, not OpenAPI). |
| GPU | RTX 4070 Ti SUPER, 16 GB VRAM | Time-sliced 4 ways by `nvidia-device-plugin`. Shared with ComfyUI. VRAM is the real budget, not GPU slots. |
| Cluster | Single node (192.168.0.142) | Two Raspberry Pis available. See Phase 6 on how to use them. |
| Secrets | Vault + VSO | HA manages its own `.storage`/`secrets.yaml`; Vault is used for anything we deploy alongside HA. |

Constraints to keep in mind for every phase:

- **HA Container ≠ HA OS.** Anything that would be an "add-on" (Whisper, Piper, openWakeWord, Mosquitto, Zigbee2MQTT…) becomes its own Helm chart in this repo.
- **VRAM budget.** An 8B model at Q4 is ~5–6 GB; Whisper `small` on GPU ~1 GB; ComfyUI can take 8+ GB. Pick models so the "always-on" assistant set (LLM + STT) fits comfortably with headroom for image generation.
- **Latency matters for voice.** A voice assistant that takes 8 s to answer is not "like Google Home". Eventually keep the model resident (`OLLAMA_KEEP_ALIVE` — deferred until after the move), prefer smaller/faster models for the voice path, and use HA's built-in intent matching before the LLM (HA's "prefer handling commands locally" option).
- **IaC first.** Model pulls, Wyoming services, HA seed config, Telegram bot deployment — all via charts/values in git. Only integration *setup* (config flows that write to HA's `.storage`) is done in the HA UI, and each such manual step is listed explicitly in the phase.

---

## Phase 1: Ollama as HA's conversation agent (text) — ✅ DONE 2026-09-14
**Priority**: High — foundation for everything else
**Estimated sessions**: 1

Outcome: In the HA UI "Assist" dialog you can type "turn off the kitchen lights" or "what's the temperature in the bedroom" and a local LLM answers and acts.

### 1.1 Pick and pin models (declarative)
- [~] In `helm/charts/ollama/values.yaml` set `models.enabled: true` and list the models the init container should pull so a fresh cluster gets them automatically. _(2026-09-14: models are **listed** in values but `enabled` stays **false** — user manages pulls manually for now; the init container had crash-looped previously (no curl in image — fixed, untested). Revisit when rebuilding the cluster.)_
- [x] Inventory what is already on the Ollama PVC (`ollama list` via the Ollama pod, or `GET /api/tags`) and put the models worth keeping into `models.list` so the values file reflects reality. Existing coding models can stay listed (the init container only pulls, it never deletes) but are not candidates for the assistant.
- [x] Choose a **tool-calling capable** model — HA's Assist control requires it. Candidates for 16 GB VRAM shared with other workloads:
  - `gemma4:e4b-it-q8_0` — **already pulled**, so try this first. Check its footprint with `ollama show gemma4:e4b-it-q8_0` (disk size) and `ollama ps` while loaded (actual VRAM incl. KV cache). Gate: verify it advertises `tools` capability (`ollama show` → Capabilities) and that a `/api/chat` call with a `tools` payload returns a tool call — if not, it can't drive Assist and we fall back to one below.
  - `qwen3:8b` — good tool use, good non-English (Swedish) handling. Recommended fallback / comparison.
  - `llama3.1:8b` — reliable tool calling, widely tested with HA.
  - `qwen3:4b` — fallback if latency is too high for voice.
- [x] **VRAM rule of thumb:** one model must never take the whole card. Budget for the assistant model is ~8 GB max (loaded size + a few GB of KV cache at the context length HA uses), leaving room for Whisper (Phase 2) and ComfyUI. **Measured 2026-09-14:** `gemma4:e4b-it-q8_0` = **5.3 GB, 100% GPU, 4096 ctx** (`ollama ps`). ✓ within budget.
- [ ] ~~Add `OLLAMA_KEEP_ALIVE` so the assistant model stays loaded~~ — **deferred until after the move.** A several-second cold start on the first request is acceptable for now, and keeping a model resident permanently eats VRAM that ComfyUI/Open WebUI also need. Revisit in Phase 2.5 (voice latency tuning) or Phase 7.
- [ ] Consider `OLLAMA_NUM_PARALLEL=2` so Open WebUI and HA can hit the model concurrently (also deferred; only matters once the model is resident).
- [x] Verify with Open WebUI that the model responds and that tool calls work (`/api/chat` with a `tools` payload via `curl` from a pod is the definitive check). **2026-09-14: passed** — see Discoveries.

### 1.2 Connect HA to Ollama
- [x] HA UI → Settings → Devices & services → Add integration → **Ollama**. URL: `http://ollama.ai-workloads.svc.cluster.local:11434`. Select the model from 1.1.
- [x] In the integration's options: enable **"Assist"** control (lets the LLM call HA services), set **"Prefer handling commands locally"** on (built-in intents answer instantly; LLM is fallback).
- [x] Set the conversation agent as default: Settings → Voice assistants → the default "Home Assistant" assistant → Conversation agent = Ollama.
- [x] Write a short system prompt (in the integration options) that states: language (Swedish + English), be terse (voice answers), the home layout/areas. _Prompt text is versioned in `docs/home-assistant/system-prompt.md` — paste from there._

### 1.3 Expose entities and organise the home
The LLM only sees entities that are **exposed** to Assist. Quality of answers depends heavily on this.
- [x] Settings → Voice assistants → Expose: expose lights, switches, climate, media players, sensors that matter. Keep the list small — a huge context slows the model and hurts accuracy.
- [x] Give every exposed entity a human-friendly name and put every device in an **Area** (Kitchen, Bedroom…). Add **aliases** for things you'll say differently ("telly" / "TV").
- [x] Write this down in `helm/charts/home-assistant/README.md` as the convention for when new devices are added after the move. _(2026-09-14: "Assist conventions" + Ollama setup steps added.)_

### 1.4 Validate
- [x] Assist (text) can: turn a device on/off, report a sensor value, answer a general question. _(2026-09-14: general Q&A verified through HA; device control verified at the API level with a tool call — few real devices exist until after the move.)_
- [x] Measure round-trip time for a simple command; record it here. _(API-level: 0.44 s warm, ~4 s cold; HA UI felt responsive. Re-measure with real devices after the move.)_ Target < 2 s for local-intent hits, < 5 s for LLM answers once the model is warm (first request after idle will be slower — accepted for now).
- [x] Check `nvidia-smi` VRAM headroom while the model is loaded + ComfyUI idle _(`ollama ps`: 5.3 GB of 16 GB)_ (model unloads after Ollama's default 5 min keep-alive; that's fine for now).

**Discoveries**:
- 2026-09-14: `ollama show gemma4:e4b-it-q8_0` → 8.0B params, Q8_0, 131k context, capabilities include `tools` (also `vision`, `audio`, `thinking`). `ollama list` says 11 GB on disk (text weights + vision/audio projectors), but loaded for text it is only **5.3 GB VRAM** at 4096 ctx — comfortably within budget.
- 2026-09-14: PVC inventory: `gemma4:e4b-it-q8_0` (11 GB), `qwen2.5-coder:14b` (9 GB), `deepseek-r1:14b` (9 GB) — all three now pinned in `ollama/values.yaml`.
- 2026-09-14: **Phase 1 closed.** Ollama integration added in HA, Assist control on, local-first intents on, Ollama set as default conversation agent. Prompt got a GLaDOS persona (`docs/home-assistant/system-prompt.md`); first exchange in Assist: "Yes, I can process your auditory input. Try to keep the rudimentary conversation manageable." Remaining Phase 1 loose ends roll into later phases: real entity exposure/areas once devices exist after the move (1.3), and round-trip re-measurement in Phase 2.5.
- 2026-09-14: **Tool-call gate passed.** `POST /api/chat` (host → ClusterIP `10.43.203.193`) with a `light_turn_off` tool: gemma4 returned `tool_calls=[light_turn_off(name="kitchen light")]`. Cold: 4.0 s total (2.9 s model load, 1.07 s generating 101 tokens ≈ 94 tok/s, incl. a "thinking" block). Warm: **0.44 s** total. So the LLM path will land well under the 5 s target once warm; cold start after the 5-min keep-alive is ~3 s extra. In HA, consider turning **thinking off** in the Ollama integration options — the thinking block is where the extra ~80 tokens went.
- 2026-09-14: The `ollama/ollama` image has **no `curl`**. The chart's init-container readiness loop used `curl` and would have crash-looped the pod once `models.enabled: true`; switched to `ollama list` as the probe. Also means tool-call tests must run from outside the pod (host → ClusterIP, or a throwaway curl pod). The `/api/chat` tool-call test was not completed (curl reachability from the host; `svc.cluster.local` only resolves in-cluster — use the ClusterIP or the Tailscale hostname). Decision: proceed with gemma4 and only switch models if it fails in practice.

---

## Phase 2: Voice pipeline — speech-to-text, text-to-speech, wake word
**Priority**: High — this is the "talk like Google Home" goal
**Estimated sessions**: 2

Outcome: A full Assist pipeline (wake word → STT → conversation → TTS) works from the HA Companion app and the HA web UI microphone button.

HA talks to these services with the **Wyoming** protocol. Each becomes a small standalone chart following the repo layout (`_helpers.tpl`, deployment, service, values, `namespace` at top level). Suggested namespace: `home-assistant` (same as HA) so ArgoCD app boundaries stay simple; add each to `root-app`.

### 2.1 `helm/charts/wyoming-whisper` (STT)
- [ ] Image options:
  - `rhasspy/wyoming-whisper` — CPU, simplest, official. Fine for `small`/`base` models; try this first.
  - GPU-enabled faster-whisper image if CPU latency is too high (e.g. `lscr.io/linuxserver/faster-whisper` with `nvidia.com/gpu: 1` share and `runtimeClassName: nvidia`, mirroring the Ollama chart).
- [ ] Args: `--model small` (or `medium` on GPU), `--language sv` if Swedish-first (Whisper auto-detect is slower and worse). Beam size 1–2 for latency.
- [ ] Service port `10300`. PVC for model cache (~1–3 GB) so restarts don't re-download.
- [ ] Health: TCP probe on 10300.

### 2.2 `helm/charts/wyoming-piper` (TTS)
- [ ] Image `rhasspy/wyoming-piper`, `--voice <voice>`. Pick a Swedish voice (`sv_SE-nst-medium`) and/or an English one (`en_US-lessac-medium`); Piper serves one default voice per instance, so either run two instances or pick the primary language.
- [ ] Service port `10200`. PVC for voice files.
- [ ] CPU is fine for Piper.

### 2.3 `helm/charts/wyoming-openwakeword` (wake word)
- [ ] Image `rhasspy/wyoming-openwakeword`, `--preload-model ok_nabu` (or `hey_jarvis`; custom wake words can be added later).
- [ ] Service port `10400`. Only needed for satellites that stream audio to HA for wake-word detection (Wyoming satellites on Pis do this; Voice PE detects on-device).

### 2.4 Wire it up in HA
- [ ] Add the **Wyoming Protocol** integration three times (whisper, piper, openwakeword) using the cluster DNS names, e.g. `wyoming-whisper.home-assistant.svc.cluster.local:10300`.
- [ ] Settings → Voice assistants → create/edit the assistant: STT = Whisper, TTS = Piper, conversation = Ollama (from Phase 1), wake word = openWakeWord.
- [ ] Test with the microphone button in the HA web UI and in the Companion app (Assist → tap-to-talk).

### 2.5 Validate
- [ ] Say "turn on the living room lights" → light turns on, spoken confirmation.
- [ ] Record end-to-end latency (wake → response audio). Tune: Whisper model size, prompt length, exposed-entity count. This is the point where `OLLAMA_KEEP_ALIVE` (deferred from 1.1) becomes worth turning on if the cold start dominates.
- [ ] Document per-language tradeoffs in the chart READMEs.

**Discoveries**: _(fill in)_

---

## Phase 3: Voice hardware — always-listening satellites in the rooms
**Priority**: Medium — needed for hands-free use; can be done in parallel with Phase 4
**Estimated sessions**: 1 (+ hardware lead time)

Outcome: Say the wake word from across the room, no phone needed.

### 3.1 Choose satellites
Two viable routes, not mutually exclusive:
- [ ] **Home Assistant Voice Preview Edition** — purpose-built, on-device wake word, best mic array, plugs straight into the Phase 2 pipeline via ESPHome. Recommended for the main rooms. Zero cluster work.
- [ ] **Raspberry Pi as a Wyoming satellite** — one of the two Pis + a USB mic/speaker or a ReSpeaker HAT running `wyoming-satellite`. Cheaper if the Pi already exists; more fiddly audio setup. Wake-word detection runs either on the Pi (`wyoming-openwakeword` locally) or streams to the cluster's openWakeWord (2.3).
- [ ] Decide which Pi (if any) is a satellite vs. a cluster node (see Phase 6). Recommendation: **one Pi as satellite, one as k3s agent** — or both as satellites if Voice PE turns out too expensive.

### 3.2 Provision satellites as code
- [ ] Voice PE: keep the ESPHome YAML in `docs/` or a new `esphome/` dir once you adopt it (ESPHome add-on doesn't exist under HA Container — run `esphome` CLI locally or as a small chart later).
- [ ] Pi satellite: add an Ansible role `wyoming_satellite` (`ansible/roles/`) that installs `wyoming-satellite` as a systemd service pointing at the HA host. Add the Pi to `ansible/inventory/hosts.ini` under a new `[voice_satellites]` group.

### 3.3 Validate
- [ ] Hands-free command from each room where a satellite sits. Note false-wake rate; adjust wake-word threshold.

**Discoveries**: _(fill in)_

---

## Phase 4: Telegram chat with the assistant
**Priority**: Medium-high — "chat with my assistant from anywhere"
**Estimated sessions**: 1

Outcome: Message your bot on Telegram, get an answer from the same Ollama-backed agent, including executing home commands. No extra services are needed for v1 — HA's built-in Telegram integration + the conversation API does it all.

### 4.1 Create the bot
- [ ] Create a bot with @BotFather, note the token and your numeric Telegram user id (`@userinfobot`).
- [ ] Store both in Vault under the repo convention: `vault kv put secret/homelab/home-assistant TELEGRAM_BOT_TOKEN=... TELEGRAM_ALLOWED_CHAT_ID=...`. HA itself stores the token in `.storage` via the config flow, but Vault is the source of record and lets us seed it if HA is ever rebuilt.

### 4.2 Configure HA
- [ ] Add the **Telegram bot** integration (polling mode — simplest, no inbound port needed; webhook mode would need the public Tailscale/funnel URL). Restrict to your chat id.
- [ ] Create an automation (store it in `/config/automations.yaml` or in a package seeded by the chart, so it's in git):
  - Trigger: event `telegram_text`
  - Action: `conversation.process` with `agent_id` = the Ollama agent, `text` = the message, `conversation_id` = the chat id (keeps context across turns)
  - Action: `telegram_bot.send_message` with the response
- [ ] Add a seeded `packages/` mechanism to the HA chart: extend `config-seed-configmap.yaml` (or add a second ConfigMap mounted at `/config/packages/`) and set `homeassistant: packages: !include_dir_named packages` in the seeded `configuration.yaml`. This is how all future HA YAML lands in git instead of the UI.

### 4.3 Nice-to-haves once the loop works
- [ ] Proactive notifications *to* Telegram (door left open, low battery, backup failed) via `notify.telegram` — this is where the Phase 5 integrations start paying off.
- [ ] Voice notes: Telegram voice message → download → STT via Whisper → conversation. (HA doesn't do this natively; needs the Phase 5 agent runtime.)

### 4.4 Validate
- [ ] Send "is anything on in the kitchen?" from Telegram while away (over cellular, not Wi-Fi) → correct answer.
- [ ] Send a command → device changes state → confirmation reply.

**Discoveries**: _(fill in)_

---

## Phase 5: Tools & task execution beyond the home
**Priority**: Medium — turns the assistant into an agent
**Estimated sessions**: 2–3

Outcome: The assistant can act on other homelab services: add a chore to Donetick, look up a recipe in Tandoor, save a link to Karakeep, check Jellyfin/Immich, search the web via SearXNG, check monitors in Uptime Kuma, etc.

### 5.1 Give HA's LLM external tools via MCP
HA has a native **Model Context Protocol** integration (client) that lets the Ollama conversation agent call tools from external MCP servers over SSE/streamable-HTTP. This reuses the mcpo idea but in the shape HA needs.
- [ ] Add a chart (e.g. `helm/charts/mcp-servers`) that runs the MCP servers HA should use, each exposed over SSE. Many stdio servers can be bridged with a small SSE gateway sidecar (e.g. `supergateway`). Start with:
  - web search (SearXNG MCP server — SearXNG is already in the cluster)
  - fetch (`mcp-server-fetch`, already used by mcpo)
  - memory (`mcp-server-memory`, persistent notes across conversations — needs a PVC)
- [ ] Add each server in HA via the MCP integration; verify tools appear in the Assist debug view.
- [ ] Refactor `mcpo` to consume the same MCP servers so Open WebUI and HA share one set of tool deployments.

### 5.2 Service-specific tools
For each homelab service, pick the cheapest path in this order: (a) existing HA integration, (b) existing MCP server, (c) HA REST command / script exposed as an Assist intent, (d) write a tiny MCP server (Python, `docker/<name>/` → GHCR via the existing CI workflow).
- [ ] Jellyfin → HA Jellyfin integration (media player entity; "play X on the TV" — pairs with the TV client after the move)
- [ ] Donetick → REST command/script or small MCP server ("add 'buy milk' to my chores")
- [ ] Tandoor → small MCP server ("what can I cook with…")
- [ ] Karakeep → small MCP server ("bookmark this")
- [ ] Uptime Kuma / Beszel → status tools ("is anything down?")
- [ ] Immich → HA integration or MCP ("show me photos from last summer" — as a link/Telegram photo)

### 5.3 Model and prompt tuning for tool use
- [ ] Re-evaluate model choice once there are 20+ tools; small models degrade with many tools. Options: a larger model for Telegram/text (e.g. `qwen3:14b` fits at Q4 if ComfyUI is idle) while voice keeps the fast 8B model — HA supports multiple conversation agents, one per assistant.
- [ ] Keep the system prompt versioned in this repo (`docs/home-assistant/system-prompt.md`) and paste it into the integration options on change.

### 5.4 Guardrails
- [ ] Only expose destructive actions (unlock doors, disarm, delete) through HA intents that require confirmation, or don't expose them at all.
- [ ] Telegram: single allowed chat id, no group chats.

**Discoveries**: _(fill in)_

---

## Phase 6: Infrastructure for the new apartment
**Priority**: Medium — do after the move; independent of Phases 1–5
**Estimated sessions**: 2

### 6.1 Add Raspberry Pi(s) as k3s agent nodes
- [ ] Add the Pi to `[k3s_agents]` in `ansible/inventory/hosts.ini` (with `ansible_host`, SSH user — no longer `local`). Verify the `common`/`containerd`/`k3s` roles handle arm64 (k3s binary, cgroup flags in `/boot/cmdline.txt`).
- [ ] Update `AGENTS.md`/memory: cluster becomes 1 server + N agents again.
- [ ] Label nodes (`kubernetes.io/arch=arm64`) and add `nodeSelector`/`nodeAffinity` to charts that must stay on the x86 GPU node (ollama, comfyui, whisper-gpu, HA with `hostNetwork` if it depends on the node's LAN position).
- [ ] Good candidates to schedule on a Pi: Piper, openWakeWord, mcp-servers, uptime-kuma, glance — light, arm64-friendly images. Check every image has an arm64 manifest before moving it.
- [ ] Longhorn/`local-path` implications: RWO `local-path` PVCs pin a pod to one node. Decide per chart; don't move stateful pods without a migration plan.

### 6.2 Jellyfin on the TV
Not a cluster change — a client choice. Document the decision in `helm/charts/jellyfin/README.md`:
- [ ] Options: smart TV app (if the TV has Jellyfin in its store), Android TV box / Chromecast with Google TV (Jellyfin app, cheap, also gives HA a Cast/Android TV media player entity for "play X on the TV"), or the second Pi running Jellyfin Media Player / Kodi + Jellyfin plugin (works, but the Pi is more valuable as a node or satellite).
- [ ] Make sure the TV client resolves `jellyfin.homelab.local` (LAN DNS via k8s-gateway must be the resolver handed out by the new router's DHCP — see `DNS-PROBLEMS.md`) or use the Tailscale hostname.
- [ ] Add the TV as an HA media player (Cast / Android TV integration) so Phase 5's "play on the TV" works.

### 6.3 Home Assistant hardening (recommended before adding many devices)
- [ ] Move the recorder from SQLite to PostgreSQL (new `home-assistant-db` StatefulSet in the chart, password via Vault/VSS) — SQLite on `local-path` gets slow with many sensors.
- [ ] Pin the HA image tag (currently `stable`) and add HA to the `volsync-backups` schedule (`/config` PVC).
- [ ] Zigbee/Z-Wave coordinator: USB stick on the server node → `hostPath` device + `nodeSelector` (already noted in the HA README), or a network coordinator (e.g. SLZB-06) which avoids node pinning entirely — prefer the network coordinator for a multi-node cluster.
- [ ] MQTT broker chart (`mosquitto`) if Zigbee2MQTT or ESPHome-over-MQTT devices are used.

**Discoveries**: _(fill in)_

---

## Phase 7: Polish & advanced agent behaviour
**Priority**: Low — after everything above is stable

- [ ] **Multiple assistants**: a fast voice assistant (small model, few tools) and a capable text assistant (larger model, all tools) — HA supports several pipelines, and Telegram can target the text one.
- [ ] **Proactive agent**: scheduled/triggered automations that ask the LLM to summarise (morning briefing to Telegram: calendar, weather, chores due, anything down in the lab).
- [ ] **Long-term memory**: `mcp-server-memory` (or a small Postgres-backed one) so the assistant remembers preferences.
- [ ] **HA as an MCP server**: HA's *MCP Server* integration exposes the home to other clients — lets Open WebUI (via mcpo) or a desktop agent control the house with the same entity permissions.
- [ ] **Custom wake word** trained with openWakeWord for the assistant's name.
- [ ] **Observability**: Assist debug traces, Ollama request latency in Beszel/Uptime Kuma, alert on VRAM exhaustion.
- [ ] **Model upgrades**: revisit models every few months; keep the choice pinned in `ollama/values.yaml` with a note on why.

---

## Session log

| Date | Phase | What was done |
|---|---|---|
| 2026-09-14 | 1 ✅ | HA side done in UI: Ollama integration, Assist control, default agent, GLaDOS prompt. Verified a general question in Assist. Phase 1 closed; next session starts Phase 2 (Wyoming Whisper/Piper charts). |
| 2026-09-14 | 1.1–1.3 | 1.1 done: all 3 PVC models listed in `ollama/values.yaml` (init container left **disabled**, manual pulls for now) in `ollama/values.yaml`; fixed init-container readiness probe (no curl in image); gemma4 tool-call gate passed (warm 0.44 s, 5.3 GB VRAM). System prompt versioned in `docs/home-assistant/system-prompt.md`; Ollama setup steps + Assist conventions in HA README. **Remaining (manual, HA UI):** 1.2 add the Ollama integration, 1.3 expose entities, 1.4 validate & record round-trip. |
| 2026-09-14 | 1.1 | Checked gemma4 capabilities (tools ✓); API tool-call test deferred. Next session: start Phase 1.1 model pinning in `ollama/values.yaml`. |
| 2026-09-14 | — | Plan created. Revised: keep-alive deferred until after the move; `gemma4:e4b-it-q8_0` (already pulled) is the first model candidate; added VRAM budget rule. |
