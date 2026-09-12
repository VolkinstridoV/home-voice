# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `server/applio/rvc_server.py`: persistent RVC conversion service (model
  loaded once, WAV in → WAV out over HTTP on 127.0.0.1:10500). Measured on the
  7840HS with the model warm: 8.5 s of audio in 2.3 s (fcpe), 2.6 s
  (crepe-tiny), 3.3 s (rmvpe); all three fully intelligible to Whisper.
- `robot_tts`: optional RVC stage between Piper and the ffmpeg filter
  (options `rvc_enabled`, `rvc_url`, `rvc_pitch`, `rvc_index_rate`,
  `rvc_f0_method`); falls back to the plain Piper audio if the service is down.
- Watchdog now also kills the spawned training worker on stop (it survived
  its parent twice).

### Result
- JobBot voice trained overnight on CPU: 199 epochs × 3.5 min, best
  checkpoint by validation metric at epoch 160. Side by side with the game
  line, the owner heard one difference: word stress in "JobBot" (that comes
  from Piper, not from the model).

### Planned
- LLM brain (Anthropic integration) behind `guarded_agent`.
- Conversation timeout that resets on wake word, not on transcript.

## [0.1.0] - 2026-09-12

First working loop, no LLM yet.

### Added
- `guarded_agent`: Home Assistant conversation entity that wraps any LLM agent
  and always answers with a fixed English phrase when the agent is missing,
  times out or fails.
- `robot_tts`: Home Assistant TTS entity that picks the Piper voice from the
  text itself (Cyrillic → Russian voice, otherwise English) and runs the audio
  through an ffmpeg "small robot" filter chain.
- `wyoming-langproxy`: Wyoming proxy between Home Assistant and
  wyoming-faster-whisper that detects the *spoken* language with a tiny Whisper
  model (~0.15 s on CPU) and forwards the real request with that language, so
  one wake word serves two languages.
- Server stack: Home Assistant Container, wyoming-whisper (large-v3-turbo,
  int8), wyoming-piper, the proxy, and an Applio (RVC) CPU image with a
  training watchdog.
- Tools: HA WebSocket one-shot client, microphone-free end-to-end pipeline
  test (Piper → Whisper → agent → TTS, prints transcript and timings), Improv
  BLE Wi-Fi provisioning for the Voice PE.
- Voice training pipeline for a character voice (silence-based clip splitter,
  Applio CPU Dockerfile, training start script, checkpoint watchdog with
  self-reconstruction metric and audio probes).
- Docs: the Wi-Fi DSCP CS1 drop that made every non-interactive SSH session
  hang, why one wake word for two languages does not work out of the box, and
  the Applio "silent training from scratch" trap.
