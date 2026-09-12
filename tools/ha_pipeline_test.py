#!/usr/bin/env python3
"""End-to-end Assist pipeline test without a microphone.

1. Ask HA to synthesize a phrase with Piper (tts_get_url) -> audio, or take a file.
2. Stream that audio into assist_pipeline/run (stt -> intent -> tts).
3. Print every pipeline event: transcript, intent response, TTS output, timings.

Usage: ha_pipeline_test.py <pipeline_id> <language> <tts_engine> <tts_voice> "<phrase>"
       phrase may be "@/path/file.wav" to feed an existing audio file.
Env:   HA_HOST (default homeassistant.local); token in ~/.config/homeassistant/token
Also importable: run_once(...) returns a dict for test runners.
"""
import asyncio
import json
import os
import subprocess
import sys
import time
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
    proc = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
         "-ar", "16000", "pipe:1"],
        input=audio_bytes, capture_output=True, check=True)
    # half a second of silence at the end so the pipeline sees the utterance finish
    return proc.stdout + b"\x00" * 16000


async def run_once(pipeline_id: str, language: str, engine: str, voice: str, phrase: str,
                   verbose: bool = False) -> dict:
    """Run one phrase through the pipeline; return transcript, response, timings, error."""
    t0 = time.time()
    if phrase.startswith("@"):
        audio = open(phrase[1:], "rb").read()
    else:
        audio = synthesize(phrase, engine, language, voice)
    pcm = to_pcm16k(audio)
    out: dict = {"phrase": phrase, "audio_ms": len(pcm) // 32, "synth_s": round(time.time() - t0, 2),
                 "transcript": None, "response": None, "error": None, "events": []}

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
        t_start = time.time()
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("type") == "result":
                if not msg.get("success"):
                    out["error"] = f"run failed: {msg}"
                    return out
                continue
            ev = msg.get("event", {})
            et, data = ev.get("type"), ev.get("data") or {}
            ts = round(time.time() - t_start, 2)
            out["events"].append((ts, et))
            if et == "run-start":
                handler_id = data["runner_data"]["stt_binary_handler_id"]
                for i in range(0, len(pcm), 2048):
                    await ws.send(bytes([handler_id]) + pcm[i:i + 2048])
                await ws.send(bytes([handler_id]))
            elif et == "stt-end":
                out["transcript"] = data["stt_output"]["text"]
                out["stt_s"] = ts
                if verbose:
                    print(f"[{ts:5.2f}s] TRANSCRIPT: {out['transcript']!r}")
            elif et == "intent-end":
                out["response"] = data["intent_output"]["response"]["speech"]["plain"]["speech"]
                out["intent_s"] = ts
                if verbose:
                    print(f"[{ts:5.2f}s] RESPONSE: {out['response']!r}")
            elif et == "tts-end":
                out["tts_url"] = data.get("tts_output", {}).get("url")
                if verbose:
                    print(f"[{ts:5.2f}s] TTS: {out['tts_url']}")
            elif et == "error":
                out["error"] = str(data)
                if verbose:
                    print(f"[{ts:5.2f}s] ERROR: {data}")
            elif et == "run-end":
                out["total_s"] = ts
                if verbose:
                    print(f"[{ts:5.2f}s] run-end")
                return out
            elif verbose:
                print(f"[{ts:5.2f}s] {et}")


async def main() -> int:
    pipeline_id, language, engine, voice, phrase = sys.argv[1:6]
    res = await run_once(pipeline_id, language, engine, voice, phrase, verbose=True)
    return 0 if res.get("error") is None else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
