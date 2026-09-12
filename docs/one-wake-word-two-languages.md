# One wake word, two languages

Goal: a household that speaks Russian and English says "Okay Nabu" and gets an
answer in whatever language it spoke. No second wake word, no switching.

## Why it does not work out of the box

An Assist pipeline in Home Assistant has one language. HA passes that language
to the STT server in the Wyoming `transcribe` event, and
`wyoming-faster-whisper` obeys it. Russian speech through an English pipeline
comes back as English gibberish, and vice versa:

```
"Переведи на английский: где ближайшая аптека?"  →  "Or see us in English, where is the nearest pharmacy."
"What is the weather like today?"                →  "Что сегодня Like?"
```

The official answer is two pipelines with two wake words ("Okay Nabu" =
English, "Hey Jarvis" = Russian). That works, but it is not what was wanted.

## First attempt: let the big model auto-detect

`--language auto` on the Whisper server, plus a proxy that strips the language
from `transcribe`. Correct on both languages — and **twice as slow**: 5.0 s
instead of 2.6 s for `large-v3-turbo` (language detection costs an extra
encoder pass). `medium` with auto was 3.4 s and got Russian wrong.

## What works: detect first, transcribe second

`server/voice/langproxy/langproxy.py` sits between HA and Whisper:

1. Buffers the utterance audio from HA.
2. Runs `faster-whisper` **tiny** `detect_language` on it — ~0.15 s on CPU,
   confidence 0.56–1.0 on the test set.
3. Sends `transcribe(language=<detected>)` plus the audio to the real
   Whisper server and relays the transcript back.

Result: 2.7 s total, correct on both languages, through **one** pipeline.
The proxy also renames the advertised ASR service (`-auto` suffix) so HA
creates a separate STT entity.

## The other half: replying in the right voice

The pipeline's TTS voice is fixed too. `robot_tts` (a custom TTS entity) picks
the Piper voice from the reply text — Cyrillic → Russian voice, otherwise
English — and only then applies the robot filter. So an English fallback
phrase is always spoken by the English voice, and a Russian reply by the
Russian one, whatever the pipeline language says.
