# Announcements on the Google Home (Piper TTS)

Smoke test for Phase 2.4 of `HOME-ASSISTANT-AI-PLAN.md`: HA speaks through
Piper on the Google Home speaker. Until the seeded `packages/` mechanism
exists (Phase 4.2) this lives in `/config/automations.yaml`, i.e. paste it in
via Settings → Automations → **Create automation** → ⋮ → *Edit in YAML*.

Prerequisites: the Wyoming Piper integration is added
(`helm/charts/home-assistant/README.md` → "Voice pipeline"), and the Google
Home is exposed to Assist with an alias (e.g. "kitchen speaker").

Find the entity ids first: Settings → Devices & services → Entities, filter
`media_player.` (the Cast speaker) and `tts.` (Piper shows up as
`tts.piper`).

```yaml
alias: "Smoke test: announce HA start on the Google Home"
description: >
  Piper TTS → Google Home. Verifies the TTS half of the voice pipeline and
  that Cast can fetch audio from HA's internal_url.
triggers:
  - trigger: homeassistant
    event: start
conditions: []
actions:
  - delay: "00:00:30"                  # let Cast discovery finish
  - action: tts.speak
    target:
      entity_id: tts.piper             # Wyoming Piper TTS entity
    data:
      media_player_entity_id: media_player.google_home   # your Cast speaker
      message: "Hemautomationen är igång."
      language: sv-SE
      options:
        voice: sv_SE-nst-medium        # any voice Piper advertises
mode: single
```

Trigger it by hand (⋮ → *Run actions*) to test without restarting HA. Expect
Piper to render in well under a second and Cast to add ~1–2 s of buffering
before audio starts — record the delay in the plan's 2.5 checklist.

If nothing plays: check `internal_url` under Settings → System → Network is
**empty / auto-detected** (`http://192.168.0.142:8123`), not
`home-assistant.homelab.local` — Cast devices bypass LAN DNS.
