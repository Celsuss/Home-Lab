# Announcements on the Google Home (Piper TTS)

Smoke test for Phase 2.4 of `HOME-ASSISTANT-AI-PLAN.md`: HA speaks through
Piper on the Google Home speaker.

**Since Phase 4.2 (2026-09-15) the automation is deployed from git:**
`helm/charts/home-assistant/packages/announcements.yaml`. If you pasted the
YAML below into the UI earlier, delete that copy (Settings → Automations) or
HA will announce twice. The YAML here is kept as the reference/explanation.

Prerequisites (done 2026-09-15): the Wyoming Piper integration is added
(`helm/charts/home-assistant/README.md` → "Voice pipeline"), and the Google
Home is exposed to Assist as `media_player.den_speaker`. The Piper TTS entity
is `tts.piper`.

Quick test without an automation — Settings → Developer tools → Actions →
YAML mode → Perform action:

```yaml
action: tts.speak
target:
  entity_id: tts.piper
data:
  media_player_entity_id: media_player.den_speaker
  message: "Hello. The cake is a lie."
  language: en_US
  options:
    voice: en_US-glados-medium
```

The automation version (now in `packages/announcements.yaml`):

```yaml
alias: "Smoke test: announce HA start on the Google Home"
description: >
  Piper TTS (GLaDOS) → Google Home. Verifies the TTS half of the voice
  pipeline and that Cast can fetch audio from HA's internal_url.
triggers:
  - trigger: homeassistant
    event: start
conditions: []
actions:
  - delay: "00:00:30"                  # let Cast discovery finish
  - action: tts.speak
    target:
      entity_id: tts.piper
    data:
      media_player_entity_id: media_player.den_speaker
      message: "Oh. It's you. Home automation is online. Try not to break anything."
      language: en_US
      options:
        voice: en_US-glados-medium     # custom voice from wyoming-piper values
mode: single
```

Trigger it by hand (⋮ → *Run actions*) to test without restarting HA. Expect
Piper to render in well under a second and Cast to add ~1–2 s of buffering
before audio starts — record the delay in the plan's 2.5 checklist.

If nothing plays: check `internal_url` under Settings → System → Network is
**empty / auto-detected** (`http://192.168.0.142:8123`), not
`home-assistant.homelab.local` — Cast devices bypass LAN DNS.
