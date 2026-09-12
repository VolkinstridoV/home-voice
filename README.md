# home-voice

A bilingual (Russian + English) voice assistant for the living room, built on a
**Home Assistant Voice Preview Edition**, a fanless **mini PC with no GPU**, and
open-source speech models — with a trained character voice on top.

One wake word. Speak Russian or English. Get the answer in the same language,
in a small friendly robot voice. Everything that hears and speaks runs at home.

> Status (v0.1.0): the full loop works without an LLM — wake word → Whisper →
> agent → Piper → speaker, both languages through a single pipeline. The
> "brain" (Claude via the Anthropic integration) and the RVC character voice
> are the next steps; see [CHANGELOG](CHANGELOG.md).

## What is in here

| Part | What it does |
|---|---|
| `ha/custom_components/guarded_agent` | HA conversation entity that wraps an LLM agent and **always** answers with a fixed English phrase when the agent is missing, times out or errors. The house never goes silent because an API key expired. |
| `ha/custom_components/robot_tts` | HA TTS entity: picks the Piper voice from the **text** (Cyrillic → Russian, otherwise English), then runs the audio through an ffmpeg "small robot" filter. Options: Piper host, voices, filter chain, on/off. |
| `server/voice/langproxy` | Wyoming proxy that detects the *spoken* language with a tiny Whisper model (~0.15 s) and forwards the request to the real Whisper with that language. This is what makes one wake word serve two languages. |
| `server/voice/docker-compose.yml` | wyoming-whisper (large-v3-turbo, int8), wyoming-piper, the proxy. All bound to `127.0.0.1`. |
| `server/applio` | CPU Dockerfile for Applio (RVC), training start script, and a checkpoint watchdog (audio probes + self-reconstruction metric + deadline). |
| `voice-training/jobbot` | Clip splitter and the recipe used to train a character voice from ~11 minutes of audio on CPU. |
| `tools` | One-shot HA WebSocket client, microphone-free end-to-end pipeline test, Improv-BLE Wi-Fi provisioning for the speaker. |
| `docs` | The stories: [hardware](docs/hardware.md), [the Wi-Fi that dropped CS1 packets](docs/wifi-cs1-drop.md), [one wake word for two languages](docs/one-wake-word-two-languages.md), [the Applio pretrained trap](docs/applio-pretrained-trap.md). |

## Architecture

```
  Voice PE ──wake word "Okay Nabu"──▶ Home Assistant (host network, port 8123)
                                          │
                        Assist pipeline "Nabu" (language: en)
                                          │
              STT: stt.faster_whisper_auto ─▶ langproxy :10301 ──▶ wyoming-whisper :10300
                    (tiny model picks ru/en)        (large-v3-turbo int8)
                                          │
              Agent: conversation.guarded_agent ─▶ [LLM agent, optional] ─▶ fallback phrase
                                          │
              TTS: tts.robot_tts ─▶ wyoming-piper :10200 (voice by text language) ─▶ ffmpeg robot filter
                                          │
                                       ◀── audio to the speaker
```

Measured on a Ryzen 7 7840HS, no GPU: ~2.7 s from end of speech to transcript,
TTS well under a second, so about 3 s to the first sound of the reply.

## Install (server side)

Debian 13 with Docker. Adjust paths to taste; the compose files assume
`/opt/homeassistant` and `/opt/voice`.

```bash
# Home Assistant Container
mkdir -p /opt/homeassistant/config && cp ha/docker-compose.yml /opt/homeassistant/
cd /opt/homeassistant && docker compose up -d

# speech stack
mkdir -p /opt/voice && cp -r server/voice/* /opt/voice/
cd /opt/voice && docker compose up -d        # whisper downloads its model on first start

# custom components
cp -r ha/custom_components/* /opt/homeassistant/config/custom_components/
docker compose -f /opt/homeassistant/docker-compose.yml restart
```

Then in Home Assistant:

1. Add **Wyoming** twice: `127.0.0.1:10301` (Whisper through the proxy) and
   `127.0.0.1:10200` (Piper).
2. Add **Robot TTS** and **Guarded Agent** (Settings → Integrations → Add).
   Leave the guarded agent's primary agent empty until you have an LLM
   integration; it will speak the fallback phrase.
3. Create one Assist pipeline: STT `faster-whisper-auto`, TTS `Robot TTS`,
   agent `Guarded Agent`. Assign it to the speaker's wake word.

If the server firewall is nftables with a default-drop `forward` chain, allow
Docker's bridges (`docker0`, `br-*`) or containers cannot download models.
Do not `flush ruleset` on reload — it wipes Docker's own tables.

## Tools

```bash
# any HA WebSocket command, token in ~/.config/homeassistant/token
HA_HOST=192.168.0.100 tools/ha_ws.py '{"type": "assist_pipeline/pipeline/list"}'

# end-to-end test without a microphone: Piper says the phrase, it goes through
# STT → agent → TTS, transcript and timings are printed
HA_HOST=192.168.0.100 tools/ha_pipeline_test.py <pipeline_id> ru_RU tts.piper ru_RU-dmitri-medium "Какая столица Франции?"
# or feed an existing file (e.g. a voice-conversion probe) to check intelligibility
HA_HOST=192.168.0.100 tools/ha_pipeline_test.py <pipeline_id> en_US tts.piper x @probe.wav

# give the speaker its Wi-Fi over Bluetooth (press its button when asked)
tools/improv_provision.py 20:F8:3B:xx:xx:xx "SSID" "password"
```

Python deps for the tools: `websockets`, `bleak`, `bleak-retry-connector`,
`py-improv-ble-client`; `ffmpeg` on PATH.

## Character voice (RVC)

The speaker's final voice is a **JobBot** (Job Simulator) timbre trained with
Applio on CPU overnight from ~11 minutes of clean lines. The pipeline, the
Dockerfile and the watchdog are in this repo; the source clips and the trained
weights are **not** — they derive from Owlchemy Labs' copyrighted audio and
stay at home. Follow `voice-training/jobbot/README.md` to train your own.

## Hardware

Voice PE, Beelink GTR7 (Ryzen 7 7840HS, 27 GB, no GPU), ThinkPad P14s Gen 7
for development. Details and measured timings in [docs/hardware.md](docs/hardware.md).

## License

MIT. Home Assistant, ESPHome, Wyoming, Piper, faster-whisper and Applio are
their own projects under their own licenses.
