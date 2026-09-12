"""Wyoming proxy that gives Whisper the *spoken* language instead of the pipeline's.

Home Assistant always sends the pipeline language in the Transcribe event and
wyoming-faster-whisper obeys it, so a single pipeline could only ever hear one
language. Letting the big model auto-detect costs an extra encoder pass (~2x
latency). This proxy instead:

  1. buffers the utterance audio from HA,
  2. detects the language with a tiny local Whisper model (fast on CPU),
  3. forwards Transcribe(language=<detected>) plus the audio to the real
     Whisper server and relays the Transcript back.

Describe/Info round-trips are passed through (the ASR service is renamed with a
suffix so HA creates a separate entity).

Usage: langproxy.py --listen tcp://127.0.0.1:10301 --upstream tcp://127.0.0.1:10300
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

import numpy as np
from faster_whisper import WhisperModel
from wyoming.asr import Transcribe
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event, async_read_event, async_write_event
from wyoming.info import Describe, Info

_LOGGER = logging.getLogger("langproxy")


def _parse(uri: str) -> tuple[str, int]:
    assert uri.startswith("tcp://"), uri
    host, port = uri[len("tcp://"):].rsplit(":", 1)
    return host, int(port)


class LangProxy:
    def __init__(self, upstream: tuple[str, int], suffix: str, model: str,
                 allowed: set[str], default_lang: str, threads: int) -> None:
        self.upstream = upstream
        self.suffix = suffix
        self.allowed = allowed
        self.default_lang = default_lang
        _LOGGER.info("loading language-id model %s", model)
        self.model = WhisperModel(model, device="cpu", compute_type="int8",
                                  cpu_threads=threads, download_root="/data")
        self.lock = asyncio.Lock()

    # ---- language id --------------------------------------------------------
    def _detect_sync(self, pcm: bytes, rate: int, width: int, channels: int) -> tuple[str, float]:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        if rate != 16000:
            idx = (np.arange(int(len(audio) * 16000 / rate)) * rate / 16000).astype(np.int64)
            audio = audio[np.clip(idx, 0, len(audio) - 1)]
        if len(audio) < 16000 // 2:
            return self.default_lang, 0.0, None
        lang, prob, all_probs = self.model.detect_language(audio)
        # Pick the most probable *allowed* language, not the global winner:
        # short Russian utterances are sometimes tagged "pl"/"uk" by the tiny
        # model, which would otherwise fall back to the default (English).
        best = None
        for item in all_probs or []:
            code, p = (item[0], item[1]) if isinstance(item, (tuple, list)) else (getattr(item, "language", None), getattr(item, "language_probability", 0.0))
            if code in self.allowed and (best is None or p > best[1]):
                best = (code, float(p))
        return lang, float(prob), best

    async def detect(self, pcm: bytes, rate: int, width: int, channels: int) -> str:
        t0 = time.monotonic()
        async with self.lock:
            lang, prob, best = await asyncio.get_running_loop().run_in_executor(
                None, self._detect_sync, pcm, rate, width, channels)
        if best is not None:
            chosen = best[0]
        else:
            chosen = lang if lang in self.allowed else self.default_lang
        _LOGGER.info("language id: %s (p=%.2f) -> %s%s in %.2fs, %.1fs audio",
                     lang, prob, chosen, f" (best allowed p={best[1]:.2f})" if best else "",
                     time.monotonic() - t0, len(pcm) / (rate * width * channels))
        return chosen

    # ---- one client connection ---------------------------------------------
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("client %s connected", peer)
        up_reader = up_writer = None
        try:
            up_reader, up_writer = await asyncio.open_connection(*self.upstream)
            transcribe: Event | None = None
            audio_start: AudioStart | None = None
            chunks: list[bytes] = []
            while True:
                event = await async_read_event(reader)
                if event is None:
                    break
                if Describe.is_type(event.type):
                    await async_write_event(event, up_writer)
                    info_event = await async_read_event(up_reader)
                    if info_event is not None and Info.is_type(info_event.type):
                        info = Info.from_event(info_event)
                        for asr in info.asr:
                            asr.name = f"{asr.name}{self.suffix}"
                            asr.description = f"{asr.description or asr.name} (spoken-language detection via proxy)"
                        info_event = info.event()
                    if info_event is not None:
                        await async_write_event(info_event, writer)
                elif Transcribe.is_type(event.type):
                    transcribe = event
                elif AudioStart.is_type(event.type):
                    audio_start = AudioStart.from_event(event)
                    chunks = []
                elif AudioChunk.is_type(event.type):
                    chunks.append(AudioChunk.from_event(event).audio)
                elif AudioStop.is_type(event.type):
                    if audio_start is None:
                        continue
                    pcm = b"".join(chunks)
                    lang = await self.detect(pcm, audio_start.rate, audio_start.width, audio_start.channels)
                    t_data = dict((transcribe.data if transcribe else {}) or {})
                    t_data["language"] = lang
                    await async_write_event(Event(type="transcribe", data=t_data), up_writer)
                    await async_write_event(audio_start.event(), up_writer)
                    for c in chunks:
                        await async_write_event(AudioChunk(rate=audio_start.rate, width=audio_start.width,
                                                           channels=audio_start.channels, audio=c).event(), up_writer)
                    await async_write_event(event, up_writer)
                    # relay everything until the transcript arrives
                    while True:
                        reply = await async_read_event(up_reader)
                        if reply is None:
                            break
                        await async_write_event(reply, writer)
                        if reply.type == "transcript":
                            break
                    transcribe, audio_start, chunks = None, None, []
                else:
                    await async_write_event(event, up_writer)
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError, OSError) as err:
            _LOGGER.debug("client %s: %s", peer, err)
        finally:
            for w in (writer, up_writer):
                if w is not None:
                    try:
                        w.close()
                    except Exception:  # noqa: BLE001
                        pass
        _LOGGER.debug("client %s done", peer)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="tcp://127.0.0.1:10301")
    ap.add_argument("--upstream", default="tcp://127.0.0.1:10300")
    ap.add_argument("--name-suffix", default="-auto")
    ap.add_argument("--langid-model", default="tiny")
    ap.add_argument("--languages", default="en,ru", help="comma list of allowed languages")
    ap.add_argument("--default-language", default="en")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    proxy = LangProxy(_parse(args.upstream), args.name_suffix, args.langid_model,
                      set(args.languages.split(",")), args.default_language, args.threads)
    host, port = _parse(args.listen)
    server = await asyncio.start_server(proxy.handle, host, port)
    _LOGGER.info("listening on %s:%s, upstream %s:%s", host, port, *proxy.upstream)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
