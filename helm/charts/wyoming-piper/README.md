# wyoming-piper

Text-to-speech for Home Assistant Assist, speaking the Wyoming protocol.
Image: `rhasspy/wyoming-piper` (upstream:
[OHF-Voice/wyoming-piper](https://github.com/OHF-Voice/wyoming-piper)).

Part of the voice pipeline in `HOME-ASSISTANT-AI-PLAN.md` (Phase 2). CPU only —
Piper is fast enough (a two-second Swedish sentence renders in ~0.3–1 s).

- **Service:** `wyoming-piper.home-assistant.svc.cluster.local:10200`
- **Storage:** `/data` PVC (downloaded voices, ~63 MB each; default 1Gi)
- **Health:** the image's own `wyoming_piper.health_check`.

## Voices

**One instance serves every voice.** The server advertises all 170+ voices
from `voices.json`, downloads a voice from Hugging Face the first time it is
requested, and Home Assistant chooses the voice per assistant pipeline
(Settings → Voice assistants → *Text-to-speech* → Voice). So a Swedish and an
English assistant share this one deployment; `piper.voice` is only the
default when a client asks for none.

| Language | Voices | Notes |
|---|---|---|
| Swedish | `sv_SE-nst-medium` (default), `sv_SE-lisa-medium`, `sv_SE-alma-medium` | `nst` is the clearest; `lisa` sounds more natural but softer |
| English | `en_US-lessac-medium`, `en_US-amy-medium`, `en_GB-alan-medium` | `lessac` is the HA reference voice; `-high` variants exist but are slower |

### Custom voices (GLaDOS)

Voices outside the official catalogue go in `piper.customVoices` (name +
URLs of the `.onnx` and `.onnx.json`). An init container downloads them into
`/data` once and Piper advertises every such pair as a custom voice. Shipped
by default: **`en_US-glados-medium`** (GLaDOS from
[DavesArmoury/GLaDOS_TTS](https://huggingface.co/DavesArmoury/GLaDOS_TTS),
63 MB, CC-BY-4.0). A higher-quality alternative is
[systemofapwne/piper-en_US-glados-high](https://huggingface.co/systemofapwne/piper-en_US-glados-high)
(114 MB). Both are English (`en-us`) voices — **HA only lists voices matching
the assistant's language**, so GLaDOS appears in an English assistant's
Text-to-speech voice picker, not a Swedish one.

Tuning: `piper.lengthScale` (>1 slower speech), `piper.sentenceSilence`,
anything else through `piper.extraArgs`. The Piper voice management web UI
(`--web-server`) is off; it has no authentication.

## Google Home output

Once Piper is the pipeline's TTS, `tts.speak` with
`media_player_entity_id: media_player.<google_home>` plays it on the speaker.
Cast devices fetch the audio from HA's `internal_url` over plain HTTP; HA
auto-detects `http://192.168.0.142:8123` (works because HA runs with
`hostNetwork: true`). **Do not set `internal_url` to
`home-assistant.homelab.local`** — Cast devices bypass LAN DNS and playback
fails silently. Announcement example: `docs/home-assistant/announcements.md`.

## Home Assistant setup

Settings → Devices & services → Add integration → **Wyoming Protocol** →
host `wyoming-piper.home-assistant.svc.cluster.local`, port `10200`. Full
pipeline steps: `helm/charts/home-assistant/README.md`.
