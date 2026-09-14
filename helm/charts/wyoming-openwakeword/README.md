# wyoming-openwakeword

Wake word detection for Home Assistant Assist, speaking the Wyoming protocol.
Image: `rhasspy/wyoming-openwakeword` (upstream:
[OHF-Voice/wyoming-openwakeword](https://github.com/OHF-Voice/wyoming-openwakeword)).

Part of the voice pipeline in `HOME-ASSISTANT-AI-PLAN.md` (Phase 2). Only
needed for satellites that **stream audio to HA** for wake-word detection
(Wyoming satellites on Raspberry Pis, the HA web UI / Companion app "always
listening" mode). Home Assistant Voice PE detects on-device and does not use
this.

- **Service:** `wyoming-openwakeword.home-assistant.svc.cluster.local:10400`
- **Storage:** none. Since 2.x the models are built into the image
  (`okay_nabu`, `hey_jarvis`, `hey_mycroft`, `hey_rhasspy`, `alexa`) and
  `--preload-model` is deprecated; every model is always available and the
  wake word is chosen per satellite in HA.
- **Health:** TCP probes (the image ships no health check).
- Tiny footprint: ~1m CPU idle, ~26 MB RAM; detection on a 1 s clip in 0.3 s.

## Tuning

`openwakeword.threshold` (default 0.5 — raise on false wakes),
`triggerLevel`, `refractorySeconds`; anything else via `extraArgs`.

## Custom wake words

Train a model with [openWakeWord](https://github.com/dscripka/openWakeWord)
(Phase 7 of the plan), then ship the `.tflite` through
`openwakeword.customModels` (file name → base64 content). The chart mounts
them at `/custom` and passes `--custom-model-dir`. Keep model files small;
they end up in a Secret (ConfigMaps cannot carry binary data). A model named
`hey_glados_v0.1.tflite` is advertised as `hey_glados`.

## Home Assistant setup

Settings → Devices & services → Add integration → **Wyoming Protocol** →
host `wyoming-openwakeword.home-assistant.svc.cluster.local`, port `10400`.
Then pick it as *Wake word* in the assistant pipeline. Full pipeline steps:
`helm/charts/home-assistant/README.md`.
