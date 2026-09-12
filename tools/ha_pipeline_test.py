"""End-to-end Assist pipeline test without a microphone.

1. Ask HA to synthesize a phrase with Piper (tts_get_url) -> WAV.
2. Stream that WAV into assist_pipeline/run (stt -> intent -> tts).
3. Print every pipeline event: transcript, intent response, TTS output, timings.

Usage: ha_pipeline_test.py <pipeline_id> <language> <tts_engine> <tts_voice> "<phrase>"
"""
import asyncio
import json
import os
import sys
import time
import wave
import io

import urllib.request
import websockets

HA_HOST = os.environ.get("HA_HOST", "homeassistant.local")
HA = f"http://{HA_HOST}:8123"
HA_WS = f"ws://{HA_HOST}:8123/api/websocket"


def token() -> str:
    return open(os.path.expanduser("~/.config/homeassistant/token")).read().strip()


def synthesize(phrase: str, engine: str, language: str, voice: str) -> bytes:
    body = json.dumps({"engine_id": engine, "message": phrase, "language": language,
                       "options": {"voice": voice}}).encode()
    req = urllib.request.Request(f"{HA}/api/tts_get_url", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token()}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        url = json.loads(r.read())["url"]
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def to_pcm16k(audio_bytes: bytes) -> bytes:
    """Decode whatever HA returned (mp3/wav) to 16 kHz mono s16le with ffmpeg."""
    import subprocess
    proc = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
         "-ar", "16000", "pipe:1"],
        input=audio_bytes, capture_output=True, check=True)
    # half a second of silence at the end so the pipeline sees the utterance finish
    return proc.stdout + b"\x00" * 16000


async def main() -> int:
    pipeline_id, language, engine, voice, phrase = sys.argv[1:6]
    t0 = time.time()
    if phrase.startswith("@"):
        # "@/path/file.wav": feed an existing audio file instead of synthesizing
        wav = open(phrase[1:], "rb").read()
    else:
        wav = synthesize(phrase, engine, language, voice)
    pcm = to_pcm16k(wav)
    print(f"synthesized {len(wav)} bytes wav, {len(pcm)//32} ms of 16k pcm in {time.time()-t0:.2f}s")

    async with websockets.connect(HA_WS, max_size=20 * 1024 * 1024) as ws:
        json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "auth", "access_token": token()}))
        assert json.loads(await ws.recv())["type"] == "auth_ok"
        await ws.send(json.dumps({
            "id": 1, "type": "assist_pipeline/run", "pipeline": pipeline_id,
            "start_stage": "stt", "end_stage": "tts",
            "input": {"sample_rate": 16000, "no_vad": True},
            "timeout": 120,
        }))
        handler_id = None
        t_start = time.time()
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("type") == "result":
                if not msg.get("success"):
                    print("run failed:", msg)
                    return 2
                continue
            ev = msg.get("event", {})
            et, data = ev.get("type"), ev.get("data") or {}
            ts = time.time() - t_start
            if et == "run-start":
                handler_id = data["runner_data"]["stt_binary_handler_id"]
                print(f"[{ts:5.2f}s] run-start, sending audio")
                # stream audio in 1024-sample chunks, prefixed with handler id byte
                for i in range(0, len(pcm), 2048):
                    await ws.send(bytes([handler_id]) + pcm[i:i + 2048])
                await ws.send(bytes([handler_id]))  # empty chunk = end of audio
            elif et == "stt-end":
                print(f"[{ts:5.2f}s] TRANSCRIPT: {data['stt_output']['text']!r}")
            elif et == "intent-end":
                speech = data["intent_output"]["response"]["speech"]["plain"]["speech"]
                print(f"[{ts:5.2f}s] RESPONSE: {speech!r}")
            elif et == "tts-end":
                print(f"[{ts:5.2f}s] TTS: {data['tts_output'].get('url')}")
            elif et == "error":
                print(f"[{ts:5.2f}s] ERROR: {data}")
            elif et == "run-end":
                print(f"[{ts:5.2f}s] run-end")
                return 0
            else:
                print(f"[{ts:5.2f}s] {et}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
