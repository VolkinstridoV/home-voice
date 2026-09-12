# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned
- Extra wake words ("Nabu", "Hello Nabu"): custom microWakeWord model + custom firmware.
- Speaker separation; low-confidence STT handling; GPU.

## [0.3.0] - 2026-09-12

Memory, tests, observability, self-healing.

### Added
- `nabu_memory`: durable household facts as an LLM API with `remember` /
  `forget` tools; facts are injected into the agent's system prompt
  (`nabu_memory.json`). Verified across separate conversations in ru and en.
- Test suite `tests/phrases.yaml` (21 spoken cases: facts, translation both
  ways, live search, honesty, style, memory, guard) and `tools/run_tests.py`
  grading language, content, length, markdown, latency. 21/21 after fixes.
- `tools/nabu_runs_export.py` (server cron, 5 min): pipeline stage timings
  appended to `nabu_runs.jsonl` before HA forgets them; `tools/nabu_daily_report.py`
  prints per-day turns, outcomes, latency percentiles, searches, estimated cost.
- `server/health/nabu_health.sh` (server cron, 1 min): checks HA, Whisper,
  proxy, Piper, RVC service and the speaker; restarts a failed container once
  per 10 min and raises an HA persistent notification.
- Prompt: name first when asked who you are; masculine self-reference in Russian.

## [0.2.0] - 2026-09-12

The brain, the guard rails, and streaming speech.

### Added
- **Claude as the brain**: Anthropic integration (Sonnet 5, web search + web
  fetch, user location, prompt caching, thinking off) behind `guarded_agent`;
  system prompt `ha/prompts/nabu.txt` (Savannah/Hardin County, household,
  per-question length policy, tool disclosure, honest refusals).
- **Spend safety in `guarded_agent`**: input gate (empty / repeated /
  duplicate transcripts never reach the LLM), sliding-window limits
  (6/min, 60/h, 400/day, configurable), circuit breaker (3 failures → 5 min
  pause), one call at a time, 30 s timeout. Every refusal is *spoken* in the
  user's language. Offline tests: `tests/test_spend.py`.
- **Persistent conversation journal** `nabu_conversations.jsonl` (HA keeps only
  the last 10 pipeline runs in memory): user text, agent, answer, LLM seconds,
  tool calls (web_search queries), guard counters.
- **Streaming speech** in `robot_tts`: sentences are synthesized and RVC-converted
  one by one while Claude is still writing; the opening chunk is kept short.
  Measured: first sound 1.8 s after the reply starts (was: whole answer +
  whole conversion, 5–8 s, and long answers were never played at all).
- `langproxy`: pick the most probable *allowed* language from the full
  probability table (short Russian was tagged "pl" and fell back to English).
- Persistent debug log levels in HA `configuration.yaml`.

### Fixed
- Long answers silently not played on the speaker (fixed by streaming).
- Applio container recreation lost the embedder/predictor files (HF returned
  429 on parallel downloads → 0-byte files → `EOFError`); copies now live in
  `/opt/applio-data/models`.

### Added earlier today
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
