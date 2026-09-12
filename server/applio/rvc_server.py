#!/usr/bin/env python3
"""Persistent RVC (Applio) voice-conversion service.

Loads the model once and converts WAV → WAV over plain HTTP, so a voice
assistant does not pay ~9 s of process start-up per sentence.

Runs INSIDE the applio container (needs /app on sys.path):
    python /data/rvc_server.py
Env:
    RVC_MODEL   path to the .pth weights   (default /app/logs/jobbot/<latest>)
    RVC_INDEX   path to the .index file    (default /app/logs/jobbot/jobbot.index)
    RVC_HOST / RVC_PORT                    (default 0.0.0.0:10500)
    RVC_F0      default f0 method          (default rmvpe)
API:
    GET  /health                           → JSON {ready, model, index, f0}
    POST /convert?pitch=0&index_rate=0.5&f0_method=rmvpe&protect=0.5
         body: WAV bytes                   → WAV bytes, header X-Convert-Seconds
"""
from __future__ import annotations

import glob
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

os.chdir("/app")
sys.path.insert(0, "/app")

from rvc.infer.infer import VoiceConverter  # noqa: E402

LOGS = "/app/logs/jobbot"


def _latest_weights() -> str:
    files = glob.glob(f"{LOGS}/jobbot_*e_*s.pth")
    if not files:
        raise SystemExit(f"no weights found in {LOGS}")
    return max(files, key=lambda p: int(p.rsplit("_", 2)[1].rstrip("e")))


MODEL = os.environ.get("RVC_MODEL") or _latest_weights()
INDEX = os.environ.get("RVC_INDEX") or f"{LOGS}/jobbot.index"
HOST = os.environ.get("RVC_HOST", "0.0.0.0")
PORT = int(os.environ.get("RVC_PORT", "10500"))
F0_DEFAULT = os.environ.get("RVC_F0", "rmvpe")

converter = VoiceConverter()
lock = threading.Lock()  # conversions are CPU-bound; serialize them
ready = False


def convert(wav_bytes: bytes, pitch: int, index_rate: float, f0_method: str, protect: float) -> tuple[bytes, float]:
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.wav")
        dst = os.path.join(td, "out.wav")
        with open(src, "wb") as f:
            f.write(wav_bytes)
        t0 = time.time()
        with lock:
            converter.convert_audio(
                audio_input_path=src,
                audio_output_path=dst,
                model_path=MODEL,
                index_path=INDEX,
                pitch=pitch,
                f0_method=f0_method,
                index_rate=index_rate,
                protect=protect,
                embedder_model="contentvec",
                export_format="WAV",
            )
        dt = time.time() - t0
        with open(dst, "rb") as f:
            return f.read(), dt


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter default logging
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._json(200, {"ready": ready, "model": os.path.basename(MODEL),
                             "index": os.path.basename(INDEX), "f0": F0_DEFAULT})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/convert":
            return self._json(404, {"error": "not found"})
        q = parse_qs(u.query)
        try:
            pitch = int(q.get("pitch", ["0"])[0])
            index_rate = float(q.get("index_rate", ["0.5"])[0])
            protect = float(q.get("protect", ["0.5"])[0])
            f0_method = q.get("f0_method", [F0_DEFAULT])[0]
            n = int(self.headers.get("Content-Length", "0"))
            wav = self.rfile.read(n)
            if len(wav) < 100:
                return self._json(400, {"error": "empty body"})
            out, dt = convert(wav, pitch, index_rate, f0_method, protect)
        except Exception as err:  # noqa: BLE001
            return self._json(500, {"error": f"{type(err).__name__}: {err}"})
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(out)))
        self.send_header("X-Convert-Seconds", f"{dt:.2f}")
        self.end_headers()
        self.wfile.write(out)


def warm_up() -> None:
    """Load model, embedder and f0 predictor by converting one second of silence."""
    global ready
    import wave

    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "silence.wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)
        with open(p, "rb") as f:
            data = f.read()
    t0 = time.time()
    try:
        convert(data, 0, 0.5, F0_DEFAULT, 0.5)
    except Exception as err:  # noqa: BLE001
        print(f"warm-up conversion failed (continuing): {err}", flush=True)
    ready = True
    print(f"rvc_server ready: model={os.path.basename(MODEL)} index={os.path.basename(INDEX)} "
          f"f0={F0_DEFAULT} warm-up {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    threading.Thread(target=warm_up, daemon=True).start()
    print(f"rvc_server listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
