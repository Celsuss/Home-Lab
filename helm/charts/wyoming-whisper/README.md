# wyoming-whisper

Speech-to-text for Home Assistant Assist, speaking the
[Wyoming](https://github.com/OHF-Voice/wyoming) protocol.
Image: `rhasspy/wyoming-whisper` (upstream:
[OHF-Voice/wyoming-faster-whisper](https://github.com/OHF-Voice/wyoming-faster-whisper)).

Part of the voice pipeline in `HOME-ASSISTANT-AI-PLAN.md` (Phase 2), together
with `wyoming-piper` (TTS) and `wyoming-openwakeword` (wake word). All three
live in the `home-assistant` namespace. No ingress: Wyoming is a plain TCP
protocol only Home Assistant talks to.

- **Service:** `wyoming-whisper.home-assistant.svc.cluster.local:10300`
- **Storage:** `/data` PVC (model cache, `persistence.storage`, default 2Gi)
- **Health:** the image's own `wyoming_faster_whisper.health_check` (a
  Describe/Info round trip) as liveness/readiness; a TCP startup probe
  covers the first-boot model download.

## Configuration

Everything is under `whisper:` in `values.yaml`. The image entrypoint passes
`--uri`, `--data-dir` and `--device cpu`; the chart appends the rest, and any
flag from `--help` can be added through `whisper.extraArgs`.

| Value | Default | Notes |
|---|---|---|
| `whisper.model` | `small-int8` | `tiny/base/small/medium-int8` on CPU, or any Hugging Face id (`Systran/faster-whisper-large-v3`) |
| `whisper.language` | `sv` | Only a fallback — HA sends the pipeline's language with every request, so one instance serves Swedish **and** English |
| `whisper.beamSize` | `1` | Fastest. Beam 5 made no difference on test audio |
| `whisper.vadFilter` | `true` | Silero VAD, cuts hallucinations on silence |
| `hass.enabled` | `false` | Bias toward HA entity/area names — see below |
| `gpu.enabled` | `false` | Needs a CUDA image — see below |

### Model tradeoffs (measured 2026-09-14, CPU, 4 threads, Piper-generated audio)

| Model | Latency, short command | Swedish | English |
|---|---|---|---|
| `small-int8` | **~0.5–0.7 s** | Good on short commands; room names get mangled in long sentences ("vardagsrummet" → "varusrummet") | Perfect |
| `medium-int8` | ~1.2–1.5 s | Not clearly better on Swedish; ~850 MB RSS (vs ~525 MB for small) | Perfect |

Short voice commands are what Assist sends, so `small-int8` is the default.
For Swedish accuracy the better lever is name biasing (below), not a bigger
model. Note Whisper needs a little leading silence: a clip that starts
mid-word lost the first consonant ("Släck" → "Läck") — satellites and the
Companion app always include some, so this only bites synthetic tests.

### Bias toward Home Assistant names (`hass.enabled`)

Whisper 3.x can fetch the names of the entities, areas and floors exposed to
Assist and use them as a decoding prompt, which is the biggest accuracy win
for "turn off the <thing> in the <room>" commands, especially in Swedish.

1. HA → profile (bottom-left) → **Security** → *Long-lived access tokens* →
   create one named `wyoming-whisper`.
2. `vault kv put secret/homelab/wyoming-whisper HASS_TOKEN=<token>`
3. Set `hass.enabled: true`. The chart adds a `VaultStaticSecret` (auth
   `wyoming-whisper-vault-auth`, since the namespace is shared) and passes the
   token as `WYO_WHISPER_HASS_TOKEN` so it never appears in the pod args.

### GPU

The official image is CPU-only; upstream's `Dockerfile.gpu` is not published
(~10.7 GB). To use the GPU: build it in `docker/wyoming-whisper-gpu/` via the
existing GHCR CI workflow, point `image.repository` at it and set
`gpu.enabled: true` (adds `runtimeClassName: nvidia`, one time-sliced
`nvidia.com/gpu` share and `--device cuda`; default GPU model becomes
`Systran/faster-whisper-small` float16). Budget ~1 GB VRAM for `small`, ~3 GB
for `large-v3`. Only worth it if CPU latency becomes the bottleneck — at
0.5 s it is not.

## Home Assistant setup

Settings → Devices & services → Add integration → **Wyoming Protocol** →
host `wyoming-whisper.home-assistant.svc.cluster.local`, port `10300`. Then
pick it as *Speech-to-text* in the assistant pipeline (Settings → Voice
assistants). Full pipeline steps: `helm/charts/home-assistant/README.md`.

## Testing without HA

```bash
pip install wyoming   # in a venv
# describe / transcribe a 16 kHz mono WAV via the ClusterIP (host can reach it)
python -c 'from wyoming.client import AsyncClient' && echo ok
```
A small test client (`describe`, `stt`, `tts`, `wake`) was used to validate
this chart; the pattern is: send `Transcribe(language)`, `AudioStart`,
`AudioChunk`s, `AudioStop`, read `Transcript`.
