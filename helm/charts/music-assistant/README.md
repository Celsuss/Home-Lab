# Music Assistant

[Music Assistant](https://www.music-assistant.io/) server (`ghcr.io/music-assistant/server`).
It is the bridge between **Navidrome** (the music library) and **Home Assistant**
(the voice agent): MA reads Navidrome over the Subsonic API and streams to the
Google Home over Cast; HA's Music Assistant integration gives the Ollama agent
a `music_assistant.play_media` action, wrapped in the `script.play_music` tool
(`helm/charts/home-assistant/packages/music.yaml`).

```
Assist / Telegram ─▶ Ollama ─▶ script.play_music ─▶ music_assistant.play_media
                                                        │
             Music Assistant (hostNetwork, 192.168.0.142:8095 / :8097)
                 │ Subsonic API                    │ Cast + HTTP audio stream
                 ▼                                 ▼
  navidrome.media.svc.cluster.local:4533     Google Home (den_speaker)
```

HA Container has no add-ons, so MA runs as its own Deployment.

## Networking

`hostNetwork: true` (+ `dnsPolicy: ClusterFirstWithHostNet` so cluster DNS
still works). MA binds **8095** (web UI / API) and **8097** (audio streams)
directly on the node. Both are required:

- Cast speakers are discovered via mDNS, which only works on the LAN.
- The Google Home fetches the audio from `http://192.168.0.142:8097/...`.
  Cast devices bypass LAN DNS, so the stream can't go through Traefik — the
  same reason HA's `internal_url` must stay the IP for TTS.

## Access

- **LAN (Traefik):** https://music-assistant.homelab.local
- **Remote (Tailscale):** `music-assistant.<tailnet>`
- **Direct:** http://192.168.0.142:8095 (use this for the HA integration)

## Storage

`/data` PVC (2Gi, `local-path`): `settings.json` (all config, including the
Navidrome credentials), library DB, artwork cache. MA has no declarative
config — everything below lives on this PVC.

## One-time setup (manual)

### 1. Navidrome: a dedicated user

https://navidrome.homelab.local → Settings → Users → **+**: username
`music-assistant`, a generated password, **not** admin. Record it in Vault:

```bash
vault kv put secret/homelab/music-assistant NAVIDROME_USER=music-assistant NAVIDROME_PASSWORD=<the-password>
```

### 2. Music Assistant: onboarding + providers

1. Open https://music-assistant.homelab.local and create the MA admin user
   (MA ≥ 2.7 requires login).
2. Settings → Providers → **Add music provider → Subsonic** (OpenSubsonic):
   - Base URL: `http://navidrome.media.svc.cluster.local`
   - Port: `4533`
   - Username / password: the Navidrome user from step 1
   - Leave the path empty.
   Wait for the first library sync (Library → Artists should fill up).
3. Settings → Providers: make sure the **Google Cast** player provider is
   present (add it if not). The Google Home appears under Settings → Players.
4. Settings → Core → **Streamserver**: the published IP must be
   `192.168.0.142`. If it shows a Tailscale (`100.x`), NordVPN or CNI
   (`10.42.x`) address, set it explicitly — otherwise the Google Home can't
   fetch the stream.
5. Smoke test without HA: pick an album → play on the Google Home.

### 3. Home Assistant: integration + Assist

1. **From a browser on the LAN:** Settings → Devices & services → Add
   integration → **Music Assistant** → URL `http://192.168.0.142:8095`. HA
   redirects to MA's login to approve a token; this redirect goes to the URL
   you entered, so the browser must reach it.
2. MA creates its own player entity for the speaker (expected
   `media_player.den_speaker_2`). If the id differs, update `player:` in
   `helm/charts/home-assistant/packages/music.yaml`.
3. Settings → Voice assistants → **Expose**: expose `script.play_music` and the
   MA player. Keep the plain Cast entity `media_player.den_speaker` exposed
   too if you like (TTS/announcements use it), but give the MA player a clear
   name/alias (e.g. "Den music") so the agent pauses/turns down the right one.

### 4. Validate

- Assist: "play Daft Punk" → music on the Google Home.
- "pause", "resume", "turn it down", "next song".
- The same over Telegram.

## Notes

- A `tts.speak` announcement on the Google Home stops the music (Cast plays
  one stream at a time). MA's `music_assistant.play_announcement` ducks and
  resumes instead — candidate for `packages/announcements.yaml` later.
- If MA can't reach Navidrome while the host can, suspect NordVPN breaking
  pod→ClusterIP routing first.
